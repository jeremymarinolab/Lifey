"""Spotify OAuth and local listening history for the Lifey helper."""
from __future__ import annotations

import base64
import datetime as dt
import hashlib
import json
import os
import secrets
import ssl
import threading
import time
from pathlib import Path
from urllib import error as urlerror
from urllib import request as urlrequest
from urllib.parse import urlencode, urlparse

from config_store import CONFIG, config, public_origin_setting, save_config


AUTH_URL = "https://accounts.spotify.com/authorize"
TOKEN_URL = "https://accounts.spotify.com/api/token"
API_URL = "https://api.spotify.com/v1"
SCOPES = "user-read-currently-playing user-read-recently-played"
HISTORY_PATH = CONFIG.parent / "spotify-history.json"
LOCAL_ORIGIN = f"http://127.0.0.1:{os.environ.get('LIFEY_PORT', '4173')}"
CALLBACK_PATH = "/api/spotify/auth/callback"
LOCK = threading.RLock()
AUTH_LOCK = threading.RLock()
SYNC_LOCK = threading.Lock()
PENDING: dict[str, dict] = {}
ACCESS: dict = {}
RUNTIME = {"current": None, "currentAt": 0.0, "currentUpdating": False, "activeAt": 0.0, "retryAt": 0.0,
           "syncError": "", "syncErrorKind": "", "playbackError": "", "playbackErrorKind": ""}
SSL_CONTEXT = ssl.create_default_context(cafile="/etc/ssl/cert.pem")
WORKER_STARTED = False


class SpotifyError(ValueError):
    def __init__(self, message: str, status: int = 400, kind: str = "error"):
        super().__init__(message)
        self.status = status
        self.kind = kind


def public_origin() -> str:
    value = public_origin_setting()
    parsed = urlparse(value)
    if not value:
        return ""
    if parsed.scheme != "https" or not parsed.hostname or parsed.path or parsed.query or parsed.fragment or parsed.username:
        raise SpotifyError("LIFEY_PUBLIC_ORIGIN must be an HTTPS origin without a path.")
    return value


def callback_origin(host: str) -> str:
    parsed_host = urlparse("//" + (host or ""))
    local_port = urlparse(LOCAL_ORIGIN).port
    if parsed_host.hostname in {"127.0.0.1", "localhost"} and parsed_host.port == local_port:
        return LOCAL_ORIGIN
    public = public_origin()
    if public and host.lower() == urlparse(public).netloc.lower():
        return public
    raise SpotifyError("Open Lifey using its local or configured HTTPS address.", 403, "origin")


def client_id(settings: dict | None = None) -> str:
    settings = config() if settings is None else settings
    return str(settings.get("spotifyClientId") or settings.get("profilePreferences", {}).get("integrations", {}).get("spotify", {}).get("clientId") or "").strip()


def _request(url: str, *, body: dict | None = None, token: str = "") -> tuple[int, dict, dict]:
    headers = {"Accept": "application/json"}
    data = None
    if body is not None:
        data = urlencode(body).encode()
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urlrequest.Request(url, data=data, headers=headers)
    try:
        with urlrequest.urlopen(request, context=SSL_CONTEXT, timeout=12) as response:
            raw = response.read()
            return response.status, json.loads(raw) if raw else {}, dict(response.headers)
    except urlerror.HTTPError as error:
        raw = error.read()
        try:
            payload = json.loads(raw) if raw else {}
        except (ValueError, TypeError):
            payload = {}
        return error.code, payload, dict(error.headers)
    except (OSError, urlerror.URLError) as error:
        raise SpotifyError(f"Spotify is unreachable: {error}", 503, "offline") from error


def _failure(status: int, payload: dict, headers: dict) -> SpotifyError:
    detail = payload.get("error", {})
    reason = detail.get("message", "") if isinstance(detail, dict) else str(detail)
    if status == 401:
        return SpotifyError("Spotify authorization expired. Reconnect Spotify.", 401, "expired")
    if status == 403:
        return SpotifyError("Spotify denied access. Check that the app owner has Premium and this account is allowed in the app dashboard.", 403, "forbidden")
    if status == 429:
        try:
            delay = max(1, int(headers.get("Retry-After", "60")))
        except ValueError:
            delay = 60
        RUNTIME["retryAt"] = time.time() + delay
        return SpotifyError(f"Spotify rate limit reached. Retry in {delay} seconds.", 429, "rate_limited")
    return SpotifyError(f"Spotify request failed ({status}){': ' + reason if reason else ''}.", 502, "error")


def _token_request(body: dict) -> dict:
    status, payload, headers = _request(TOKEN_URL, body=body)
    if status != 200 or not payload.get("access_token"):
        if payload.get("error") == "invalid_grant":
            raise SpotifyError("Spotify authorization expired. Reconnect Spotify.", 401, "expired")
        raise _failure(status, payload, headers)
    return payload


def _access_token(force: bool = False) -> str:
    with AUTH_LOCK:
        if not force and ACCESS.get("token") and ACCESS.get("expiresAt", 0) > time.time() + 60:
            return ACCESS["token"]
        settings = config()
        refresh = str(settings.get("spotifyRefreshToken") or "")
        if not client_id(settings) or not refresh:
            raise SpotifyError("Connect Spotify first.", 401, "disconnected")
        try:
            token = _token_request({"grant_type": "refresh_token", "refresh_token": refresh, "client_id": client_id(settings)})
        except SpotifyError as error:
            if error.kind == "expired":
                save_config({"spotifyRefreshToken": ""})
                ACCESS.clear()
            raise
        rotated = token.get("refresh_token")
        if rotated and rotated != refresh:
            save_config({"spotifyRefreshToken": rotated})
        ACCESS.update(token=token["access_token"], expiresAt=time.time() + int(token.get("expires_in", 3600)))
        return ACCESS["token"]


def _api(path: str) -> dict | None:
    if RUNTIME["retryAt"] > time.time():
        raise SpotifyError("Spotify is rate limited. Lifey will retry automatically.", 429, "rate_limited")
    for attempt in range(2):
        status, payload, headers = _request(API_URL + path, token=_access_token(force=attempt == 1))
        if status == 204:
            return None
        if status == 401 and attempt == 0:
            continue
        if status != 200:
            raise _failure(status, payload, headers)
        return payload
    raise SpotifyError("Spotify authorization expired. Reconnect Spotify.", 401, "expired")


def _base64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode().rstrip("=")


def auth_url(host: str) -> str:
    settings = config()
    identifier = client_id(settings)
    if not identifier:
        raise SpotifyError("Add a Spotify client ID first.")
    origin = callback_origin(host)
    verifier = _base64url(secrets.token_bytes(64))
    state = secrets.token_urlsafe(32)
    with LOCK:
        now = time.time()
        for key in list(PENDING):
            if PENDING[key]["expiresAt"] < now:
                del PENDING[key]
        PENDING[state] = {"verifier": verifier, "redirect": origin + CALLBACK_PATH, "expiresAt": now + 600}
    return AUTH_URL + "?" + urlencode({
        "client_id": identifier, "response_type": "code", "redirect_uri": origin + CALLBACK_PATH,
        "scope": SCOPES, "state": state, "code_challenge_method": "S256",
        "code_challenge": _base64url(hashlib.sha256(verifier.encode()).digest()),
    })


def finish_auth(query: dict[str, list[str]], host: str) -> str:
    state = query.get("state", [""])[0]
    with LOCK:
        pending = PENDING.pop(state, None) if state else None
    if not pending or pending["expiresAt"] < time.time():
        raise SpotifyError("Spotify sign-in expired or did not match. Start again.", 400, "oauth")
    origin = callback_origin(host)
    if pending["redirect"] != origin + CALLBACK_PATH:
        raise SpotifyError("Spotify callback address did not match.", 400, "oauth")
    if query.get("error"):
        raise SpotifyError("Spotify sign-in was declined.", 400, "oauth")
    code = query.get("code", [""])[0]
    if not code:
        raise SpotifyError("Spotify did not return an authorization code.", 400, "oauth")
    token = _token_request({
        "client_id": client_id(), "grant_type": "authorization_code", "code": code,
        "redirect_uri": pending["redirect"], "code_verifier": pending["verifier"],
    })
    refresh = token.get("refresh_token")
    if not refresh:
        raise SpotifyError("Spotify did not return a refresh token. Reconnect.", 502, "oauth")
    profile_status, profile, headers = _request(API_URL + "/me", token=token["access_token"])
    if profile_status != 200:
        raise _failure(profile_status, profile, headers)
    save_config({"spotifyRefreshToken": refresh, "spotifyAccountName": profile.get("display_name") or profile.get("id") or "Spotify"})
    with LOCK:
        ACCESS.update(token=token["access_token"], expiresAt=time.time() + int(token.get("expires_in", 3600)))
        RUNTIME.update(syncError="", syncErrorKind="", playbackError="", playbackErrorKind="", retryAt=0.0)
    threading.Thread(target=sync_recent, kwargs={"force": True}, daemon=True).start()
    return origin


def configure(identifier: str) -> dict:
    identifier = identifier.strip()
    if not identifier or len(identifier) > 200:
        raise SpotifyError("Enter a valid Spotify client ID.")
    settings = config()
    if identifier != client_id(settings) and settings.get("spotifyRefreshToken"):
        save_config({"spotifyRefreshToken": "", "spotifyClientId": identifier, "spotifyAccountName": ""})
        with LOCK:
            ACCESS.clear()
    else:
        save_config({"spotifyClientId": identifier})
    return status()


def disconnect() -> dict:
    save_config({"spotifyRefreshToken": "", "spotifyAccountName": ""})
    with LOCK:
        ACCESS.clear()
        RUNTIME.update(current=None, syncError="", syncErrorKind="", playbackError="", playbackErrorKind="", retryAt=0.0)
    return status()


def _read_history() -> dict:
    try:
        value = json.loads(HISTORY_PATH.read_text())
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_history(value: dict) -> None:
    HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary = HISTORY_PATH.with_suffix(".tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w") as stream:
        json.dump(value, stream, separators=(",", ":"))
    os.replace(temporary, HISTORY_PATH)


def _normalize_play(item: dict, legacy: bool = False) -> dict | None:
    if legacy and item.get("source") not in {"recently-played", "spotify", "imported"}:
        return None
    track = item if legacy else item.get("track", {})
    if not isinstance(track, dict) or track.get("type", "track") != "track":
        return None
    played_at = item.get("playedAt") if legacy else item.get("played_at")
    try:
        played = dt.datetime.fromisoformat(str(played_at).replace("Z", "+00:00"))
        if played.tzinfo is None or played > dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=5):
            return None
    except (TypeError, ValueError):
        return None
    identifier = str((item.get("trackId") if legacy else track.get("id")) or track.get("uri") or "")[:200]
    title = str((item.get("title") if legacy else track.get("name")) or "")[:300]
    if not identifier or not title:
        return None
    artists = item.get("artists", []) if legacy else track.get("artists", [])
    artists = [{"id": str(artist.get("id") or artist.get("name") or "")[:200], "name": str(artist.get("name") or "")[:200]} for artist in artists if isinstance(artist, dict)][:12]
    images = track.get("album", {}).get("images", []) if isinstance(track.get("album"), dict) else []
    artwork = str((item.get("artwork") if legacy else images[0].get("url") if images else "") or "")[:1000]
    duration = item.get("durationMs") if legacy else track.get("duration_ms")
    try:
        duration = max(0, min(3_600_000, int(duration)))
    except (TypeError, ValueError):
        duration = 0
    stamp = played.astimezone(dt.timezone.utc).isoformat()
    return {"playId": f"{identifier}:{stamp}", "trackId": identifier, "title": title, "artists": artists,
            "artist": ", ".join(artist["name"] for artist in artists) or str(item.get("artist", ""))[:300],
            "artwork": artwork, "durationMs": duration, "playedAt": stamp, "source": "imported" if legacy else "spotify"}


def _merge_plays(history: dict, items: list[dict], legacy: bool = False) -> int:
    plays = {play["playId"]: play for play in history.get("plays", []) if isinstance(play, dict) and play.get("playId")}
    before = len(plays)
    for item in items:
        play = _normalize_play(item, legacy)
        if play and play["playedAt"] > history.get("clearedBefore", ""):
            plays.setdefault(play["playId"], play)
    history["plays"] = sorted(plays.values(), key=lambda play: play["playedAt"], reverse=True)
    return len(plays) - before


def import_legacy(items: list[dict]) -> dict:
    with LOCK:
        history = _read_history()
        added = _merge_plays(history, items[:1000], legacy=True)
        _write_history(history)
    return {"imported": added}


def clear_history() -> dict:
    with LOCK:
        _write_history({"plays": [], "backfillComplete": True, "clearedBefore": dt.datetime.now(dt.timezone.utc).isoformat(),
                        "lastSync": "", "lastSyncAt": 0})
    return {"cleared": True}


def _record_error(error: SpotifyError, source: str) -> None:
    with LOCK:
        RUNTIME.update(**{source + "Error": str(error), source + "ErrorKind": error.kind})


def sync_recent(force: bool = False) -> dict:
    with SYNC_LOCK:
        settings = config()
        if not settings.get("spotifyRefreshToken"):
            raise SpotifyError("Connect Spotify first.", 401, "disconnected")
        with LOCK:
            history = _read_history()
        last = history.get("lastSyncAt", 0)
        interval = 900 if time.time() - RUNTIME["activeAt"] < 300 else 3600
        if not force and time.time() - last < interval:
            return {"added": 0, "lastSync": history.get("lastSync", "")}
        if RUNTIME["retryAt"] > time.time():
            raise SpotifyError("Spotify is rate limited. Lifey will retry automatically.", 429, "rate_limited")
        try:
            previous_newest = history.get("latestPlay", "")
            latest = _api("/me/player/recently-played?limit=50") or {}
            rows_latest = latest.get("items", [])
            added = _merge_plays(history, rows_latest)
            latest_plays = [play for play in (_normalize_play(row) for row in rows_latest) if play]
            oldest_latest = min((int(dt.datetime.fromisoformat(play["playedAt"]).timestamp() * 1000) for play in latest_plays), default=0)
            if latest_plays:
                history["latestPlay"] = max(play["playedAt"] for play in latest_plays)
            pages_left = 4
            gap_before = history.get("catchupBefore")
            gap_until = history.get("catchupUntil", "")
            if not gap_before and previous_newest and oldest_latest and dt.datetime.fromtimestamp(oldest_latest / 1000, dt.timezone.utc).isoformat() > previous_newest:
                gap_before, gap_until = oldest_latest, previous_newest
            if gap_before:
                while pages_left:
                    pages_left -= 1
                    page = _api("/me/player/recently-played?" + urlencode({"limit": 50, "before": gap_before})) or {}
                    rows = page.get("items", [])
                    added += _merge_plays(history, rows)
                    parsed_rows = [play for play in (_normalize_play(row) for row in rows) if play]
                    if not parsed_rows:
                        history["unrecoverableGap"] = True
                        gap_before = None
                        break
                    oldest = min(int(dt.datetime.fromisoformat(play["playedAt"]).timestamp() * 1000) for play in parsed_rows)
                    if min(play["playedAt"] for play in parsed_rows) <= gap_until:
                        gap_before = None
                        break
                    if oldest >= gap_before or ("next" in page and not page["next"]) or ("next" not in page and len(rows) < 50):
                        history["unrecoverableGap"] = True
                        gap_before = None
                        break
                    gap_before = oldest
                history["catchupBefore"] = gap_before
                history["catchupUntil"] = gap_until if gap_before else ""
            before = history.get("backfillBefore") or oldest_latest
            if not rows_latest and not history.get("plays"):
                history["backfillComplete"] = True
            if not gap_before and not history.get("backfillComplete") and before:
                while pages_left:
                    pages_left -= 1
                    page = _api("/me/player/recently-played?" + urlencode({"limit": 50, "before": before})) or {}
                    rows = page.get("items", [])
                    if not rows:
                        history["backfillComplete"] = True
                        break
                    added += _merge_plays(history, rows)
                    parsed_rows = [play for play in (_normalize_play(row) for row in rows) if play]
                    if not parsed_rows:
                        history["backfillComplete"] = True
                        break
                    oldest = min(int(dt.datetime.fromisoformat(play["playedAt"]).timestamp() * 1000) for play in parsed_rows)
                    if oldest >= before or ("next" in page and not page["next"]) or ("next" not in page and len(rows) < 50):
                        history["backfillComplete"] = True
                        break
                    before = oldest
                history["backfillBefore"] = before
            history["lastSync"] = dt.datetime.now(dt.timezone.utc).isoformat()
            history["lastSyncAt"] = time.time()
            with LOCK:
                current_history = _read_history()
                current_plays = {play["playId"]: play for play in current_history.get("plays", []) if isinstance(play, dict) and play.get("playId")}
                for play in history.get("plays", []):
                    current_plays.setdefault(play["playId"], play)
                history["plays"] = sorted(current_plays.values(), key=lambda play: play["playedAt"], reverse=True)
                if current_history.get("clearedBefore", "") > history.get("clearedBefore", ""):
                    history["clearedBefore"] = current_history["clearedBefore"]
                    history["plays"] = [play for play in history["plays"] if play["playedAt"] > history["clearedBefore"]]
                    history["backfillComplete"] = True
                _write_history(history)
            RUNTIME.update(syncError="", syncErrorKind="")
            return {"added": added, "lastSync": history["lastSync"]}
        except SpotifyError as error:
            _record_error(error, "sync")
            raise


def _current_playback() -> dict | None:
    with LOCK:
        if time.time() - RUNTIME["currentAt"] < 60 or RUNTIME["currentUpdating"]:
            return RUNTIME["current"]
        RUNTIME["currentUpdating"] = True
    try:
        result = _api("/me/player/currently-playing?additional_types=track,episode")
        item = result.get("item") if result else None
        current = None
        if item:
            artists = item.get("artists") or item.get("show", {}).get("name") or []
            artist = ", ".join(row.get("name", "") for row in artists) if isinstance(artists, list) else str(artists)
            album = item.get("album") if isinstance(item.get("album"), dict) else {}
            images = album.get("images") or item.get("images") or []
            current = {"title": item.get("name", ""), "artist": artist, "artwork": images[0].get("url", "") if images else "",
                       "isPlaying": bool(result.get("is_playing")), "type": item.get("type", "track")}
        with LOCK:
            RUNTIME.update(current=current, currentAt=time.time(), playbackError="", playbackErrorKind="")
        return current
    except SpotifyError as error:
        with LOCK:
            RUNTIME["currentAt"] = time.time()
        _record_error(error, "playback")
        return RUNTIME["current"]
    finally:
        with LOCK:
            RUNTIME["currentUpdating"] = False


def status() -> dict:
    settings = config()
    return {"configured": bool(client_id(settings)), "clientId": client_id(settings),
            "connected": bool(settings.get("spotifyRefreshToken")), "account": settings.get("spotifyAccountName", ""),
            "error": RUNTIME["syncError"] or RUNTIME["playbackError"],
            "errorKind": RUNTIME["syncErrorKind"] or RUNTIME["playbackErrorKind"]}


def summary(range_name: str = "today", active: bool = False) -> dict:
    if range_name not in {"today", "week", "month"}:
        raise SpotifyError("Choose today, week, or month.")
    with LOCK:
        if active:
            RUNTIME["activeAt"] = time.time()
        history = _read_history()
        today = dt.datetime.now().astimezone().replace(hour=0, minute=0, second=0, microsecond=0)
        start = today if range_name == "today" else today - dt.timedelta(days=today.weekday()) if range_name == "week" else today.replace(day=1)
        plays = [play for play in history.get("plays", []) if dt.datetime.fromisoformat(play["playedAt"]).astimezone() >= start]
        songs: dict[str, dict] = {}
        artists: dict[str, dict] = {}
        def minutes(play):
            return max(1, round(play.get("durationMs", 0) / 60000))
        for play in plays:
            duration = minutes(play)
            song = songs.setdefault(play["trackId"], {"title": play["title"], "artist": play["artist"], "artwork": play["artwork"], "playbacks": 0, "minutes": 0})
            song["playbacks"] += 1
            song["minutes"] += duration
            for artist in play.get("artists", []):
                row = artists.setdefault(artist["id"], {"name": artist["name"], "artwork": play["artwork"], "playbacks": 0, "minutes": 0})
                row["playbacks"] += 1
                row["minutes"] += duration
        today_minutes = sum(minutes(play) for play in history.get("plays", []) if dt.datetime.fromisoformat(play["playedAt"]).astimezone() >= today)
        connection = status()
        refreshing = RUNTIME["currentUpdating"]
        if active and connection["connected"] and time.time() - RUNTIME["currentAt"] >= 60 and not refreshing:
            threading.Thread(target=_current_playback, daemon=True).start()
            refreshing = True
        current = RUNTIME["current"]
        return {**connection, "range": range_name, "current": current,
                "currentCheckedAt": int(RUNTIME["currentAt"] * 1000), "currentRefreshing": refreshing,
                "stats": {"playCount": len(plays), "minutes": sum(minutes(play) for play in plays),
                          "songs": sorted(songs.values(), key=lambda row: (-row["playbacks"], -row["minutes"]))[:10],
                          "artists": sorted(artists.values(), key=lambda row: (-row["minutes"], -row["playbacks"]))[:10]},
                "todayMinutes": today_minutes, "lastSync": history.get("lastSync", ""),
                "oldestPlay": history["plays"][-1]["playedAt"] if history.get("plays") else "",
                "backfillComplete": bool(history.get("backfillComplete")),
                "historyGap": bool(history.get("catchupBefore") or history.get("unrecoverableGap")),
                "historyGapUnrecoverable": bool(history.get("unrecoverableGap"))}


def _worker() -> None:
    while True:
        try:
            if status()["connected"]:
                sync_recent()
        except (SpotifyError, OSError):
            pass
        time.sleep(60)


def start_worker() -> None:
    global WORKER_STARTED
    with LOCK:
        if WORKER_STARTED:
            return
        WORKER_STARTED = True
    threading.Thread(target=_worker, name="lifey-spotify-sync", daemon=True).start()

"""Small, local-only server for Today Command Center.

It serves the dashboard and provides a deliberately narrow Obsidian adapter:
configure one Daily-notes folder, read today's note, and replace only the
DASHBOARD marker block while saving a sibling backup. It never listens beyond
127.0.0.1 and never sends vault contents anywhere.
"""
from __future__ import annotations

import base64
import datetime as dt
import gzip
import hashlib
import json
import os
import re
import secrets
import ssl
import subprocess
import threading
import time
import zlib
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse
from urllib import error as urlerror
from urllib import request as urlrequest

ROOT = Path(__file__).resolve().parent
LEGACY_CONFIG = ROOT / ".local-dashboard.json"
CONFIG = Path.home() / "Library" / "Application Support" / "Lifey" / "profile.json"
ACTIVITY = ROOT / ".activity-log.json"
MOBILE_LOCATIONS = Path.home() / "Library" / "Application Support" / "Lifey" / "location-samples.json"
START = END = "---"
LEGACY_START, LEGACY_END = "<!-- DASHBOARD:START -->", "<!-- DASHBOARD:END -->"
SSL_CONTEXT = ssl.create_default_context(cafile="/etc/ssl/cert.pem")
LAST_NOMINATIM_REQUEST = 0.0
DEFAULT_LOCATION_ARCHIVE_TEMPLATES = {
    "weekly": "---\n## Lifey · {{period}}\n\n### Top places\n{{topPlaces}}\n\n### Days\n{{dailyPlaces}}\n---",
    "monthly": "---\n## Lifey · {{period}}\n\n### Top places\n{{topPlaces}}\n---",
    "yearly": "---\n## Lifey · {{period}}\n\n### Top places\n{{topPlaces}}\n---",
}
DEFAULT_ARCHIVE_TITLES = {
    "daily": "Lifey · MMMM DD, YYYY",
    "weekly": "Lifey · {{period}}",
    "monthly": "Lifey · {{period}}",
    "yearly": "Lifey · {{period}}",
}
SECRET_FIELDS = {"notionToken", "traccarToken", "googlePlacesKey", "lifeyLocationToken", "googleRefreshToken", "googleClientSecret"}
KEYCHAIN_SERVICE = "Lifey"
PROFILE_PREFERENCE_FIELDS = {"appearance", "visibility", "taskDisplay", "contentDisplay", "heroMetricOrder", "heroMetricVisibility", "cardOrder", "integrations", "habitSettings"}
PROFILE_SECRET_KEYS = {"token", "accessToken", "refreshToken", "notionToken", "traccarToken", "googlePlacesKey", "lifeyLocationToken", "googleClientSecret", "clientSecret", "password", "secret"}
PROFILE_EXCLUDED_SECRETS = [
    "notionToken",
    "googlePlacesKey",
    "traccarToken",
    "lifeyLocationToken",
    "googleRefreshToken",
    "googleClientSecret",
    "oauthAccessTokens",
]
GOOGLE_SCOPES = "openid email https://www.googleapis.com/auth/calendar.events https://www.googleapis.com/auth/gmail.readonly"
GOOGLE_REDIRECT_URI = "http://127.0.0.1:4173/api/google/auth/callback"


def keychain_get(name: str) -> str:
    try:
        result = subprocess.run(["security", "find-generic-password", "-s", KEYCHAIN_SERVICE, "-a", name, "-w"], capture_output=True, timeout=3, check=False)
        if result.returncode != 0:
            return ""
        raw = result.stdout.rstrip(b"\r\n")
        # Keychain passwords are normally UTF-8, but never allow one malformed
        # legacy entry to take down an unrelated dashboard request.
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError:
            return raw.decode("latin-1")
    except (OSError, subprocess.SubprocessError):
        return ""


def keychain_set(name: str, value: str) -> bool:
    try:
        result = subprocess.run(["security", "add-generic-password", "-U", "-s", KEYCHAIN_SERVICE, "-a", name, "-w", value], capture_output=True, text=True, timeout=3, check=False)
        return result.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def keychain_delete(name: str) -> bool:
    try:
        subprocess.run(["security", "delete-generic-password", "-s", KEYCHAIN_SERVICE, "-a", name], capture_output=True, text=True, timeout=3, check=False)
        return True
    except (OSError, subprocess.SubprocessError):
        return False


def config() -> dict:
    try:
        settings = json.loads((CONFIG if CONFIG.exists() else LEGACY_CONFIG).read_text())
    except (OSError, json.JSONDecodeError):
        settings = {}
    for key in SECRET_FIELDS:
        secret = keychain_get(key)
        if secret:
            settings[key] = secret
    return settings


def save_config(values: dict) -> None:
    migrating_legacy = not CONFIG.exists() and LEGACY_CONFIG.exists()
    current = config()
    current.update(values)
    persisted = dict(current)
    for key in SECRET_FIELDS:
        value = str(current.get(key) or "")
        if key in values and not value:
            keychain_delete(key)
            persisted.pop(key, None)
        elif value and keychain_set(key, value):
            persisted.pop(key, None)
    CONFIG.parent.mkdir(parents=True, exist_ok=True)
    CONFIG.write_text(json.dumps(persisted, indent=2))
    if migrating_legacy:
        try:
            legacy = json.loads(LEGACY_CONFIG.read_text())
            for key in SECRET_FIELDS:
                if keychain_get(key):
                    legacy.pop(key, None)
            LEGACY_CONFIG.write_text(json.dumps(legacy, indent=2))
        except (OSError, json.JSONDecodeError):
            pass


def strip_profile_secrets(value):
    if isinstance(value, dict):
        return {key: strip_profile_secrets(item) for key, item in value.items() if key not in PROFILE_SECRET_KEYS}
    if isinstance(value, list):
        return [strip_profile_secrets(item) for item in value]
    return value


def safe_profile_preferences(settings: dict) -> dict:
    preferences = settings.get("profilePreferences", {})
    if not isinstance(preferences, dict):
        preferences = {}
    clean = {key: preferences[key] for key in PROFILE_PREFERENCE_FIELDS if key in preferences}
    integrations = strip_profile_secrets(dict(clean.get("integrations", {}))) if isinstance(clean.get("integrations"), dict) else {}
    if settings.get("notionParentId"):
        notion = dict(integrations.get("notion", {})) if isinstance(integrations.get("notion"), dict) else {}
        notion.setdefault("database", settings.get("notionParentId", ""))
        notion.setdefault("dataSourceId", settings.get("notionDataSourceId", ""))
        notion.setdefault("property", settings.get("notionTitleProperty", "Name"))
        integrations["notion"] = strip_profile_secrets(notion)
    if settings.get("traccarServer") or settings.get("traccarDeviceId"):
        traccar = dict(integrations.get("traccar", {})) if isinstance(integrations.get("traccar"), dict) else {}
        traccar.setdefault("server", settings.get("traccarServer", ""))
        traccar.setdefault("deviceId", settings.get("traccarDeviceId", ""))
        integrations["traccar"] = strip_profile_secrets(traccar)
    if settings.get("googleClientId") or settings.get("googleCalendarId"):
        google = dict(integrations.get("google", {})) if isinstance(integrations.get("google"), dict) else {}
        google.setdefault("clientId", settings.get("googleClientId", ""))
        google.setdefault("calendar", settings.get("googleCalendarId", "primary"))
        integrations["google"] = strip_profile_secrets(google)
    if settings.get("gmailQuery"):
        gmail = dict(integrations.get("gmail", {})) if isinstance(integrations.get("gmail"), dict) else {}
        gmail.setdefault("query", settings.get("gmailQuery", ""))
        integrations["gmail"] = strip_profile_secrets(gmail)
    if integrations:
        clean["integrations"] = integrations
    return strip_profile_secrets(clean)


def profile_export_bundle() -> dict:
    settings = config()
    return {
        "version": 1,
        "app": "Lifey",
        "exportedAt": dt.datetime.now(dt.timezone.utc).isoformat(),
        "profile": {
            "preferences": safe_profile_preferences(settings),
            "archiveTemplate": settings.get("archiveTemplate", ""),
            "locationArchiveTemplates": archive_templates(),
            "archiveTitles": archive_titles(),
            "obsidian": {"dailyNotesPath": settings.get("dailyNotesPath", "")},
            "location": {
                "radiusMeters": grouping_radius(),
                "localPlaceLabels": settings.get("localPlaceLabels", []),
                "placeMerges": settings.get("placeMerges", []),
                "osmPlacesEnabled": bool(settings.get("osmPlacesEnabled")),
            },
        },
        "excludedSecrets": PROFILE_EXCLUDED_SECRETS,
    }


def clean_profile_import(body: dict) -> dict:
    profile = body.get("profile", body) if isinstance(body, dict) else {}
    if not isinstance(profile, dict):
        raise ValueError("Invalid Lifey profile.")
    updates: dict = {}
    preferences = profile.get("preferences", {})
    if not isinstance(preferences, dict):
        preferences = {}
    clean_preferences = {key: strip_profile_secrets(preferences[key]) for key in PROFILE_PREFERENCE_FIELDS if key in preferences}
    if clean_preferences:
        updates["profilePreferences"] = clean_preferences
    archive_template = str(profile.get("archiveTemplate", "") or "").strip()
    if archive_template:
        if len(archive_template) > 20_000 or not has_archive_markers(archive_template):
            raise ValueError("The daily archive template must begin and end with ---.")
        updates["archiveTemplate"] = archive_template
    location_templates = profile.get("locationArchiveTemplates")
    if isinstance(location_templates, dict):
        merged = {key: str(location_templates.get(key) or DEFAULT_LOCATION_ARCHIVE_TEMPLATES[key]).strip() for key in DEFAULT_LOCATION_ARCHIVE_TEMPLATES}
        if any(not has_archive_markers(template) for template in merged.values()):
            raise ValueError("Each location archive template must begin and end with ---.")
        updates["locationArchiveTemplates"] = merged
    titles = profile.get("archiveTitles")
    if isinstance(titles, dict):
        merged_titles = {key: str(titles.get(key) or DEFAULT_ARCHIVE_TITLES[key]).strip()[:160] for key in DEFAULT_ARCHIVE_TITLES}
        if any(not value for value in merged_titles.values()):
            raise ValueError("Every archive needs a title.")
        updates["archiveTitles"] = merged_titles
    obsidian = profile.get("obsidian")
    if isinstance(obsidian, dict):
        daily_path = str(obsidian.get("dailyNotesPath", "") or "").strip()
        if daily_path:
            updates["dailyNotesPath"] = daily_path[:2000]
    location = profile.get("location")
    if isinstance(location, dict):
        if "radiusMeters" in location:
            radius = int(location.get("radiusMeters", 50))
            if not 20 <= radius <= 500:
                raise ValueError("Location radius must be between 20 and 500 metres.")
            updates["placeGroupingRadiusMeters"] = radius
        labels = location.get("localPlaceLabels")
        if isinstance(labels, list):
            clean_labels = []
            for label in labels[:500]:
                if not isinstance(label, dict):
                    continue
                name = str(label.get("name", "")).strip()[:120]
                try:
                    latitude, longitude = float(label.get("latitude")), float(label.get("longitude"))
                    radius = int(label.get("radiusMeters", 50))
                except (TypeError, ValueError):
                    continue
                if name and -90 <= latitude <= 90 and -180 <= longitude <= 180:
                    clean_labels.append({"name": name, "latitude": latitude, "longitude": longitude, "radiusMeters": max(20, min(500, radius))})
            updates["localPlaceLabels"] = clean_labels
        merges = location.get("placeMerges")
        if isinstance(merges, list):
            updates["placeMerges"] = strip_profile_secrets(merges[:500])
        if "osmPlacesEnabled" in location:
            updates["osmPlacesEnabled"] = bool(location.get("osmPlacesEnabled"))
    if not updates:
        raise ValueError("No importable Lifey settings were found.")
    return updates


def has_archive_markers(text: str) -> bool:
    lines = text.strip().splitlines()
    return len(lines) >= 2 and lines[0].strip() == START and lines[-1].strip() == END


def archive_block(text: str) -> re.Pattern[str] | None:
    legacy = re.compile(re.escape(LEGACY_START) + r"[\s\S]*?" + re.escape(LEGACY_END))
    if legacy.search(text):
        return legacy
    # A divider followed by the archive heading makes the simple Markdown markers safe to find.
    modern = re.compile(r"^---[ \t]*\r?\n(?=## Lifey\b)[\s\S]*?^---[ \t]*$", re.MULTILINE)
    return modern if modern.search(text) else None


def tailscale_ipv4() -> str | None:
    """Use the Mac's private tailnet address, never its public or LAN address."""
    try:
        result = subprocess.run(["tailscale", "ip", "-4"], capture_output=True, text=True, timeout=3, check=False)
        address = result.stdout.strip().splitlines()[0]
        return address if re.fullmatch(r"100\.(?:6[4-9]|[7-9]\d|1[01]\d|12[0-7])(?:\.\d{1,3}){2}", address) else None
    except (OSError, subprocess.SubprocessError, IndexError):
        return None


def activity_log() -> dict:
    try:
        return json.loads(ACTIVITY.read_text())
    except (OSError, json.JSONDecodeError):
        return {}


def save_activity(values: dict) -> None:
    ACTIVITY.write_text(json.dumps(values, indent=2))


def quote_path(value: str) -> str:
    return urlencode({"": value})[1:]


def base64url_bytes(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def google_oauth_status(settings: dict | None = None) -> dict:
    settings = settings or config()
    return {
        "configured": bool(google_client_id(settings)),
        "hasClientSecret": bool(google_client_secret(settings)),
        "connected": bool(settings.get("googleRefreshToken")),
        "email": settings.get("googleAccountEmail", ""),
        "calendar": google_calendar_id(settings),
        "gmailQuery": google_gmail_query(settings),
        "clientId": google_client_id(settings),
    }


def google_client_id(settings: dict | None = None) -> str:
    settings = settings or config()
    return str(settings.get("googleClientId") or settings.get("profilePreferences", {}).get("integrations", {}).get("google", {}).get("clientId") or "").strip()


def google_client_secret(settings: dict | None = None) -> str:
    settings = settings or config()
    return str(settings.get("googleClientSecret", "")).strip()


def google_calendar_id(settings: dict | None = None) -> str:
    settings = settings or config()
    return str(settings.get("googleCalendarId") or settings.get("profilePreferences", {}).get("integrations", {}).get("google", {}).get("calendar") or "primary").strip() or "primary"


def google_gmail_query(settings: dict | None = None) -> str:
    settings = settings or config()
    return str(settings.get("gmailQuery") or settings.get("profilePreferences", {}).get("integrations", {}).get("gmail", {}).get("query") or "newer_than:14d (medium OR newsletter)").strip()


def google_oauth_request(payload: dict) -> dict:
    body = urlencode(payload).encode()
    req = urlrequest.Request("https://oauth2.googleapis.com/token", data=body, method="POST", headers={"Content-Type": "application/x-www-form-urlencoded"})
    try:
        with urlrequest.urlopen(req, context=SSL_CONTEXT, timeout=12) as response:
            return json.loads(response.read())
    except urlerror.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise ValueError(f"Google OAuth failed ({error.code}): {detail}")


def google_api_request(method: str, url: str, token: str, payload: dict | None = None) -> dict:
    data = json.dumps(payload).encode() if payload is not None else None
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    if payload is not None:
        headers["Content-Type"] = "application/json"
    req = urlrequest.Request(url, data=data, method=method, headers=headers)
    try:
        with urlrequest.urlopen(req, context=SSL_CONTEXT, timeout=15) as response:
            raw = response.read()
            return json.loads(raw) if raw else {}
    except urlerror.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        if error.code == 401:
            raise ValueError("Google authorization expired. Reconnect Google on this Mac.")
        raise ValueError(f"Google API failed ({error.code}): {detail}")


def google_access_token() -> str:
    settings = config()
    client_id = google_client_id(settings)
    refresh_token = str(settings.get("googleRefreshToken", "")).strip()
    if not client_id:
        raise ValueError("Add a Google Desktop OAuth Client ID first.")
    if not refresh_token:
        raise ValueError("Connect Google on this Mac first.")
    payload = {"client_id": client_id, "refresh_token": refresh_token, "grant_type": "refresh_token"}
    if google_client_secret(settings):
        payload["client_secret"] = google_client_secret(settings)
    token = google_oauth_request(payload)
    access_token = token.get("access_token")
    if not access_token:
        raise ValueError("Google did not return an access token. Reconnect Google on this Mac.")
    return access_token


def google_auth_url() -> str:
    settings = config()
    client_id = google_client_id(settings)
    if not client_id:
        raise ValueError("Add a Google Desktop OAuth Client ID first.")
    if not google_client_secret(settings):
        raise ValueError("Add and save the Google Desktop OAuth Client Secret first.")
    verifier = base64url_bytes(secrets.token_bytes(64))
    challenge = base64url_bytes(hashlib.sha256(verifier.encode()).digest())
    state = secrets.token_urlsafe(24)
    save_config({"googleOAuthState": state, "googleCodeVerifier": verifier, "googleRedirectUri": GOOGLE_REDIRECT_URI})
    return "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode({
        "client_id": client_id,
        "redirect_uri": GOOGLE_REDIRECT_URI,
        "response_type": "code",
        "scope": GOOGLE_SCOPES,
        "access_type": "offline",
        "prompt": "consent",
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    })


def google_finish_auth(query: dict[str, list[str]]) -> str:
    settings = config()
    if query.get("error"):
        raise ValueError(f"Google authorization failed: {query.get('error', ['unknown'])[0]}")
    state = query.get("state", [""])[0]
    code = query.get("code", [""])[0]
    if not state or not secrets.compare_digest(state, str(settings.get("googleOAuthState", ""))):
        save_config({"googleOAuthState": "", "googleCodeVerifier": ""})
        raise ValueError("Google authorization state did not match. That usually means this was an old Google tab or Lifey was restarted mid-login. Start the connection again from Lifey.")
    if not code:
        raise ValueError("Google did not return an authorization code.")
    payload = {
        "client_id": google_client_id(settings),
        "code": code,
        "code_verifier": str(settings.get("googleCodeVerifier", "")),
        "redirect_uri": str(settings.get("googleRedirectUri") or GOOGLE_REDIRECT_URI),
        "grant_type": "authorization_code",
    }
    if google_client_secret(settings):
        payload["client_secret"] = google_client_secret(settings)
    token = google_oauth_request(payload)
    refresh_token = token.get("refresh_token") or settings.get("googleRefreshToken")
    if not refresh_token:
        raise ValueError("Google did not return a refresh token. Reconnect and approve offline access.")
    access_token = token.get("access_token")
    email = ""
    if access_token:
        try:
            email = google_api_request("GET", "https://openidconnect.googleapis.com/v1/userinfo", access_token).get("email", "")
        except ValueError:
            email = ""
    save_config({"googleRefreshToken": refresh_token, "googleAccountEmail": email, "googleOAuthState": "", "googleCodeVerifier": "", "googleRedirectUri": GOOGLE_REDIRECT_URI})
    return email


def google_calendar_today() -> dict:
    settings = config()
    token = google_access_token()
    start = dt.datetime.now().astimezone().replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + dt.timedelta(days=1)
    query = urlencode({"singleEvents": "true", "orderBy": "startTime", "timeMin": start.isoformat(), "timeMax": end.isoformat()})
    return google_api_request("GET", f"https://www.googleapis.com/calendar/v3/calendars/{quote_path(google_calendar_id(settings))}/events?{query}", token)


def google_calendar_create(body: dict) -> dict:
    token = google_access_token()
    return google_api_request("POST", f"https://www.googleapis.com/calendar/v3/calendars/{quote_path(google_calendar_id())}/events", token, body)


def google_calendar_update(event_id: str, body: dict) -> dict:
    token = google_access_token()
    return google_api_request("PATCH", f"https://www.googleapis.com/calendar/v3/calendars/{quote_path(google_calendar_id())}/events/{quote_path(event_id)}", token, body)


def google_calendar_delete(event_id: str) -> dict:
    token = google_access_token()
    return google_api_request("DELETE", f"https://www.googleapis.com/calendar/v3/calendars/{quote_path(google_calendar_id())}/events/{quote_path(event_id)}", token)


def google_gmail_suggestions() -> dict:
    token = google_access_token()
    result = google_api_request("GET", f"https://gmail.googleapis.com/gmail/v1/users/me/messages?{urlencode({'q': google_gmail_query(), 'maxResults': '6'})}", token)
    messages = []
    for item in result.get("messages", [])[:6]:
        message_id = item.get("id", "")
        if not message_id:
            continue
        detail = google_api_request("GET", f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{quote_path(message_id)}?format=metadata&metadataHeaders=Subject&metadataHeaders=From", token)
        headers = {header.get("name"): header.get("value", "") for header in detail.get("payload", {}).get("headers", [])}
        messages.append({"id": message_id, "subject": headers.get("Subject", "(No subject)"), "from": headers.get("From", "Gmail"), "snippet": detail.get("snippet", "")})
    return {"messages": messages}


def mobile_location_samples() -> list[dict]:
    """Read Lifey Location's durable, phone-originated sample store."""
    try:
        data = json.loads(MOBILE_LOCATIONS.read_text())
        return data if isinstance(data, list) else []
    except (OSError, json.JSONDecodeError):
        return []


def mobile_positions(start: dt.datetime, end: dt.datetime) -> list[dict]:
    """Convert phone-originated samples into the same shape used by Traccar."""
    positions = []
    for sample in mobile_location_samples():
        stamp = parse_stamp(sample.get("capturedAt"))
        if not stamp or not start <= stamp.astimezone() < end:
            continue
        positions.append({
            "latitude": sample.get("latitude"),
            "longitude": sample.get("longitude"),
            "fixTime": stamp.astimezone().isoformat(),
            "deviceTime": stamp.astimezone().isoformat(),
            "accuracy": sample.get("accuracyMeters"),
            "source": "Lifey Location",
        })
    return positions


def location_positions(start: dt.datetime, end: dt.datetime) -> tuple[list[dict], str]:
    """Prefer Lifey Location samples, then fall back to a configured Traccar device."""
    phone_positions = mobile_positions(start, end)
    if phone_positions:
        return phone_positions, "Lifey Location"
    settings = config()
    if settings.get("traccarServer") and settings.get("traccarToken") and settings.get("traccarDeviceId"):
        return traccar_positions(start, end), "Traccar"
    return [], "Lifey Location"


def save_mobile_location_samples(samples: list[dict]) -> None:
    MOBILE_LOCATIONS.parent.mkdir(parents=True, exist_ok=True)
    MOBILE_LOCATIONS.write_text(json.dumps(samples, indent=2))


def location_collector_token() -> str:
    token = config().get("lifeyLocationToken", "")
    if token:
        return token
    token = secrets.token_urlsafe(32)
    save_config({"lifeyLocationToken": token})
    return token


def add_mobile_location_samples(samples: list[dict]) -> tuple[int, int]:
    """Validate/deduplicate an idempotent batch sent by the iOS collector."""
    existing = mobile_location_samples()
    known = {str(item.get("id", "")) for item in existing}
    added = 0
    for sample in samples[:250]:
        try:
            sample_id = str(sample["id"]).strip()
            latitude, longitude = float(sample["latitude"]), float(sample["longitude"])
            captured_at = parse_stamp(sample.get("capturedAt"))
        except (KeyError, TypeError, ValueError):
            continue
        if not captured_at or not sample_id or sample_id in known or not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
            continue
        existing.append({
            "id": sample_id[:100], "latitude": latitude, "longitude": longitude,
            "capturedAt": captured_at.astimezone().isoformat(),
            "accuracyMeters": max(0, min(float(sample.get("accuracyMeters", 0)), 50_000)),
            "source": "Lifey Location",
        })
        known.add(sample_id); added += 1
    existing.sort(key=lambda item: item.get("capturedAt", ""))
    # Keep all recent history and cap pathological growth without making retention a daily concern.
    save_mobile_location_samples(existing[-200_000:])
    return added, len(existing)


def youtube_video_identity(raw_url: str, raw_video_id: str = "") -> tuple[str, str, str] | None:
    parsed = urlparse(raw_url)
    if parsed.scheme != "https" or not parsed.netloc.endswith("youtube.com"):
        return None
    video_id = raw_video_id.strip()
    kind = "watch"
    if not video_id and parsed.path == "/watch":
        video_id = parse_qs(parsed.query).get("v", [""])[0].strip()
    if not video_id and parsed.path.startswith("/shorts/"):
        parts = [part for part in parsed.path.split("/") if part]
        video_id = parts[1].strip() if len(parts) > 1 else ""
        kind = "shorts"
    if not video_id:
        return None
    canonical = f"https://www.youtube.com/shorts/{video_id}" if kind == "shorts" else f"https://www.youtube.com/watch?v={video_id}"
    return video_id, canonical, kind


def youtube_normalized_videos(videos: list[dict]) -> list[dict]:
    merged: dict[str, dict] = {}
    for video in videos or []:
        identity = youtube_video_identity(str(video.get("url", "")), str(video.get("videoId", "")))
        if not identity:
            continue
        video_id, canonical_url, kind = identity
        item = merged.setdefault(video_id, {
            "title": video.get("title") or "YouTube video",
            "url": canonical_url,
            "videoId": video_id,
            "kind": kind,
            "firstSeen": video.get("firstSeen", ""),
            "lastSeen": video.get("lastSeen", ""),
            "activeSeconds": 0,
        })
        if video.get("title"):
            item["title"] = video["title"]
        item["activeSeconds"] += int(video.get("activeSeconds", 0) or 0)
        if video.get("firstSeen") and (not item.get("firstSeen") or video["firstSeen"] < item["firstSeen"]):
            item["firstSeen"] = video["firstSeen"]
        if video.get("lastSeen") and video["lastSeen"] > item.get("lastSeen", ""):
            item["lastSeen"] = video["lastSeen"]
    return list(merged.values())


def youtube_today() -> dict:
    log = activity_log()
    today = dt.date.today().isoformat()
    data = youtube_day_data(log, today)
    videos = sorted(youtube_normalized_videos(data.get("videos", [])), key=lambda video: (int(video.get("activeSeconds", 0)), video.get("lastSeen", "")), reverse=True)
    return {"date": today, "videos": videos, "totalActiveSeconds": sum(video.get("activeSeconds", 0) for video in videos), "extensionLastSeen": log.get("youtubeExtensionLastSeen")}


def youtube_day_data(log: dict, date: str) -> dict:
    days = log.get("youtubeDays", {})
    if isinstance(days, dict) and isinstance(days.get(date), dict):
        return days[date]
    current = log.get("youtube", {})
    if isinstance(current, dict) and current.get("date") == date:
        return current
    return {"date": date, "videos": []}


def youtube_week() -> dict:
    log = activity_log()
    start, _ = period_bounds("week")
    days = []
    aggregate: dict[str, dict] = {}
    for offset in range(7):
        date = (start.date() + dt.timedelta(days=offset)).isoformat()
        data = youtube_day_data(log, date)
        videos = sorted(youtube_normalized_videos(data.get("videos", [])), key=lambda video: (int(video.get("activeSeconds", 0)), video.get("lastSeen", "")), reverse=True)
        total = sum(video.get("activeSeconds", 0) for video in videos)
        days.append({"date": date, "videos": videos, "totalActiveSeconds": total})
        for video in videos:
            key = video.get("videoId") or video.get("url") or video.get("title") or f"{date}:{len(aggregate)}"
            item = aggregate.setdefault(key, {"title": video.get("title", "YouTube video"), "url": video.get("url", ""), "videoId": video.get("videoId", ""), "kind": video.get("kind", "watch"), "activeSeconds": 0, "firstSeen": video.get("firstSeen", ""), "lastSeen": video.get("lastSeen", "")})
            item["title"] = video.get("title") or item["title"]
            item["url"] = video.get("url") or item["url"]
            item["videoId"] = video.get("videoId") or item.get("videoId", "")
            item["kind"] = video.get("kind") or item.get("kind", "watch")
            item["activeSeconds"] += int(video.get("activeSeconds", 0))
            if video.get("firstSeen") and (not item.get("firstSeen") or video["firstSeen"] < item["firstSeen"]):
                item["firstSeen"] = video["firstSeen"]
            if video.get("lastSeen") and video["lastSeen"] > item.get("lastSeen", ""):
                item["lastSeen"] = video["lastSeen"]
    top_videos = sorted(aggregate.values(), key=lambda video: (video.get("activeSeconds", 0), video.get("lastSeen", "")), reverse=True)
    return {"start": start.date().isoformat(), "days": days, "videos": top_videos, "totalActiveSeconds": sum(day["totalActiveSeconds"] for day in days), "extensionLastSeen": log.get("youtubeExtensionLastSeen")}


def notion_request(method: str, path: str, token: str, payload: dict | None = None) -> dict:
    body = json.dumps(payload).encode() if payload is not None else None
    req = urlrequest.Request(f"https://api.notion.com/v1{path}", data=body, method=method, headers={"Authorization": f"Bearer {token}", "Notion-Version": "2026-03-11", "Content-Type": "application/json"})
    try:
        with urlrequest.urlopen(req, timeout=15, context=SSL_CONTEXT) as response:
            return json.loads(response.read())
    except urlerror.HTTPError as error:
        detail = json.loads(error.read() or b"{}").get("message", error.reason)
        raise ValueError(f"Notion: {detail}") from error


def traccar_request(path: str, token: str, server: str) -> dict:
    target = server.rstrip("/") + path
    req = urlrequest.Request(target, headers={"Authorization": f"Bearer {token}"})
    try:
        with urlrequest.urlopen(req, timeout=20, context=SSL_CONTEXT) as response:
            raw = response.read()
            if response.headers.get("Content-Encoding", "").lower() == "gzip" or raw.startswith(b"\x1f\x8b"):
                raw = gzip.decompress(raw)
            for candidate in (raw,):
                for encoding in ("utf-8", "latin-1"):
                    try:
                        return json.loads(candidate.decode(encoding))
                    except (UnicodeDecodeError, json.JSONDecodeError):
                        continue
            try:
                decompressed = zlib.decompress(raw)
                for encoding in ("utf-8", "latin-1"):
                    try:
                        return json.loads(decompressed.decode(encoding))
                    except (UnicodeDecodeError, json.JSONDecodeError):
                        continue
            except zlib.error:
                pass
            raise ValueError("Traccar returned a response Lifey could not decode. Refresh Traccar and try again.")
    except urlerror.HTTPError as error:
        raise ValueError(f"Traccar endpoint {target} returned {error.code} {error.reason}") from error


def google_place(latitude: float, longitude: float) -> dict | None:
    settings = config(); key = settings.get("googlePlacesKey", "")
    if not key: return None
    cache_key = f"{latitude:.3f},{longitude:.3f}"; cache = settings.get("placeCache", {})
    if cache_key in cache: return cache[cache_key]
    payload = json.dumps({"maxResultCount": 1, "locationRestriction": {"circle": {"center": {"latitude": latitude, "longitude": longitude}, "radius": 100.0}}}).encode()
    req = urlrequest.Request("https://places.googleapis.com/v1/places:searchNearby", data=payload, method="POST", headers={"Content-Type": "application/json", "X-Goog-Api-Key": key, "X-Goog-FieldMask": "places.displayName,places.formattedAddress"})
    try:
        with urlrequest.urlopen(req, timeout=12, context=SSL_CONTEXT) as response: data = json.loads(response.read())
        place = (data.get("places") or [{}])[0]; result = {"name": place.get("displayName", {}).get("text"), "address": place.get("formattedAddress")}
        if result["name"]: cache[cache_key] = result; save_config({"placeCache": cache, "osmLastError": ""}); return result
    except (urlerror.URLError, urlerror.HTTPError): return None


def osm_place(latitude: float, longitude: float) -> dict | None:
    global LAST_NOMINATIM_REQUEST
    settings = config(); cache_key = f"osm:{latitude:.3f},{longitude:.3f}"; cache = settings.get("placeCache", {})
    if cache_key in cache: return cache[cache_key]
    time.sleep(max(0, 1 - (time.monotonic() - LAST_NOMINATIM_REQUEST))); LAST_NOMINATIM_REQUEST = time.monotonic()
    url = "https://nominatim.openstreetmap.org/reverse?" + urlencode({"lat": latitude, "lon": longitude, "format": "jsonv2", "zoom": 18, "namedetails": 1})
    try:
        req = urlrequest.Request(url, headers={"User-Agent": "TodayCommandCenter/0.1 (personal local dashboard)"})
        with urlrequest.urlopen(req, timeout=12, context=SSL_CONTEXT) as response: data = json.loads(response.read())
        display = data.get("display_name", ""); result = {"name": data.get("namedetails", {}).get("name") or display.split(",")[0], "address": display}
        if result["name"]: cache[cache_key] = result; save_config({"placeCache": cache}); return result
    except (urlerror.URLError, urlerror.HTTPError) as error:
        save_config({"osmLastError": str(error)}); return None


def distance_meters(latitude_a: float, longitude_a: float, latitude_b: float, longitude_b: float) -> float:
    """Return the great-circle distance without sending coordinates anywhere."""
    from math import asin, cos, radians, sin, sqrt
    lat_delta = radians(latitude_b - latitude_a)
    lon_delta = radians(longitude_b - longitude_a)
    a = sin(lat_delta / 2) ** 2 + cos(radians(latitude_a)) * cos(radians(latitude_b)) * sin(lon_delta / 2) ** 2
    return 6_371_000 * 2 * asin(sqrt(a))


def local_place_label(latitude: float, longitude: float) -> dict | None:
    matches = []
    for label in config().get("localPlaceLabels", []):
        try:
            distance = distance_meters(latitude, longitude, float(label["latitude"]), float(label["longitude"]))
            if distance <= float(label.get("radiusMeters", 50)):
                matches.append((distance, label))
        except (KeyError, TypeError, ValueError):
            continue
    if not matches:
        return None
    distance, label = min(matches, key=lambda item: item[0])
    return {"name": label["name"], "distance": round(distance)}


def grouping_radius() -> int:
    try:
        return max(20, min(500, int(config().get("placeGroupingRadiusMeters", 50))))
    except (TypeError, ValueError):
        return 50


def manual_merge_for(latitude: float, longitude: float) -> dict | None:
    for merge in config().get("placeMerges", []):
        for anchor in merge.get("anchors", []):
            try:
                if distance_meters(latitude, longitude, float(anchor["latitude"]), float(anchor["longitude"])) <= float(merge.get("anchorRadiusMeters", 50)):
                    return merge
            except (KeyError, TypeError, ValueError):
                continue
    return None


def is_coordinate_label(value: str) -> bool:
    return bool(re.fullmatch(r"-?\d+\.\d+,\s*-?\d+\.\d+", str(value).strip()))


def consolidate_place_visits(visits: list[dict]) -> list[dict]:
    """Combine separate visits to the same slider-defined place and sum dwell time."""
    groups: list[dict] = []
    for visit in visits:
        latitude, longitude = float(visit["latitude"]), float(visit["longitude"])
        merge_id = visit.get("mergeId")
        local = local_place_label(latitude, longitude)
        group = None
        if merge_id:
            group = next((item for item in groups if item.get("mergeId") == merge_id), None)
        elif local:
            group = next((item for item in groups if item.get("localLabel") == local["name"]), None)
        if not group:
            group = next((item for item in groups if not merge_id and not item.get("mergeId") and not item.get("localLabel") and distance_meters(item["_lastLatitude"], item["_lastLongitude"], latitude, longitude) <= grouping_radius()), None)
        if not group:
            group = {**visit, "_lastLatitude": latitude, "_lastLongitude": longitude, "_names": [visit["name"]], "_ranges": [visit], "totalSeconds": 0, "visits": 0}
            if merge_id:
                group["mergeId"] = merge_id
            if local:
                group["localLabel"] = local["name"]
            groups.append(group)
        else:
            group["departure"] = visit["departure"]
            group["_lastLatitude"], group["_lastLongitude"] = latitude, longitude
            group["_names"].append(visit["name"])
            group["_ranges"].append(visit)
            group.setdefault("points", []).extend(visit.get("points", []))
        group["totalSeconds"] += place_duration_seconds(visit)
        group["visits"] += 1
    for group in groups:
        meaningful_names = list(dict.fromkeys(name for name in group.pop("_names") if not is_coordinate_label(name)))
        if meaningful_names:
            group["name"] = " – ".join(meaningful_names[:2])
        group.pop("_ranges", None)
        group.pop("_lastLatitude", None)
        group.pop("_lastLongitude", None)
        group.pop("localLabel", None)
    return groups


def traccar_places(positions: list[dict], source_label: str = "Traccar") -> list[dict]:
    positions.sort(key=lambda item: item.get("fixTime", "")); places = []
    radius = grouping_radius()
    for point in positions:
        latitude, longitude = point.get("latitude", 0), point.get("longitude", 0); label = point.get("address") or f"{latitude:.4f}, {longitude:.4f}"
        stamp = point.get("fixTime") or point.get("deviceTime")
        # Compare to the latest point in a stay, not its first point. iPhone GPS
        # can drift enough over several 10-minute samples to exceed the radius
        # from the original point even while the phone never left the place.
        near_previous = places and distance_meters(places[-1]["_lastLatitude"], places[-1]["_lastLongitude"], latitude, longitude) <= radius
        if not near_previous:
            places.append({"name": label, "label": label, "latitude": latitude, "longitude": longitude, "_lastLatitude": latitude, "_lastLongitude": longitude, "arrival": stamp, "departure": stamp, "source": source_label, "points": [{"latitude": latitude, "longitude": longitude, "timestamp": stamp}]})
        else:
            places[-1]["departure"] = stamp
            places[-1]["_lastLatitude"], places[-1]["_lastLongitude"] = latitude, longitude
            places[-1]["points"].append({"latitude": latitude, "longitude": longitude, "timestamp": stamp})
    osm_budget = 1
    for place in places:
        merge = manual_merge_for(place["latitude"], place["longitude"])
        if merge:
            place["name"] = merge["name"]
            place["source"] = f"Merged · {source_label}"
            place["merged"] = True
            place["mergeId"] = merge["id"]
            continue
        local_label = local_place_label(place["latitude"], place["longitude"])
        if local_label:
            place["name"] = local_label["name"]
            place["source"] = f"Local label · {source_label}"
            place["labelDistance"] = local_label["distance"]
            continue
        osm_cache_key = f"osm:{place['latitude']:.3f},{place['longitude']:.3f}"
        settings = config()
        was_cached = osm_cache_key in settings.get("placeCache", {})
        use_osm = settings.get("osmPlacesEnabled") and (was_cached or osm_budget > 0)
        if settings.get("googlePlacesKey"):
            enriched, source = google_place(place["latitude"], place["longitude"]), f"Google Places · {source_label}"
        elif use_osm:
            enriched, source = osm_place(place["latitude"], place["longitude"]), f"OpenStreetMap · {source_label}"
        else:
            enriched, source = None, source_label
        if use_osm and not settings.get("googlePlacesKey") and not was_cached: osm_budget -= 1
        if enriched: place["name"] = enriched["name"]; place["address"] = enriched.get("address"); place["source"] = source
    return consolidate_place_visits(places)


def parse_stamp(value: str | None) -> dt.datetime | None:
    if not value:
        return None
    if isinstance(value, (int, float)):
        # Swift Date's default Codable form is seconds since 2001-01-01.
        # Accept Unix seconds too so older queued batches are not lost.
        base = 978_307_200 if value < 1_200_000_000 else 0
        try:
            return dt.datetime.fromtimestamp(value + base, tz=dt.timezone.utc)
        except (OSError, OverflowError, ValueError):
            return None
    try:
        return dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def traccar_positions(start: dt.datetime, end: dt.datetime) -> list[dict]:
    settings = config()
    query = "/api/reports/route?" + urlencode({
        "deviceId": settings["traccarDeviceId"],
        "from": start.astimezone(dt.timezone.utc).isoformat(),
        "to": end.astimezone(dt.timezone.utc).isoformat(),
    })
    return traccar_request(query, settings["traccarToken"], settings["traccarServer"])


def period_bounds(period: str) -> tuple[dt.datetime, dt.datetime]:
    now = dt.datetime.now().astimezone()
    start_day = now.replace(hour=0, minute=0, second=0, microsecond=0)
    if period == "today":
        return start_day, start_day + dt.timedelta(days=1)
    if period == "week":
        return start_day - dt.timedelta(days=start_day.weekday()), start_day + dt.timedelta(days=1)
    if period == "weekly":
        start = start_day - dt.timedelta(days=start_day.weekday())
        return start, start + dt.timedelta(days=7)
    if period == "monthly":
        start = start_day.replace(day=1)
        next_month = (start.replace(day=28) + dt.timedelta(days=4)).replace(day=1)
        return start, next_month
    if period == "yearly":
        start = start_day.replace(month=1, day=1)
        return start, start.replace(year=start.year + 1)
    raise ValueError("Choose today, week, weekly, monthly, or yearly.")


def place_duration_seconds(place: dict) -> int:
    if "totalSeconds" in place:
        return max(0, int(place["totalSeconds"]))
    start, end = parse_stamp(place.get("arrival")), parse_stamp(place.get("departure"))
    if not start or not end:
        return 0
    return max(0, round((end - start).total_seconds()))


def human_duration(seconds: int) -> str:
    minutes = max(0, round(seconds / 60))
    if minutes < 1:
        return "<1 min"
    if minutes < 60:
        return f"{minutes} min"
    hours, remainder = divmod(minutes, 60)
    return f"{hours}h" + (f" {remainder}m" if remainder else "")


def place_key(place: dict) -> str:
    if place.get("mergeId"):
        return "merge:" + str(place["mergeId"])
    local = local_place_label(float(place.get("latitude", 0)), float(place.get("longitude", 0)))
    if local:
        return "label:" + local["name"].strip().lower()
    return f"coordinate:{float(place.get('latitude', 0)):.3f},{float(place.get('longitude', 0)):.3f}"


def top_places(places: list[dict], limit: int = 10) -> list[dict]:
    totals: list[dict] = []
    for place in places:
        latitude, longitude = float(place.get("latitude", 0)), float(place.get("longitude", 0))
        key = place_key(place)
        item = next((candidate for candidate in totals if candidate["key"] == key), None)
        if not item and key.startswith("coordinate:"):
            item = next((candidate for candidate in totals if candidate["key"].startswith("coordinate:") and distance_meters(candidate["latitude"], candidate["longitude"], latitude, longitude) <= grouping_radius()), None)
        if not item:
            item = {"key": key, "name": place.get("name") or "Unknown place", "seconds": 0, "visits": 0, "source": place.get("source", "Traccar"), "latitude": latitude, "longitude": longitude}
            totals.append(item)
        item["seconds"] += place_duration_seconds(place)
        item["visits"] += 1
    return [{key: value for key, value in item.items() if key not in {"key", "latitude", "longitude"}} for item in sorted(totals, key=lambda item: (item["seconds"], item["visits"]), reverse=True)[:limit]]


def week_location_data(source_mode: str = "auto") -> dict:
    start, end = period_bounds("week")
    if source_mode == "traccar":
        positions, source = traccar_positions(start, end), "Traccar"
    else:
        positions, source = location_positions(start, end)
    by_day: dict[str, list[dict]] = {}
    for point in positions:
        stamp = parse_stamp(point.get("fixTime") or point.get("deviceTime"))
        if stamp:
            by_day.setdefault(stamp.astimezone().date().isoformat(), []).append(point)
    days = []
    all_places: list[dict] = []
    for offset in range(7):
        day = (start.date() + dt.timedelta(days=offset)).isoformat()
        places = traccar_places(by_day.get(day, []), source)
        all_places.extend(places)
        days.append({"date": day, "places": places})
    return {"start": start.date().isoformat(), "end": end.date().isoformat(), "days": days, "topPlaces": top_places(all_places), "positions": len(positions), "source": source}


def notion_data_source(settings: dict) -> str:
    token, parent = settings.get("notionToken", ""), settings.get("notionParentId", "")
    if not token or not parent:
        raise ValueError("Configure a Notion token and database/data source ID first.")
    try:
        notion_request("GET", f"/data_sources/{parent}", token)
        return parent
    except ValueError:
        database = notion_request("GET", f"/databases/{parent}", token)
        sources = database.get("data_sources", [])
        if not sources:
            raise ValueError("That Notion database has no data source.")
        return sources[0]["id"]


def notion_title(item: dict) -> str:
    title = item.get("title") or item.get("name") or []
    if isinstance(title, str):
        return title
    return "".join(part.get("plain_text") or part.get("text", {}).get("content", "") for part in title) or "Untitled"


def daily_names_for(day: dt.date) -> list[str]:
    return [
        f"{day.strftime('%B')} {day.day:02d}, {day.year}.md",
        f"{day.strftime('%B')} {day.day}, {day.year}.md",
        f"{day.isoformat()}.md",
    ]


def daily_names() -> list[str]:
    return daily_names_for(dt.date.today())


def daily_candidate_folders() -> list[Path]:
    raw = config().get("dailyNotesPath", "")
    folder = Path(raw).expanduser()
    if not folder.is_dir():
        raise FileNotFoundError("Configure an existing Journals or Daily notes folder first.")
    folders = [folder]
    folders.append(folder.parent if folder.name.lower() == "daily" else folder / "Daily")
    unique: list[Path] = []
    for item in folders:
        if item not in unique:
            unique.append(item)
    return unique


def daily_file() -> Path:
    today = dt.date.today()
    for candidate_folder in daily_candidate_folders():
        for name in daily_names_for(today):
            candidate = candidate_folder / name
            if candidate.is_file():
                return candidate
    raise FileNotFoundError(f"No note found for today ({daily_names()[0]}).")


def daily_file_for_date(day: dt.date) -> Path | None:
    for candidate_folder in daily_candidate_folders():
        for name in daily_names_for(day):
            candidate = candidate_folder / name
            if candidate.is_file():
                return candidate
    return None


def task_due_date(text: str) -> dt.date | None:
    match = re.search(r"📅\s*(\d{4}-\d{2}-\d{2})", text)
    if not match:
        return None
    try:
        return dt.date.fromisoformat(match.group(1))
    except ValueError:
        return None


def task_section_bounds(lines: list[str]) -> tuple[int | None, int | None]:
    start = next((index for index, line in enumerate(lines) if re.match(r"^#{1,6}\s*Tasks::\s*$", line.strip(), re.IGNORECASE)), None)
    if start is None:
        return None, None
    end = len(lines)
    for index in range(start + 1, len(lines)):
        if re.match(r"^#{1,6}\s+", lines[index]):
            end = index
            break
    return start, end


def archive_start_line(lines: list[str]) -> int | None:
    for index in range(len(lines) - 1):
        if lines[index].strip() == START and re.match(r"^##\s+Lifey\b", lines[index + 1].strip()):
            return index
    return None


def insert_task_under_tasks(note: Path, text: str) -> dict:
    previous = note.read_text()
    lines = previous.splitlines()
    task_line = f"- [ ] {text}"
    start, end = task_section_bounds(lines)
    if start is not None and end is not None:
        prefix = lines[:end]
        suffix = lines[end:]
        while len(prefix) > start + 1 and not prefix[-1].strip():
            prefix.pop()
        insert = []
        if len(prefix) == start + 1:
            insert.append("")
        insert.append(task_line)
        if suffix and suffix[0].strip():
            insert.append("")
        line_number = len(prefix) + insert.index(task_line) + 1
        updated_lines = prefix + insert + suffix
    else:
        habit_start, _ = habit_section_bounds(lines)
        archive_start = archive_start_line(lines)
        candidates = [index for index in (archive_start, habit_start) if index is not None]
        insert_at = min(candidates) if candidates else len(lines)
        prefix = lines[:insert_at]
        suffix = lines[insert_at:]
        while prefix and not prefix[-1].strip():
            prefix.pop()
        insert = []
        if prefix:
            insert.append("")
        insert.extend(["## Tasks::", "", task_line])
        if suffix and suffix[0].strip():
            insert.append("")
        line_number = len(prefix) + insert.index(task_line) + 1
        updated_lines = prefix + insert + suffix
    note.write_text("\n".join(updated_lines).rstrip() + "\n")
    return {"line": line_number, "text": text, "path": str(note), "noteDate": (note_date_from_path(note) or dt.date.fromtimestamp(note.stat().st_mtime)).isoformat()}


def target_note_for_new_task(text: str, prefer_due_date_note: bool = False) -> Path:
    if prefer_due_date_note:
        due = task_due_date(text)
        if due:
            due_note = daily_file_for_date(due)
            if due_note:
                return due_note
    return daily_file()


def journals_folder() -> Path:
    folder = Path(config().get("dailyNotesPath", "")).expanduser()
    if not folder.is_dir():
        raise FileNotFoundError("Configure your Journals folder first.")
    return folder.parent if folder.name.lower() == "daily" else folder


def vault_folder() -> Path:
    journals = journals_folder()
    return journals.parent if journals.name.lower() in {"journals", "journal"} else journals.parent


def note_safe_name(name: str) -> str:
    return re.sub(r"[/:\\]", "-", name).strip()[:160]


def wiki_place(name: str) -> str:
    clean = str(name).replace('"', "'").replace("]]", "").strip() or "Unknown place"
    return f'[[Place - "{clean}"]]'


def project_slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


def project_title_from_slug(slug: str) -> str:
    return " ".join(part.capitalize() for part in slug.split("-") if part) or slug


def decimal_field(body: str, field: str) -> float:
    match = re.search(rf"\[{re.escape(field)}::\s*([0-9]+(?:\.[0-9]+)?)\]", body, re.IGNORECASE)
    return float(match.group(1)) if match else 0.0


def strip_project_task_text(body: str) -> str:
    clean = re.sub(r"#project/[A-Za-z0-9/_-]+", "", body)
    clean = re.sub(r"#milestone\b", "", clean)
    clean = re.sub(r"\[(?:estimate|time)::\s*[0-9]+(?:\.[0-9]+)?\]", "", clean, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", clean).strip()


def project_notes() -> dict[str, dict]:
    projects_dir = vault_folder() / "Projects"
    notes: dict[str, dict] = {}
    if not projects_dir.is_dir():
        return notes
    for note in sorted(projects_dir.glob("*.md")):
        slug = project_slug(note.stem)
        notes[slug] = {"slug": slug, "title": note.stem, "path": str(note)}
    return notes


def project_task_notes() -> list[Path]:
    folders: list[Path] = []
    for folder in daily_candidate_folders():
        if folder.is_dir() and folder not in folders:
            folders.append(folder)
    notes: list[Path] = []
    for folder in folders:
        notes.extend(sorted(folder.glob("*.md")))
    return sorted(set(notes))


def parse_project_tasks_from_note(note: Path) -> list[dict]:
    try:
        markdown = note.read_text()
    except OSError:
        return []
    lines = markdown.splitlines()
    start, end = habit_section_bounds(lines)
    tasks = []
    for index, line in enumerate(lines):
        if start is not None and end is not None and start < index < end:
            continue
        match = re.match(r"^\s*-\s+\[([ xX])\]\s+(.+?)\s*$", line)
        if not match:
            continue
        body = match.group(2).strip()
        project_tags = re.findall(r"#project/([A-Za-z0-9/_-]+)", body)
        if not project_tags:
            continue
        for raw_slug in project_tags:
            slug = project_slug(raw_slug)
            if not slug:
                continue
            tasks.append({
                "projectSlug": slug,
                "projectTag": f"#project/{raw_slug}",
                "text": strip_project_task_text(body),
                "raw": body,
                "done": match.group(1).lower() == "x",
                "milestone": bool(re.search(r"#milestone\b", body)),
                "estimate": decimal_field(body, "estimate"),
                "time": decimal_field(body, "time"),
                "source": str(note),
                "line": index + 1,
                "date": (note_date_from_path(note) or dt.date.fromtimestamp(note.stat().st_mtime)).isoformat(),
            })
    return tasks


def projects_summary() -> dict:
    notes = project_notes()
    tasks = [task for note in project_task_notes() for task in parse_project_tasks_from_note(note)]
    grouped: dict[str, dict] = {}
    for slug, note in notes.items():
        grouped[slug] = {**note, "tasks": []}
    for task in tasks:
        slug = task["projectSlug"]
        grouped.setdefault(slug, {"slug": slug, "title": project_title_from_slug(slug), "path": "", "tasks": []})
        grouped[slug]["tasks"].append(task)
    projects = []
    for project in grouped.values():
        project_tasks = sorted(project["tasks"], key=lambda item: (not item["milestone"], item["done"], item["date"], item["line"]))
        completed = sum(1 for task in project_tasks if task["done"])
        milestones = [task for task in project_tasks if task["milestone"]]
        projects.append({
            **{key: project.get(key, "") for key in ("slug", "title", "path")},
            "taskCount": len(project_tasks),
            "completedCount": completed,
            "openCount": len(project_tasks) - completed,
            "milestoneCount": len(milestones),
            "milestoneCompleted": sum(1 for task in milestones if task["done"]),
            "estimateTotal": round(sum(task["estimate"] for task in project_tasks), 2),
            "timeTotal": round(sum(task["time"] for task in project_tasks), 2),
            "tasks": project_tasks,
        })
    projects.sort(key=lambda item: (item["openCount"] == 0, -item["milestoneCount"], -item["openCount"], item["title"].lower()))
    return {"projects": projects, "taskCount": len(tasks), "projectsPath": str(vault_folder() / "Projects"), "templatePath": str(vault_folder() / "Templates" / "Project.md")}


def project_note_path(slug: str, title: str = "") -> Path:
    notes = project_notes()
    if slug in notes and notes[slug].get("path"):
        return Path(notes[slug]["path"])
    return vault_folder() / "Projects" / f"{note_safe_name(title or project_title_from_slug(slug))}.md"


def create_project_note(slug: str, title: str = "") -> dict:
    clean_slug = project_slug(slug or title)
    if not clean_slug:
        raise ValueError("Choose a project name first.")
    project_title = title.strip() or project_title_from_slug(clean_slug)
    destination = project_note_path(clean_slug, project_title)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if not destination.exists():
        templates_dir = vault_folder() / "Templates"
        template = templates_dir / "Project.md"
        if not template.is_file():
            template = templates_dir / "Project"
        content = template.read_text() if template.is_file() else "# {{title}}\n\n## Tasks\n\n```tasks\nnot done\ntag includes #project/{{slug}}\n```\n"
        content = content.replace("{{title}}", project_title).replace("{{project}}", project_title).replace("{{slug}}", clean_slug)
        destination.write_text(content.rstrip() + "\n")
    return {"slug": clean_slug, "title": project_title, "path": str(destination)}


def open_project_note(slug: str) -> dict:
    note = project_note_path(project_slug(slug))
    if not note.is_file():
        raise FileNotFoundError("Create the project note first.")
    subprocess.run(["open", str(note)], check=False)
    return {"opened": True, "path": str(note)}


def safe_project_task_source(source: str) -> Path:
    source_path = Path(source).expanduser().resolve()
    allowed = [folder.resolve() for folder in daily_candidate_folders()]
    if not any(source_path.is_relative_to(folder) for folder in allowed):
        raise ValueError("Project task source must be inside your Daily Notes folders.")
    if not source_path.is_file():
        raise FileNotFoundError("Project task source note no longer exists.")
    return source_path


def update_project_task(body: dict) -> dict:
    note = safe_project_task_source(str(body.get("source", "")))
    line_number = int(body.get("line", 0))
    expected_text = str(body.get("previousText", "")).strip()
    lines = note.read_text().splitlines(keepends=True)
    if not 1 <= line_number <= len(lines):
        raise ValueError("Project task line no longer exists.")
    if line_in_habit_section(lines, line_number):
        raise ValueError("That line is inside Habits::. Use the Habits card instead.")
    match = re.match(r"^(\s*-\s+\[)[ xX](\]\s+)(.*?)(\r?\n?)$", lines[line_number - 1])
    if not match or match.group(3).strip() != expected_text:
        raise ValueError("Project task changed in Obsidian. Refresh projects first.")
    if "completed" in body:
        marker = "x" if body.get("completed") else " "
        replacement_text = match.group(3)
    else:
        marker = "x" if match.group(0).lower().find("[x]") >= 0 else " "
        replacement_text = " ".join(str(body.get("text", "")).splitlines()).strip()
        if not replacement_text:
            raise ValueError("Write a task first.")
        if "#project/" not in replacement_text:
            raise ValueError("Project tasks must keep a #project/... tag.")
    lines[line_number - 1] = match.group(1) + marker + match.group(2) + replacement_text + match.group(4)
    note.write_text("".join(lines))
    return {"line": line_number, "path": str(note), "text": replacement_text, "completed": marker == "x"}


WEEKDAY_CODES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def habits_config_path() -> Path:
    root = journals_folder()
    preferred = root / "Habits" / "Active Habits.md"
    fallback = root / "Active Habits.md"
    return preferred if preferred.exists() or not fallback.exists() else fallback


def split_markdown_table_row(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def normalise_habit_time(value: str) -> tuple[str, int | None]:
    raw = (value or "").strip()
    if not raw:
        return "", None
    cleaned = raw.lower().replace(".", "")
    match = re.match(r"^(\d{1,2})(?::([0-5]\d))?\s*(am|pm)?$", cleaned)
    if not match:
        return raw, None
    hour = int(match.group(1))
    minute = int(match.group(2) or 0)
    period = match.group(3)
    if period:
        if hour == 12:
            hour = 0
        if period == "pm":
            hour += 12
    if hour > 23:
        return raw, None
    return f"{hour:02d}:{minute:02d}", hour * 60 + minute


def habit_note_schedule(body: str) -> dict:
    time_label = ""
    time_minutes = None
    time_match = re.search(r"⏰\s*(\d{1,2}(?::[0-5]\d)?\s*(?:a\.?m\.?|p\.?m\.?)?)", body, re.IGNORECASE)
    if not time_match:
        time_match = re.search(r"\b(?:at\s+)?(\d{1,2}(?::[0-5]\d)?\s*(?:a\.?m\.?|p\.?m\.?))\b", body, re.IGNORECASE)
    if not time_match:
        time_match = re.search(r"\b(?:at\s+)?([01]?\d|2[0-3]):([0-5]\d)\b", body)
    if time_match:
        time_value = f"{time_match.group(1)}:{time_match.group(2)}" if len(time_match.groups()) > 1 and time_match.group(2) else time_match.group(1)
        time_label, time_minutes = normalise_habit_time(time_value)
    date_match = re.search(r"📅\s*(\d{4}-\d{2}-\d{2})", body)
    return {
        "dueDate": date_match.group(1) if date_match else "",
        "time": time_label,
        "timeMinutes": time_minutes,
    }


def habit_body_without_schedule(body: str) -> str:
    cleaned = re.sub(r"\s*📅\s*\d{4}-\d{2}-\d{2}", "", body)
    cleaned = re.sub(r"\s*⏰\s*\d{1,2}(?::[0-5]\d)?\s*(?:a\.?m\.?|p\.?m\.?)?", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*\b(?:at\s+)?\d{1,2}(?::[0-5]\d)?\s*(?:a\.?m\.?|p\.?m\.?)\b", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*\b(?:at\s+)?(?:[01]?\d|2[0-3]):[0-5]\d\b", "", cleaned)
    return re.sub(r"\s+", " ", cleaned).strip()


def read_habit_config() -> list[dict]:
    path = habits_config_path()
    if not path.is_file():
        return []
    rows: list[str] = []
    for line in path.read_text().splitlines():
        if line.strip().startswith("|"):
            rows.append(line)
        elif rows:
            break
    if len(rows) < 2:
        return []
    headers = [header.strip().lower() for header in split_markdown_table_row(rows[0])]
    habits = []
    for order, line in enumerate(rows[2:]):
        if re.match(r"^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?\s*$", line):
            continue
        cells = split_markdown_table_row(line)
        if not cells or not any(cells):
            continue
        item = {headers[index]: cells[index] if index < len(cells) else "" for index in range(len(headers))}
        name = item.get("habit", "").strip()
        if not name:
            continue
        days_raw = item.get("days", "Daily").strip() or "Daily"
        days = ["Daily"] if days_raw.lower() == "daily" else [day.strip() for day in days_raw.split(",") if day.strip()]
        try:
            start = dt.date.fromisoformat(item.get("start", "").strip())
        except ValueError:
            start = None
        try:
            duration = int(item.get("duration", "").strip()) if item.get("duration", "").strip() else None
        except ValueError:
            duration = None
        time_label, time_minutes = normalise_habit_time(item.get("time", ""))
        habits.append({
            "habit": name,
            "start": start.isoformat() if start else "",
            "duration": duration,
            "days": days,
            "daysText": days_raw,
            "time": time_label,
            "timeMinutes": time_minutes,
            "order": order,
            "label": item.get("label", "Day").strip() or "Day",
            "status": item.get("status", "").strip().lower() or "active",
        })
    return habits


def note_date_from_path(path: Path) -> dt.date | None:
    stem = path.stem
    for pattern in ("%B %d, %Y", "%B %e, %Y", "%Y-%m-%d"):
        try:
            return dt.datetime.strptime(stem, pattern).date()
        except ValueError:
            continue
    return None


def habit_scheduled_for(habit: dict, day: dt.date) -> bool:
    if habit.get("status") != "active":
        return False
    try:
        start = dt.date.fromisoformat(habit.get("start", ""))
        if day < start:
            return False
    except ValueError:
        pass
    days = habit.get("days") or ["Daily"]
    return "Daily" in days or WEEKDAY_CODES[day.weekday()] in days


def habit_progress_label(habit: dict, day: dt.date) -> str:
    label = habit.get("label") or "Day"
    try:
        start = dt.date.fromisoformat(habit.get("start", ""))
        number = (day - start).days + 1
    except ValueError:
        number = 1
    suffix = f"/{habit['duration']}" if habit.get("duration") else ""
    return f"{label} {max(1, number)}{suffix}"


def expected_habits_for(day: dt.date) -> list[dict]:
    expected = []
    for habit in read_habit_config():
        if not habit_scheduled_for(habit, day):
            continue
        label = habit_progress_label(habit, day)
        metadata = f" ⏰ {habit['time']}" if habit.get("time") else ""
        expected.append({**habit, "date": day.isoformat(), "progress": label, "text": f"{habit['habit']} — {label}{metadata}"})
    return sorted(expected, key=habit_sort_key)


def habit_sort_key(habit: dict) -> tuple[str, int, int, int, str]:
    due_date = habit.get("dueDate") or habit.get("date") or ""
    minutes = habit.get("timeMinutes")
    return (due_date, 0 if isinstance(minutes, int) else 1, minutes if isinstance(minutes, int) else 24 * 60, int(habit.get("order", 9999)), habit.get("habit", "").lower())


def attach_habit_config(habits: list[dict], config_habits: list[dict]) -> list[dict]:
    by_name = {habit.get("habit", "").strip().lower(): habit for habit in config_habits}
    enriched = []
    for habit in habits:
        config_habit = by_name.get(habit.get("habit", "").strip().lower(), {})
        enriched.append({
            **habit,
            "dueDate": habit.get("dueDate") or config_habit.get("date", ""),
            "time": habit.get("time") or config_habit.get("time", ""),
            "timeMinutes": habit.get("timeMinutes") if isinstance(habit.get("timeMinutes"), int) else config_habit.get("timeMinutes"),
            "order": config_habit.get("order", 9999),
        })
    return sorted(enriched, key=habit_sort_key)


def habit_section_bounds(lines: list[str]) -> tuple[int | None, int | None]:
    start = next((index for index, line in enumerate(lines) if re.match(r"^(?:#{1,6}\s*)?Habits::\s*$", line.strip(), re.IGNORECASE)), None)
    if start is None:
        return None, None
    end = len(lines)
    for index in range(start + 1, len(lines)):
        if re.match(r"^#{1,6}\s+", lines[index]):
            end = index
            break
    return start, end


def line_in_habit_section(lines: list[str], line_number: int) -> bool:
    start, end = habit_section_bounds([line.rstrip("\r\n") for line in lines])
    return start is not None and end is not None and start < line_number - 1 < end


def parse_habit_lines(markdown: str, source: str = "") -> list[dict]:
    lines = markdown.splitlines()
    start, end = habit_section_bounds(lines)
    if start is None or end is None:
        return []
    habits = []
    for index in range(start + 1, end):
        match = re.match(r"^(\s*)-\s+\[([ xX-])\]\s+(.+?)\s*$", lines[index])
        if not match:
            continue
        body = match.group(3).strip()
        schedule = habit_note_schedule(body)
        clean_body = habit_body_without_schedule(body)
        name, progress = (clean_body.split(" — ", 1) + [""])[:2] if " — " in clean_body else (clean_body, "")
        marker = match.group(2).lower()
        state = "completed" if marker == "x" else "skipped" if marker == "-" else "pending"
        habits.append({"habit": name.strip(), "progress": progress.strip(), "text": body, **schedule, "state": state, "line": index + 1, "source": source})
    return habits


def sync_today_habits() -> dict:
    note = daily_file()
    day = note_date_from_path(note) or dt.date.today()
    previous = note.read_text()
    lines = previous.splitlines()
    start, end = habit_section_bounds(lines)
    if start is None:
        if lines and lines[-1].strip():
            lines.append("")
        lines.extend(["## Habits::"])
        start, end = len(lines) - 1, len(lines)
    existing = parse_habit_lines("\n".join(lines), str(note))
    existing_names = {item["habit"].strip().lower() for item in existing}
    additions = [habit for habit in expected_habits_for(day) if habit["habit"].strip().lower() not in existing_names]
    if additions:
        insert_at = end if end is not None else len(lines)
        new_lines = [f"- [ ] {habit['text']}" for habit in additions]
        lines[insert_at:insert_at] = new_lines
        note.write_text("\n".join(lines).rstrip() + "\n")
    return habits_today()


def habits_today() -> dict:
    note = daily_file()
    day = note_date_from_path(note) or dt.date.today()
    markdown = note.read_text()
    config_habits = read_habit_config()
    parsed = attach_habit_config([{**habit, "date": day.isoformat()} for habit in parse_habit_lines(markdown, str(note))], config_habits)
    expected = expected_habits_for(day)
    archived = [habit for habit in config_habits if habit.get("status") != "active"]
    return {"date": day.isoformat(), "path": str(note), "habits": parsed, "expected": expected, "archived": archived, "configPath": str(habits_config_path())}


def update_today_habit(line_number: int, habit: str, state: str) -> dict:
    note = daily_file()
    lines = note.read_text().splitlines(keepends=True)
    if not 1 <= line_number <= len(lines):
        raise ValueError("Habit line no longer exists in today's note.")
    if not line_in_habit_section(lines, line_number):
        raise ValueError("That line is not inside the Habits:: section. Refresh habits first.")
    match = re.match(r"^(\s*-\s+\[)[ xX-](\]\s+)(.*?)(\r?\n?)$", lines[line_number - 1])
    if not match:
        raise ValueError("Habit line changed in Obsidian. Refresh habits first.")
    body = match.group(3).strip()
    current_name = body.split(" — ", 1)[0].strip()
    if current_name != habit:
        raise ValueError("Habit changed in Obsidian. Refresh habits first.")
    marker = {"completed": "x", "pending": " ", "skipped": "-"}.get(state)
    if marker is None:
        raise ValueError("Choose completed, pending, or skipped.")
    lines[line_number - 1] = match.group(1) + marker + match.group(2) + match.group(3) + match.group(4)
    note.write_text("".join(lines))
    return habits_today()


def habit_history(range_name: str = "month") -> dict:
    today = dt.date.today()
    month_start = today.replace(day=1)
    entries = []
    daily_totals: dict[str, dict] = {}
    habit_names: set[str] = set()
    for folder in daily_candidate_folders():
        if not folder.is_dir():
            continue
        for note in sorted(folder.glob("*.md")):
            day = note_date_from_path(note)
            if not day or (range_name != "all" and day < month_start):
                continue
            try:
                habits = parse_habit_lines(note.read_text(), str(note))
            except OSError:
                continue
            if not habits:
                continue
            total = daily_totals.setdefault(day.isoformat(), {"date": day.isoformat(), "completed": 0, "scheduled": 0, "skipped": 0})
            for habit in habits:
                habit_names.add(habit["habit"])
                entries.append({**habit, "date": day.isoformat()})
                total["scheduled"] += 1
                if habit["state"] == "completed":
                    total["completed"] += 1
                if habit["state"] == "skipped":
                    total["skipped"] += 1
    config_habits = read_habit_config()
    config_by_name = {habit.get("habit", "").strip().lower(): habit for habit in config_habits}
    entries = [{**entry, "time": config_by_name.get(entry.get("habit", "").strip().lower(), {}).get("time", ""), "timeMinutes": config_by_name.get(entry.get("habit", "").strip().lower(), {}).get("timeMinutes"), "order": config_by_name.get(entry.get("habit", "").strip().lower(), {}).get("order", 9999)} for entry in entries]
    archived = [habit for habit in config_habits if habit.get("status") != "active"]
    for habit in config_habits:
        habit_names.add(habit["habit"])
    return {"range": range_name, "entries": sorted(entries, key=lambda item: (item.get("date", ""), *habit_sort_key(item))), "dailyTotals": sorted(daily_totals.values(), key=lambda item: item["date"]), "habits": sorted(habit_names), "active": sorted([h for h in config_habits if h.get("status") == "active"], key=habit_sort_key), "archived": sorted(archived, key=habit_sort_key)}


def archive_period_title(period: str) -> str:
    today = dt.datetime.now().astimezone().date()
    if period == "weekly":
        return f"{((today.day - 1) // 7) + 1}th Week of {today.strftime('%B')}, {today.year}"
    if period == "monthly":
        return f"{today.strftime('%B')}, {today.year}"
    if period == "yearly":
        return str(today.year)
    raise ValueError("Choose weekly, monthly, or yearly.")


def archive_templates() -> dict:
    saved = config().get("locationArchiveTemplates", {})
    return {key: str(saved.get(key) or value) for key, value in DEFAULT_LOCATION_ARCHIVE_TEMPLATES.items()}


def archive_titles() -> dict:
    saved = config().get("archiveTitles", {})
    titles = {key: str(saved.get(key) or value) for key, value in DEFAULT_ARCHIVE_TITLES.items()}
    if titles["daily"] == "Lifey · mmm dd, yyyy":
        titles["daily"] = DEFAULT_ARCHIVE_TITLES["daily"]
    return titles


def moment_ordinal(value: int) -> str:
    return f"{value}{'th' if 10 <= value % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(value % 10, 'th')}"


def moment_format(value: dt.datetime, pattern: str = "YYYY-MM-DDTHH:mm:ssZ") -> str:
    """A compact local Moment-style formatter for archive titles."""
    literals: list[str] = []
    def hold(match):
        literals.append(match.group(1)); return f"\x00{len(literals) - 1}\x00"
    pattern = re.sub(r"\[([^\]]*)\]", hold, pattern)
    weekday = (value.weekday() + 1) % 7
    day_year = int(value.strftime("%j"))
    iso_year, iso_week, iso_day = value.isocalendar()
    locale_week = int(value.strftime("%U")) + 1
    offset = value.utcoffset() or dt.timedelta()
    offset_minutes = int(offset.total_seconds() // 60); sign = "+" if offset_minutes >= 0 else "-"; offset_minutes = abs(offset_minutes)
    zone = value.tzname() or ""
    milliseconds = f"{value.microsecond // 1000:03d}"
    tokens = {
        "YYYYYY": f"{value.year:+07d}", "YYYY": f"{value.year:04d}", "YY": f"{value.year % 100:02d}", "Y": str(value.year),
        "MMMM": value.strftime("%B"), "MMM": value.strftime("%b"), "MM": f"{value.month:02d}", "Mo": moment_ordinal(value.month), "M": str(value.month),
        "DDDD": f"{day_year:03d}", "DDDo": moment_ordinal(day_year), "DDD": str(day_year), "DD": f"{value.day:02d}", "Do": moment_ordinal(value.day), "D": str(value.day),
        "dddd": value.strftime("%A"), "ddd": value.strftime("%a"), "dd": value.strftime("%a")[:2], "do": moment_ordinal(weekday), "d": str(weekday), "e": str(weekday), "E": str(iso_day),
        "Qo": moment_ordinal((value.month - 1) // 3 + 1), "Q": str((value.month - 1) // 3 + 1),
        "ww": f"{locale_week:02d}", "wo": moment_ordinal(locale_week), "w": str(locale_week), "WW": f"{iso_week:02d}", "Wo": moment_ordinal(iso_week), "W": str(iso_week),
        "gggg": str(value.year), "gg": f"{value.year % 100:02d}", "GGGG": str(iso_year), "GG": f"{iso_year % 100:02d}",
        "HH": f"{value.hour:02d}", "H": str(value.hour), "hh": f"{value.hour % 12 or 12:02d}", "h": str(value.hour % 12 or 12), "kk": f"{value.hour or 24:02d}", "k": str(value.hour or 24),
        "mm": f"{value.minute:02d}", "m": str(value.minute), "ss": f"{value.second:02d}", "s": str(value.second), "A": "AM" if value.hour < 12 else "PM", "a": "am" if value.hour < 12 else "pm",
        "z": zone, "zz": zone, "Z": f"{sign}{offset_minutes // 60:02d}:{offset_minutes % 60:02d}", "ZZ": f"{sign}{offset_minutes // 60:02d}{offset_minutes % 60:02d}", "X": str(int(value.timestamp())), "x": str(int(value.timestamp() * 1000)),
        "N": "AD" if value.year >= 1 else "BC", "NN": "AD" if value.year >= 1 else "BC", "NNN": "AD" if value.year >= 1 else "BC", "NNNN": "Anno Domini" if value.year >= 1 else "Before Christ", "NNNNN": "AD" if value.year >= 1 else "BC", "y": str(value.year),
    }
    token_pattern = re.compile(r"YYYYYY|YYYY|YY|Y|MMMM|MMM|MM|Mo|M|DDDD|DDDo|DDD|DD|Do|D|dddd|ddd|dd|do|d|Qo|Q|ww|wo|w|WW|Wo|W|gggg|gg|GGGG|GG|HH|H|hh|h|kk|k|mm|m|ss|s|A|a|zz|z|ZZ|Z|X|x|NNNNN|NNNN|NNN|NN|N|y|e|E|S{1,9}")
    def replace(match):
        token = match.group(0)
        if token.startswith("S"):
            return (milliseconds + "0" * len(token))[:len(token)]
        return tokens[token]
    rendered = token_pattern.sub(replace, pattern)
    return re.sub(r"\x00(\d+)\x00", lambda match: literals[int(match.group(1))], rendered)


def resolved_archive_title(period: str) -> str:
    title = archive_titles()[period].replace("{{date}}", "MMMM DD, YYYY")
    return moment_format(dt.datetime.now().astimezone(), title).replace("{{period}}", archive_period_title(period))


def render_location_archive(period: str, places: list[dict], daily_places: str = "") -> str:
    template = archive_templates()[period]
    if not has_archive_markers(template):
        raise ValueError("Location archive templates must begin and end with ---.")
    rows = top_places(places, 20 if period == "yearly" else 10)
    top_markdown = "\n".join(f"- {wiki_place(item['name'])} — {human_duration(item['seconds'])} · {item['visits']} visit(s)" for item in rows) or "- No places recorded"
    values = {"period": archive_period_title(period), "topPlaces": top_markdown, "dailyPlaces": daily_places or "- No places recorded"}
    rendered = re.sub(r"\{\{(\w+)\}\}", lambda match: values.get(match.group(1), match.group(0)), template)
    return re.sub(r"^##\s+.*$", f"## {resolved_archive_title(period)}", rendered, count=1, flags=re.MULTILINE)


def write_generated_note(path: Path, title: str, generated: str) -> Path | None:
    if path.exists():
        previous = path.read_text()
        backup = path.with_name(f"{path.stem}.lifey-backup-{dt.datetime.now():%Y%m%d-%H%M%S}.md")
        backup.write_text(previous)
        block = archive_block(previous)
        path.write_text(block.sub(generated, previous) if block else previous.rstrip() + "\n\n" + generated + "\n")
        return backup
    path.write_text(f"# {title}\n\n{generated}\n")
    return None


def place_note_title(name: str) -> str:
    clean = str(name).replace('"', "'").replace("]]", "").strip() or "Unknown place"
    return f'Place - "{clean}"'


def unique_archive_path(path: Path) -> Path:
    candidate = path.with_name(f"{path.stem}-lifey-archive{path.suffix}")
    if not candidate.exists():
        return candidate
    return path.with_name(f"{path.stem}-lifey-archive-{dt.datetime.now():%Y%m%d-%H%M%S}{path.suffix}")


def merge_place_notes(name: str, source_names: list[str]) -> dict:
    """Preserve old place notes by moving them aside and collecting them in the merged note."""
    root = journals_folder()
    target_title = place_note_title(name)
    target_path = root / f"{note_safe_name(target_title)}.md"
    archived = []
    source_sections = []
    for source_name in dict.fromkeys(str(item).strip() for item in source_names if str(item).strip()):
        source_title = place_note_title(source_name)
        source_path = root / f"{note_safe_name(source_title)}.md"
        entry = {"name": source_name, "original": source_path.name, "archive": "", "existed": source_path.exists()}
        if source_path.exists() and source_path != target_path:
            old_content = source_path.read_text()
            archive_path = unique_archive_path(source_path)
            source_path.rename(archive_path)
            entry["archive"] = archive_path.name
            source_sections.append(f"\n\n### Archived source · {source_name}\n\n{old_content.strip()}\n")
        archived.append(entry)
    if source_sections:
        if target_path.exists():
            target_path.write_text(target_path.read_text().rstrip() + "".join(source_sections) + "\n")
        else:
            target_path.write_text(f"# {target_title}\n\n## Merged place notes\n" + "".join(source_sections) + "\n")
    elif not target_path.exists():
        target_path.write_text(f"# {target_title}\n\n## Merged place notes\n\nCreated by Lifey.\n")
    return {"target": target_path.name, "sources": archived}


def create_place_merge(name: str, places: list[dict]) -> dict:
    clean_name = str(name).strip()[:120]
    if not clean_name:
        raise ValueError("Give the merged place a name.")
    anchors = []
    source_names = []
    for place in places:
        try:
            latitude, longitude = float(place["latitude"]), float(place["longitude"])
        except (KeyError, TypeError, ValueError):
            continue
        anchors.append({"latitude": latitude, "longitude": longitude})
        source_names.append(str(place.get("name") or "Unknown place"))
    if len(anchors) < 2:
        raise ValueError("Select at least two places to merge.")
    merge = {
        "id": f"merge-{int(time.time() * 1000)}",
        "name": clean_name,
        "anchors": anchors,
        "anchorRadiusMeters": grouping_radius(),
        "createdAt": dt.datetime.now().astimezone().isoformat(),
    }
    merge.update(merge_place_notes(clean_name, source_names))
    settings = config()
    settings["placeMerges"] = [*settings.get("placeMerges", []), merge]
    save_config(settings)
    return merge


def undo_place_merge(merge_id: str) -> dict:
    settings = config()
    merges = settings.get("placeMerges", [])
    merge = next((item for item in merges if item.get("id") == merge_id), None)
    if not merge:
        raise ValueError("That place merge no longer exists.")
    root = journals_folder()
    restored, skipped = [], []
    for source in merge.get("sources", []):
        archive_name, original_name = source.get("archive"), source.get("original")
        if not archive_name or not original_name:
            continue
        archive_path, original_path = root / archive_name, root / original_name
        if archive_path.exists() and not original_path.exists():
            archive_path.rename(original_path)
            restored.append(original_name)
        elif archive_path.exists():
            skipped.append(original_name)
    settings["placeMerges"] = [item for item in merges if item.get("id") != merge_id]
    save_config(settings)
    return {"restored": restored, "skipped": skipped, "name": merge.get("name", "Merged place")}


def write_location_archive(period: str) -> dict:
    start, end = period_bounds(period)
    positions, source = location_positions(start, end)
    places = traccar_places(positions, source)
    daily_places = ""
    if period == "weekly":
        by_day: dict[str, list[dict]] = {}
        for point in positions:
            stamp = parse_stamp(point.get("fixTime") or point.get("deviceTime"))
            if stamp:
                by_day.setdefault(stamp.astimezone().date().isoformat(), []).append(point)
        daily_sections = []
        for offset in range(7):
            date = start.date() + dt.timedelta(days=offset)
            visits = traccar_places(by_day.get(date.isoformat(), []), source)
            rows = "\n".join(f"- {wiki_place(visit['name'])} — {human_duration(place_duration_seconds(visit))}" for visit in visits) or "- No places recorded"
            daily_sections.append(f"### {date.strftime('%A, %B')} {date.day}\n{rows}")
        daily_places = "\n\n".join(daily_sections)
    title = archive_period_title(period)
    generated = render_location_archive(period, places, daily_places)
    root = journals_folder()
    note = root / f"{note_safe_name(title)}.md"
    backup = write_generated_note(note, title, generated)
    place_notes = []
    for item in top_places(places, 20 if period == "yearly" else 10):
        place_title = place_note_title(item["name"])
        place_generated = f"---\n## Lifey · Place report\n\n- Latest archive: [[{title}]]\n- {human_duration(item['seconds'])} this period · {item['visits']} visit(s)\n---"
        place_path = root / f"{note_safe_name(place_title)}.md"
        write_generated_note(place_path, place_title, place_generated)
        place_notes.append(place_path.name)
    return {"path": str(note), "backup": str(backup) if backup else None, "placeNotes": place_notes, "positions": len(positions), "source": source}


class Handler(SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        super().end_headers()

    def do_OPTIONS(self):
        self.send_response(HTTPStatus.NO_CONTENT)
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()

    def json(self, value: dict, status=HTTPStatus.OK):
        payload = json.dumps(value).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def html(self, value: str, status=HTTPStatus.OK):
        payload = value.encode()
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", 0))
        return json.loads(self.rfile.read(length) or b"{}")

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        if path == "/api/obsidian/status":
            settings = config()
            return self.json({"configured": bool(settings.get("dailyNotesPath")), "dailyNotesPath": settings.get("dailyNotesPath", ""), "notionConfigured": bool(settings.get("notionToken") and settings.get("notionParentId")), "archiveTemplate": settings.get("archiveTemplate", "")})
        if path == "/api/profile/preferences":
            return self.json({"preferences": config().get("profilePreferences", {})})
        if path == "/api/profile/export":
            return self.json(profile_export_bundle())
        if path == "/api/google/status":
            return self.json(google_oauth_status())
        if path == "/api/google/auth/start":
            try:
                if self.client_address[0] not in {"127.0.0.1", "::1"}:
                    return self.json({"error": "Google must be connected from the Mac at http://127.0.0.1:4173."}, HTTPStatus.FORBIDDEN)
                self.send_response(HTTPStatus.FOUND)
                self.send_header("Location", google_auth_url())
                self.end_headers()
                return
            except ValueError as error:
                return self.json({"error": str(error)}, HTTPStatus.BAD_REQUEST)
        if path == "/api/google/auth/callback":
            try:
                email = google_finish_auth(parse_qs(parsed.query))
                escaped_email = email.replace("<", "&lt;").replace(">", "&gt;") or "your Google account"
                return self.html(f"<!doctype html><title>Lifey Google connected</title><meta http-equiv='refresh' content='1;url=/'><body style='font-family:system-ui;background:#2F383E;color:white;padding:32px'><h1>Google connected</h1><p>Lifey is connected to {escaped_email}. Returning to Lifey…</p><p><a style='color:#ff907d' href='/'>Open Lifey</a></p></body>")
            except ValueError as error:
                message = str(error).replace("<", "&lt;").replace(">", "&gt;")
                return self.html(f"<!doctype html><title>Lifey Google error</title><body style='font-family:system-ui;background:#2F383E;color:white;padding:32px'><h1>Google connection failed</h1><p>{message}</p><p><a style='color:#ff907d' href='/'>Back to Lifey</a></p></body>", HTTPStatus.BAD_REQUEST)
        if path == "/api/google/calendar/today":
            try:
                return self.json(google_calendar_today())
            except ValueError as error:
                return self.json({"error": str(error)}, HTTPStatus.BAD_REQUEST)
        if path == "/api/google/gmail/suggestions":
            try:
                return self.json(google_gmail_suggestions())
            except ValueError as error:
                return self.json({"error": str(error)}, HTTPStatus.BAD_REQUEST)
        if path == "/api/notion/status":
            settings = config()
            return self.json({"configured": bool(settings.get("notionToken") and settings.get("notionParentId"))})
        if path == "/api/traccar/status":
            settings = config(); return self.json({"configured": bool(settings.get("traccarServer") and settings.get("traccarToken") and settings.get("traccarDeviceId"))})
        if path == "/api/location/mobile/status":
            samples = mobile_location_samples()
            return self.json({"configured": bool(config().get("lifeyLocationToken")), "samples": len(samples), "latest": samples[-1].get("capturedAt") if samples else None})
        if path == "/api/google-places/status": return self.json({"configured": bool(config().get("googlePlacesKey"))})
        if path == "/api/osm-places/status": return self.json({"configured": bool(config().get("osmPlacesEnabled"))})
        if path == "/api/location-archive-templates": return self.json({"templates": archive_templates()})
        if path == "/api/archive-titles": return self.json({"titles": archive_titles()})
        if path == "/api/location/settings":
            settings = config()
            return self.json({"radiusMeters": grouping_radius(), "merges": settings.get("placeMerges", [])})
        if path == "/api/place-labels": return self.json({"labels": config().get("localPlaceLabels", [])})
        if path == "/api/traccar/today":
            try:
                start, end = period_bounds("today"); positions = traccar_positions(start, end)
                return self.json({"places": traccar_places(positions, "Traccar"), "positions": len(positions), "source": "Traccar", "osmError": config().get("osmLastError", "")})
            except (KeyError, ValueError) as error: return self.json({"error": str(error)}, HTTPStatus.BAD_REQUEST)
        if path == "/api/traccar/week":
            try:
                data = week_location_data("traccar"); data["osmError"] = config().get("osmLastError", "")
                return self.json(data)
            except (KeyError, ValueError) as error: return self.json({"error": str(error)}, HTTPStatus.BAD_REQUEST)
        if path == "/api/location/today":
            try:
                start, end = period_bounds("today"); positions, source = location_positions(start, end)
                return self.json({"places": traccar_places(positions, source), "positions": len(positions), "source": source, "osmError": config().get("osmLastError", "")})
            except ValueError as error: return self.json({"error": str(error)}, HTTPStatus.BAD_REQUEST)
        if path == "/api/location/week":
            try:
                data = week_location_data(); data["osmError"] = config().get("osmLastError", "")
                return self.json(data)
            except ValueError as error: return self.json({"error": str(error)}, HTTPStatus.BAD_REQUEST)
        if path == "/api/habits/today":
            try:
                return self.json(habits_today())
            except (OSError, FileNotFoundError, ValueError) as error:
                return self.json({"error": str(error)}, HTTPStatus.BAD_REQUEST)
        if path == "/api/habits/history":
            try:
                range_name = parse_qs(parsed.query).get("range", ["month"])[0]
                return self.json(habit_history("all" if range_name == "all" else "month"))
            except (OSError, FileNotFoundError, ValueError) as error:
                return self.json({"error": str(error)}, HTTPStatus.BAD_REQUEST)
        if path == "/api/projects":
            try:
                return self.json(projects_summary())
            except (OSError, FileNotFoundError, ValueError) as error:
                return self.json({"error": str(error)}, HTTPStatus.BAD_REQUEST)
        if path == "/api/activity/youtube/today":
            return self.json(youtube_today())
        if path == "/api/activity/youtube/week":
            return self.json(youtube_week())
        if path == "/api/obsidian/daily":
            try:
                note = daily_file()
                return self.json({"name": note.name, "path": str(note), "markdown": note.read_text()})
            except (OSError, FileNotFoundError) as error:
                return self.json({"error": str(error)}, HTTPStatus.NOT_FOUND)
        return super().do_GET()

    def do_POST(self):
        path = urlparse(self.path).path
        try:
            body = self.read_json()
            if path == "/api/location/mobile/setup":
                # This endpoint is intentionally local-only because it returns the collector secret.
                if self.client_address[0] not in {"127.0.0.1", "::1"}:
                    return self.json({"error": "Create the Lifey Location token from the Mac dashboard."}, HTTPStatus.FORBIDDEN)
                return self.json({"token": location_collector_token()})
            if path == "/api/location/mobile/ingest":
                supplied = self.headers.get("Authorization", "").removeprefix("Bearer ").strip()
                if not secrets.compare_digest(supplied, str(config().get("lifeyLocationToken", ""))):
                    return self.json({"error": "Lifey Location is not authorised."}, HTTPStatus.UNAUTHORIZED)
                samples = body.get("samples", [])
                if not isinstance(samples, list):
                    return self.json({"error": "Invalid location batch."}, HTTPStatus.BAD_REQUEST)
                added, total = add_mobile_location_samples(samples)
                return self.json({"accepted": added, "stored": total})
            if path == "/api/obsidian/config":
                folder = Path(body.get("dailyNotesPath", "")).expanduser()
                if not folder.is_dir():
                    return self.json({"error": "That Daily notes folder does not exist."}, HTTPStatus.BAD_REQUEST)
                save_config({"dailyNotesPath": str(folder)})
                return self.json({"dailyNotesPath": str(folder)})
            if path == "/api/profile/preferences":
                preferences = body.get("preferences", {})
                if not isinstance(preferences, dict):
                    return self.json({"error": "Invalid Lifey profile preferences."}, HTTPStatus.BAD_REQUEST)
                clean = {key: strip_profile_secrets(preferences[key]) for key in PROFILE_PREFERENCE_FIELDS if key in preferences}
                save_config({"profilePreferences": clean})
                return self.json({"saved": True, "preferences": clean})
            if path == "/api/profile/import":
                updates = clean_profile_import(body)
                save_config(updates)
                return self.json({"imported": True, "profile": profile_export_bundle()["profile"], "excludedSecrets": PROFILE_EXCLUDED_SECRETS})
            if path == "/api/projects/create":
                return self.json(create_project_note(str(body.get("slug", "")), str(body.get("title", ""))))
            if path == "/api/projects/open":
                return self.json(open_project_note(str(body.get("slug", ""))))
            if path == "/api/projects/task":
                return self.json(update_project_task(body))
            if path == "/api/google/config":
                client_id = str(body.get("clientId", "")).strip()
                client_secret = str(body.get("clientSecret", "")).strip()
                calendar = str(body.get("calendar", "primary")).strip() or "primary"
                gmail_query = str(body.get("gmailQuery", "")).strip()
                if not client_id:
                    return self.json({"error": "Google Desktop OAuth Client ID is required."}, HTTPStatus.BAD_REQUEST)
                updates = {"googleClientId": client_id, "googleCalendarId": calendar, "googleOAuthState": "", "googleCodeVerifier": ""}
                if client_secret:
                    updates["googleClientSecret"] = client_secret
                if gmail_query:
                    updates["gmailQuery"] = gmail_query
                save_config(updates)
                return self.json({"saved": True, "status": google_oauth_status()})
            if path == "/api/google/disconnect":
                save_config({"googleRefreshToken": "", "googleAccountEmail": "", "googleOAuthState": "", "googleCodeVerifier": ""})
                return self.json({"disconnected": True, "status": google_oauth_status()})
            if path == "/api/google/calendar/event":
                return self.json(google_calendar_create(body))
            if path == "/api/google/calendar/event/update":
                event_id = str(body.get("eventId", "")).strip()
                event = body.get("event", {})
                if not event_id or not isinstance(event, dict):
                    return self.json({"error": "Calendar event ID and update are required."}, HTTPStatus.BAD_REQUEST)
                return self.json(google_calendar_update(event_id, event))
            if path == "/api/google/calendar/event/delete":
                event_id = str(body.get("eventId", "")).strip()
                if not event_id:
                    return self.json({"error": "Calendar event ID is required."}, HTTPStatus.BAD_REQUEST)
                google_calendar_delete(event_id)
                return self.json({"deleted": True})
            if path == "/api/obsidian/archive":
                note = daily_file()
                generated = body.get("archive", "")
                if not has_archive_markers(generated):
                    return self.json({"error": "Invalid dashboard archive."}, HTTPStatus.BAD_REQUEST)
                previous = note.read_text()
                block = archive_block(previous)
                updated = block.sub(generated, previous) if block else previous.rstrip() + "\n\n" + generated + "\n"
                backup = note.with_name(f"{note.stem}.dashboard-backup-{dt.datetime.now():%Y%m%d-%H%M%S}.md")
                backup.write_text(previous)
                note.write_text(updated)
                return self.json({"path": str(note), "backup": str(backup)})
            if path == "/api/archive-template":
                template = str(body.get("template", "")).strip()
                if not has_archive_markers(template):
                    return self.json({"error": "Keep both DASHBOARD markers in the archive default."}, HTTPStatus.BAD_REQUEST)
                if len(template) > 20_000:
                    return self.json({"error": "The archive default is too long."}, HTTPStatus.BAD_REQUEST)
                save_config({"archiveTemplate": template})
                return self.json({"saved": True})
            if path == "/api/location-archive-templates":
                templates = body.get("templates", {})
                if not isinstance(templates, dict):
                    return self.json({"error": "Invalid location archive templates."}, HTTPStatus.BAD_REQUEST)
                merged = {key: str(templates.get(key) or DEFAULT_LOCATION_ARCHIVE_TEMPLATES[key]).strip() for key in DEFAULT_LOCATION_ARCHIVE_TEMPLATES}
                if any(not has_archive_markers(template) for template in merged.values()):
                    return self.json({"error": "Each location archive default must begin and end with ---."}, HTTPStatus.BAD_REQUEST)
                save_config({"locationArchiveTemplates": merged})
                return self.json({"saved": True, "templates": merged})
            if path == "/api/archive-titles":
                titles = body.get("titles", {})
                if not isinstance(titles, dict):
                    return self.json({"error": "Invalid archive titles."}, HTTPStatus.BAD_REQUEST)
                merged = {key: str(titles.get(key) or DEFAULT_ARCHIVE_TITLES[key]).strip()[:160] for key in DEFAULT_ARCHIVE_TITLES}
                if any(not value for value in merged.values()):
                    return self.json({"error": "Every archive needs a title."}, HTTPStatus.BAD_REQUEST)
                save_config({"archiveTitles": merged})
                return self.json({"saved": True, "titles": merged})
            if path == "/api/location/settings":
                try:
                    radius = int(body.get("radiusMeters", 50))
                except (TypeError, ValueError):
                    return self.json({"error": "Choose a whole-number distance."}, HTTPStatus.BAD_REQUEST)
                if not 20 <= radius <= 500:
                    return self.json({"error": "Choose a distance from 20 to 500 metres."}, HTTPStatus.BAD_REQUEST)
                save_config({"placeGroupingRadiusMeters": radius})
                return self.json({"radiusMeters": radius, "merges": config().get("placeMerges", [])})
            if path == "/api/place-merges":
                places = body.get("places", [])
                if not isinstance(places, list):
                    return self.json({"error": "Invalid place selection."}, HTTPStatus.BAD_REQUEST)
                merge = create_place_merge(body.get("name", ""), places)
                return self.json({"merge": merge})
            if path == "/api/place-merges/undo":
                result = undo_place_merge(str(body.get("id", "")).strip())
                return self.json(result)
            if path == "/api/obsidian/location-archive":
                period = str(body.get("period", "")).strip()
                if period not in {"weekly", "monthly", "yearly"}:
                    return self.json({"error": "Choose weekly, monthly, or yearly."}, HTTPStatus.BAD_REQUEST)
                return self.json(write_location_archive(period))
            if path == "/api/habits/sync":
                return self.json(sync_today_habits())
            if path == "/api/habits/state":
                line_number = int(body.get("line", 0))
                habit = str(body.get("habit", "")).strip()
                state = str(body.get("state", "")).strip()
                return self.json(update_today_habit(line_number, habit, state))
            if path == "/api/obsidian/task":
                note = daily_file()
                line_number = int(body.get("line", 0))
                expected_text = str(body.get("text", "")).strip()
                lines = note.read_text().splitlines(keepends=True)
                if not 1 <= line_number <= len(lines):
                    return self.json({"error": "Task line no longer exists in today's note."}, HTTPStatus.CONFLICT)
                if line_in_habit_section(lines, line_number):
                    return self.json({"error": "That checkbox is inside Habits::. Use the Habits card to edit it."}, HTTPStatus.CONFLICT)
                match = re.match(r"^(\s*-\s+\[)[ xX](\]\s+)(.*?)(\r?\n?)$", lines[line_number - 1])
                if not match or match.group(3).strip() != expected_text:
                    return self.json({"error": "Task changed in Obsidian. Refresh the daily note before completing it."}, HTTPStatus.CONFLICT)
                mark = "x" if body.get("completed") else " "
                lines[line_number - 1] = match.group(1) + mark + match.group(2) + match.group(3) + match.group(4)
                note.write_text("".join(lines))
                return self.json({"line": line_number, "completed": bool(body.get("completed"))})
            if path == "/api/obsidian/task/edit":
                note = daily_file()
                line_number = int(body.get("line", 0))
                expected_text = str(body.get("previousText", "")).strip()
                text = " ".join(str(body.get("text", "")).splitlines()).strip()
                if not text:
                    return self.json({"error": "Write a task first."}, HTTPStatus.BAD_REQUEST)
                if len(text) > 2_000:
                    return self.json({"error": "Keep the task under 2,000 characters."}, HTTPStatus.BAD_REQUEST)
                lines = note.read_text().splitlines(keepends=True)
                if not 1 <= line_number <= len(lines):
                    return self.json({"error": "Task line no longer exists in today's note."}, HTTPStatus.CONFLICT)
                if line_in_habit_section(lines, line_number):
                    return self.json({"error": "That checkbox is inside Habits::. Use the Habits card to edit it."}, HTTPStatus.CONFLICT)
                match = re.match(r"^(\s*-\s+\[)[ xX](\]\s+)(.*?)(\r?\n?)$", lines[line_number - 1])
                if not match or match.group(3).strip() != expected_text:
                    return self.json({"error": "Task changed in Obsidian. Refresh the daily note before editing it."}, HTTPStatus.CONFLICT)
                lines[line_number - 1] = match.group(1) + ("x" if match.group(0).lower().find("[x]") >= 0 else " ") + match.group(2) + text + match.group(4)
                note.write_text("".join(lines))
                return self.json({"line": line_number, "text": text})
            if path == "/api/obsidian/task/delete":
                note = daily_file()
                line_number = int(body.get("line", 0))
                expected_text = str(body.get("text", "")).strip()
                lines = note.read_text().splitlines(keepends=True)
                if not 1 <= line_number <= len(lines):
                    return self.json({"error": "Task line no longer exists in today's note."}, HTTPStatus.CONFLICT)
                if line_in_habit_section(lines, line_number):
                    return self.json({"error": "That checkbox is inside Habits::. Use the Habits card to edit it."}, HTTPStatus.CONFLICT)
                match = re.match(r"^\s*-\s+\[[ xX]\]\s+(.*?)(?:\r?\n)?$", lines[line_number - 1])
                if not match or match.group(1).strip() != expected_text:
                    return self.json({"error": "Task changed in Obsidian. Refresh the daily note before deleting it."}, HTTPStatus.CONFLICT)
                lines.pop(line_number - 1)
                note.write_text("".join(lines))
                return self.json({"line": line_number, "deleted": True})
            if path == "/api/obsidian/task/add":
                text = " ".join(str(body.get("text", "")).splitlines()).strip()
                if not text:
                    return self.json({"error": "Write a task first."}, HTTPStatus.BAD_REQUEST)
                if len(text) > 2_000:
                    return self.json({"error": "Keep the task under 2,000 characters."}, HTTPStatus.BAD_REQUEST)
                note = target_note_for_new_task(text, bool(body.get("preferDueDateNote")))
                return self.json(insert_task_under_tasks(note, text))
            if path == "/api/notion/config":
                token = str(body.get("token", "")).strip()
                parent = str(body.get("parentId", "")).strip()
                if not token or not parent:
                    return self.json({"error": "Notion token and database/data source ID are required."}, HTTPStatus.BAD_REQUEST)
                settings = config()
                source = notion_data_source({**settings, "notionToken": token, "notionParentId": parent})
                schema = notion_request("GET", f"/data_sources/{source}", token)
                title_property = next((name for name, details in schema.get("properties", {}).items() if details.get("type") == "title"), str(body.get("titleProperty", "Name")).strip() or "Name")
                save_config({"notionToken": token, "notionParentId": parent, "notionDataSourceId": source, "notionTitleProperty": title_property})
                return self.json({"configured": True, "dataSourceId": source, "titleProperty": title_property})
            if path == "/api/traccar/config":
                server, token = str(body.get("server", "")).rstrip("/"), str(body.get("token", "")).strip(); device_id = str(body.get("deviceId", "")).strip()
                devices = traccar_request("/api/devices", token, server)
                if not device_id and len(devices) == 1: device_id = str(devices[0]["id"])
                device = next((item for item in devices if str(item.get("id")) == device_id or str(item.get("uniqueId")) == device_id), None)
                if not device: return self.json({"error": "Add the iPhone as a device in Traccar first, then enter its Identifier or internal ID."}, HTTPStatus.BAD_REQUEST)
                save_config({"traccarServer": server, "traccarToken": token, "traccarDeviceId": str(device["id"])})
                return self.json({"configured": True})
            if path == "/api/google-places/config":
                key = str(body.get("key", "")).strip()
                if not key: return self.json({"error": "Google Maps API key is required."}, HTTPStatus.BAD_REQUEST)
                save_config({"googlePlacesKey": key, "placeCache": {}}); return self.json({"configured": True})
            if path == "/api/osm-places/config":
                save_config({"osmPlacesEnabled": True}); return self.json({"configured": True})
            if path == "/api/place-labels":
                name = str(body.get("name", "")).strip()
                try:
                    latitude, longitude = float(body.get("latitude")), float(body.get("longitude"))
                except (TypeError, ValueError):
                    return self.json({"error": "Choose a valid Traccar place first."}, HTTPStatus.BAD_REQUEST)
                if not name:
                    return self.json({"error": "Enter a name for this place."}, HTTPStatus.BAD_REQUEST)
                labels = config().get("localPlaceLabels", [])
                replacement = {"name": name[:100], "latitude": latitude, "longitude": longitude, "radiusMeters": 50}
                existing = next((index for index, label in enumerate(labels) if distance_meters(latitude, longitude, float(label.get("latitude", 0)), float(label.get("longitude", 0))) <= 50), None)
                if existing is None: labels.append(replacement)
                else: labels[existing] = replacement
                # Local labels are the no-cost replacement for public geocoding.
                save_config({"localPlaceLabels": labels, "osmPlacesEnabled": False, "osmLastError": ""})
                return self.json({"label": replacement, "labels": labels})
            if path == "/api/traccar/devices":
                return self.json({"devices": traccar_request("/api/devices", str(body.get("token", "")), str(body.get("server", "")).rstrip("/"))})
            if path == "/api/activity/youtube":
                url = str(body.get("url", "")).strip()
                title = str(body.get("title", "")).strip() or "YouTube video"
                identity = youtube_video_identity(url, str(body.get("videoId", "")))
                if not identity:
                    return self.json(youtube_today())
                video_id, canonical_url, kind = identity
                now = dt.datetime.now().astimezone().isoformat()
                log = activity_log(); today = dt.date.today().isoformat(); days = log.setdefault("youtubeDays", {})
                if not isinstance(days, dict):
                    days = {}; log["youtubeDays"] = days
                current = log.get("youtube", {})
                if isinstance(current, dict) and current.get("date") and current.get("videos") and current.get("date") not in days:
                    days[current["date"]] = current
                data = days.setdefault(today, {"date": today, "videos": []})
                videos = data.setdefault("videos", [])
                video = next((item for item in videos if item.get("videoId") == video_id or item.get("url") == canonical_url), None)
                if not video:
                    video = {"title": title, "url": canonical_url, "videoId": video_id, "kind": kind, "firstSeen": body.get("firstSeen") or now, "lastSeen": now, "activeSeconds": 0}
                    videos.append(video)
                video["title"] = title
                video["url"] = canonical_url
                video["videoId"] = video_id
                video["kind"] = kind
                video["lastSeen"] = body.get("lastSeen") or now
                video["activeSeconds"] += min(max(int(body.get("activeSeconds", 0)), 0), 60)
                days[today] = data; log["youtube"] = data; save_activity(log)
                return self.json(youtube_today())
            if path == "/api/activity/youtube/ping":
                log = activity_log(); log["youtubeExtensionLastSeen"] = dt.datetime.now().astimezone().isoformat(); save_activity(log)
                return self.json({"ok": True})
            if path == "/api/notion/diagnose":
                token = str(body.get("token", "")).strip(); parent = str(body.get("parentId", "")).strip()
                if not token or not parent:
                    return self.json({"error": "Enter a token and database/data source ID first."}, HTTPStatus.BAD_REQUEST)
                try:
                    me = notion_request("GET", "/users/me", token)
                except ValueError as error:
                    return self.json({"tokenValid": False, "resourceAccessible": False, "message": f"Token failed: {error}"})
                try:
                    notion_request("GET", f"/data_sources/{parent}", token)
                    return self.json({"tokenValid": True, "resourceAccessible": True, "kind": "data source", "message": "Connection is ready. The data source is shared with this token."})
                except ValueError:
                    try:
                        database = notion_request("GET", f"/databases/{parent}", token)
                        return self.json({"tokenValid": True, "resourceAccessible": True, "kind": "database", "message": f"Connection is ready. Database visible; it has {len(database.get('data_sources', []))} data source(s)."})
                    except ValueError:
                        return self.json({"tokenValid": True, "resourceAccessible": False, "message": f"Token is valid for {me.get('name', 'this connection')}, but it cannot see that database. Share the database (or its parent page) through Add connections or Content access."})
            if path == "/api/notion/data-sources":
                token = str(body.get("token", "")).strip()
                if not token:
                    return self.json({"error": "Enter a token first."}, HTTPStatus.BAD_REQUEST)
                found = notion_request("POST", "/search", token, {"page_size": 100, "filter": {"value": "data_source", "property": "object"}})
                sources = [{"id": item.get("id"), "title": notion_title(item), "databaseId": item.get("parent", {}).get("database_id", "")} for item in found.get("results", [])]
                return self.json({"dataSources": sources})
            if path == "/api/notion/task":
                settings = config(); source = settings.get("notionDataSourceId") or notion_data_source(settings)
                title_property = settings.get("notionTitleProperty", "Name")
                text = str(body.get("text", "")).strip()
                if not text:
                    return self.json({"error": "Task text is required."}, HTTPStatus.BAD_REQUEST)
                page = notion_request("POST", "/pages", settings["notionToken"], {"parent": {"type": "data_source_id", "data_source_id": source}, "properties": {title_property: {"title": [{"type": "text", "text": {"content": text}}]}}})
                return self.json({"id": page["id"], "url": page.get("url", "")})
        except json.JSONDecodeError:
            return self.json({"error": "Invalid request."}, HTTPStatus.BAD_REQUEST)
        except (OSError, FileNotFoundError, ValueError) as error:
            return self.json({"error": str(error)}, HTTPStatus.BAD_REQUEST)
        return self.json({"error": "Not found."}, HTTPStatus.NOT_FOUND)


if __name__ == "__main__":
    lan_enabled = os.environ.get("LIFEY_LAN", "").lower() in {"1", "true", "yes"}
    local_host = "0.0.0.0" if lan_enabled else "127.0.0.1"
    local_server = ThreadingHTTPServer((local_host, 4173), Handler)
    tailnet_address = None if lan_enabled else tailscale_ipv4()
    if tailnet_address:
        tailnet_server = ThreadingHTTPServer((tailnet_address, 4173), Handler)
        threading.Thread(target=tailnet_server.serve_forever, daemon=True).start()
        print(f"Lifey → http://127.0.0.1:4173\nLifey on your private Tailscale network → http://{tailnet_address}:4173")
    else:
        print("Lifey → http://127.0.0.1:4173")
    if lan_enabled:
        print("Lifey on this Wi‑Fi/LAN → http://YOUR-MAC-WIFI-IP:4173")
    local_server.serve_forever()

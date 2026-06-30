"""Small, local-only server for Today Command Center.

It serves the dashboard and provides a deliberately narrow Obsidian adapter:
configure one Daily-notes folder, read today's note, and replace only the
DASHBOARD marker block while saving a sibling backup. It never listens beyond
127.0.0.1 and never sends vault contents anywhere.
"""
from __future__ import annotations

import datetime as dt
import gzip
import json
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
from urllib.parse import urlencode, urlparse
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
SECRET_FIELDS = {"notionToken", "traccarToken", "googlePlacesKey", "lifeyLocationToken"}
KEYCHAIN_SERVICE = "Lifey"


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
        if value and keychain_set(key, value):
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


def youtube_today() -> dict:
    log = activity_log()
    today = dt.date.today().isoformat()
    data = log.get("youtube", {})
    if data.get("date") != today:
        return {"date": today, "videos": [], "totalActiveSeconds": 0, "extensionLastSeen": log.get("youtubeExtensionLastSeen")}
    videos = sorted(data.get("videos", []), key=lambda video: video.get("lastSeen", ""), reverse=True)
    return {"date": today, "videos": videos, "totalActiveSeconds": sum(video.get("activeSeconds", 0) for video in videos), "extensionLastSeen": log.get("youtubeExtensionLastSeen")}


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


def daily_names() -> list[str]:
    today = dt.date.today()
    return [
        f"{today.strftime('%B')} {today.day:02d}, {today.year}.md",
        f"{today.strftime('%B')} {today.day}, {today.year}.md",
        f"{today.isoformat()}.md",
    ]


def daily_file() -> Path:
    raw = config().get("dailyNotesPath", "")
    folder = Path(raw).expanduser()
    if not folder.is_dir():
        raise FileNotFoundError("Configure an existing Journals or Daily notes folder first.")
    folders = [folder]
    if folder.name.lower() == "daily":
        folders.append(folder.parent)
    else:
        folders.append(folder / "Daily")
    for candidate_folder in folders:
        for name in daily_names():
            candidate = candidate_folder / name
            if candidate.is_file():
                return candidate
    raise FileNotFoundError(f"No note found for today ({daily_names()[0]}).")


def journals_folder() -> Path:
    folder = Path(config().get("dailyNotesPath", "")).expanduser()
    if not folder.is_dir():
        raise FileNotFoundError("Configure your Journals folder first.")
    return folder.parent if folder.name.lower() == "daily" else folder


def note_safe_name(name: str) -> str:
    return re.sub(r"[/:\\]", "-", name).strip()[:160]


def wiki_place(name: str) -> str:
    clean = str(name).replace('"', "'").replace("]]", "").strip() or "Unknown place"
    return f'[[Place - "{clean}"]]'


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

    def read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", 0))
        return json.loads(self.rfile.read(length) or b"{}")

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/api/obsidian/status":
            settings = config()
            return self.json({"configured": bool(settings.get("dailyNotesPath")), "dailyNotesPath": settings.get("dailyNotesPath", ""), "notionConfigured": bool(settings.get("notionToken") and settings.get("notionParentId")), "archiveTemplate": settings.get("archiveTemplate", "")})
        if path == "/api/profile/preferences":
            return self.json({"preferences": config().get("profilePreferences", {})})
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
        if path == "/api/activity/youtube/today":
            return self.json(youtube_today())
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
                allowed = {"appearance", "visibility", "taskDisplay", "contentDisplay", "heroMetricOrder", "integrations"}
                clean = {key: preferences[key] for key in allowed if key in preferences}
                save_config({"profilePreferences": clean})
                return self.json({"saved": True, "preferences": clean})
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
            if path == "/api/obsidian/task":
                note = daily_file()
                line_number = int(body.get("line", 0))
                expected_text = str(body.get("text", "")).strip()
                lines = note.read_text().splitlines(keepends=True)
                if not 1 <= line_number <= len(lines):
                    return self.json({"error": "Task line no longer exists in today's note."}, HTTPStatus.CONFLICT)
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
                note = daily_file()
                previous = note.read_text()
                generated = archive_block(previous)
                task_line = f"- [ ] {text}\n"
                if generated:
                    prefix, suffix = previous[:generated.search(previous).start()].rstrip(), previous[generated.search(previous).start():]
                    line_number = prefix.count("\n") + (2 if prefix else 1)
                    updated = f"{prefix}\n{task_line}\n{suffix.lstrip()}" if prefix else f"{task_line}\n{suffix.lstrip()}"
                else:
                    line_number = previous.rstrip().count("\n") + (2 if previous.rstrip() else 1)
                    updated = f"{previous.rstrip()}\n{task_line}" if previous.rstrip() else task_line
                note.write_text(updated)
                return self.json({"line": line_number, "text": text, "path": str(note)})
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
                if not url.startswith("https://"):
                    return self.json({"error": "A valid YouTube URL is required."}, HTTPStatus.BAD_REQUEST)
                now = dt.datetime.now().astimezone().isoformat()
                log = activity_log(); today = dt.date.today().isoformat(); data = log.get("youtube", {})
                if data.get("date") != today:
                    data = {"date": today, "videos": []}
                videos = data.setdefault("videos", [])
                video = next((item for item in videos if item.get("url") == url), None)
                if not video:
                    video = {"title": title, "url": url, "firstSeen": body.get("firstSeen") or now, "lastSeen": now, "activeSeconds": 0}
                    videos.append(video)
                video["title"] = title
                video["lastSeen"] = body.get("lastSeen") or now
                video["activeSeconds"] += min(max(int(body.get("activeSeconds", 0)), 0), 60)
                log["youtube"] = data; save_activity(log)
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
    local_server = ThreadingHTTPServer(("127.0.0.1", 4173), Handler)
    tailnet_address = tailscale_ipv4()
    if tailnet_address:
        tailnet_server = ThreadingHTTPServer((tailnet_address, 4173), Handler)
        threading.Thread(target=tailnet_server.serve_forever, daemon=True).start()
        print(f"Lifey → http://127.0.0.1:4173\nLifey on your private Tailscale network → http://{tailnet_address}:4173")
    else:
        print("Lifey → http://127.0.0.1:4173")
    local_server.serve_forever()

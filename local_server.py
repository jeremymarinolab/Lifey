"""Small, local-only server for Lifey.

It serves Lifey and provides a deliberately narrow Obsidian adapter:
configure one Daily-notes folder, read today's note, and replace only the
DASHBOARD marker block while saving a sibling backup. It never listens beyond
127.0.0.1 and never sends vault contents anywhere.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import re
import secrets
import subprocess
import threading
import time
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse

from activity_service import (
    activity_log,
    save_activity,
    youtube_today as activity_youtube_today,
    youtube_video_identity,
    youtube_week as activity_youtube_week,
)
from archive_service import (
    DEFAULT_ARCHIVE_TITLES,
    DEFAULT_LOCATION_ARCHIVE_TEMPLATES,
    archive_block,
    has_archive_markers,
)
from config_store import (
    PROFILE_PREFERENCE_FIELDS,
    config,
    save_config,
    strip_profile_secrets,
)
from google_client import (
    GOOGLE_REDIRECT_URI,
    google_auth_url,
    google_calendar_create,
    google_calendar_delete,
    google_calendar_today,
    google_calendar_update,
    google_finish_auth,
    google_gmail_suggestions,
    google_oauth_status,
)
from habit_service import habit_history, habits_today, sync_today_habits, update_today_habit
from location_service import distance_meters, human_duration, parse_stamp, period_bounds, place_duration_seconds
from notion_client import notion_data_source, notion_request, notion_title
from obsidian_repo import (
    daily_file,
    daily_names,
    journals_folder,
    line_in_habit_section,
    note_safe_name,
    resolve_obsidian_root,
    wiki_place,
)
from places_service import (
    add_mobile_location_samples,
    grouping_radius,
    location_collector_token,
    location_places,
    location_positions,
    mobile_location_samples,
    top_places,
    traccar_positions,
    traccar_request,
    week_location_data,
)
from profile_service import PROFILE_EXCLUDED_SECRETS, clean_profile_import, profile_export_bundle
from project_service import create_project_note, open_project_note, projects_summary, update_project_task
from routes import ApiError, ApiResponse, RouteRegistry
from routes import origin_allowed as route_origin_allowed
from routes import read_json_body, request_allowed as route_request_allowed, validate_json_body
from task_service import insert_task_under_tasks, target_note_for_new_task

ROOT = Path(__file__).resolve().parent
ACTIVITY = ROOT / ".activity-log.json"
MOBILE_INGEST_RATE_WINDOW_SECONDS = 60
MOBILE_INGEST_RATE_LIMIT = 30
MOBILE_INGEST_RATE: dict[tuple[str, str], list[float]] = {}
MOBILE_INGEST_RATE_LOCK = threading.Lock()


def mobile_ingest_retry_after(client: str, token: str, now: float | None = None) -> int:
    """Return seconds to wait when this collector is over the ingest request rate."""
    timestamp = time.time() if now is None else now
    token_fingerprint = hashlib.sha256(token.encode()).hexdigest()[:16]
    key = (client, token_fingerprint)
    with MOBILE_INGEST_RATE_LOCK:
        recent = [item for item in MOBILE_INGEST_RATE.get(key, []) if timestamp - item < MOBILE_INGEST_RATE_WINDOW_SECONDS]
        if len(recent) >= MOBILE_INGEST_RATE_LIMIT:
            MOBILE_INGEST_RATE[key] = recent
            return max(1, int(MOBILE_INGEST_RATE_WINDOW_SECONDS - (timestamp - recent[0])))
        recent.append(timestamp)
        MOBILE_INGEST_RATE[key] = recent
    return 0


def tailscale_ipv4() -> str | None:
    """Use the Mac's private tailnet address, never its public or LAN address."""
    try:
        result = subprocess.run(["tailscale", "ip", "-4"], capture_output=True, text=True, timeout=3, check=False)
        address = result.stdout.strip().splitlines()[0]
        return address if re.fullmatch(r"100\.(?:6[4-9]|[7-9]\d|1[01]\d|12[0-7])(?:\.\d{1,3}){2}", address) else None
    except (OSError, subprocess.SubprocessError, IndexError):
        return None


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
    places = location_places(positions, source)
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
            visits = location_places(by_day.get(date.isoformat(), []), source)
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


def build_api_routes() -> RouteRegistry:
    routes = RouteRegistry()
    for path, group in [
        ("/api/obsidian/status", "obsidian"),
        ("/api/obsidian/daily", "obsidian"),
        ("/api/profile/preferences", "profile"),
        ("/api/profile/export", "profile"),
        ("/api/google/status", "google"),
        ("/api/google/auth/start", "google"),
        ("/api/google/auth/callback", "google"),
        ("/api/google/calendar/today", "google"),
        ("/api/google/gmail/suggestions", "google"),
        ("/api/notion/status", "notion"),
        ("/api/traccar/status", "location"),
        ("/api/location/mobile/status", "location"),
        ("/api/google-places/status", "location"),
        ("/api/osm-places/status", "location"),
        ("/api/location-archive-templates", "archive"),
        ("/api/archive-titles", "archive"),
        ("/api/location/settings", "location"),
        ("/api/place-labels", "location"),
        ("/api/traccar/today", "location"),
        ("/api/traccar/week", "location"),
        ("/api/location/today", "location"),
        ("/api/location/week", "location"),
        ("/api/habits/today", "habits"),
        ("/api/habits/history", "habits"),
        ("/api/projects", "projects"),
        ("/api/activity/youtube/today", "activity"),
        ("/api/activity/youtube/week", "activity"),
    ]:
        routes.add("GET", path, group, "handle_get_api_route")
    for path, group in [
        ("/api/location/mobile/setup", "location"),
        ("/api/location/mobile/ingest", "location"),
        ("/api/obsidian/config", "obsidian"),
        ("/api/obsidian/pick-folder", "obsidian"),
        ("/api/profile/preferences", "profile"),
        ("/api/profile/import", "profile"),
        ("/api/projects/create", "projects"),
        ("/api/projects/open", "projects"),
        ("/api/projects/task", "projects"),
        ("/api/google/config", "google"),
        ("/api/google/disconnect", "google"),
        ("/api/google/calendar/event", "google"),
        ("/api/google/calendar/event/update", "google"),
        ("/api/google/calendar/event/delete", "google"),
        ("/api/obsidian/archive", "archive"),
        ("/api/archive-template", "archive"),
        ("/api/location-archive-templates", "archive"),
        ("/api/archive-titles", "archive"),
        ("/api/location/settings", "location"),
        ("/api/place-merges", "location"),
        ("/api/place-merges/undo", "location"),
        ("/api/obsidian/location-archive", "archive"),
        ("/api/habits/sync", "habits"),
        ("/api/habits/state", "habits"),
        ("/api/obsidian/task", "obsidian"),
        ("/api/obsidian/task/edit", "obsidian"),
        ("/api/obsidian/task/delete", "obsidian"),
        ("/api/obsidian/task/add", "obsidian"),
        ("/api/notion/config", "notion"),
        ("/api/traccar/config", "location"),
        ("/api/google-places/config", "location"),
        ("/api/osm-places/config", "location"),
        ("/api/place-labels", "location"),
        ("/api/traccar/devices", "location"),
        ("/api/activity/youtube", "activity"),
        ("/api/activity/youtube/ping", "activity"),
        ("/api/notion/diagnose", "notion"),
        ("/api/notion/data-sources", "notion"),
        ("/api/notion/task", "notion"),
    ]:
        routes.add("POST", path, group, "handle_post_api_route", auth_required=path != "/api/location/mobile/ingest", reads_json=True)
    return routes


API_ROUTES = build_api_routes()


class Handler(SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        origin = self.headers.get("Origin", "")
        if origin and self.origin_allowed(origin, urlparse(self.path).path):
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
        super().end_headers()

    def do_OPTIONS(self):
        path = urlparse(self.path).path
        if path.startswith("/api/") and not self.request_allowed(path):
            return self.json({"error": "Lifey only accepts browser API calls from its own origin."}, HTTPStatus.FORBIDDEN)
        self.send_response(HTTPStatus.NO_CONTENT)
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
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
        return read_json_body(self.headers, self.rfile)

    def route_error(self, message: str, status=HTTPStatus.BAD_REQUEST):
        return self.json({"error": message}, status)

    def dispatch_api_route(self, route, parsed):
        if route.auth_required and not self.request_allowed(route.path):
            return self.route_error("Lifey only accepts browser API calls from its own origin.", HTTPStatus.FORBIDDEN)
        try:
            body = self.read_json() if route.reads_json else None
            if route.reads_json:
                validate_json_body(route.path, body)
            result = getattr(self, route.handler)(parsed, body, route)
            if isinstance(result, ApiResponse):
                return self.json(result.payload, result.status)
            if isinstance(result, dict):
                return self.json(result)
            return result
        except json.JSONDecodeError:
            return self.route_error("Invalid request.", HTTPStatus.BAD_REQUEST)
        except ApiError as error:
            return self.route_error(error.message, error.status)
        except (OSError, FileNotFoundError, ValueError) as error:
            return self.route_error(str(error), HTTPStatus.BAD_REQUEST)

    def origin_allowed(self, origin: str, path: str = "") -> bool:
        return route_origin_allowed(origin, self.headers.get("Host", ""), path)

    def request_allowed(self, path: str = "") -> bool:
        return route_request_allowed(self.headers, self.client_address, path)

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        route = API_ROUTES.get("GET", path)
        if route:
            return self.dispatch_api_route(route, parsed)
        if path.startswith("/api/"):
            if not self.request_allowed(path):
                return self.route_error("Lifey only accepts browser API calls from its own origin.", HTTPStatus.FORBIDDEN)
            return self.route_error("Not found.", HTTPStatus.NOT_FOUND)
        return super().do_GET()

    def handle_get_api_route(self, parsed, body=None, route=None):
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
                return self.json({"places": location_places(positions, "Traccar"), "positions": len(positions), "source": "Traccar", "osmError": config().get("osmLastError", "")})
            except (KeyError, ValueError) as error: return self.json({"error": str(error)}, HTTPStatus.BAD_REQUEST)
        if path == "/api/traccar/week":
            try:
                data = week_location_data("traccar"); data["osmError"] = config().get("osmLastError", "")
                return self.json(data)
            except (KeyError, ValueError) as error: return self.json({"error": str(error)}, HTTPStatus.BAD_REQUEST)
        if path == "/api/location/today":
            try:
                start, end = period_bounds("today"); positions, source = location_positions(start, end)
                return self.json({"places": location_places(positions, source), "positions": len(positions), "source": source, "osmError": config().get("osmLastError", "")})
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
            return self.json(activity_youtube_today(ACTIVITY))
        if path == "/api/activity/youtube/week":
            return self.json(activity_youtube_week(ACTIVITY))
        if path == "/api/obsidian/daily":
            try:
                note = daily_file()
                return self.json({"name": note.name, "path": str(note), "markdown": note.read_text()})
            except (OSError, FileNotFoundError) as error:
                return self.json({"error": str(error)}, HTTPStatus.NOT_FOUND)
        return self.route_error("Not found.", HTTPStatus.NOT_FOUND)

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path
        route = API_ROUTES.get("POST", path)
        if route:
            return self.dispatch_api_route(route, parsed)
        if path.startswith("/api/"):
            if not self.request_allowed(path):
                return self.route_error("Lifey only accepts browser API calls from its own origin.", HTTPStatus.FORBIDDEN)
            return self.route_error("Not found.", HTTPStatus.NOT_FOUND)
        return self.route_error("Not found.", HTTPStatus.NOT_FOUND)

    def handle_post_api_route(self, parsed, body=None, route=None):
        path = parsed.path
        body = body or {}
        try:
            if path == "/api/location/mobile/setup":
                # This endpoint is intentionally local-only because it returns the collector secret.
                if self.client_address[0] not in {"127.0.0.1", "::1"}:
                    return self.json({"error": "Create the Lifey Location token from the Mac app."}, HTTPStatus.FORBIDDEN)
                rotate = body.get("rotate") is True
                return self.json({"token": location_collector_token(rotate=rotate), "rotated": rotate, "tokenCreatedAt": config().get("lifeyLocationTokenCreatedAt", "")})
            if path == "/api/location/mobile/ingest":
                supplied = self.headers.get("Authorization", "").removeprefix("Bearer ").strip()
                if not secrets.compare_digest(supplied, str(config().get("lifeyLocationToken", ""))):
                    return self.json({"error": "Lifey Location is not authorised."}, HTTPStatus.UNAUTHORIZED)
                retry_after = mobile_ingest_retry_after(self.client_address[0], supplied)
                if retry_after:
                    return self.json({"error": "Too many Lifey Location sync attempts.", "retryAfterSeconds": retry_after}, HTTPStatus.TOO_MANY_REQUESTS)
                samples = body.get("samples", [])
                if not isinstance(samples, list):
                    return self.json({"error": "Invalid location batch."}, HTTPStatus.BAD_REQUEST)
                return self.json(add_mobile_location_samples(samples))
            if path == "/api/obsidian/config":
                try:
                    folder = resolve_obsidian_root(str(body.get("dailyNotesPath", "")))
                except FileNotFoundError as error:
                    return self.json({"error": str(error)}, HTTPStatus.BAD_REQUEST)
                save_config({"dailyNotesPath": str(folder)})
                return self.json({"dailyNotesPath": str(folder)})
            if path == "/api/obsidian/pick-folder":
                if self.client_address[0] not in {"127.0.0.1", "::1"}:
                    return self.json({"error": "Choose the Obsidian folder from Lifey on the Mac at http://127.0.0.1:4173."}, HTTPStatus.FORBIDDEN)
                script = '\n'.join([
                    'tell application "Finder" to activate',
                    'delay 0.2',
                    'POSIX path of (choose folder with prompt "Choose your Obsidian vault, Journals folder, or Daily folder for Lifey")',
                ])
                try:
                    result = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=120, check=False)
                except subprocess.TimeoutExpired:
                    return self.json({"error": "Folder picker timed out. Paste the folder path instead, or try again from Lifey on the Mac."}, HTTPStatus.BAD_REQUEST)
                if result.returncode != 0:
                    detail = (result.stderr or result.stdout or "").strip()
                    if "User canceled" in detail or str(result.returncode) == "1":
                        detail = "Folder selection was cancelled."
                    return self.json({"error": detail or "macOS could not open the folder picker. Paste the folder path instead."}, HTTPStatus.BAD_REQUEST)
                try:
                    folder = resolve_obsidian_root(result.stdout.strip())
                except FileNotFoundError as error:
                    return self.json({"error": str(error)}, HTTPStatus.BAD_REQUEST)
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
                    return self.json({"error": "Invalid Lifey archive."}, HTTPStatus.BAD_REQUEST)
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
                    return self.json(activity_youtube_today(ACTIVITY))
                video_id, canonical_url, kind = identity
                now = dt.datetime.now().astimezone().isoformat()
                log = activity_log(ACTIVITY); today = dt.date.today().isoformat(); days = log.setdefault("youtubeDays", {})
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
                days[today] = data; log["youtube"] = data; save_activity(ACTIVITY, log)
                return self.json(activity_youtube_today(ACTIVITY))
            if path == "/api/activity/youtube/ping":
                log = activity_log(ACTIVITY); log["youtubeExtensionLastSeen"] = dt.datetime.now().astimezone().isoformat(); save_activity(ACTIVITY, log)
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
    port = int(os.environ.get("LIFEY_PORT", "4173"))
    local_host = "0.0.0.0" if lan_enabled else "127.0.0.1"
    local_server = ThreadingHTTPServer((local_host, port), Handler)
    tailnet_address = None if lan_enabled else tailscale_ipv4()
    if tailnet_address:
        tailnet_server = ThreadingHTTPServer((tailnet_address, port), Handler)
        threading.Thread(target=tailnet_server.serve_forever, daemon=True).start()
        print(f"Lifey → http://127.0.0.1:{port}\nLifey on your private Tailscale network → http://{tailnet_address}:{port}")
    else:
        print(f"Lifey → http://127.0.0.1:{port}")
    if lan_enabled:
        print(f"Lifey on this Wi‑Fi/LAN → http://YOUR-MAC-WIFI-IP:{port}")
    local_server.serve_forever()

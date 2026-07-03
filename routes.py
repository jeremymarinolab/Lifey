from __future__ import annotations

from dataclasses import dataclass
import json
from http import HTTPStatus
from typing import Any, Callable
from urllib.parse import urlparse


LOCAL_HOSTS = {"127.0.0.1", "::1", "localhost"}
EXTENSION_ORIGIN_SCHEMES = {"chrome-extension", "moz-extension", "safari-web-extension"}
EXTENSION_API_PATHS = {"/api/activity/youtube", "/api/activity/youtube/ping"}
MAX_JSON_BODY_BYTES = 1_000_000
RouteHandler = Callable[..., Any]


@dataclass(frozen=True)
class ApiResponse:
    payload: dict
    status: HTTPStatus = HTTPStatus.OK


class ApiError(Exception):
    def __init__(self, message: str, status: HTTPStatus = HTTPStatus.BAD_REQUEST):
        super().__init__(message)
        self.message = message
        self.status = status


@dataclass(frozen=True)
class RouteSpec:
    method: str
    path: str
    group: str
    handler: str
    auth_required: bool = True
    reads_json: bool = False


class RouteRegistry:
    def __init__(self):
        self._routes: dict[tuple[str, str], RouteSpec] = {}

    def add(
        self,
        method: str,
        path: str,
        group: str,
        handler: str,
        *,
        auth_required: bool = True,
        reads_json: bool = False,
    ) -> None:
        spec = RouteSpec(method.upper(), path, group, handler, auth_required, reads_json)
        key = (spec.method, spec.path)
        if key in self._routes:
            raise ValueError(f"Duplicate route: {spec.method} {spec.path}")
        self._routes[key] = spec

    def get(self, method: str, path: str) -> RouteSpec | None:
        return self._routes.get((method.upper(), path))

    def groups(self) -> dict[str, list[RouteSpec]]:
        grouped: dict[str, list[RouteSpec]] = {}
        for spec in sorted(self._routes.values(), key=lambda item: (item.group, item.method, item.path)):
            grouped.setdefault(spec.group, []).append(spec)
        return grouped


def api_response(payload: dict, status: HTTPStatus = HTTPStatus.OK) -> ApiResponse:
    return ApiResponse(payload, status)


def api_error(message: str, status: HTTPStatus = HTTPStatus.BAD_REQUEST) -> ApiError:
    return ApiError(message, status)


def string_field(body: dict, key: str, *, required: bool = False, max_length: int = 2_000) -> str:
    value = body.get(key, "")
    if required and not str(value).strip():
        raise ApiError(f"{key} is required.")
    if not isinstance(value, str):
        raise ApiError(f"{key} must be text.")
    if len(value) > max_length:
        raise ApiError(f"{key} is too long.")
    return value


def int_field(body: dict, key: str, *, minimum: int | None = None, maximum: int | None = None) -> int:
    try:
        value = int(body.get(key, 0))
    except (TypeError, ValueError) as error:
        raise ApiError(f"{key} must be a whole number.") from error
    if minimum is not None and value < minimum:
        raise ApiError(f"{key} is too small.")
    if maximum is not None and value > maximum:
        raise ApiError(f"{key} is too large.")
    return value


def dict_field(body: dict, key: str, *, required: bool = False) -> dict:
    value = body.get(key, {})
    if required and not isinstance(value, dict):
        raise ApiError(f"{key} must be an object.")
    if not isinstance(value, dict):
        raise ApiError(f"{key} must be an object.")
    return value


def list_field(body: dict, key: str, *, required: bool = False, max_length: int = 500) -> list:
    value = body.get(key, [])
    if required and not isinstance(value, list):
        raise ApiError(f"{key} must be a list.")
    if not isinstance(value, list):
        raise ApiError(f"{key} must be a list.")
    if len(value) > max_length:
        raise ApiError(f"{key} has too many items.")
    return value


def validate_json_body(path: str, body: dict) -> None:
    if path == "/api/location/mobile/ingest":
        list_field(body, "samples", required=True, max_length=500)
    elif path == "/api/obsidian/config":
        string_field(body, "dailyNotesPath", required=True)
    elif path == "/api/profile/preferences":
        dict_field(body, "preferences", required=True)
    elif path == "/api/projects/create":
        string_field(body, "slug", max_length=200)
        string_field(body, "title", max_length=300)
    elif path == "/api/projects/open":
        string_field(body, "slug", required=True, max_length=200)
    elif path == "/api/projects/task":
        string_field(body, "source", required=True, max_length=2_000)
        int_field(body, "line", minimum=1)
    elif path == "/api/google/config":
        string_field(body, "clientId", required=True, max_length=500)
        string_field(body, "clientSecret", max_length=500)
        string_field(body, "calendar", max_length=500)
        string_field(body, "gmailQuery", max_length=1_000)
    elif path in {"/api/google/calendar/event/update", "/api/google/calendar/event/delete"}:
        string_field(body, "eventId", required=True, max_length=500)
        if path.endswith("/update"):
            dict_field(body, "event", required=True)
    elif path == "/api/obsidian/archive":
        string_field(body, "archive", required=True, max_length=200_000)
    elif path == "/api/archive-template":
        string_field(body, "template", required=True, max_length=20_000)
    elif path == "/api/location-archive-templates":
        dict_field(body, "templates", required=True)
    elif path == "/api/archive-titles":
        dict_field(body, "titles", required=True)
    elif path == "/api/location/settings":
        int_field(body, "radiusMeters", minimum=20, maximum=500)
    elif path == "/api/place-merges":
        string_field(body, "name", required=True, max_length=120)
        list_field(body, "places", required=True, max_length=100)
    elif path == "/api/place-merges/undo":
        string_field(body, "id", required=True, max_length=200)
    elif path == "/api/obsidian/location-archive":
        period = string_field(body, "period", required=True, max_length=20)
        if period not in {"weekly", "monthly", "yearly"}:
            raise ApiError("Choose weekly, monthly, or yearly.")
    elif path == "/api/habits/state":
        int_field(body, "line", minimum=1)
        string_field(body, "habit", required=True, max_length=300)
        state = string_field(body, "state", required=True, max_length=20)
        if state not in {"completed", "pending", "skipped"}:
            raise ApiError("Choose completed, pending, or skipped.")
    elif path in {"/api/obsidian/task", "/api/obsidian/task/edit", "/api/obsidian/task/delete"}:
        int_field(body, "line", minimum=1)
        if path == "/api/obsidian/task/edit":
            string_field(body, "previousText", required=True, max_length=2_000)
            string_field(body, "text", required=True, max_length=2_000)
        else:
            string_field(body, "text", required=True, max_length=2_000)
    elif path == "/api/obsidian/task/add":
        string_field(body, "text", required=True, max_length=2_000)
    elif path == "/api/notion/config":
        string_field(body, "token", required=True, max_length=1_000)
        string_field(body, "parentId", required=True, max_length=500)
        string_field(body, "titleProperty", max_length=200)
    elif path == "/api/traccar/config":
        string_field(body, "server", required=True, max_length=1_000)
        string_field(body, "token", required=True, max_length=1_000)
        string_field(body, "deviceId", max_length=200)
    elif path == "/api/google-places/config":
        string_field(body, "key", required=True, max_length=1_000)
    elif path == "/api/place-labels":
        string_field(body, "name", required=True, max_length=120)
        if not isinstance(body.get("latitude"), (int, float, str)) or not isinstance(body.get("longitude"), (int, float, str)):
            raise ApiError("latitude and longitude are required.")
    elif path == "/api/traccar/devices":
        string_field(body, "server", required=True, max_length=1_000)
        string_field(body, "token", required=True, max_length=1_000)
    elif path == "/api/activity/youtube":
        string_field(body, "url", max_length=2_000)
        string_field(body, "title", max_length=500)
        string_field(body, "videoId", max_length=200)
    elif path == "/api/notion/diagnose":
        string_field(body, "token", required=True, max_length=1_000)
        string_field(body, "parentId", required=True, max_length=500)
    elif path == "/api/notion/data-sources":
        string_field(body, "token", required=True, max_length=1_000)
    elif path == "/api/notion/task":
        string_field(body, "text", required=True, max_length=2_000)


def origin_allowed(origin: str, host_header: str, path: str = "") -> bool:
    parsed_origin = urlparse(origin)
    if parsed_origin.scheme in EXTENSION_ORIGIN_SCHEMES:
        return path in EXTENSION_API_PATHS
    if parsed_origin.scheme not in {"http", "https"} or not parsed_origin.hostname:
        return False
    raw_host = host_header.lower()
    host = raw_host[1:].split("]", 1)[0] if raw_host.startswith("[") else raw_host.split(":", 1)[0]
    origin_host = parsed_origin.hostname.lower()
    return origin_host == host or (origin_host in LOCAL_HOSTS and host in LOCAL_HOSTS)


def request_allowed(headers, client_address: tuple[str, int], path: str = "") -> bool:
    origin = headers.get("Origin", "")
    if origin:
        return origin_allowed(origin, headers.get("Host", ""), path)
    referer = headers.get("Referer", "")
    if referer:
        return origin_allowed(referer, headers.get("Host", ""), path)
    return client_address[0] in {"127.0.0.1", "::1"}


def read_json_body(headers, stream) -> dict:
    try:
        length = int(headers.get("Content-Length", 0))
    except ValueError as error:
        raise ValueError("Invalid Content-Length header.") from error
    if length > MAX_JSON_BODY_BYTES:
        raise ValueError("Request body is too large.")
    data = json.loads(stream.read(length) or b"{}")
    if not isinstance(data, dict):
        raise ValueError("Request body must be a JSON object.")
    return data

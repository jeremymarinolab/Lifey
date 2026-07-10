from __future__ import annotations

import datetime as dt
import gzip
import json
from pathlib import Path
import secrets
import ssl
import time
import zlib
import re
from urllib import error as urlerror
from urllib import request as urlrequest
from urllib.parse import urlencode

from config_store import config, save_config
from location_service import distance_meters, parse_stamp, period_bounds, place_duration_seconds


MOBILE_LOCATIONS = Path.home() / "Library" / "Application Support" / "Lifey" / "location-samples.json"
SSL_CONTEXT = ssl.create_default_context(cafile="/etc/ssl/cert.pem")
LAST_NOMINATIM_REQUEST = 0.0
MOBILE_SAMPLE_MAX_AGE = dt.timedelta(days=30)
MOBILE_SAMPLE_FUTURE_SKEW = dt.timedelta(minutes=10)


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


def location_collector_token(*, rotate: bool = False) -> str:
    token = config().get("lifeyLocationToken", "")
    if token and not rotate:
        return token
    token = secrets.token_urlsafe(32)
    save_config({"lifeyLocationToken": token, "lifeyLocationTokenCreatedAt": dt.datetime.now(dt.timezone.utc).isoformat()})
    return token


def add_mobile_location_samples(samples: list[dict]) -> dict:
    """Validate/deduplicate an idempotent batch sent by the iOS collector."""
    existing = mobile_location_samples()
    known = {str(item.get("id", "")) for item in existing}
    added = duplicates = rejected = replayed = 0
    now = dt.datetime.now(dt.timezone.utc)
    for sample in samples[:250]:
        try:
            sample_id = str(sample["id"]).strip()
            latitude, longitude = float(sample["latitude"]), float(sample["longitude"])
            captured_at = parse_stamp(sample.get("capturedAt"))
        except (KeyError, TypeError, ValueError):
            rejected += 1
            continue
        if not captured_at or not sample_id or not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
            rejected += 1
            continue
        captured_at = captured_at.astimezone(dt.timezone.utc)
        if captured_at < now - MOBILE_SAMPLE_MAX_AGE or captured_at > now + MOBILE_SAMPLE_FUTURE_SKEW:
            replayed += 1
            continue
        if sample_id in known:
            duplicates += 1
            continue
        accuracy = sample.get("accuracyMeters", sample.get("accuracy", 0))
        existing.append({
            "id": sample_id[:100], "latitude": latitude, "longitude": longitude,
            "capturedAt": captured_at.astimezone().isoformat(),
            "accuracyMeters": max(0, min(float(accuracy), 50_000)),
            "source": "Lifey Location",
        })
        known.add(sample_id); added += 1
    existing.sort(key=lambda item: item.get("capturedAt", ""))
    save_mobile_location_samples(existing[-200_000:])
    return {"accepted": added, "duplicates": duplicates, "replayed": replayed, "rejected": rejected, "stored": len(existing)}


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
        req = urlrequest.Request(url, headers={"User-Agent": "Lifey/0.1 (personal local dashboard)"})
        with urlrequest.urlopen(req, timeout=12, context=SSL_CONTEXT) as response: data = json.loads(response.read())
        display = data.get("display_name", ""); result = {"name": data.get("namedetails", {}).get("name") or display.split(",")[0], "address": display}
        if result["name"]: cache[cache_key] = result; save_config({"placeCache": cache}); return result
    except (urlerror.URLError, urlerror.HTTPError) as error:
        save_config({"osmLastError": str(error)}); return None


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


def location_places(positions: list[dict], source_label: str = "Traccar") -> list[dict]:
    positions.sort(key=lambda item: item.get("fixTime", "")); places = []
    radius = grouping_radius()
    for point in positions:
        latitude, longitude = point.get("latitude", 0), point.get("longitude", 0); label = point.get("address") or f"{latitude:.4f}, {longitude:.4f}"
        stamp = point.get("fixTime") or point.get("deviceTime")
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


def traccar_positions(start: dt.datetime, end: dt.datetime) -> list[dict]:
    settings = config()
    query = "/api/reports/route?" + urlencode({
        "deviceId": settings["traccarDeviceId"],
        "from": start.astimezone(dt.timezone.utc).isoformat(),
        "to": end.astimezone(dt.timezone.utc).isoformat(),
    })
    return traccar_request(query, settings["traccarToken"], settings["traccarServer"])


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
        places = location_places(by_day.get(day, []), source)
        all_places.extend(places)
        days.append({"date": day, "places": places})
    return {"start": start.date().isoformat(), "end": end.date().isoformat(), "days": days, "topPlaces": top_places(all_places), "positions": len(positions), "source": source}

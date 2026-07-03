from __future__ import annotations

import datetime as dt


def distance_meters(latitude_a: float, longitude_a: float, latitude_b: float, longitude_b: float) -> float:
    from math import asin, cos, radians, sin, sqrt
    lat_delta = radians(latitude_b - latitude_a)
    lon_delta = radians(longitude_b - longitude_a)
    a = sin(lat_delta / 2) ** 2 + cos(radians(latitude_a)) * cos(radians(latitude_b)) * sin(lon_delta / 2) ** 2
    return 6_371_000 * 2 * asin(sqrt(a))


def parse_stamp(value: str | None) -> dt.datetime | None:
    if not value:
        return None
    if isinstance(value, (int, float)):
        base = 978_307_200 if value < 1_200_000_000 else 0
        try:
            return dt.datetime.fromtimestamp(value + base, tz=dt.timezone.utc)
        except (OSError, OverflowError, ValueError):
            return None
    try:
        return dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


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

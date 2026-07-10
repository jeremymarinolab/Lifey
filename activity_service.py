from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from location_service import period_bounds


def activity_log(path: Path) -> dict:
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return {}


def save_activity(path: Path, values: dict) -> None:
    path.write_text(json.dumps(values, indent=2))


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


def youtube_day_data(log: dict, date: str) -> dict:
    days = log.get("youtubeDays", {})
    if isinstance(days, dict) and isinstance(days.get(date), dict):
        return days[date]
    current = log.get("youtube", {})
    if isinstance(current, dict) and current.get("date") == date:
        return current
    return {"date": date, "videos": []}


def youtube_today(path: Path) -> dict:
    log = activity_log(path)
    today = dt.date.today().isoformat()
    data = youtube_day_data(log, today)
    videos = sorted(youtube_normalized_videos(data.get("videos", [])), key=lambda video: (int(video.get("activeSeconds", 0)), video.get("lastSeen", "")), reverse=True)
    return {"date": today, "videos": videos, "totalActiveSeconds": sum(video.get("activeSeconds", 0) for video in videos), "extensionLastSeen": log.get("youtubeExtensionLastSeen")}


def youtube_week(path: Path) -> dict:
    log = activity_log(path)
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

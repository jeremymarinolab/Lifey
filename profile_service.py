from __future__ import annotations

import datetime as dt

from archive_service import DEFAULT_ARCHIVE_TITLES, DEFAULT_LOCATION_ARCHIVE_TEMPLATES, has_archive_markers
from config_store import PROFILE_PREFERENCE_FIELDS, config, safe_profile_preferences, strip_profile_secrets
from places_service import grouping_radius


PROFILE_EXCLUDED_SECRETS = [
    "notionToken",
    "googlePlacesKey",
    "traccarToken",
    "lifeyLocationToken",
    "googleRefreshToken",
    "googleClientSecret",
    "oauthAccessTokens",
]


def archive_templates() -> dict:
    saved = config().get("locationArchiveTemplates", {})
    return {key: str(saved.get(key) or value) for key, value in DEFAULT_LOCATION_ARCHIVE_TEMPLATES.items()}


def archive_titles() -> dict:
    saved = config().get("archiveTitles", {})
    titles = {key: str(saved.get(key) or value) for key, value in DEFAULT_ARCHIVE_TITLES.items()}
    if titles["daily"] == "Lifey · mmm dd, yyyy":
        titles["daily"] = DEFAULT_ARCHIVE_TITLES["daily"]
    return titles


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

from __future__ import annotations

import re


START = END = "---"
LEGACY_START, LEGACY_END = "<!-- DASHBOARD:START -->", "<!-- DASHBOARD:END -->"
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


def has_archive_markers(text: str) -> bool:
    lines = text.strip().splitlines()
    return len(lines) >= 2 and lines[0].strip() == START and lines[-1].strip() == END


def archive_block(text: str) -> re.Pattern[str] | None:
    legacy = re.compile(re.escape(LEGACY_START) + r"[\s\S]*?" + re.escape(LEGACY_END))
    if legacy.search(text):
        return legacy
    modern = re.compile(r"^---[ \t]*\r?\n(?=## Lifey\b)[\s\S]*?^---[ \t]*$", re.MULTILINE)
    return modern if modern.search(text) else None

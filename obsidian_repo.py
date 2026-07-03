from __future__ import annotations

import datetime as dt
from pathlib import Path
import re

from config_store import config


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


def archive_start_line(lines: list[str]) -> int | None:
    for index in range(len(lines) - 1):
        if lines[index].strip() == "---" and re.match(r"^##\s+Lifey\b", lines[index + 1].strip()):
            return index
    return None


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


def journals_folder() -> Path:
    folder = Path(config().get("dailyNotesPath", "")).expanduser()
    if not folder.is_dir():
        raise FileNotFoundError("Configure your Journals folder first.")
    return folder.parent if folder.name.lower() == "daily" else folder


def vault_folder() -> Path:
    journals = journals_folder()
    return journals.parent if journals.name.lower() in {"journals", "journal"} else journals.parent


def note_date_from_path(path: Path) -> dt.date | None:
    stem = path.stem
    for pattern in ("%B %d, %Y", "%B %e, %Y", "%Y-%m-%d"):
        try:
            return dt.datetime.strptime(stem, pattern).date()
        except ValueError:
            continue
    return None

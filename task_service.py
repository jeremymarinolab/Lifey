from __future__ import annotations

import datetime as dt
import re
from pathlib import Path

from obsidian_repo import archive_start_line, daily_file, daily_file_for_date, habit_section_bounds, note_date_from_path, task_section_bounds


def task_due_date(text: str) -> dt.date | None:
    match = re.search(r"📅\s*(\d{4}-\d{2}-\d{2})", text)
    if not match:
        return None
    try:
        return dt.date.fromisoformat(match.group(1))
    except ValueError:
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

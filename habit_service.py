from __future__ import annotations

import datetime as dt
from pathlib import Path
import re

from obsidian_repo import daily_candidate_folders, daily_file, journals_folder, line_in_habit_section, note_date_from_path, habit_section_bounds


WEEKDAY_CODES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def habits_config_path() -> Path:
    root = journals_folder()
    preferred = root / "Habits" / "Active Habits.md"
    fallback = root / "Active Habits.md"
    return preferred if preferred.exists() or not fallback.exists() else fallback


def split_markdown_table_row(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def normalise_habit_time(value: str) -> tuple[str, int | None]:
    raw = (value or "").strip()
    if not raw:
        return "", None
    cleaned = raw.lower().replace(".", "")
    match = re.match(r"^(\d{1,2})(?::([0-5]\d))?\s*(am|pm)?$", cleaned)
    if not match:
        return raw, None
    hour = int(match.group(1))
    minute = int(match.group(2) or 0)
    period = match.group(3)
    if period:
        if hour == 12:
            hour = 0
        if period == "pm":
            hour += 12
    if hour > 23:
        return raw, None
    return f"{hour:02d}:{minute:02d}", hour * 60 + minute


def habit_note_schedule(body: str) -> dict:
    time_label = ""
    time_minutes = None
    time_match = re.search(r"⏰\s*(\d{1,2}(?::[0-5]\d)?\s*(?:a\.?m\.?|p\.?m\.?)?)", body, re.IGNORECASE)
    if not time_match:
        time_match = re.search(r"\b(?:at\s+)?(\d{1,2}(?::[0-5]\d)?\s*(?:a\.?m\.?|p\.?m\.?))\b", body, re.IGNORECASE)
    if not time_match:
        time_match = re.search(r"\b(?:at\s+)?([01]?\d|2[0-3]):([0-5]\d)\b", body)
    if time_match:
        time_value = f"{time_match.group(1)}:{time_match.group(2)}" if len(time_match.groups()) > 1 and time_match.group(2) else time_match.group(1)
        time_label, time_minutes = normalise_habit_time(time_value)
    date_match = re.search(r"📅\s*(\d{4}-\d{2}-\d{2})", body)
    return {
        "dueDate": date_match.group(1) if date_match else "",
        "time": time_label,
        "timeMinutes": time_minutes,
    }


def habit_body_without_schedule(body: str) -> str:
    cleaned = re.sub(r"\s*📅\s*\d{4}-\d{2}-\d{2}", "", body)
    cleaned = re.sub(r"\s*⏰\s*\d{1,2}(?::[0-5]\d)?\s*(?:a\.?m\.?|p\.?m\.?)?", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*\b(?:at\s+)?\d{1,2}(?::[0-5]\d)?\s*(?:a\.?m\.?|p\.?m\.?)\b", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*\b(?:at\s+)?(?:[01]?\d|2[0-3]):[0-5]\d\b", "", cleaned)
    return re.sub(r"\s+", " ", cleaned).strip()


def read_habit_config() -> list[dict]:
    path = habits_config_path()
    if not path.is_file():
        return []
    rows: list[str] = []
    for line in path.read_text().splitlines():
        if line.strip().startswith("|"):
            rows.append(line)
        elif rows:
            break
    if len(rows) < 2:
        return []
    headers = [header.strip().lower() for header in split_markdown_table_row(rows[0])]
    habits = []
    for order, line in enumerate(rows[2:]):
        if re.match(r"^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?\s*$", line):
            continue
        cells = split_markdown_table_row(line)
        if not cells or not any(cells):
            continue
        item = {headers[index]: cells[index] if index < len(cells) else "" for index in range(len(headers))}
        name = item.get("habit", "").strip()
        if not name:
            continue
        days_raw = item.get("days", "Daily").strip() or "Daily"
        days = ["Daily"] if days_raw.lower() == "daily" else [day.strip() for day in days_raw.split(",") if day.strip()]
        try:
            start = dt.date.fromisoformat(item.get("start", "").strip())
        except ValueError:
            start = None
        try:
            duration = int(item.get("duration", "").strip()) if item.get("duration", "").strip() else None
        except ValueError:
            duration = None
        time_label, time_minutes = normalise_habit_time(item.get("time", ""))
        habits.append({
            "habit": name,
            "start": start.isoformat() if start else "",
            "duration": duration,
            "days": days,
            "daysText": days_raw,
            "time": time_label,
            "timeMinutes": time_minutes,
            "order": order,
            "label": item.get("label", "Day").strip() or "Day",
            "status": item.get("status", "").strip().lower() or "active",
        })
    return habits


def habit_scheduled_for(habit: dict, day: dt.date) -> bool:
    if habit.get("status") != "active":
        return False
    try:
        start = dt.date.fromisoformat(habit.get("start", ""))
        if day < start:
            return False
    except ValueError:
        pass
    days = habit.get("days") or ["Daily"]
    return "Daily" in days or WEEKDAY_CODES[day.weekday()] in days


def habit_progress_label(habit: dict, day: dt.date) -> str:
    label = habit.get("label") or "Day"
    try:
        start = dt.date.fromisoformat(habit.get("start", ""))
        number = (day - start).days + 1
    except ValueError:
        number = 1
    suffix = f"/{habit['duration']}" if habit.get("duration") else ""
    return f"{label} {max(1, number)}{suffix}"


def expected_habits_for(day: dt.date) -> list[dict]:
    expected = []
    for habit in read_habit_config():
        if not habit_scheduled_for(habit, day):
            continue
        label = habit_progress_label(habit, day)
        metadata = f" ⏰ {habit['time']}" if habit.get("time") else ""
        expected.append({**habit, "date": day.isoformat(), "progress": label, "text": f"{habit['habit']} — {label}{metadata}"})
    return sorted(expected, key=habit_sort_key)


def habit_sort_key(habit: dict) -> tuple[str, int, int, int, str]:
    due_date = habit.get("dueDate") or habit.get("date") or ""
    minutes = habit.get("timeMinutes")
    return (due_date, 0 if isinstance(minutes, int) else 1, minutes if isinstance(minutes, int) else 24 * 60, int(habit.get("order", 9999)), habit.get("habit", "").lower())


def attach_habit_config(habits: list[dict], config_habits: list[dict]) -> list[dict]:
    by_name = {habit.get("habit", "").strip().lower(): habit for habit in config_habits}
    enriched = []
    for habit in habits:
        config_habit = by_name.get(habit.get("habit", "").strip().lower(), {})
        enriched.append({
            **habit,
            "dueDate": habit.get("dueDate") or config_habit.get("date", ""),
            "time": habit.get("time") or config_habit.get("time", ""),
            "timeMinutes": habit.get("timeMinutes") if isinstance(habit.get("timeMinutes"), int) else config_habit.get("timeMinutes"),
            "order": config_habit.get("order", 9999),
        })
    return sorted(enriched, key=habit_sort_key)


def parse_habit_lines(markdown: str, source: str = "") -> list[dict]:
    lines = markdown.splitlines()
    start, end = habit_section_bounds(lines)
    if start is None or end is None:
        return []
    habits = []
    for index in range(start + 1, end):
        match = re.match(r"^(\s*)-\s+\[([ xX-])\]\s+(.+?)\s*$", lines[index])
        if not match:
            continue
        body = match.group(3).strip()
        schedule = habit_note_schedule(body)
        clean_body = habit_body_without_schedule(body)
        name, progress = (clean_body.split(" — ", 1) + [""])[:2] if " — " in clean_body else (clean_body, "")
        marker = match.group(2).lower()
        state = "completed" if marker == "x" else "skipped" if marker == "-" else "pending"
        habits.append({"habit": name.strip(), "progress": progress.strip(), "text": body, **schedule, "state": state, "line": index + 1, "source": source})
    return habits


def sync_today_habits() -> dict:
    note = daily_file()
    day = note_date_from_path(note) or dt.date.today()
    previous = note.read_text()
    lines = previous.splitlines()
    start, end = habit_section_bounds(lines)
    if start is None:
        if lines and lines[-1].strip():
            lines.append("")
        lines.extend(["## Habits::"])
        start, end = len(lines) - 1, len(lines)
    existing = parse_habit_lines("\n".join(lines), str(note))
    existing_names = {item["habit"].strip().lower() for item in existing}
    additions = [habit for habit in expected_habits_for(day) if habit["habit"].strip().lower() not in existing_names]
    if additions:
        insert_at = end if end is not None else len(lines)
        new_lines = [f"- [ ] {habit['text']}" for habit in additions]
        lines[insert_at:insert_at] = new_lines
        note.write_text("\n".join(lines).rstrip() + "\n")
    return habits_today()


def habits_today() -> dict:
    note = daily_file()
    day = note_date_from_path(note) or dt.date.today()
    markdown = note.read_text()
    config_habits = read_habit_config()
    parsed = attach_habit_config([{**habit, "date": day.isoformat()} for habit in parse_habit_lines(markdown, str(note))], config_habits)
    expected = expected_habits_for(day)
    archived = [habit for habit in config_habits if habit.get("status") != "active"]
    return {"date": day.isoformat(), "path": str(note), "habits": parsed, "expected": expected, "archived": archived, "configPath": str(habits_config_path())}


def update_today_habit(line_number: int, habit: str, state: str) -> dict:
    note = daily_file()
    lines = note.read_text().splitlines(keepends=True)
    if not 1 <= line_number <= len(lines):
        raise ValueError("Habit line no longer exists in today's note.")
    if not line_in_habit_section(lines, line_number):
        raise ValueError("That line is not inside the Habits:: section. Refresh habits first.")
    match = re.match(r"^(\s*-\s+\[)[ xX-](\]\s+)(.*?)(\r?\n?)$", lines[line_number - 1])
    if not match:
        raise ValueError("Habit line changed in Obsidian. Refresh habits first.")
    body = match.group(3).strip()
    current_name = body.split(" — ", 1)[0].strip()
    if current_name != habit:
        raise ValueError("Habit changed in Obsidian. Refresh habits first.")
    marker = {"completed": "x", "pending": " ", "skipped": "-"}.get(state)
    if marker is None:
        raise ValueError("Choose completed, pending, or skipped.")
    lines[line_number - 1] = match.group(1) + marker + match.group(2) + match.group(3) + match.group(4)
    note.write_text("".join(lines))
    return habits_today()


def habit_history(range_name: str = "month") -> dict:
    today = dt.date.today()
    month_start = today.replace(day=1)
    entries = []
    daily_totals: dict[str, dict] = {}
    habit_names: set[str] = set()
    for folder in daily_candidate_folders():
        if not folder.is_dir():
            continue
        for note in sorted(folder.glob("*.md")):
            day = note_date_from_path(note)
            if not day or (range_name != "all" and day < month_start):
                continue
            try:
                habits = parse_habit_lines(note.read_text(), str(note))
            except OSError:
                continue
            if not habits:
                continue
            total = daily_totals.setdefault(day.isoformat(), {"date": day.isoformat(), "completed": 0, "scheduled": 0, "skipped": 0})
            for habit in habits:
                habit_names.add(habit["habit"])
                entries.append({**habit, "date": day.isoformat()})
                total["scheduled"] += 1
                if habit["state"] == "completed":
                    total["completed"] += 1
                if habit["state"] == "skipped":
                    total["skipped"] += 1
    config_habits = read_habit_config()
    config_by_name = {habit.get("habit", "").strip().lower(): habit for habit in config_habits}
    entries = [{**entry, "time": config_by_name.get(entry.get("habit", "").strip().lower(), {}).get("time", ""), "timeMinutes": config_by_name.get(entry.get("habit", "").strip().lower(), {}).get("timeMinutes"), "order": config_by_name.get(entry.get("habit", "").strip().lower(), {}).get("order", 9999)} for entry in entries]
    archived = [habit for habit in config_habits if habit.get("status") != "active"]
    for habit in config_habits:
        habit_names.add(habit["habit"])
    return {"range": range_name, "entries": sorted(entries, key=lambda item: (item.get("date", ""), *habit_sort_key(item))), "dailyTotals": sorted(daily_totals.values(), key=lambda item: item["date"]), "habits": sorted(habit_names), "active": sorted([h for h in config_habits if h.get("status") == "active"], key=habit_sort_key), "archived": sorted(archived, key=habit_sort_key)}

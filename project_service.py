from __future__ import annotations

import datetime as dt
from pathlib import Path
import re
import subprocess

from obsidian_repo import (
    daily_candidate_folders,
    decimal_field,
    line_in_habit_section,
    note_date_from_path,
    note_safe_name,
    project_slug,
    project_title_from_slug,
    strip_project_task_text,
    vault_folder,
)


def project_notes() -> dict[str, dict]:
    projects_dir = vault_folder() / "Projects"
    notes: dict[str, dict] = {}
    if not projects_dir.is_dir():
        return notes
    for note in sorted(projects_dir.glob("*.md")):
        slug = project_slug(note.stem)
        notes[slug] = {"slug": slug, "title": note.stem, "path": str(note)}
    return notes


def project_task_notes() -> list[Path]:
    folders: list[Path] = []
    for folder in daily_candidate_folders():
        if folder.is_dir() and folder not in folders:
            folders.append(folder)
    notes: list[Path] = []
    for folder in folders:
        notes.extend(sorted(folder.glob("*.md")))
    return sorted(set(notes))


def parse_project_tasks_from_note(note: Path) -> list[dict]:
    try:
        markdown = note.read_text()
    except OSError:
        return []
    lines = markdown.splitlines()
    tasks = []
    for index, line in enumerate(lines):
        if line_in_habit_section(lines, index + 1):
            continue
        match = re.match(r"^\s*-\s+\[([ xX])\]\s+(.+?)\s*$", line)
        if not match:
            continue
        body = match.group(2).strip()
        project_tags = re.findall(r"#project/([A-Za-z0-9/_-]+)", body)
        if not project_tags:
            continue
        for raw_slug in project_tags:
            slug = project_slug(raw_slug)
            if not slug:
                continue
            tasks.append({
                "projectSlug": slug,
                "projectTag": f"#project/{raw_slug}",
                "text": strip_project_task_text(body),
                "raw": body,
                "done": match.group(1).lower() == "x",
                "milestone": bool(re.search(r"#milestone\b", body)),
                "estimate": decimal_field(body, "estimate"),
                "time": decimal_field(body, "time"),
                "source": str(note),
                "line": index + 1,
                "date": (note_date_from_path(note) or dt.date.fromtimestamp(note.stat().st_mtime)).isoformat(),
            })
    return tasks


def projects_summary() -> dict:
    notes = project_notes()
    tasks = [task for note in project_task_notes() for task in parse_project_tasks_from_note(note)]
    grouped: dict[str, dict] = {}
    for slug, note in notes.items():
        grouped[slug] = {**note, "tasks": []}
    for task in tasks:
        slug = task["projectSlug"]
        grouped.setdefault(slug, {"slug": slug, "title": project_title_from_slug(slug), "path": "", "tasks": []})
        grouped[slug]["tasks"].append(task)
    projects = []
    for project in grouped.values():
        project_tasks = sorted(project["tasks"], key=lambda item: (not item["milestone"], item["done"], item["date"], item["line"]))
        completed = sum(1 for task in project_tasks if task["done"])
        milestones = [task for task in project_tasks if task["milestone"]]
        projects.append({
            **{key: project.get(key, "") for key in ("slug", "title", "path")},
            "taskCount": len(project_tasks),
            "completedCount": completed,
            "openCount": len(project_tasks) - completed,
            "milestoneCount": len(milestones),
            "milestoneCompleted": sum(1 for task in milestones if task["done"]),
            "estimateTotal": round(sum(task["estimate"] for task in project_tasks), 2),
            "timeTotal": round(sum(task["time"] for task in project_tasks), 2),
            "tasks": project_tasks,
        })
    projects.sort(key=lambda item: (item["openCount"] == 0, -item["milestoneCount"], -item["openCount"], item["title"].lower()))
    return {"projects": projects, "taskCount": len(tasks), "projectsPath": str(vault_folder() / "Projects"), "templatePath": str(vault_folder() / "Templates" / "Project.md")}


def project_note_path(slug: str, title: str = "") -> Path:
    notes = project_notes()
    if slug in notes and notes[slug].get("path"):
        return Path(notes[slug]["path"])
    return vault_folder() / "Projects" / f"{note_safe_name(title or project_title_from_slug(slug))}.md"


def create_project_note(slug: str, title: str = "") -> dict:
    clean_slug = project_slug(slug or title)
    if not clean_slug:
        raise ValueError("Choose a project name first.")
    project_title = title.strip() or project_title_from_slug(clean_slug)
    destination = project_note_path(clean_slug, project_title)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if not destination.exists():
        templates_dir = vault_folder() / "Templates"
        template = templates_dir / "Project.md"
        if not template.is_file():
            template = templates_dir / "Project"
        content = template.read_text() if template.is_file() else "# {{title}}\n\n## Tasks\n\n```tasks\nnot done\ntag includes #project/{{slug}}\n```\n"
        content = content.replace("{{title}}", project_title).replace("{{project}}", project_title).replace("{{slug}}", clean_slug)
        destination.write_text(content.rstrip() + "\n")
    return {"slug": clean_slug, "title": project_title, "path": str(destination)}


def open_project_note(slug: str) -> dict:
    note = project_note_path(project_slug(slug))
    if not note.is_file():
        raise FileNotFoundError("Create the project note first.")
    subprocess.run(["open", str(note)], check=False)
    return {"opened": True, "path": str(note)}


def safe_project_task_source(source: str) -> Path:
    source_path = Path(source).expanduser().resolve()
    allowed = [folder.resolve() for folder in daily_candidate_folders()]
    if not any(source_path.is_relative_to(folder) for folder in allowed):
        raise ValueError("Project task source must be inside your Daily Notes folders.")
    if not source_path.is_file():
        raise FileNotFoundError("Project task source note no longer exists.")
    return source_path


def update_project_task(body: dict) -> dict:
    note = safe_project_task_source(str(body.get("source", "")))
    line_number = int(body.get("line", 0))
    expected_text = str(body.get("previousText", "")).strip()
    lines = note.read_text().splitlines(keepends=True)
    if not 1 <= line_number <= len(lines):
        raise ValueError("Project task line no longer exists.")
    if line_in_habit_section(lines, line_number):
        raise ValueError("That line is inside Habits::. Use the Habits card instead.")
    match = re.match(r"^(\s*-\s+\[)[ xX](\]\s+)(.*?)(\r?\n?)$", lines[line_number - 1])
    if not match or match.group(3).strip() != expected_text:
        raise ValueError("Project task changed in Obsidian. Refresh projects first.")
    if "completed" in body:
        marker = "x" if body.get("completed") else " "
        replacement_text = match.group(3)
    else:
        marker = "x" if match.group(0).lower().find("[x]") >= 0 else " "
        replacement_text = " ".join(str(body.get("text", "")).splitlines()).strip()
        if not replacement_text:
            raise ValueError("Write a task first.")
        if "#project/" not in replacement_text:
            raise ValueError("Project tasks must keep a #project/... tag.")
    lines[line_number - 1] = match.group(1) + marker + match.group(2) + replacement_text + match.group(4)
    note.write_text("".join(lines))
    return {"line": line_number, "path": str(note), "text": replacement_text, "completed": marker == "x"}

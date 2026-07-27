"""Skill registry — load, list, create, update, and delete Hermes skill files.

Skills are Markdown files in the `skills/` directory at the project root.
Each skill describes a BIM workflow the Hermes agent can execute.
"""

from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Optional

from ifc_agent.config import config

_SKILLS_DIR = Path(__file__).resolve().parents[2] / "skills"


def _skills_dir() -> Path:
    _SKILLS_DIR.mkdir(parents=True, exist_ok=True)
    return _SKILLS_DIR


def _skill_path(name: str) -> Path:
    safe_name = re.sub(r"[^a-zA-Z0-9_-]", "-", name).strip("-")
    if not safe_name.endswith(".md"):
        safe_name += ".md"
    return _skills_dir() / safe_name


def _parse_skill_file(path: Path) -> dict:
    content = path.read_text(encoding="utf-8")
    name = path.stem
    lines = content.splitlines()

    # Extract title (first # heading)
    title = name
    for line in lines:
        if line.startswith("# "):
            title = line[2:].strip()
            break

    # Extract description (first paragraph after title)
    description = ""
    in_body = False
    for line in lines:
        if line.startswith("# "):
            in_body = True
            continue
        if in_body and line.strip():
            description = line.strip()
            break

    # Extract ## When to use section
    when_to_use = ""
    in_section = False
    section_lines = []
    for line in lines:
        if line.startswith("## When to use"):
            in_section = True
            continue
        if in_section:
            if line.startswith("## "):
                break
            section_lines.append(line)
    when_to_use = "\n".join(section_lines).strip()

    # Extract tools list
    tools = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("`") and "`" in stripped[1:]:
            tool_match = re.findall(r"`([a-z_]+)`", stripped)
            tools.extend(tool_match)

    stat = path.stat()
    return {
        "name": name,
        "file": path.name,
        "path": str(path),
        "title": title,
        "description": description,
        "when_to_use": when_to_use,
        "tools_mentioned": list(dict.fromkeys(tools)),
        "content": content,
        "size_bytes": stat.st_size,
        "modified": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(stat.st_mtime)),
    }


def list_skills() -> list[dict]:
    """Return metadata for all skill files in the skills directory."""
    skills_dir = _skills_dir()
    skills = []
    for path in sorted(skills_dir.glob("*.md")):
        try:
            skills.append(_parse_skill_file(path))
        except Exception:
            skills.append({"name": path.stem, "file": path.name, "path": str(path), "error": "Could not parse"})
    return skills


def get_skill(name: str) -> Optional[dict]:
    """Return full skill data for a given skill name (without .md suffix)."""
    path = _skill_path(name)
    if not path.exists():
        # Try exact name match
        for candidate in _skills_dir().glob("*.md"):
            if candidate.stem == name:
                path = candidate
                break
        else:
            return None
    return _parse_skill_file(path)


def create_skill(
    name: str,
    title: str,
    description: str,
    when_to_use: str,
    workflow: str,
    tools_needed: list[str] = None,
) -> dict:
    """Create a new skill Markdown file.

    Args:
        name: Skill filename (without .md). Use kebab-case.
        title: Human-readable title.
        description: One-paragraph description of what the skill does.
        when_to_use: Bullet-point list of when to invoke this skill.
        workflow: Step-by-step workflow content (Markdown).
        tools_needed: List of MCP tool names used by this skill.

    Returns:
        Dict with status and skill metadata.
    """
    path = _skill_path(name)
    if path.exists():
        return {"status": "error", "message": f"Skill '{name}' already exists. Use update to modify it."}

    tools_section = ""
    if tools_needed:
        tools_list = "\n".join(f"- `{t}`" for t in tools_needed)
        tools_section = f"\n## Tools needed\nThis skill uses the `ifc-agent` MCP server tools:\n{tools_list}\n"

    content = f"""# {title}

{description}

## When to use
{when_to_use}
{tools_section}
## Workflow

{workflow}
"""
    path.write_text(content, encoding="utf-8")
    return {"status": "created", "skill": _parse_skill_file(path)}


def update_skill(name: str, content: str) -> dict:
    """Overwrite a skill file with new Markdown content.

    Args:
        name: Skill name (without .md).
        content: Full new Markdown content.

    Returns:
        Dict with status and updated skill metadata.
    """
    path = _skill_path(name)
    if not path.exists():
        # Check for existing file
        for candidate in _skills_dir().glob("*.md"):
            if candidate.stem == name:
                path = candidate
                break
        else:
            return {"status": "error", "message": f"Skill '{name}' not found. Use create to add it."}

    path.write_text(content, encoding="utf-8")
    return {"status": "updated", "skill": _parse_skill_file(path)}


def delete_skill(name: str) -> dict:
    """Delete a skill file.

    Args:
        name: Skill name (without .md).

    Returns:
        Dict with status.
    """
    path = _skill_path(name)
    if not path.exists():
        for candidate in _skills_dir().glob("*.md"):
            if candidate.stem == name:
                path = candidate
                break
        else:
            return {"status": "error", "message": f"Skill '{name}' not found."}

    path.unlink()
    return {"status": "deleted", "name": name}

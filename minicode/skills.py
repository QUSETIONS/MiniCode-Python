from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class SkillSummary:
    name: str
    description: str
    path: str
    source: str


@dataclass(slots=True)
class LoadedSkill(SkillSummary):
    content: str


def extract_description(markdown: str) -> str:
    normalized = markdown.replace("\r\n", "\n")
    paragraphs = [block.strip() for block in normalized.split("\n\n") if block.strip()]
    for block in paragraphs:
        if block.startswith("#"):
            continue
        for line in [part.strip() for part in block.split("\n")]:
            if line and not line.startswith("#"):
                return line.replace("`", "")
    return "No description provided."


def _home_dir() -> Path:
    return Path.home()


def _skill_roots(cwd: str | Path) -> list[tuple[Path, str]]:
    base = Path(cwd)
    home = _home_dir()
    return [
        (base / ".mini-code" / "skills", "project"),
        (home / ".mini-code" / "skills", "user"),
        (base / ".claude" / "skills", "compat_project"),
        (home / ".claude" / "skills", "compat_user"),
    ]


def _list_skill_dirs(root: Path, source: str) -> list[LoadedSkill]:
    if not root.exists():
        return []
    results: list[LoadedSkill] = []
    for entry in root.iterdir():
        try:
            if not entry.is_dir():
                continue
        except OSError:
            # Windows: untrusted mount points, broken symlinks, etc.
            continue
        skill_path = entry / "SKILL.md"
        if not skill_path.exists():
            continue
        try:
            content = skill_path.read_text(encoding="utf-8")
        except OSError:
            continue
        results.append(
            LoadedSkill(
                name=entry.name,
                description=extract_description(content),
                path=str(skill_path),
                source=source,
                content=content,
            )
        )
    return results


def discover_skills(cwd: str | Path) -> list[SkillSummary]:
    by_name: dict[str, LoadedSkill] = {}
    for root, source in _skill_roots(cwd):
        for skill in _list_skill_dirs(root, source):
            by_name.setdefault(skill.name, skill)
    return [
        SkillSummary(
            name=skill.name,
            description=skill.description,
            path=skill.path,
            source=skill.source,
        )
        for skill in by_name.values()
    ]


def load_skill(cwd: str | Path, name: str) -> LoadedSkill | None:
    normalized_name = name.strip()
    if not normalized_name:
        return None
    for root, source in _skill_roots(cwd):
        skill_path = root / normalized_name / "SKILL.md"
        if skill_path.exists():
            content = skill_path.read_text(encoding="utf-8")
            return LoadedSkill(
                name=normalized_name,
                description=extract_description(content),
                path=str(skill_path),
                source=source,
                content=content,
            )
    return None


def _managed_skill_root(scope: str, cwd: str | Path) -> Path:
    return (Path(cwd) / ".mini-code" / "skills") if scope == "project" else (_home_dir() / ".mini-code" / "skills")


def install_skill(cwd: str | Path, source_path: str, name: str | None = None, scope: str = "user") -> dict[str, str]:
    source = Path(source_path)
    if not source.is_absolute():
        source = Path(cwd) / source
    if source.is_dir():
        skill_file = source / "SKILL.md"
        inferred_name = source.name
    else:
        skill_file = source if source.name == "SKILL.md" else source / "SKILL.md"
        inferred_name = skill_file.parent.name
    if not skill_file.exists():
        raise RuntimeError(f"No SKILL.md found in {source}")

    skill_name = (name or inferred_name).strip()
    if not skill_name:
        raise RuntimeError("Skill name cannot be empty.")

    target_dir = _managed_skill_root(scope, cwd) / skill_name
    target_dir.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(skill_file, target_dir / "SKILL.md")
    return {"name": skill_name, "targetPath": str(target_dir / "SKILL.md")}


def remove_managed_skill(cwd: str | Path, name: str, scope: str = "user") -> dict[str, object]:
    target_path = _managed_skill_root(scope, cwd) / name
    if not target_path.exists():
        return {"removed": False, "targetPath": str(target_path)}
    shutil.rmtree(target_path)
    return {"removed": True, "targetPath": str(target_path)}


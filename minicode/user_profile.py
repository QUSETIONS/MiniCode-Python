"""USER.md user profile system for persisting user preferences.

Supports two scopes:
- Global: ~/.mini-code/USER.md  (applies across all projects)
- Project: .mini-code/USER.md   (project-specific overrides)

Profile sections:
- preferences: General preferences (language, verbosity, response style)
- coding_style: Code formatting and style preferences
- common_patterns: Frequently used patterns and conventions
- project_context: Project-specific notes and context
- custom_instructions: Free-form instructions for the assistant
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class UserPreferences:
    """General user preferences."""
    language: str = ""           # e.g. "zh-CN", "en-US"
    verbosity: str = ""          # "concise" | "normal" | "detailed"
    response_style: str = ""    # "formal" | "casual" | "technical"
    preferred_framework: str = ""  # e.g. "react", "vue", "svelte"
    preferred_test_framework: str = ""  # e.g. "pytest", "jest"
    auto_format: bool = False    # Auto-format code on edit


@dataclass
class CodingStyle:
    """Code style preferences."""
    indent_style: str = ""       # "spaces" | "tabs"
    indent_size: int = 0         # 2, 4, etc.
    quote_style: str = ""        # "single" | "double"
    semicolons: bool = False     # For JS/TS
    trailing_comma: bool = False
    max_line_length: int = 0
    naming_convention: str = ""  # "camelCase", "snake_case", "PascalCase"


@dataclass
class UserProfile:
    """Complete user profile loaded from USER.md."""
    preferences: UserPreferences = field(default_factory=UserPreferences)
    coding_style: CodingStyle = field(default_factory=CodingStyle)
    common_patterns: list[str] = field(default_factory=list)
    project_context: str = ""
    custom_instructions: str = ""
    # Metadata
    source_path: str = ""        # Which file this was loaded from
    raw_content: str = ""        # Original Markdown content


# ---------------------------------------------------------------------------
# Markdown parser
# ---------------------------------------------------------------------------

_SECTION_RE = re.compile(r"^##\s+(.+)$", re.MULTILINE)
_KV_RE = re.compile(r"^-\s+\*\*(.+?)\*\*:\s*(.+)$")
_LIST_ITEM_RE = re.compile(r"^-\s+(.+)$", re.MULTILINE)


def _parse_section_body(body: str) -> dict[str, str]:
    """Parse key-value pairs from a section body like '- **key**: value'."""
    result: dict[str, str] = {}
    for line in body.strip().splitlines():
        m = _KV_RE.match(line.strip())
        if m:
            result[m.group(1).strip().lower().replace(" ", "_")] = m.group(2).strip()
    return result


def _parse_list_items(body: str) -> list[str]:
    """Parse list items from a section body like '- item'."""
    items: list[str] = []
    for line in body.strip().splitlines():
        m = _LIST_ITEM_RE.match(line.strip())
        if m:
            items.append(m.group(1).strip())
    return items


def parse_user_md(content: str) -> UserProfile:
    """Parse USER.md Markdown content into a UserProfile."""
    profile = UserProfile(raw_content=content)

    # Split into sections by ## headings
    sections: dict[str, str] = {}
    parts = _SECTION_RE.split(content)

    # parts[0] is before first heading, then alternating: heading, body
    for i in range(1, len(parts) - 1, 2):
        heading = parts[i].strip().lower().replace(" ", "_")
        body = parts[i + 1]
        sections[heading] = body

    # Parse preferences
    if "preferences" in sections:
        kv = _parse_section_body(sections["preferences"])
        p = profile.preferences
        p.language = kv.get("language", "")
        p.verbosity = kv.get("verbosity", "")
        p.response_style = kv.get("response_style", "")
        p.preferred_framework = kv.get("preferred_framework", "")
        p.preferred_test_framework = kv.get("preferred_test_framework", "")
        p.auto_format = kv.get("auto_format", "").lower() in ("true", "yes", "1")

    # Parse coding_style
    if "coding_style" in sections:
        kv = _parse_section_body(sections["coding_style"])
        cs = profile.coding_style
        cs.indent_style = kv.get("indent_style", "")
        try:
            cs.indent_size = int(kv.get("indent_size", "0"))
        except ValueError:
            cs.indent_size = 0
        cs.quote_style = kv.get("quote_style", "")
        cs.semicolons = kv.get("semicolons", "").lower() in ("true", "yes", "1")
        cs.trailing_comma = kv.get("trailing_comma", "").lower() in ("true", "yes", "1")
        try:
            cs.max_line_length = int(kv.get("max_line_length", "0"))
        except ValueError:
            cs.max_line_length = 0
        cs.naming_convention = kv.get("naming_convention", "")

    # Parse common_patterns
    if "common_patterns" in sections:
        profile.common_patterns = _parse_list_items(sections["common_patterns"])

    # Parse project_context (free text after heading)
    if "project_context" in sections:
        profile.project_context = sections["project_context"].strip()

    # Parse custom_instructions (free text after heading)
    if "custom_instructions" in sections:
        profile.custom_instructions = sections["custom_instructions"].strip()

    return profile


# ---------------------------------------------------------------------------
# Markdown serializer
# ---------------------------------------------------------------------------

def serialize_user_md(profile: UserProfile) -> str:
    """Serialize a UserProfile back into USER.md Markdown format."""
    lines: list[str] = ["# User Profile", ""]

    # Preferences
    p = profile.preferences
    if any([p.language, p.verbosity, p.response_style, p.preferred_framework,
            p.preferred_test_framework, p.auto_format]):
        lines.append("## Preferences")
        if p.language:
            lines.append(f"- **Language**: {p.language}")
        if p.verbosity:
            lines.append(f"- **Verbosity**: {p.verbosity}")
        if p.response_style:
            lines.append(f"- **Response Style**: {p.response_style}")
        if p.preferred_framework:
            lines.append(f"- **Preferred Framework**: {p.preferred_framework}")
        if p.preferred_test_framework:
            lines.append(f"- **Preferred Test Framework**: {p.preferred_test_framework}")
        if p.auto_format:
            lines.append("- **Auto Format**: true")
        lines.append("")

    # Coding Style
    cs = profile.coding_style
    if any([cs.indent_style, cs.indent_size, cs.quote_style, cs.naming_convention,
            cs.semicolons, cs.trailing_comma, cs.max_line_length]):
        lines.append("## Coding Style")
        if cs.indent_style:
            lines.append(f"- **Indent Style**: {cs.indent_style}")
        if cs.indent_size:
            lines.append(f"- **Indent Size**: {cs.indent_size}")
        if cs.quote_style:
            lines.append(f"- **Quote Style**: {cs.quote_style}")
        if cs.semicolons:
            lines.append("- **Semicolons**: true")
        if cs.trailing_comma:
            lines.append("- **Trailing Comma**: true")
        if cs.max_line_length:
            lines.append(f"- **Max Line Length**: {cs.max_line_length}")
        if cs.naming_convention:
            lines.append(f"- **Naming Convention**: {cs.naming_convention}")
        lines.append("")

    # Common Patterns
    if profile.common_patterns:
        lines.append("## Common Patterns")
        for pattern in profile.common_patterns:
            lines.append(f"- {pattern}")
        lines.append("")

    # Project Context
    if profile.project_context:
        lines.append("## Project Context")
        lines.append(profile.project_context)
        lines.append("")

    # Custom Instructions
    if profile.custom_instructions:
        lines.append("## Custom Instructions")
        lines.append(profile.custom_instructions)
        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Profile manager
# ---------------------------------------------------------------------------

class UserProfileManager:
    """Manage USER.md profiles with global + project scope merging."""

    def __init__(self, cwd: str | Path | None = None):
        from minicode.config import MINI_CODE_DIR
        self._global_path = MINI_CODE_DIR / "USER.md"
        self._project_path = Path(cwd or Path.cwd()) / ".mini-code" / "USER.md"

    @property
    def global_path(self) -> Path:
        return self._global_path

    @property
    def project_path(self) -> Path:
        return self._project_path

    def load_global(self) -> Optional[UserProfile]:
        """Load global profile from ~/.mini-code/USER.md."""
        return self._load_from(self._global_path)

    def load_project(self) -> Optional[UserProfile]:
        """Load project profile from .mini-code/USER.md."""
        return self._load_from(self._project_path)

    def load_merged(self) -> UserProfile:
        """Load and merge global + project profiles. Project overrides global."""
        global_profile = self.load_global()
        project_profile = self.load_project()

        if global_profile is None and project_profile is None:
            return UserProfile()
        if global_profile is None:
            return project_profile  # type: ignore[return-value]
        if project_profile is None:
            return global_profile

        return self._merge_profiles(global_profile, project_profile)

    def save_global(self, profile: UserProfile) -> None:
        """Save profile to global path."""
        self._save_to(self._global_path, profile)

    def save_project(self, profile: UserProfile) -> None:
        """Save profile to project path."""
        self._save_to(self._project_path, profile)

    def to_prompt_section(self, profile: UserProfile) -> str:
        """Convert profile to a system prompt section for LLM injection."""
        parts: list[str] = ["## User Profile", ""]

        p = profile.preferences
        prefs = []
        if p.language:
            prefs.append(f"Language: {p.language}")
        if p.verbosity:
            prefs.append(f"Verbosity: {p.verbosity}")
        if p.response_style:
            prefs.append(f"Response style: {p.response_style}")
        if p.preferred_framework:
            prefs.append(f"Preferred framework: {p.preferred_framework}")
        if p.preferred_test_framework:
            prefs.append(f"Preferred test framework: {p.preferred_test_framework}")
        if p.auto_format:
            prefs.append("Auto-format on edit: yes")
        if prefs:
            parts.append("Preferences: " + ", ".join(prefs))

        cs = profile.coding_style
        style = []
        if cs.indent_style:
            style.append(f"indent: {cs.indent_style}" + (f" ({cs.indent_size})" if cs.indent_size else ""))
        if cs.quote_style:
            style.append(f"quotes: {cs.quote_style}")
        if cs.naming_convention:
            style.append(f"naming: {cs.naming_convention}")
        if cs.max_line_length:
            style.append(f"max line: {cs.max_line_length}")
        if style:
            parts.append("Coding style: " + ", ".join(style))

        if profile.common_patterns:
            parts.append("Common patterns: " + "; ".join(profile.common_patterns[:5]))

        if profile.project_context:
            parts.append(f"Project context: {profile.project_context[:200]}")

        if profile.custom_instructions:
            parts.append(f"Custom instructions: {profile.custom_instructions[:300]}")

        if len(parts) <= 2:
            return ""  # No meaningful content

        return "\n".join(parts)

    def search_preferences(self, profile: UserProfile, query: str) -> list[str]:
        """Search profile for preferences matching a query string."""
        query_lower = query.lower()
        matches: list[str] = []

        # Check preferences
        for attr in ["language", "verbosity", "response_style",
                     "preferred_framework", "preferred_test_framework"]:
            val = getattr(profile.preferences, attr, "")
            if val and query_lower in val.lower():
                matches.append(f"preference.{attr} = {val}")

        # Check coding style
        for attr in ["indent_style", "quote_style", "naming_convention"]:
            val = getattr(profile.coding_style, attr, "")
            if val and query_lower in val.lower():
                matches.append(f"coding_style.{attr} = {val}")

        # Check patterns
        for pattern in profile.common_patterns:
            if query_lower in pattern.lower():
                matches.append(f"pattern: {pattern}")

        # Check free text
        for text, label in [
            (profile.project_context, "project_context"),
            (profile.custom_instructions, "custom_instructions"),
        ]:
            if text and query_lower in text.lower():
                matches.append(f"{label}: (matched)")

        return matches

    # -----------------------------------------------------------------------
    # Internal helpers
    # -----------------------------------------------------------------------

    @staticmethod
    def _load_from(path: Path) -> Optional[UserProfile]:
        """Load a profile from a specific path."""
        if not path.exists() or not path.is_file():
            return None
        try:
            content = path.read_text(encoding="utf-8")
            profile = parse_user_md(content)
            profile.source_path = str(path)
            return profile
        except Exception:
            return None

    @staticmethod
    def _save_to(path: Path, profile: UserProfile) -> None:
        """Save a profile to a specific path."""
        path.parent.mkdir(parents=True, exist_ok=True)
        content = serialize_user_md(profile)
        path.write_text(content, encoding="utf-8")

    @staticmethod
    def _merge_profiles(global_p: UserProfile, project_p: UserProfile) -> UserProfile:
        """Merge global and project profiles. Project values override global."""
        merged = UserProfile()

        # Merge preferences (project overrides global for non-empty values)
        gp, pp, mp = global_p.preferences, project_p.preferences, merged.preferences
        for attr in ["language", "verbosity", "response_style",
                     "preferred_framework", "preferred_test_framework"]:
            setattr(mp, attr, getattr(pp, attr, "") or getattr(gp, attr, ""))
        mp.auto_format = pp.auto_format or gp.auto_format

        # Merge coding style
        gcs, pcs, mcs = global_p.coding_style, project_p.coding_style, merged.coding_style
        for attr in ["indent_style", "quote_style", "naming_convention"]:
            setattr(mcs, attr, getattr(pcs, attr, "") or getattr(gcs, attr, ""))
        for attr in ["indent_size", "max_line_length"]:
            setattr(mcs, attr, getattr(pcs, attr, 0) or getattr(gcs, attr, 0))
        mcs.semicolons = pcs.semicolons or gcs.semicolons
        mcs.trailing_comma = pcs.trailing_comma or gcs.trailing_comma

        # Merge lists (deduplicated)
        seen: set[str] = set()
        for pattern in global_p.common_patterns + project_p.common_patterns:
            if pattern not in seen:
                merged.common_patterns.append(pattern)
                seen.add(pattern)

        # Free text: project overrides global
        merged.project_context = project_p.project_context or global_p.project_context
        merged.custom_instructions = project_p.custom_instructions or global_p.custom_instructions

        # Source metadata
        merged.source_path = f"{global_p.source_path} + {project_p.source_path}"

        return merged


# ---------------------------------------------------------------------------
# CLI command handler
# ---------------------------------------------------------------------------

def handle_user_command(args: str, cwd: str | Path | None = None) -> str:
    """Handle /user CLI commands.

    Subcommands:
        /user           — Show merged profile summary
        /user global    — Show global profile
        /user project   — Show project profile
        /user paths     — Show profile file paths
        /user reset     — Reset (delete) the project profile
        /user reset-global — Reset (delete) the global profile
        /user set <key> <value> — Set a preference (dot-notation, e.g. preferences.language)
        /user search <query> — Search profile for matching preferences
    """
    manager = UserProfileManager(cwd)
    parts = args.strip().split(maxsplit=1)
    subcmd = parts[0] if parts else ""
    subcmd_args = parts[1] if len(parts) > 1 else ""

    if not subcmd or subcmd == "show":
        # Show merged profile
        profile = manager.load_merged()
        prompt_section = manager.to_prompt_section(profile)
        if not prompt_section:
            return "No user profile configured. Create ~/.mini-code/USER.md or .mini-code/USER.md"
        source = profile.source_path or "none"
        return f"{prompt_section}\n\nSource: {source}"

    if subcmd == "global":
        profile = manager.load_global()
        if profile is None:
            return f"No global profile found at {manager.global_path}"
        return f"Global Profile ({manager.global_path})\n\n{manager.to_prompt_section(profile)}"

    if subcmd == "project":
        profile = manager.load_project()
        if profile is None:
            return f"No project profile found at {manager.project_path}"
        return f"Project Profile ({manager.project_path})\n\n{manager.to_prompt_section(profile)}"

    if subcmd == "paths":
        return "\n".join([
            f"Global:  {manager.global_path} ({'exists' if manager.global_path.exists() else 'not found'})",
            f"Project: {manager.project_path} ({'exists' if manager.project_path.exists() else 'not found'})",
        ])

    if subcmd == "reset":
        if not manager.project_path.exists():
            return f"No project profile to reset at {manager.project_path}"
        manager.project_path.unlink()
        return f"Deleted project profile: {manager.project_path}"

    if subcmd == "reset-global":
        if not manager.global_path.exists():
            return f"No global profile to reset at {manager.global_path}"
        manager.global_path.unlink()
        return f"Deleted global profile: {manager.global_path}"

    if subcmd == "set":
        return _handle_user_set(subcmd_args, manager)

    if subcmd == "search":
        profile = manager.load_merged()
        results = manager.search_preferences(profile, subcmd_args)
        if not results:
            return f"No preferences matching '{subcmd_args}'"
        return "\n".join(f"  - {r}" for r in results)

    return (
        f"Unknown /user subcommand: {subcmd}\n"
        "Available: show, global, project, paths, reset, reset-global, set, search"
    )


def _handle_user_set(args: str, manager: UserProfileManager) -> str:
    """Handle /user set <key> <value>."""
    parts = args.strip().split(maxsplit=1)
    if len(parts) < 2:
        return "Usage: /user set <key> <value>\nKeys: preferences.language, preferences.verbosity, etc."
    key, value = parts[0].strip(), parts[1].strip()

    # Determine scope: if key starts with "project.", save to project; else global
    scope = "global"
    if key.startswith("project."):
        key = key[len("project."):]
        scope = "project"

    # Load existing profile
    if scope == "project":
        profile = manager.load_project() or UserProfile()
    else:
        profile = manager.load_global() or UserProfile()

    # Apply the setting
    changed = _apply_setting(profile, key, value)
    if not changed:
        return f"Unknown profile key: {key}\nValid keys: preferences.*, coding_style.*, project_context, custom_instructions"

    # Save
    if scope == "project":
        manager.save_project(profile)
        return f"Set {key} = {value} in project profile ({manager.project_path})"
    else:
        manager.save_global(profile)
        return f"Set {key} = {value} in global profile ({manager.global_path})"


def _apply_setting(profile: UserProfile, key: str, value: str) -> bool:
    """Apply a single setting to a profile. Returns True if key was valid."""
    # Preferences
    pref_keys = {
        "preferences.language": "language",
        "preferences.verbosity": "verbosity",
        "preferences.response_style": "response_style",
        "preferences.preferred_framework": "preferred_framework",
        "preferences.preferred_test_framework": "preferred_test_framework",
    }
    if key in pref_keys:
        setattr(profile.preferences, pref_keys[key], value)
        return True
    if key == "preferences.auto_format":
        profile.preferences.auto_format = value.lower() in ("true", "yes", "1")
        return True

    # Coding style
    style_keys = {
        "coding_style.indent_style": "indent_style",
        "coding_style.quote_style": "quote_style",
        "coding_style.naming_convention": "naming_convention",
    }
    if key in style_keys:
        setattr(profile.coding_style, style_keys[key], value)
        return True

    int_keys = {
        "coding_style.indent_size": "indent_size",
        "coding_style.max_line_length": "max_line_length",
    }
    if key in int_keys:
        try:
            setattr(profile.coding_style, int_keys[key], int(value))
            return True
        except ValueError:
            return False

    bool_keys = {
        "coding_style.semicolons": "semicolons",
        "coding_style.trailing_comma": "trailing_comma",
    }
    if key in bool_keys:
        setattr(profile.coding_style, bool_keys[key], value.lower() in ("true", "yes", "1"))
        return True

    # Free text
    if key == "project_context":
        profile.project_context = value
        return True
    if key == "custom_instructions":
        profile.custom_instructions = value
        return True

    return False

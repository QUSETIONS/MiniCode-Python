from pathlib import Path

from minicode.skills import discover_skills, load_skill


def test_discover_skills_prefers_project_root(tmp_path: Path, monkeypatch) -> None:
    project_skill = tmp_path / ".mini-code" / "skills" / "demo" / "SKILL.md"
    project_skill.parent.mkdir(parents=True)
    project_skill.write_text("# Demo\n\nProject description\n", encoding="utf-8")

    user_home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(user_home))
    monkeypatch.setenv("USERPROFILE", str(user_home))
    user_skill = user_home / ".mini-code" / "skills" / "demo" / "SKILL.md"
    user_skill.parent.mkdir(parents=True)
    user_skill.write_text("# Demo\n\nUser description\n", encoding="utf-8")

    skills = discover_skills(tmp_path)

    assert len(skills) == 1
    assert skills[0].description == "Project description"
    loaded = load_skill(tmp_path, "demo")
    assert loaded is not None
    assert loaded.content.startswith("# Demo")


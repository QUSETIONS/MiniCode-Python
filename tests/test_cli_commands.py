from minicode.cli_commands import find_matching_slash_commands, format_slash_commands
from minicode.local_tool_shortcuts import parse_local_tool_shortcut


def test_find_matching_slash_commands_returns_help_variants() -> None:
    matches = find_matching_slash_commands("/mo")
    assert "/model" in matches
    assert "/model <model-name>" in matches


def test_parse_local_tool_shortcut_parses_cmd() -> None:
    shortcut = parse_local_tool_shortcut("/cmd src::git status")
    assert shortcut == {
        "toolName": "run_command",
        "input": {"command": "git status", "cwd": "src"},
    }


def test_parse_local_tool_shortcut_parses_patch_pairs() -> None:
    shortcut = parse_local_tool_shortcut("/patch demo.txt::hello::hi::world::earth")
    assert shortcut == {
        "toolName": "patch_file",
        "input": {
            "path": "demo.txt",
            "replacements": [
                {"search": "hello", "replace": "hi"},
                {"search": "world", "replace": "earth"},
            ],
        },
    }


def test_format_slash_commands_includes_permissions() -> None:
    assert "/permissions" in format_slash_commands()


def test_format_slash_commands_describes_patch_replacements() -> None:
    commands = format_slash_commands()
    assert "/patch <path>::<search1>::<replace1>::<search2>::<replace2>..." in commands


def test_format_slash_commands_includes_history_and_retry() -> None:
    commands = format_slash_commands()
    assert "/history" in commands
    assert "/retry" in commands

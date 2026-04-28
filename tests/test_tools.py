from pathlib import Path
import sys

from minicode.permissions import PermissionManager
from minicode.tools.run_command import _build_execution_command, split_command_line
from minicode.tools.patch_file import patch_file_tool
from minicode.tools.run_command import run_command_tool
from minicode.tools.write_file import write_file_tool
from minicode.tooling import ToolContext
from minicode.tools import create_default_tool_registry


def test_split_command_line_supports_quotes() -> None:
    import os

    result = split_command_line("git commit -m 'hello world'")
    assert result[:3] == ["git", "commit", "-m"]
    # On Windows, shlex.split(posix=False) preserves the quotes around
    # the argument; on Unix, posix=True strips them.
    if os.name == "nt":
        assert result[3] == "'hello world'"
    else:
        assert result[3] == "hello world"


def test_write_file_tool_writes_after_review(tmp_path: Path) -> None:
    permissions = PermissionManager(str(tmp_path), prompt=lambda request: {"decision": "allow_once"})
    result = write_file_tool.run(
        {"path": "demo.txt", "content": "hello"},
        ToolContext(cwd=str(tmp_path), permissions=permissions),
    )

    assert result.ok is True
    assert (tmp_path / "demo.txt").read_text(encoding="utf-8") == "hello"


def test_patch_file_tool_applies_multiple_replacements(tmp_path: Path) -> None:
    permissions = PermissionManager(str(tmp_path), prompt=lambda request: {"decision": "allow_once"})
    target = tmp_path / "demo.txt"
    target.write_text("hello world\nhello cc\n", encoding="utf-8")

    result = patch_file_tool.run(
        {
            "path": "demo.txt",
            "replacements": [
                {"search": "hello world", "replace": "hi world"},
                {"search": "hello cc", "replace": "hi cc"},
            ],
        },
        ToolContext(cwd=str(tmp_path), permissions=permissions),
    )

    assert result.ok is True
    assert "2 replacement" in result.output
    assert target.read_text(encoding="utf-8") == "hi world\nhi cc\n"


def test_build_execution_command_uses_cmd_for_windows_shell_builtins() -> None:
    command, args = _build_execution_command(
        "echo hello world",
        "echo",
        ["hello", "world"],
        use_shell=False,
        background_shell=False,
    )

    if __import__("os").name == "nt":
        assert command == "cmd"
        assert args[:3] == ["/d", "/s", "/c"]
        assert args[3] == "echo hello world"
    else:
        assert command == "echo"
        assert args == ["hello", "world"]


def test_run_command_tool_supports_echo_on_current_platform(tmp_path: Path) -> None:
    permissions = PermissionManager(str(tmp_path), prompt=lambda request: {"decision": "allow_once"})
    result = run_command_tool.run(
        {"command": "echo hello"},
        ToolContext(cwd=str(tmp_path), permissions=permissions),
    )

    assert result.ok is True
    assert "hello" in result.output.lower()


def test_default_tool_registry_is_core_first(tmp_path: Path) -> None:
    tools = create_default_tool_registry(str(tmp_path), runtime=None)
    names = {tool.name for tool in tools.list()}

    assert "read_file" in names
    assert "run_command" in names
    assert "base64_encode" not in names
    assert "csv_parse" not in names


def test_full_tool_registry_can_opt_into_utility_wrappers(tmp_path: Path) -> None:
    tools = create_default_tool_registry(str(tmp_path), runtime={"toolProfile": "full"})
    names = {tool.name for tool in tools.list()}

    assert "base64_encode" in names
    assert "csv_parse" in names


def test_core_tool_registry_does_not_import_utility_modules(tmp_path: Path) -> None:
    utility_modules = [
        "minicode.tools.archive_utils",
        "minicode.tools.crypto_utils",
        "minicode.tools.csv_utils",
        "minicode.tools.encoding_utils",
        "minicode.tools.http_utils",
        "minicode.tools.json_utils",
        "minicode.tools.regex_utils",
        "minicode.tools.text_utils",
    ]
    for module_name in utility_modules:
        sys.modules.pop(module_name, None)

    create_default_tool_registry(str(tmp_path), runtime={"toolProfile": "core"})

    assert all(module_name not in sys.modules for module_name in utility_modules)

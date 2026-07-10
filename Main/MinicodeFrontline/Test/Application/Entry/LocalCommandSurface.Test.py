from __future__ import annotations

from Main.MinicodeFrontline.Src.Application.Entry.LocalCommandSurface import (
    SLASH_COMMANDS,
)


def test_local_command_surface_declares_core_product_commands() -> None:
    names = {command.name for command in SLASH_COMMANDS}

    assert "/session" in names
    assert "/session-replay" in names
    assert "/sessions" in names
    assert "/readiness" in names
    assert "/extensions" in names
    assert "/rewind" in names


def test_local_command_surface_keeps_usage_metadata_complete() -> None:
    assert len(SLASH_COMMANDS) >= 40
    assert all(command.name.startswith("/") for command in SLASH_COMMANDS)
    assert all(command.usage.startswith(command.name) for command in SLASH_COMMANDS)
    assert all(command.description for command in SLASH_COMMANDS)

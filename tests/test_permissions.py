from pathlib import Path

import pytest

from minicode.permissions import PermissionManager


def test_permission_manager_uses_prompt_for_external_path(tmp_path: Path) -> None:
    external = tmp_path.parent / "outside.txt"
    manager = PermissionManager(str(tmp_path), prompt=lambda request: {"decision": "allow_once"})
    manager.ensure_path_access(str(external), "read")


def test_permission_manager_denies_external_path_without_prompt(tmp_path: Path) -> None:
    external = tmp_path.parent / "outside.txt"
    manager = PermissionManager(str(tmp_path))
    with pytest.raises(RuntimeError):
        manager.ensure_path_access(str(external), "read")

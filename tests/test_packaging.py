from __future__ import annotations

import importlib
import json
import subprocess
import sys
import threading
import tomllib
import urllib.error
import urllib.request
from pathlib import Path

import pytest
from setuptools import find_namespace_packages

from Main.MinicodeFrontline.Src.Application.Entry.RuntimeLifecycleSurface import (
    lifecycle_script_targets,
)


ROOT = Path(__file__).resolve().parent.parent


def test_dev_extra_declares_packaging_test_dependencies() -> None:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    assert "setuptools>=68" in pyproject["project"]["optional-dependencies"]["dev"]


def test_console_script_entry_points_import() -> None:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    failures = []
    for name, target in pyproject["project"]["scripts"].items():
        module_name, _, attr_name = target.partition(":")
        try:
            module = importlib.import_module(module_name)
        except Exception as exc:  # noqa: BLE001
            failures.append(f"{name}: cannot import {module_name}: {exc}")
            continue
        if not hasattr(module, attr_name):
            failures.append(f"{name}: {module_name}.{attr_name} does not exist")

    assert failures == []


def test_console_script_entry_points_match_main_lifecycle_contract() -> None:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    assert pyproject["project"]["scripts"] == {
        **lifecycle_script_targets(),
        "minicode-structure-check": "minicode.structure_check:main",
        "minicode-provider-smoke": "minicode.provider_smoke:main",
    }


def test_engineering_structure_namespace_is_packaged() -> None:
    discovered = set(
        find_namespace_packages(
            where=str(ROOT),
            include=["minicode*", "Main*", "Package*"],
        )
    )

    assert "Main.MinicodeFrontline.Src.Application.Entry" in discovered
    assert "Package.EngineeringStructure.Src.Application.Query" in discovered
    assert "minicode" in discovered


def test_legacy_root_smoke_scripts_are_not_pytest_collected() -> None:
    import conftest

    root_smoke_scripts = {
        path.name
        for pattern in ("test_*.py", "*_test.py")
        for path in ROOT.glob(pattern)
    }

    # After cleanup: root smoke scripts were migrated to tests/ or deleted.
    # If any remain, they must be excluded from pytest collection.
    if root_smoke_scripts:
        assert root_smoke_scripts.issubset(set(conftest.collect_ignore))
    assert "benchmarks/*.py" in conftest.collect_ignore_glob


def test_ci_workflow_runs_release_quality_gates() -> None:
    workflow = ROOT / ".github" / "workflows" / "ci.yml"

    assert workflow.exists()
    content = workflow.read_text(encoding="utf-8")
    assert "python -m compileall -q minicode tests benchmarks Main Package" in content
    assert "python -m minicode.structure_check --root ." in content
    assert "--hotspots 5 --max-dependency-upstream 4" in content
    assert "--check-material-inventory" in content
    assert "--report .temp/structure-compliance.json" in content
    assert "--check-structure-compliance-artifact .temp/structure-compliance.json" in content
    assert "python -m minicode.readiness --json" in content
    assert "python -m minicode.readiness --examples-out .temp/readiness-fallback-examples.json" in content
    assert "python -m minicode.readiness --doctor-out .temp/readiness-doctor.md" in content
    assert "python -m minicode.readiness --repair-plan-out .temp/readiness-repair-plan.json" in content
    assert "python -m minicode.readiness --patch-preview-out .temp/readiness-fallback-patch-preview.json" in content
    assert "python -m minicode.readiness --bundle-out .temp/readiness-bundle" in content
    readiness_commands = [
        line.strip()
        for line in content.splitlines()
        if "python -m minicode.readiness" in line
    ]
    assert readiness_commands
    assert all("--fail-on" not in command for command in readiness_commands)
    assert "MINI_CODE_MODEL_MODE" not in content
    assert "OPENAI_API_KEY" not in content
    assert "python -m minicode.release_readiness --check-artifact-redaction" in content
    assert "python -m minicode.release_readiness" in content
    assert "--write-artifact-manifest .temp/readiness-artifact-manifest.json" in content
    assert "--check-artifact-manifest .temp/readiness-artifact-manifest.json" in content
    assert "--check-fallback-patch-preview .temp/readiness-fallback-patch-preview.json" in content
    assert (
        "--check-fallback-simulation "
        ".temp/readiness-bundle/readiness-fallback-simulations.json"
    ) in content
    assert "--check-fallback-switch-smoke" in content
    assert "--check-readiness-bundle .temp/readiness-bundle" in content
    assert "--artifact patch_preview_json=.temp/readiness-fallback-patch-preview.json" in content
    assert ".temp/readiness-fallback-examples.json" in content
    assert ".temp/readiness-doctor.md" in content
    assert ".temp/readiness-repair-plan.json" in content
    assert ".temp/readiness-fallback-patch-preview.json" in content
    assert ".temp/readiness-artifact-manifest.json" in content
    assert ".temp/readiness-bundle/readiness-artifact-manifest.json" in content
    assert "Runtime readiness gate" in content
    assert "Runtime readiness fallback examples" in content
    assert "Runtime readiness doctor" in content
    assert "Runtime readiness repair plan" in content
    assert "Runtime readiness patch preview" in content
    assert "Runtime readiness bundle" in content
    assert "Runtime readiness artifact redaction" in content
    assert "Runtime readiness artifact manifest" in content
    assert "Runtime readiness artifact manifest gate" in content
    assert "Runtime readiness patch preview gate" in content
    assert "Runtime fallback switch smoke" in content
    assert "Runtime readiness bundle manifest gate" in content
    assert "Runtime readiness bundle gate" in content
    assert "AGENTS structure artifact gate" in content
    assert "Run AGENTS mirror tests" in content
    assert "StructureCompliance.Test.py" in content
    assert "Build and install package artifacts" in content
    assert "python -m pip install build" in content
    assert "python benchmarks/package_smoke.py" in content
    mypy_step = content.split("- name: Type check (mypy baseline)", 1)[1]
    mypy_step = mypy_step.split("- name: Run packaging smoke tests", 1)[0]
    assert "shell: bash" in mypy_step
    assert "python -m pytest -q" in content
    assert "tests/test_packaging.py" in content

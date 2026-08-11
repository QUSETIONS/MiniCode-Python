"""Build and install package artifacts, then smoke-test their CLI entry points."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import venv
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_BUILD_OUTPUT_NAMES = ("build", "minicode_py.egg-info")


def _run(command: list[str], *, cwd: Path) -> None:
    subprocess.run(command, cwd=cwd, check=True)


def _remove_path(path: Path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink()
    elif path.is_dir():
        shutil.rmtree(path)


@contextmanager
def _preserve_build_outputs(work: Path) -> Iterator[None]:
    """Keep PEP 517's source-tree build outputs out of the checkout."""
    backup_dir = work / "source-build-output-backups"
    paths = [ROOT / name for name in _BUILD_OUTPUT_NAMES]
    backups: dict[Path, Path] = {}

    for path in paths:
        if path.exists() or path.is_symlink():
            backup = backup_dir / path.name
            backup.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(path), str(backup))
            backups[path] = backup

    try:
        yield
    finally:
        for path in paths:
            _remove_path(path)
        for path, backup in backups.items():
            shutil.move(str(backup), str(path))


def _venv_python(venv_dir: Path) -> Path:
    return venv_dir / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def _venv_entrypoint(venv_dir: Path, name: str) -> Path:
    suffix = ".exe" if os.name == "nt" else ""
    directory = "Scripts" if os.name == "nt" else "bin"
    return venv_dir / directory / f"{name}{suffix}"


def main() -> int:
    temp_dir = "/tmp" if os.name != "nt" and Path("/tmp").is_dir() else None
    with tempfile.TemporaryDirectory(
        prefix="minicode-package-smoke-",
        dir=temp_dir,
    ) as raw:
        work = Path(raw)
        dist = work / "dist"
        dist.mkdir()

        with _preserve_build_outputs(work):
            _run(
                [
                    sys.executable,
                    "-m",
                    "build",
                    "--wheel",
                    "--sdist",
                    "--outdir",
                    str(dist),
                ],
                cwd=ROOT,
            )

        wheels = sorted(dist.glob("*.whl"))
        sdists = sorted(dist.glob("*.tar.gz"))
        if len(wheels) != 1 or len(sdists) != 1:
            raise RuntimeError(
                f"expected one wheel and one sdist, found {len(wheels)} wheels "
                f"and {len(sdists)} sdists"
            )

        for label, artifact in (("wheel", wheels[0]), ("sdist", sdists[0])):
            env_dir = work / f"{label}-venv"
            venv.EnvBuilder(
                symlinks=os.name != "nt",
                with_pip=True,
            ).create(env_dir)
            python = _venv_python(env_dir)
            _run(
                [str(python), "-m", "pip", "install", "--no-deps", str(artifact)],
                cwd=work,
            )

            for entrypoint in (
                "minicode-py",
                "minicode-headless",
                "minicode-readiness",
                "minicode-provider-smoke",
            ):
                command = _venv_entrypoint(env_dir, entrypoint)
                completed = subprocess.run(
                    [str(command), "--help"],
                    cwd=work,
                    check=False,
                    capture_output=True,
                    text=True,
                )
                if completed.returncode != 0:
                    raise RuntimeError(
                        f"{label} {entrypoint} --help failed:\n"
                        f"{completed.stdout}\n{completed.stderr}"
                    )

    print("package smoke passed: wheel, sdist, and four CLI entrypoints")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Build and install package artifacts, then smoke-test their CLI entry points."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import venv
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _run(command: list[str], *, cwd: Path) -> None:
    subprocess.run(command, cwd=cwd, check=True)


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

            for entrypoint in ("minicode-py", "minicode-headless", "minicode-readiness"):
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

    print("package smoke passed: wheel, sdist, and three CLI entrypoints")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

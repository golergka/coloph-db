"""Run preserved examples outside the checkout against an installed wheel."""

import argparse
import shutil
import subprocess
import sys
import tempfile
from importlib.metadata import version
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--wheel", help="Built wheel path or published wheel URL")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    built_wheel = root / "dist" / f"coloph_db-{version('coloph-db')}-py3-none-any.whl"
    if args.wheel is None and not built_wheel.is_file():
        parser.error("Build the current version or supply --wheel")
    wheel = args.wheel or str(built_wheel)
    with tempfile.TemporaryDirectory(prefix="coloph-db-wheel-") as directory:
        temporary = Path(directory)
        environment = temporary / "environment"
        subprocess.run(["uv", "venv", "--python", sys.executable, str(environment)], check=True)
        python = environment / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
        subprocess.run(
            ["uv", "pip", "install", "--python", str(python), f"{wheel}[binary]", "pytest", "pytest-asyncio"],
            check=True,
        )
        target = temporary / "examples"
        shutil.copytree(root / "examples", target, ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache"))
        subprocess.run([str(python), "-I", "-m", "pytest", "-q", str(target)], cwd=temporary, check=True)


if __name__ == "__main__":
    main()

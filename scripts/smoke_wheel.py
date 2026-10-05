"""Run preserved examples outside the checkout against an installed wheel."""

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--wheel", help="Built wheel path or published wheel URL")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    wheels = list((root / "dist").glob("coloph_db-*.whl"))
    if args.wheel is None and len(wheels) != 1:
        parser.error("Build one wheel or supply --wheel")
    wheel = args.wheel or str(wheels[0])
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

"""Install each standalone example through its own dependency metadata."""

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(prefix="coloph-db-manifests-") as directory:
        temporary = Path(directory)
        for source in sorted((root / "examples").iterdir()):
            if not (source / "pyproject.toml").is_file():
                continue
            target = temporary / source.name
            shutil.copytree(
                source,
                target,
                ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache", ".venv", "uv.lock"),
            )
            subprocess.run(["uv", "sync", "--python", sys.executable], cwd=target, check=True)
            subprocess.run(["uv", "run", "--locked", "pytest", "-q"], cwd=target, check=True)


if __name__ == "__main__":
    main()

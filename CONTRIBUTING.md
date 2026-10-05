# Contributing

## Local checks

```sh
uv sync --locked
uv run pytest
uv run mypy
uv run python -m ruff check .
uv run python -m ruff format --check .
uv build
uv run python scripts/smoke_wheel.py
uv run python scripts/smoke_manifests.py
```

The examples use public package imports.
Keep each example independent of any private checkout or service.
Local unit tests require no database. PostgreSQL integration tests require an explicit `COLOPH_DB_TEST_DSN`.
CI provides a disposable PostgreSQL service and runs those tests on each supported Python version.
The artifact smoke installs the wheel outside the checkout and runs both example projects.
The manifest smoke separately installs each example through its own metadata outside the checkout.

## Release

Keep versions on `0.1.*` until the user changes this constraint.

1. Update the version in `pyproject.toml` and its changelog entry.
2. Run all local checks and the installed-wheel smoke.
3. Review and commit the changes.
4. Push the tested commit to the public default branch.
5. Record validation on that exact commit. Use CI for the full PostgreSQL and Python-version matrix. When the user explicitly requests local-only validation, use the local unit, type, lint, build, and offline artifact checks and record that narrower scope.
6. Create an immutable matching `v0.1.*` tag.
7. Build distributions from that tag and publish a GitHub release with those files.
8. Install the published artifact in a clean environment and run the smoke procedure.

The GitHub release is the initial distribution channel. PyPI requires a separate trusted-publisher registration.
Never move a release tag or replace a published version.

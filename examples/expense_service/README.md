# Expense service

This imaginary service receives an employee identity from its authentication layer.
It checks submission permission before it opens a connection.
It installs its own PostgreSQL settings before it creates a callback-aware wrapper.
Its execution hook rejects expense inserts for a different employee or organization.
The database commit precedes the asynchronous notification.
The caller supplies the notification sender and error reporter.

The application owns its production RLS policies and session reset behavior.
The package does not interpret the employee identity or the settings.

From the repository root:

```sh
uv run pytest examples/expense_service
```

The unit tests use a recording driver and require no database.
CI also exercises this example against PostgreSQL through `tests/test_postgres.py`.

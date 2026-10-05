# Warehouse

This imaginary service has no identity, tenant, or PostgreSQL session context.
It stores stock movements and derives a summary in the same transaction.
The first movement creates transaction state and registers one before-commit callback.
A summary read refreshes pending changes before the read executes.
Commit also refreshes pending changes. Rollback discards the transaction state.
The application owns SQL classification and refresh recursion control.

From the repository root:

```sh
uv run pytest examples/warehouse
```

The unit tests use a recording driver and require no database.
CI also exercises read consistency and rollback against PostgreSQL through `tests/test_postgres.py`.

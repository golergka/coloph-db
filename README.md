# coloph-db

Explicit transaction lifecycle and execution hooks for psycopg applications.

The package wraps a PostgreSQL connection that your application opens.
It runs application hooks around queries and transaction boundaries.
It tracks successful writes and rejects a connection close with uncommitted mutations.
It keeps application state for one transaction.

Your application owns identity, authorization, tenant selection, RLS, PostgreSQL settings, and connection acquisition.
The package requires Python 3.11 or later and psycopg 3.3.2 or later within major version 3.
Versions remain on `0.1.*` while the interface settles.

## Install

```sh
uv add "coloph-db[binary] @ https://github.com/golergka/coloph-db/releases/download/v0.1.1/coloph_db-0.1.1-py3-none-any.whl"
```

GitHub Releases is the initial distribution channel. The command pins an immutable published wheel.

## Use a connection

```python
import psycopg
from psycopg.rows import dict_row
from coloph_db import SyncConnection

raw = psycopg.connect(database_url, row_factory=dict_row)
with SyncConnection(raw) as conn:
    conn.execute("INSERT INTO orders (number) VALUES (%s)", ("order-7",))
```

The context commits on success. It rolls back on failure and closes the driver.
Applications can also call `commit()`, `rollback()`, and `close()` explicitly.
Connections and transaction state belong to one execution owner. Do not share them across concurrent tasks.

## Configure application hooks

```python
from coloph_db import ConnectionBase, Execution, ExecutionHooks, StateKey, SyncConnection

changed_ids = StateKey[set[str]]()


def before_query(conn: ConnectionBase, event: Execution) -> None:
    application_policy.check(event.query, event.params, event.route)


conn = SyncConnection(raw, hooks=ExecutionHooks(before_execute=before_query))
ids = conn.state.get_or_create(changed_ids, set)
ids.add("order-7")
conn.before_commit(lambda: application_policy.validate_orders(conn, ids))
conn.after_commit(lambda: application_cache.invalidate(ids))
conn.commit()
assert conn.state.get(changed_ids) is None
```

`StateKey[T]` associates one type with one key.
The state clears after commit or rollback. Each new transaction creates fresh values.
The application controls lazy registration, query classification, and recursion in its hooks.

## Await callbacks after commit

```python
from coloph_db import CallbackConnection

conn = CallbackConnection(raw, report_callback_error=application_errors.report)
conn.execute("INSERT INTO orders (number) VALUES (%s)", ("order-7",))
conn.on_commit(lambda: notifications.send("order-7"))
await conn.commit()
conn.close()
```

Database I/O remains synchronous. `CallbackConnection` awaits callbacks after the database commit.
Callbacks run in registration order. A failed callback goes to the required error reporter, then the next callback runs.
Rollback discards callbacks. A callback cannot re-enter commit or rollback.
Callbacks are in memory. Use an application outbox when delivery must survive a process exit.

## Contracts and examples

- [Lifecycle and hook contract](docs/contracts.md)
- [Design evaluation](docs/design.md)
- [Expense service: application identity and PostgreSQL settings](examples/expense_service/README.md)
- [Warehouse: derived state without identity or tenant selection](examples/warehouse/README.md)
- [Development and release procedure](CONTRIBUTING.md)
- [Changes](CHANGELOG.md)

The public driver property is an infrastructure escape hatch.
Driver operations bypass hooks and write tracking.
Session settings and pool reset behavior remain application responsibilities.

MIT licensed.

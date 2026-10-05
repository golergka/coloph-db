# Lifecycle contract

The application opens a psycopg connection with `dict_row` and installs any application-specific context.
`SyncConnection` or `CallbackConnection` wraps that driver and owns its close.
Connections do not create identities, select tenants, or configure database access policies.

## Execution

`execute`, `cursor.execute`, and `cursor.executemany` use the same hook pipeline:

1. Run `before_execute` with an `Execution` object.
2. Execute the driver operation.
3. Record mutation command tags before any application telemetry.
4. Run `after_execute` with an `ExecutionResult` object.

`Execution` contains the SQL, parameters, route, and a batch flag.
Batch parameters are not consumed by the hook. A batch event has `params=None` and `many=True`.
On a driver error, `query_error` runs and the original exception propagates unless the hook itself raises.
`ExecutionResult` contains elapsed driver time, command status, and row count.
Application hooks can reject operations before the driver runs.
They are not a substitute for database security policies.

## Commit

Commit runs before-commit callbacks in registration order, then commits the driver.
It clears transaction state and write tracking, runs `transaction_end`, then runs synchronous after-commit callbacks.
`CallbackConnection` also awaits its asynchronous callbacks.
Callbacks registered for one transaction do not repeat in the next transaction.

A failed before-commit callback requires rollback before another commit.
A driver commit failure propagates and requires application recovery.
A synchronous post-commit failure raises `AfterCommitError` with the original error as its cause.
The database is already committed. Applications must not retry that transaction.
Asynchronous callback failures go to the required error reporter and do not stop later callbacks.
A reporter failure propagates. Cancellation also propagates.

Before-commit callbacks can execute SQL. They cannot register more transaction callbacks during commit.
Synchronous callbacks cannot re-enter commit or rollback.
Asynchronous callbacks cannot register more asynchronous callbacks while the queue drains.

## Rollback and close

Rollback clears transaction state, mutation tracking, and all pending callbacks.
It runs `transaction_end` with `rollback` after the driver rollback.
Close releases the driver even when the abandoned-write hook raises.
A tracked mutation in an open transaction raises `UncommittedMutationCloseError`.
An implicit transaction containing only reads is rolled back before close.
`rollback_open_readonly_transaction()` returns whether it rolled back such a transaction.

The guard uses PostgreSQL command tags. A successful batch without a tag and with affected rows counts as a mutation.
The guard is conservative and does not parse arbitrary SQL.
Raw driver operations bypass the guard.
Applications can inspect `dirty_write`, `last_write_command`, `last_write_route`, and `write_routes` for diagnostics.
`pending_callback_count` includes every callback waiting for the next transaction boundary.
`run_on_commit_callbacks` runs a detached callback queue with an explicit error reporter.

## Explicit transaction context

`SyncConnection.transaction()` is an infrastructure API for a top-level transaction.
It requires an idle driver and no pending callbacks.
It executes before-commit callbacks inside the transaction and after-commit callbacks after success.
`force_rollback=True` discards after-commit callbacks and ends with rollback state.
Nested transactions and application savepoint lifecycle are outside this contract.

## Ownership

The application owns connection acquisition, authentication, session settings, pool reset, retry classification, and SQL policy.
The package owns hook dispatch, callback queues, transaction state, tracked cursor operations, and close guards.
The explicit `driver` property gives application infrastructure access to PostgreSQL-specific facilities.

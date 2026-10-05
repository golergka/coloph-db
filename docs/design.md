# Design evaluation

Two independent application sketches preceded the package implementation.

## Expense service

The expense service accepts an employee identity from its authentication layer.
The application rejects employees without submission permission before it opens a connection.
It selects its PostgreSQL settings and installs them before it wraps the driver.
It sends a notification after a successful commit.
A rollback discards the notification.
The package does not interpret the identity or create RLS policies.

## Warehouse

The warehouse has no principal, tenant, or session settings.
It maintains a stock summary inside the same transaction as stock movements.
Its execution hook creates transaction state on the first movement.
It refreshes the summary before a stock read and before commit.
The application prevents recursive refreshes.
The package clears transaction state after commit or rollback.

## Changes to the initial sketch

- Connection lifecycle works without an identity or tenant.
- Typed state keys replace an untyped object-key map.
- The driver has an explicit public property for application-specific setup and transaction inspection.
- Execution hooks receive the route, query, and parameters.
- Cursor execution uses the same hook path as connection execution.
- The package tracks successful writes from PostgreSQL command tags, without application table names.
- Callback failures after commit cannot make the database transaction eligible for retry.
- The application owns SQL classification, session settings, RLS, derived data, telemetry, and connection acquisition.

## Limits

Database I/O is synchronous, including on a callback-aware connection.
Asynchronous callbacks run after the synchronous database commit.
Callbacks are in memory. Applications that require durable delivery need a separate outbox.
Driver access bypasses execution hooks and write tracking.
Application session settings require an application-defined pool reset policy.
The package does not claim to parse arbitrary SQL or enforce authorization.

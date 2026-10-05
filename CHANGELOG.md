# Changes

## 0.1.0

- Extract transaction lifecycle, execution hooks, tracked cursors, and close guards into a standalone psycopg package.
- Add typed transaction state and synchronous or awaited post-commit callbacks.
- Keep identity, authorization, PostgreSQL settings, RLS, and domain maintenance in applications.
- Add independent expense-service and warehouse examples.
- Add lifecycle contracts, PostgreSQL integration tests, CI, and installed-wheel smoke tests.

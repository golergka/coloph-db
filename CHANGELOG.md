# Changes

## 0.1.2

- Use published GitHub wheels in documented installation and standalone example manifests.
- Verify each example's dependency metadata in a separate environment outside the checkout.

## 0.1.1

- Expose write routes and pending callback counts for application adapters.
- Share the callback queue runner through a public function with an explicit error reporter.
- Preserve the primary application or commit error when context cleanup also fails.

## 0.1.0

- Extract transaction lifecycle, execution hooks, tracked cursors, and close guards into a standalone psycopg package.
- Add typed transaction state and synchronous or awaited post-commit callbacks.
- Keep identity, authorization, PostgreSQL settings, RLS, and domain maintenance in applications.
- Add independent expense-service and warehouse examples.
- Add lifecycle contracts, PostgreSQL integration tests, CI, and installed-wheel smoke tests.

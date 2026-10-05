"""An expense service owns identity, tenant selection, and PostgreSQL settings."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

import psycopg
from psycopg.rows import dict_row

from coloph_db import CallbackConnection, ConnectionBase, Execution, ExecutionHooks


@dataclass(frozen=True)
class ExpenseIdentity:
    organization: str
    employee: str
    can_submit: bool


def open_expenses(dsn: str, identity: ExpenseIdentity, report_error: Callable[[Exception], None]) -> CallbackConnection:
    if not identity.can_submit:
        raise PermissionError("Employee cannot submit expenses")
    raw = psycopg.connect(dsn, row_factory=dict_row)
    try:
        raw.execute(
            "SELECT set_config('expenses.organization', %s, false), set_config('expenses.employee', %s, false)",
            (identity.organization, identity.employee),
        )
        raw.commit()
    except BaseException:
        raw.close()
        raise

    def enforce_context(conn: ConnectionBase, event: Execution) -> None:
        # A second application check catches a mismatched identity at dispatch.
        # Production read/write enforcement belongs in this service's RLS policies.
        if str(event.query).lower().startswith("insert into expense_receipts"):
            if (
                event.many
                or not isinstance(event.params, tuple)
                or event.params[:2] != (identity.organization, identity.employee)
            ):
                raise PermissionError("Expense identity differs from connection identity")

    return CallbackConnection(
        raw,
        hooks=ExecutionHooks(before_execute=enforce_context),
        report_callback_error=report_error,
    )


async def submit_expense(
    conn: CallbackConnection,
    identity: ExpenseIdentity,
    amount_cents: int,
    notify: Callable[[str], Awaitable[None]],
) -> None:
    conn.execute(
        "INSERT INTO expense_receipts (organization, employee, amount_cents) VALUES (%s, %s, %s)",
        (identity.organization, identity.employee, amount_cents),
    )
    conn.on_commit(lambda: notify(identity.employee))
    await conn.commit()

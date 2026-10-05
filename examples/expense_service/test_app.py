from unittest.mock import MagicMock

import pytest
from psycopg.pq import TransactionStatus

from .app import ExpenseIdentity, open_expenses, submit_expense


def driver() -> MagicMock:
    raw = MagicMock()
    raw.closed = False
    raw.info.transaction_status = TransactionStatus.IDLE
    raw.execute.return_value.statusmessage = "INSERT 0 1"
    return raw


def test_denied_employee_does_not_open_connection(monkeypatch: pytest.MonkeyPatch) -> None:
    connect = MagicMock()
    monkeypatch.setattr("psycopg.connect", connect)
    with pytest.raises(PermissionError):
        open_expenses("unused", ExpenseIdentity("org", "employee", False), lambda error: None)
    connect.assert_not_called()


@pytest.mark.asyncio
async def test_settings_belong_to_application_and_notification_follows_commit(monkeypatch: pytest.MonkeyPatch) -> None:
    raw = driver()
    monkeypatch.setattr("psycopg.connect", lambda *a, **kw: raw)
    identity = ExpenseIdentity("org", "employee", True)
    errors: list[Exception] = []
    conn = open_expenses("unused", identity, errors.append)
    assert raw.execute.call_args.args[1] == ("org", "employee")
    assert "expenses.organization" in raw.execute.call_args.args[0]
    order = []
    raw.commit.side_effect = lambda: order.append("commit")

    async def notify(employee: str) -> None:
        order.append(employee)

    await submit_expense(conn, identity, 1200, notify)
    assert order == ["commit", "employee"]
    assert errors == []
    conn.close()


@pytest.mark.asyncio
async def test_mismatched_identity_is_rejected_and_rollback_discards_notification(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw = driver()
    monkeypatch.setattr("psycopg.connect", lambda *a, **kw: raw)
    identity = ExpenseIdentity("org", "employee", True)
    conn = open_expenses("unused", identity, lambda error: None)
    with pytest.raises(PermissionError):
        conn.execute("INSERT INTO expense_receipts VALUES (%s, %s, %s)", ("other", "employee", 100))
    notified = []

    async def notify() -> None:
        notified.append(True)

    conn.on_commit(notify)
    conn.rollback()
    await conn.commit()
    assert notified == []
    conn.close()

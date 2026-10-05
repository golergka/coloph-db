"""Integration tests use a disposable PostgreSQL database supplied by CI."""

import os

import psycopg
import pytest
from psycopg.rows import dict_row

from coloph_db import SyncConnection, UncommittedMutationCloseError
from examples.expense_service.app import ExpenseIdentity, open_expenses, submit_expense
from examples.warehouse.app import STOCK, open_warehouse, receive_stock


@pytest.fixture
def dsn():
    value = os.environ.get("COLOPH_DB_TEST_DSN")
    if not value:
        pytest.skip("PostgreSQL integration requires COLOPH_DB_TEST_DSN; CI supplies it")
    return value


def test_real_cursor_batch_is_tracked_and_close_rejects_uncommitted_write(dsn):
    conn = SyncConnection(psycopg.connect(dsn, row_factory=dict_row))
    conn.execute("CREATE TEMP TABLE tracked_batch (value integer)")
    conn.commit()
    with conn.cursor() as cursor:
        cursor.executemany("INSERT INTO tracked_batch VALUES (%s)", [(1,), (2,)])
    assert conn.dirty_write
    with pytest.raises(UncommittedMutationCloseError):
        conn.close()


def test_real_warehouse_read_consistency_and_transaction_reset(dsn):
    conn = open_warehouse(dsn)
    conn.execute("CREATE TEMP TABLE stock_movements (sku text, quantity integer)")
    conn.execute("CREATE TEMP TABLE stock_summary (sku text, quantity bigint)")
    conn.commit()
    assert receive_stock(conn, "widget", 7) == 7
    conn.commit()
    assert conn.state.get(STOCK) is None
    assert receive_stock(conn, "widget", 3) == 10
    conn.rollback()
    assert conn.execute("SELECT quantity FROM stock_summary WHERE sku = 'widget'").fetchone() == {"quantity": 7}
    assert receive_stock(conn, "widget", 2) == 9
    conn.commit()
    conn.close()


async def test_real_expense_settings_and_committed_notification(dsn):
    identity = ExpenseIdentity("org", "employee", True)
    errors = []
    conn = open_expenses(dsn, identity, errors.append)
    assert conn.execute("SELECT current_setting('expenses.organization') AS organization").fetchone() == {
        "organization": "org"
    }
    conn.execute("CREATE TEMP TABLE expense_receipts (organization text, employee text, amount_cents integer)")
    await conn.commit()
    notified = []

    async def notify(employee):
        row = conn.execute("SELECT amount_cents FROM expense_receipts").fetchone()
        notified.append((employee, row["amount_cents"]))

    await submit_expense(conn, identity, 1200, notify)
    assert notified == [("employee", 1200)]
    assert errors == []
    conn.close()

"""A warehouse owns a stock summary, with no principal or tenant concept."""

from dataclasses import dataclass

import psycopg
from psycopg.rows import dict_row

from coloph_db import ConnectionBase, Execution, ExecutionHooks, StateKey, SyncConnection


@dataclass
class StockChanges:
    pending: bool = False
    inside_flush: bool = False


STOCK = StateKey[StockChanges]()


def flush_stock(conn: ConnectionBase, changes: StockChanges) -> None:
    if not changes.pending or changes.inside_flush:
        return
    changes.inside_flush = True
    try:
        conn.execute("DELETE FROM stock_summary")
        conn.execute(
            "INSERT INTO stock_summary (sku, quantity) SELECT sku, sum(quantity) FROM stock_movements GROUP BY sku"
        )
        changes.pending = False
    finally:
        changes.inside_flush = False


def warehouse_hook(conn: ConnectionBase, event: Execution) -> None:
    # This example accepts a fixed set of SQL statements. It does not claim
    # that text inspection is a general SQL security boundary.
    sql = str(event.query).strip().lower()
    changes = conn.state.get(STOCK)
    if changes is not None and changes.inside_flush:
        return
    if sql.startswith("insert into stock_movements"):
        if changes is None:
            changes = conn.state.get_or_create(STOCK, StockChanges)
            state = changes
            conn.before_commit(lambda: flush_stock(conn, state))
        changes.pending = True
    elif sql.startswith("select") and changes is not None:
        flush_stock(conn, changes)


def open_warehouse(dsn: str) -> SyncConnection:
    return SyncConnection(
        psycopg.connect(dsn, row_factory=dict_row),
        hooks=ExecutionHooks(before_execute=warehouse_hook),
    )


def receive_stock(conn: SyncConnection, sku: str, quantity: int) -> int:
    conn.execute("INSERT INTO stock_movements (sku, quantity) VALUES (%s, %s)", (sku, quantity))
    row = conn.execute("SELECT quantity FROM stock_summary WHERE sku = %s", (sku,)).fetchone()
    assert row is not None
    return int(row["quantity"])

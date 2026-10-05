from unittest.mock import MagicMock

import pytest
from psycopg.pq import TransactionStatus

from .app import STOCK, open_warehouse, receive_stock


def test_summary_flushes_before_read_and_state_ends_at_commit(monkeypatch: pytest.MonkeyPatch) -> None:
    raw = MagicMock()
    raw.closed = False
    raw.info.transaction_status = TransactionStatus.IDLE
    raw.execute.return_value.fetchone.return_value = {"quantity": 7}
    raw.execute.return_value.statusmessage = "SELECT 1"
    monkeypatch.setattr("psycopg.connect", lambda *a, **kw: raw)
    conn = open_warehouse("unused")
    assert receive_stock(conn, "widget", 7) == 7
    statements = [call.args[0] for call in raw.execute.call_args_list]
    assert statements[0].startswith("INSERT INTO stock_movements")
    assert statements[1] == "DELETE FROM stock_summary"
    assert statements[2].startswith("INSERT INTO stock_summary")
    assert statements[3].startswith("SELECT quantity")
    changes = conn.state.get(STOCK)
    assert changes is not None and changes.pending is False
    conn.commit()
    assert conn.state.get(STOCK) is None
    conn.close()


def test_commit_flushes_without_a_read_and_rollback_drops_pending_work(monkeypatch: pytest.MonkeyPatch) -> None:
    raw = MagicMock()
    raw.closed = False
    raw.info.transaction_status = TransactionStatus.IDLE
    raw.execute.return_value.statusmessage = "INSERT 0 1"
    monkeypatch.setattr("psycopg.connect", lambda *a, **kw: raw)
    conn = open_warehouse("unused")
    conn.execute("INSERT INTO stock_movements VALUES (%s, %s)", ("widget", 4))
    conn.commit()
    assert raw.execute.call_count == 3
    conn.execute("INSERT INTO stock_movements VALUES (%s, %s)", ("widget", 2))
    conn.rollback()
    conn.commit()
    assert raw.execute.call_count == 4
    assert conn.state.get(STOCK) is None
    conn.close()

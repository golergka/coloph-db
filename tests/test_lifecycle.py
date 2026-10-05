from unittest.mock import MagicMock

import psycopg
import pytest
from psycopg.pq import TransactionStatus

from coloph_db import (
    AfterCommitError,
    CallbackConnection,
    ExecutionHooks,
    StateKey,
    SyncConnection,
    TransactionLifecycleError,
    UncommittedMutationCloseError,
)


def raw_connection():
    raw = MagicMock()
    raw.closed = False
    raw.autocommit = False
    raw.info.transaction_status = TransactionStatus.IDLE
    raw.execute.return_value.statusmessage = "SELECT 1"
    raw.execute.return_value.rowcount = 1
    return raw


def test_hooks_track_both_cursor_routes_and_parameters():
    raw = raw_connection()
    events, results = [], []
    conn = SyncConnection(
        raw,
        hooks=ExecutionHooks(
            before_execute=lambda conn, event: events.append(event),
            after_execute=lambda conn, result: results.append(result),
        ),
    )
    raw.cursor.return_value.execute.return_value = raw.cursor.return_value
    raw.cursor.return_value.statusmessage = "INSERT 0 1"
    conn.execute("SELECT %s", (2,))
    with conn.cursor() as cursor:
        assert cursor.execute("INSERT INTO things VALUES (%s)", (3,)) is cursor
        cursor.executemany("INSERT INTO things VALUES (%s)", [(4,), (5,)])
    assert [event.route for event in events] == ["execute", "cursor.execute", "cursor.executemany"]
    assert events[0].params == (2,)
    assert events[-1].many
    assert len(results) == 3
    assert conn.dirty_write


def test_rejected_query_never_reaches_driver():
    raw = raw_connection()

    def reject(conn, event):
        raise PermissionError("Application rejected query")

    conn = SyncConnection(raw, hooks=ExecutionHooks(before_execute=reject))
    with pytest.raises(PermissionError):
        conn.execute("DELETE FROM things")
    raw.execute.assert_not_called()


def test_query_failure_hook_preserves_original_error():
    raw = raw_connection()
    failure = psycopg.errors.SerializationFailure("retry")
    raw.execute.side_effect = failure
    errors = []
    conn = SyncConnection(raw, hooks=ExecutionHooks(query_error=lambda c, e, error: errors.append(error)))
    with pytest.raises(psycopg.errors.SerializationFailure) as raised:
        conn.execute("SELECT 1")
    assert raised.value is failure
    assert errors == [failure]


@pytest.mark.parametrize("outcome", ["commit", "rollback"])
def test_state_does_not_cross_transaction_boundary(outcome):
    conn = SyncConnection(raw_connection())
    key = StateKey[list[int]]()
    first = conn.state.get_or_create(key, list)
    first.append(1)
    assert conn.state.get_or_create(key, list) is first
    getattr(conn, outcome)()
    assert conn.state.get(key) is None
    assert conn.state.get_or_create(key, list) == []


def test_before_and_after_hooks_order_and_one_shot_lifetime():
    raw = raw_connection()
    order = []
    raw.commit.side_effect = lambda: order.append("database")
    conn = SyncConnection(raw)
    conn.before_commit(lambda: order.append("before"))
    conn.after_commit(lambda: order.append("after"))
    conn.commit()
    conn.commit()
    assert order == ["before", "database", "after", "database"]


def test_failed_before_hook_requires_rollback_before_another_commit():
    raw = raw_connection()
    conn = SyncConnection(raw)

    def fail():
        raise ValueError("Invalid derived state")

    conn.before_commit(fail)
    with pytest.raises(ValueError):
        conn.commit()
    with pytest.raises(TransactionLifecycleError, match="requires rollback"):
        conn.commit()
    raw.commit.assert_not_called()
    conn.rollback()
    conn.commit()


def test_after_commit_failure_is_distinguishable_and_state_is_cleared():
    raw = raw_connection()
    conn = SyncConnection(raw)
    key = StateKey[list[int]]()
    conn.state.get_or_create(key, list)

    def fail():
        raise psycopg.errors.SerializationFailure("already committed")

    conn.after_commit(fail)
    with pytest.raises(AfterCommitError) as raised:
        conn.commit()
    assert isinstance(raised.value.__cause__, psycopg.errors.SerializationFailure)
    raw.commit.assert_called_once()
    assert conn.state.get(key) is None


def test_context_commit_failure_rolls_back_and_closes():
    raw = raw_connection()
    raw.commit.side_effect = psycopg.errors.DeadlockDetected("commit failed")
    with pytest.raises(psycopg.errors.DeadlockDetected):
        with SyncConnection(raw):
            pass
    raw.rollback.assert_called_once()
    raw.close.assert_called_once()


def test_close_detects_successful_mutation_before_telemetry_hook():
    raw = raw_connection()
    raw.info.transaction_status = TransactionStatus.INTRANS
    raw.execute.return_value.statusmessage = "UPDATE 1"
    errors = []
    conn = SyncConnection(raw, hooks=ExecutionHooks(abandoned_write=lambda c, e: errors.append(e)))
    conn.execute("UPDATE things SET value = 1")
    with pytest.raises(UncommittedMutationCloseError):
        conn.close()
    assert len(errors) == 1
    raw.close.assert_called_once()


def test_readonly_close_rolls_back_implicit_select():
    raw = raw_connection()
    raw.info.transaction_status = TransactionStatus.INTRANS
    SyncConnection(raw).close()
    raw.rollback.assert_called_once()
    raw.close.assert_called_once()


async def test_async_callbacks_order_failure_reporting_and_rollback():
    raw = raw_connection()
    order, errors = [], []
    raw.commit.side_effect = lambda: order.append("database")
    conn = CallbackConnection(raw, report_callback_error=errors.append)

    async def fail():
        order.append("failed callback")
        raise ValueError("delivery failed")

    async def succeed():
        order.append("successful callback")

    conn.on_commit(fail)
    conn.on_commit(succeed)
    await conn.commit()
    assert order == ["database", "failed callback", "successful callback"]
    assert len(errors) == 1
    conn.on_commit(succeed)
    conn.rollback()
    await conn.commit()
    assert order[-1] == "database"


async def test_async_reentry_is_reported_without_second_database_commit():
    raw = raw_connection()
    errors = []
    conn = CallbackConnection(raw, report_callback_error=errors.append)
    conn.on_commit(conn.commit)
    await conn.commit()
    raw.commit.assert_called_once()
    assert isinstance(errors[0], TransactionLifecycleError)


def test_forced_rollback_does_not_run_after_commit_callbacks():
    raw = raw_connection()
    conn = SyncConnection(raw)
    order = []
    with conn.transaction(force_rollback=True):
        conn.before_commit(lambda: order.append("before"))
        conn.after_commit(lambda: order.append("after"))
    assert order == ["before"]


def test_batch_without_command_tag_is_conservatively_tracked():
    raw = raw_connection()
    raw.cursor.return_value.statusmessage = None
    raw.cursor.return_value.rowcount = 2
    conn = SyncConnection(raw)
    with conn.cursor() as cursor:
        cursor.executemany("INSERT INTO things VALUES (%s)", [(1,), (2,)])
    assert conn.dirty_write
    assert conn.last_write_command == "BATCH"


def test_driver_commit_failure_requires_rollback_before_retry():
    raw = raw_connection()
    raw.commit.side_effect = psycopg.errors.SerializationFailure("failed")
    conn = SyncConnection(raw)
    with pytest.raises(psycopg.errors.SerializationFailure):
        conn.commit()
    with pytest.raises(TransactionLifecycleError):
        conn.commit()
    raw.commit.assert_called_once()

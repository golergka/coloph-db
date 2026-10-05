"""Synchronous PostgreSQL I/O with explicit transaction lifecycle hooks."""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable, Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from types import TracebackType
from typing import Literal

import psycopg
from psycopg.abc import Params, QueryNoTemplate
from psycopg.pq import TransactionStatus
from psycopg.rows import DictRow

from .state import TransactionState

RawConnection = psycopg.Connection[DictRow]
RawCursor = psycopg.Cursor[DictRow]
OnCommitCallback = Callable[[], Awaitable[None]]


@dataclass(frozen=True)
class Execution:
    query: QueryNoTemplate
    params: Params | None
    route: str
    many: bool = False


@dataclass(frozen=True)
class ExecutionResult:
    execution: Execution
    duration_ms: float
    statusmessage: str | None
    rowcount: int


@dataclass(frozen=True)
class ExecutionHooks:
    before_execute: Callable[[ConnectionBase, Execution], None] | None = None
    after_execute: Callable[[ConnectionBase, ExecutionResult], None] | None = None
    query_error: Callable[[ConnectionBase, Execution, psycopg.Error], None] | None = None
    transaction_end: Callable[[ConnectionBase, Literal["commit", "rollback"]], None] | None = None
    abandoned_write: Callable[[ConnectionBase, UncommittedMutationCloseError], None] | None = None


class UncommittedMutationCloseError(RuntimeError):
    """A connection closed with a successful write in an open transaction."""


class TransactionLifecycleError(RuntimeError):
    """A transaction boundary is invalid for the current lifecycle state."""


class AfterCommitError(RuntimeError):
    """A synchronous callback failed after the database commit succeeded."""


_MUTATING_TAGS = frozenset(
    "ALTER ANALYZE CALL CLUSTER COMMENT COPY CREATE DELETE DISCARD DO DROP GRANT "
    "INSERT LOCK MERGE NOTIFY REFRESH REINDEX REVOKE SECURITY TRUNCATE UNLISTEN UPDATE VACUUM".split()
)


class TrackingCursor:
    def __init__(self, owner: ConnectionBase, cursor: RawCursor) -> None:
        self._owner = owner
        self._cursor = cursor

    def __enter__(self) -> TrackingCursor:
        self._cursor.__enter__()
        return self

    def __exit__(self, kind: type[BaseException] | None, error: BaseException | None, tb: TracebackType | None) -> None:
        self._cursor.__exit__(kind, error, tb)

    def execute(
        self,
        query: QueryNoTemplate,
        params: Params | None = None,
        *,
        prepare: bool | None = None,
        binary: bool | None = None,
    ) -> TrackingCursor:
        event = Execution(query, params, "cursor.execute")
        self._owner._run_execution(event, lambda: self._cursor.execute(query, params, prepare=prepare, binary=binary))
        return self

    def executemany(self, query: QueryNoTemplate, params_seq: Iterable[Params], *, returning: bool = False) -> None:
        event = Execution(query, None, "cursor.executemany", many=True)

        def execute() -> RawCursor:
            self._cursor.executemany(query, params_seq, returning=returning)
            return self._cursor

        self._owner._run_execution(event, execute)

    def fetchone(self) -> DictRow | None:
        return self._cursor.fetchone()

    def fetchmany(self, size: int = 0) -> list[DictRow]:
        return self._cursor.fetchmany(size)

    def fetchall(self) -> list[DictRow]:
        return self._cursor.fetchall()

    def __iter__(self) -> Iterator[DictRow]:
        return iter(self._cursor)

    @property
    def rowcount(self) -> int:
        return self._cursor.rowcount

    @property
    def statusmessage(self) -> str | None:
        return self._cursor.statusmessage


class ConnectionBase:
    def __init__(self, driver: RawConnection, *, hooks: ExecutionHooks | None = None) -> None:
        self._driver = driver
        self.hooks = hooks or ExecutionHooks()
        self.state = TransactionState()
        self._before_commit_callbacks: list[Callable[[], None]] = []
        self._after_commit_callbacks: list[Callable[[], None]] = []
        self._dirty_write = False
        self._dirty_write_command: str | None = None
        self._dirty_write_route: str | None = None
        self._dirty_write_kinds: set[str] = set()
        self._commit_phase: str | None = None
        self._precommit_failed = False

    @property
    def driver(self) -> RawConnection:
        """Explicit infrastructure escape hatch; bypasses hooks and tracking."""
        return self._driver

    @property
    def closed(self) -> bool:
        return self.driver.closed

    @property
    def transaction_status(self) -> TransactionStatus:
        return self.driver.info.transaction_status

    @property
    def autocommit(self) -> bool:
        return self.driver.autocommit

    @property
    def dirty_write(self) -> bool:
        return self._dirty_write

    @property
    def last_write_command(self) -> str | None:
        return self._dirty_write_command

    @property
    def last_write_route(self) -> str | None:
        return self._dirty_write_route

    def cancel(self) -> None:
        self.driver.cancel()

    def execute(
        self,
        query: QueryNoTemplate,
        params: Params | None = None,
        *,
        prepare: bool | None = None,
        binary: bool | None = None,
        route: str = "execute",
    ) -> RawCursor:
        event = Execution(query, params, route)
        return self._run_execution(
            event, lambda: self.driver.execute(query, params, prepare=prepare, binary=binary or False)
        )

    def cursor(
        self,
        name: str | None = None,
        *,
        binary: bool = False,
        scrollable: bool | None = None,
        withhold: bool = False,
    ) -> TrackingCursor:
        if name is None:
            cursor = self.driver.cursor(binary=binary)
        else:
            cursor = self.driver.cursor(name=name, binary=binary, scrollable=scrollable, withhold=withhold)
        return TrackingCursor(self, cursor)

    def _run_execution(self, event: Execution, execute: Callable[[], RawCursor]) -> RawCursor:
        if self.hooks.before_execute is not None:
            self.hooks.before_execute(self, event)
        started = time.monotonic()
        try:
            result = execute()
        except psycopg.Error as error:
            if self.hooks.query_error is not None:
                self.hooks.query_error(self, event, error)
            raise
        self._record_dirty_write(result, route=event.route)
        # psycopg can omit the final command tag for a pipeline batch. Treat
        # an unclassified successful batch conservatively as a mutation.
        if event.many and result.statusmessage is None and result.rowcount > 0:
            self._dirty_write = True
            self._dirty_write_command = "BATCH"
            self._dirty_write_route = event.route
            self._dirty_write_kinds.add(event.route)
        if self.hooks.after_execute is not None:
            self.hooks.after_execute(
                self, ExecutionResult(event, (time.monotonic() - started) * 1000, result.statusmessage, result.rowcount)
            )
        return result

    @staticmethod
    def _is_mutating_status(status: object) -> bool:
        return isinstance(status, str) and status.strip().split(" ", 1)[0].upper() in _MUTATING_TAGS

    def _record_dirty_write(self, result: RawCursor, *, route: str) -> None:
        if not self._is_mutating_status(result.statusmessage):
            return
        self._dirty_write = True
        self._dirty_write_command = str(result.statusmessage).strip().split(" ", 1)[0].upper()
        self._dirty_write_route = route
        self._dirty_write_kinds.add(route)

    def before_commit(self, callback: Callable[[], None]) -> None:
        if self._commit_phase is not None:
            raise TransactionLifecycleError("Cannot register a before-commit callback during commit")
        self._before_commit_callbacks.append(callback)

    def after_commit(self, callback: Callable[[], None]) -> None:
        if self._commit_phase is not None:
            raise TransactionLifecycleError("Cannot register an after-commit callback during commit")
        self._after_commit_callbacks.append(callback)

    def _run_before_commit_callbacks(self) -> int:
        if self._precommit_failed:
            raise TransactionLifecycleError("A failed before-commit callback requires rollback")
        callbacks, self._before_commit_callbacks = self._before_commit_callbacks, []
        self._commit_phase = "before"
        try:
            for callback in callbacks:
                callback()
        except BaseException:
            self._precommit_failed = True
            raise
        finally:
            self._commit_phase = None
        return len(callbacks)

    def _run_after_commit_callbacks(self) -> int:
        callbacks, self._after_commit_callbacks = self._after_commit_callbacks, []
        self._commit_phase = "after"
        try:
            for callback in callbacks:
                callback()
        except Exception as error:
            raise AfterCommitError("Callback failed after successful database commit") from error
        finally:
            self._commit_phase = None
        return len(callbacks)

    def _finish_transaction(self, outcome: Literal["commit", "rollback"]) -> None:
        self._dirty_write = False
        self._dirty_write_command = None
        self._dirty_write_route = None
        self._dirty_write_kinds.clear()
        self._precommit_failed = False
        self.state.clear()
        if self.hooks.transaction_end is not None:
            self.hooks.transaction_end(self, outcome)

    def _commit_sync(self) -> None:
        if self._commit_phase is not None:
            raise TransactionLifecycleError("Commit callbacks cannot re-enter commit")
        self._run_before_commit_callbacks()
        try:
            self.driver.commit()
        except BaseException:
            self._precommit_failed = True
            raise
        try:
            self._finish_transaction("commit")
        except Exception as error:
            self._after_commit_callbacks.clear()
            raise AfterCommitError("Transaction-end hook failed after successful database commit") from error
        self._run_after_commit_callbacks()

    def rollback(self) -> None:
        if self._commit_phase is not None:
            raise TransactionLifecycleError("Commit callbacks cannot roll back the connection")
        self.driver.rollback()
        self._before_commit_callbacks.clear()
        self._after_commit_callbacks.clear()
        self._finish_transaction("rollback")

    def rollback_open_readonly_transaction(self) -> bool:
        open_states = (TransactionStatus.ACTIVE, TransactionStatus.INTRANS, TransactionStatus.INERROR)
        if self.transaction_status not in open_states:
            return False
        if self._dirty_write or self._before_commit_callbacks or self._after_commit_callbacks:
            return False
        self.rollback()
        return True

    def close(self) -> None:
        if self.closed:
            return
        error: UncommittedMutationCloseError | None = None
        try:
            if self.transaction_status != TransactionStatus.IDLE and self._dirty_write:
                error = UncommittedMutationCloseError(
                    f"Connection closed with uncommitted {self._dirty_write_command} via {self._dirty_write_route}"
                )
                if self.hooks.abandoned_write is not None:
                    self.hooks.abandoned_write(self, error)
            elif self.transaction_status in (
                TransactionStatus.ACTIVE,
                TransactionStatus.INTRANS,
                TransactionStatus.INERROR,
            ):
                self.driver.rollback()
        finally:
            self.driver.close()
            self.state.clear()
            self._before_commit_callbacks.clear()
            self._after_commit_callbacks.clear()
        if error is not None:
            raise error


class SyncConnection(ConnectionBase):
    def commit(self) -> None:
        self._commit_sync()

    def __enter__(self) -> SyncConnection:
        return self

    def __exit__(self, kind: type[BaseException] | None, error: BaseException | None, tb: TracebackType | None) -> None:
        if kind is not None:
            try:
                self.rollback()
            finally:
                self.close()
            return
        try:
            self.commit()
        except BaseException:
            try:
                self.rollback()
            finally:
                self.close()
            raise
        else:
            self.close()

    @contextmanager
    def transaction(self, *, savepoint_name: str | None = None, force_rollback: bool = False) -> Iterator[None]:
        if self.transaction_status != TransactionStatus.IDLE:
            raise TransactionLifecycleError("Explicit transaction requires an idle connection")
        if self._before_commit_callbacks or self._after_commit_callbacks:
            raise TransactionLifecycleError("Explicit transaction cannot inherit pending callbacks")
        try:
            with self.driver.transaction(savepoint_name=savepoint_name, force_rollback=force_rollback):
                yield
                self._run_before_commit_callbacks()
        except BaseException:
            self._before_commit_callbacks.clear()
            self._after_commit_callbacks.clear()
            self._finish_transaction("rollback")
            raise
        if force_rollback:
            self._after_commit_callbacks.clear()
            self._finish_transaction("rollback")
        else:
            try:
                self._finish_transaction("commit")
            except Exception as error:
                self._after_commit_callbacks.clear()
                raise AfterCommitError("Transaction-end hook failed after successful database commit") from error
            self._run_after_commit_callbacks()


class CallbackConnection(ConnectionBase):
    """Synchronous DB I/O; commit awaits application callbacks afterward."""

    def __init__(
        self,
        driver: RawConnection,
        *,
        hooks: ExecutionHooks | None = None,
        report_callback_error: Callable[[Exception], None],
    ) -> None:
        super().__init__(driver, hooks=hooks)
        self._report_callback_error = report_callback_error
        self._on_commit_callbacks: list[OnCommitCallback] = []
        self._callbacks_running = False

    def on_commit(self, callback: OnCommitCallback) -> None:
        if self._callbacks_running:
            raise TransactionLifecycleError("Cannot register callbacks while callbacks are running")
        self._on_commit_callbacks.append(callback)

    async def commit(self) -> None:
        if self._callbacks_running:
            raise TransactionLifecycleError("Commit callbacks cannot re-enter commit")
        try:
            self._commit_sync()
        except AfterCommitError:
            self._on_commit_callbacks.clear()
            raise
        callbacks, self._on_commit_callbacks = self._on_commit_callbacks, []
        self._callbacks_running = True
        try:
            for callback in callbacks:
                try:
                    await callback()
                except Exception as error:
                    self._report_callback_error(error)
        finally:
            self._callbacks_running = False

    def rollback(self) -> None:
        if self._callbacks_running:
            raise TransactionLifecycleError("Commit callbacks cannot roll back the connection")
        super().rollback()
        self._on_commit_callbacks.clear()

    def close(self) -> None:
        try:
            super().close()
        finally:
            self._on_commit_callbacks.clear()

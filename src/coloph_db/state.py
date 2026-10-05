"""Application-owned values with a transaction-bound lifetime."""

from collections.abc import Callable
from typing import Generic, TypeVar, cast

T = TypeVar("T")


class StateKey(Generic[T]):
    """An identity key whose type fixes the type of its stored value."""


class TransactionState:
    def __init__(self) -> None:
        self._values: dict[object, object] = {}

    def get(self, key: StateKey[T]) -> T | None:
        return cast(T | None, self._values.get(key))

    def get_or_create(self, key: StateKey[T], factory: Callable[[], T]) -> T:
        if key not in self._values:
            self._values[key] = factory()
        return cast(T, self._values[key])

    def clear(self) -> None:
        self._values.clear()

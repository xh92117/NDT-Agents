"""Typed failures shared by storage adapters."""

from __future__ import annotations


class StorageError(RuntimeError):
    """A non-disclosing storage failure with a stable recovery contract."""

    def __init__(self, *, code: str, message: str, retryable: bool, next_action: str) -> None:
        self.code = code
        self.retryable = retryable
        self.next_action = next_action
        super().__init__(f"{code}: {message}")

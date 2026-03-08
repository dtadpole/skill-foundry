"""Abstract storage backend interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional


class StorageBackend(ABC):
    """Key-value storage interface used by all skill-foundry tools.

    Keys use forward-slash path segments (e.g. "thread_tracker/active.json").
    Values are UTF-8 strings.
    """

    @abstractmethod
    def get(self, key: str) -> Optional[str]:
        """Return the value for *key*, or None if it doesn't exist."""

    @abstractmethod
    def put(self, key: str, content: str) -> None:
        """Write *content* to *key*, creating or overwriting."""

    @abstractmethod
    def append(self, key: str, content: str) -> None:
        """Append *content* to *key* (creates the object if absent)."""

    @abstractmethod
    def exists(self, key: str) -> bool:
        """Return True if *key* exists."""

    @abstractmethod
    def list_prefix(self, prefix: str) -> list[str]:
        """Return all keys that start with *prefix* (sorted)."""

    @abstractmethod
    def delete(self, key: str) -> None:
        """Delete *key* (no-op if absent)."""

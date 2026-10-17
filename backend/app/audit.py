import threading
from collections import deque
from typing import Any

MAX_ENTRIES = 200


class AuditLog:
    """Thread-safe, in-memory, bounded audit history (lost on restart)."""

    def __init__(self, max_entries: int = MAX_ENTRIES):
        self._entries: deque[dict[str, Any]] = deque(maxlen=max_entries)
        self._lock = threading.Lock()

    def add(self, entry: dict[str, Any]) -> None:
        with self._lock:
            self._entries.appendleft(entry)

    def list(self) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._entries)

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()

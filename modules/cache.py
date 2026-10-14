"""Small cache for slow or unreliable data sources (weather now, calendar/Spotify later)."""
from __future__ import annotations

import logging
import threading
import time
from typing import Callable, Generic, TypeVar

log = logging.getLogger(__name__)
T = TypeVar("T")


class StaleCache(Generic[T]):
    """Keeps one value fresh, and keeps serving it (stale) when the source fails.

    ttl_seconds        value is reused without calling the source for this long
    max_stale_seconds  after a failed refresh, the old value is still served this long
    retry_after        pause before calling a failing source again (avoids hammering it
                       while the internet is down)
    """

    def __init__(self, name: str, ttl_seconds: float, max_stale_seconds: float, retry_after: float = 30):
        self._name = name
        self._ttl = ttl_seconds
        self._max_stale = max_stale_seconds
        self._retry_after = retry_after
        self._value: T | None = None
        self._has_value = False
        self._fetched_at = 0.0
        self._failed_at = float("-inf")
        self._lock = threading.Lock()

    def get(self, fetch: Callable[[], T]) -> T:
        with self._lock:
            now = time.monotonic()

            if self._has_value and now - self._fetched_at < self._ttl:
                return self._value  # type: ignore[return-value]

            if now - self._failed_at >= self._retry_after:
                try:
                    value = fetch()
                except Exception as exc:
                    self._failed_at = time.monotonic()
                    log.warning("%s: refresh failed (%s)", self._name, exc)
                else:
                    self._value, self._has_value = value, True
                    self._fetched_at = time.monotonic()
                    return value

            if self._has_value and time.monotonic() - self._fetched_at < self._max_stale:
                return self._value  # type: ignore[return-value]

            raise RuntimeError(f"{self._name}: no data available")

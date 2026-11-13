from __future__ import annotations

import os
import threading
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any, Generic, Hashable, Optional, TypeVar

T = TypeVar("T")


class CacheInterface(Generic[T]):
    def get(self, key: Hashable) -> Optional[T]:
        raise NotImplementedError

    def set(self, key: Hashable, value: T) -> None:
        raise NotImplementedError


def _approx_bytes(value: Any) -> int:
    """Size of a cached step output: the arrays of an XY (x, y, var); 0 for anything without arrays."""
    total = 0
    for name in ("x", "y", "var"):
        arr = getattr(value, name, None)
        total += int(getattr(arr, "nbytes", 0) or 0)
    return total


@dataclass
class InProcessLRUCache(CacheInterface[T]):
    """
    Least-recently-used cache of pipeline step outputs, safe to share between request threads.

    Bounded by item count and, when ``max_bytes`` > 0, by the summed size of the cached arrays (a cache of
    4096 Raman maps is not the same as 4096 short XPS regions).
    """

    max_items: int = 2048
    max_bytes: int = 0

    def __post_init__(self) -> None:
        self._data: OrderedDict[Hashable, T] = OrderedDict()
        self._sizes: dict[Hashable, int] = {}
        self._bytes = 0
        # Sync endpoints run in a thread pool: without the lock, two requests could pop the same key.
        self._lock = threading.Lock()

    def get(self, key: Hashable) -> Optional[T]:
        with self._lock:
            if key not in self._data:
                return None
            self._data.move_to_end(key)
            return self._data[key]

    def set(self, key: Hashable, value: T) -> None:
        size = _approx_bytes(value) if self.max_bytes else 0
        with self._lock:
            if key in self._data:
                self._data.pop(key)
                self._bytes -= self._sizes.pop(key, 0)
            self._data[key] = value
            self._sizes[key] = size
            self._bytes += size
            while len(self._data) > 1 and (
                len(self._data) > int(self.max_items) or (self.max_bytes and self._bytes > int(self.max_bytes))
            ):
                old, _ = self._data.popitem(last=False)
                self._bytes -= self._sizes.pop(old, 0)

    def __len__(self) -> int:
        with self._lock:
            return len(self._data)


_SHARED: InProcessLRUCache[Any] | None = None
_SHARED_LOCK = threading.Lock()


def shared_pipeline_cache() -> InProcessLRUCache[Any]:
    """
    The one step-output cache of the API process.

    Every router / service used to keep its own 4096-item cache, so a QC preview and the session run that
    follows it recomputed the same steps, and memory was bounded six times over. Keys already include the
    cache namespace, the spectrum, the step parameters and the file identity, so sharing cannot mix results.
    Size: ``SERSFLOW_PIPELINE_CACHE_ITEMS`` (default 8192) and ``SERSFLOW_PIPELINE_CACHE_MB`` (default 512).
    """
    global _SHARED
    with _SHARED_LOCK:
        if _SHARED is None:

            def _env_int(name: str, default: int) -> int:
                try:
                    return max(1, int(float(os.environ.get(name, "") or default)))
                except ValueError:
                    return default

            _SHARED = InProcessLRUCache(
                max_items=_env_int("SERSFLOW_PIPELINE_CACHE_ITEMS", 8192),
                max_bytes=_env_int("SERSFLOW_PIPELINE_CACHE_MB", 512) * 1024 * 1024,
            )
        return _SHARED


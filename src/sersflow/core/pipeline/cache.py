from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from typing import Generic, Hashable, Optional, TypeVar

T = TypeVar("T")


class CacheInterface(Generic[T]):
    def get(self, key: Hashable) -> Optional[T]:
        raise NotImplementedError

    def set(self, key: Hashable, value: T) -> None:
        raise NotImplementedError


@dataclass
class InProcessLRUCache(CacheInterface[T]):
    max_items: int = 2048

    def __post_init__(self) -> None:
        self._data: OrderedDict[Hashable, T] = OrderedDict()

    def get(self, key: Hashable) -> Optional[T]:
        if key not in self._data:
            return None
        v = self._data.pop(key)
        self._data[key] = v
        return v

    def set(self, key: Hashable, value: T) -> None:
        if key in self._data:
            self._data.pop(key)
        self._data[key] = value
        while len(self._data) > int(self.max_items):
            self._data.popitem(last=False)


from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from sersflow.client.client import SersflowClient


class RawResource:
    """Low-level access to the underlying ``httpx.Client`` (e.g. custom streaming)."""

    __slots__ = ("_root",)

    def __init__(self, root: SersflowClient):
        self._root = root

    def stream(self, method: str, url: str, **kwargs: Any):
        """Return a streaming context manager: ``with client.raw.stream(...) as resp: ...``."""
        return self._root.http.stream(method, url, **kwargs)

    def request_stream(self, method: str, url: str, **kwargs: Any):
        """Alias for :meth:`stream` (alternative naming used in docs)."""
        return self.stream(method, url, **kwargs)

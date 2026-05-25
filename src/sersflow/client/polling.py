from __future__ import annotations

import time
from collections.abc import Callable
from typing import TypeVar

from sersflow.client.exceptions import JobTimeoutError, TerminalJobFailedError

T = TypeVar("T")


def poll_until(
    fetch: Callable[[], T],
    *,
    job_id: str,
    is_terminal: Callable[[T], bool],
    timeout_s: float,
    initial_interval_s: float = 0.25,
    max_interval_s: float = 2.0,
) -> T:
    """
    Poll ``fetch`` until ``is_terminal`` is true or ``timeout_s`` elapses.
    Uses simple exponential backoff capped at ``max_interval_s``.
    """
    deadline = time.monotonic() + max(0.01, timeout_s)
    interval = max(0.05, initial_interval_s)
    last: T | None = None
    last_status: str | None = None
    while time.monotonic() < deadline:
        last = fetch()
        if isinstance(last, dict):
            last_status = str(last.get("status") or "") or None
        elif hasattr(last, "status"):
            try:
                last_status = str(getattr(last, "status"))
            except Exception:
                last_status = None
        if is_terminal(last):
            return last
        time.sleep(min(interval, max(0.0, deadline - time.monotonic())))
        interval = min(max_interval_s, interval * 1.5)
    raise JobTimeoutError(job_id=job_id, timeout_s=timeout_s, last_status=last_status)


def analysis_job_terminal_statuses() -> frozenset[str]:
    return frozenset({"completed", "failed"})


def matrix_job_terminal_statuses() -> frozenset[str]:
    return frozenset({"completed", "failed"})


def ensure_analysis_job_ok(status: str, *, job_id: str, error: str | None) -> None:
    if status == "failed":
        raise TerminalJobFailedError(job_id=job_id, status=status, error=error)


def ensure_matrix_job_ok(status: str, *, job_id: str, error: str | None) -> None:
    if status == "failed":
        raise TerminalJobFailedError(job_id=job_id, status=status, error=error)

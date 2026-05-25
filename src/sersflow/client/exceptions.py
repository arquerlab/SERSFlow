from __future__ import annotations

from typing import Any


class SersflowApiError(Exception):
    """HTTP failure from SERSFlow API."""

    def __init__(
        self,
        *,
        status_code: int,
        detail: Any = None,
        text: str | None = None,
    ):
        super().__init__(detail if detail is not None else (text or f"HTTP {status_code}"))
        self.status_code = status_code
        self.detail = detail
        self.text = text


class JobTimeoutError(RuntimeError):
    """Exceeded timeout while polling a background job."""

    def __init__(self, *, job_id: str, timeout_s: float, last_status: str | None = None):
        msg = f"Timeout waiting for job {job_id} after {timeout_s}s"
        if last_status:
            msg += f" (last status: {last_status})"
        super().__init__(msg)
        self.job_id = job_id
        self.timeout_s = timeout_s
        self.last_status = last_status


class TerminalJobFailedError(RuntimeError):
    """Job ended in a failed/error state."""

    def __init__(self, *, job_id: str, status: str, error: str | None):
        msg = f"Job {job_id} ended with status {status}"
        if error:
            msg += f": {error}"
        super().__init__(msg)
        self.job_id = job_id
        self.status = status
        self.error = error

"""Map exceptions to compact JSON tool payloads (no stack traces)."""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from sersflow.client.exceptions import JobTimeoutError, SersflowApiError, TerminalJobFailedError
from sersflow.mcp.confirm import NeedsConfirmError


def _resume_args(job_id: str, *, status_tool: str) -> dict[str, str]:
    if "matrix" in status_tool:
        return {"matrix_job_id": job_id}
    return {"job_id": job_id}


def timeout_payload(
    exc: JobTimeoutError,
    *,
    status_tool: str,
    wait_tool: str,
) -> dict[str, Any]:
    job_id = exc.job_id
    args = _resume_args(job_id, status_tool=status_tool)
    arg_name = next(iter(args))
    return {
        "ok": False,
        "error": "timeout",
        "job_id": job_id,
        "last_status": exc.last_status,
        "timeout_s": exc.timeout_s,
        "resume": {
            "tool": status_tool,
            "args": args,
            "alternate_tool": wait_tool,
            "hint": (
                f"Call {status_tool} with {arg_name}={job_id!r} to check status, "
                f"or {wait_tool} with the same {arg_name} to wait again."
            ),
        },
        "message": str(exc),
    }


def exception_to_payload(
    exc: BaseException,
    *,
    status_tool: str = "get_analysis_jobs",
    wait_tool: str = "post_analysis_jobs_wait",
) -> dict[str, Any]:
    if isinstance(exc, NeedsConfirmError):
        return exc.payload
    if isinstance(exc, JobTimeoutError):
        return timeout_payload(exc, status_tool=status_tool, wait_tool=wait_tool)
    if isinstance(exc, TerminalJobFailedError):
        return {
            "ok": False,
            "error": "job_failed",
            "job_id": exc.job_id,
            "status": exc.status,
            "detail": _truncate(exc.error),
            "message": str(exc),
        }
    if isinstance(exc, SersflowApiError):
        return {
            "ok": False,
            "error": "http",
            "status_code": exc.status_code,
            "detail": _truncate(exc.detail if exc.detail is not None else exc.text),
            "message": _truncate(str(exc)),
        }
    if isinstance(exc, ValidationError):
        return {
            "ok": False,
            "error": "validation",
            "message": _truncate(str(exc), limit=800),
            "details": _truncate(exc.errors(), limit=1500),
        }
    if isinstance(exc, (ValueError, TypeError, FileNotFoundError, PermissionError, OSError)):
        return {"ok": False, "error": "validation", "message": _truncate(str(exc))}
    if isinstance(exc, RuntimeError):
        return {"ok": False, "error": "runtime", "message": _truncate(str(exc))}
    return {"ok": False, "error": "internal", "message": _truncate(str(exc))}


def _truncate(value: Any, *, limit: int = 500) -> Any:
    if value is None:
        return None
    if isinstance(value, (dict, list)):
        text = str(value)
        if len(text) <= limit:
            return value
        return text[: limit - 3] + "..."
    text = str(value)
    if len(text) <= limit:
        return text if isinstance(value, str) else value
    return text[: limit - 3] + "..."

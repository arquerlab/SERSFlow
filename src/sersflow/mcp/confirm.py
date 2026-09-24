"""Confirmation gates for large uploads and heavy fitting pipelines."""

from __future__ import annotations

from pathlib import Path
from typing import Any


def refusal(*, reason: str, message: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "ok": False,
        "needs_confirm": True,
        "confirm_param": "confirm",
        "reason": reason,
        "message": message,
        "details": details or {},
    }


def require_confirm(
    confirm: bool | None, *, reason: str, message: str, details: dict[str, Any]
) -> dict[str, Any] | None:
    if confirm is True:
        return None
    return refusal(reason=reason, message=message, details=details)


def check_upload_size(
    paths: list[Path | str],
    *,
    threshold: int,
    confirm: bool | None,
    folder_pattern: str | None = None,
) -> dict[str, Any] | None:
    """
    Sum sizes of files that will be uploaded.

    For directories, when ``folder_pattern`` is set, only matching files count
    (same glob used by ``upload_folder``).
    """
    total = 0
    missing: list[str] = []
    matched_files = 0
    for p in paths:
        path = Path(p)
        if not path.exists():
            missing.append(str(path))
            continue
        if path.is_file():
            total += path.stat().st_size
            matched_files += 1
        elif path.is_dir():
            if folder_pattern:
                children = sorted(path.rglob(folder_pattern))
            else:
                children = [c for c in path.rglob("*") if c.is_file()]
            files = [c for c in children if c.is_file()]
            if not files:
                raise FileNotFoundError(
                    f"No files matched in {path}"
                    + (f" with pattern {folder_pattern!r}" if folder_pattern else "")
                )
            for child in files:
                total += child.stat().st_size
                matched_files += 1
        else:
            missing.append(str(path))
    if missing:
        raise FileNotFoundError(f"Upload path(s) not found: {', '.join(missing)}")
    if matched_files == 0:
        raise FileNotFoundError("No files to upload")
    if total <= threshold:
        return None
    return require_confirm(
        confirm,
        reason="upload_exceeds_threshold",
        message=(
            f"Upload is {total} bytes > {threshold} bytes. "
            "Retry with confirm=true after user approval."
        ),
        details={"bytes": total, "threshold": threshold, "files": matched_files},
    )


def _step_name(step: Any) -> str:
    if isinstance(step, dict):
        return str(step.get("name") or "")
    return str(getattr(step, "name", "") or "")


def _step_enabled(step: Any) -> bool:
    if isinstance(step, dict):
        return bool(step.get("enabled", True))
    return bool(getattr(step, "enabled", True))


def _step_params(step: Any) -> dict[str, Any]:
    if isinstance(step, dict):
        params = step.get("params") or {}
        return params if isinstance(params, dict) else {}
    params = getattr(step, "params", None) or {}
    if hasattr(params, "model_dump"):
        return dict(params.model_dump())
    return dict(params) if isinstance(params, dict) else {}


def _pipeline_steps(pipeline: Any) -> list[Any]:
    if pipeline is None:
        return []
    if isinstance(pipeline, dict):
        steps = pipeline.get("steps") or []
        return list(steps) if isinstance(steps, list) else []
    steps = getattr(pipeline, "steps", None) or []
    return list(steps)


def max_fitting_components(pipeline: Any) -> int:
    """Largest ``params.components`` length among enabled fitting steps."""
    max_n = 0
    for step in _pipeline_steps(pipeline):
        if _step_name(step) != "fitting" or not _step_enabled(step):
            continue
        components = _step_params(step).get("components") or []
        if isinstance(components, list):
            max_n = max(max_n, len(components))
    return max_n


def check_fitting_components(
    pipeline: Any,
    *,
    max_components: int,
    confirm: bool | None,
) -> dict[str, Any] | None:
    n = max_fitting_components(pipeline)
    if n <= max_components:
        return None
    return require_confirm(
        confirm,
        reason="fitting_components_exceed_threshold",
        message=(
            f"Pipeline has a fitting step with {n} components > {max_components}. "
            "Retry with confirm=true after user approval."
        ),
        details={"components": n, "threshold": max_components},
    )


def reject_overwrite(overwrite: bool | None) -> dict[str, Any] | None:
    if overwrite:
        return {
            "ok": False,
            "error": "policy",
            "message": "Library pipeline overwrite is forbidden via MCP; create a new named pipeline instead.",
        }
    return None


class NeedsConfirmError(Exception):
    """Raised when a tool must return a confirm refusal payload."""

    def __init__(self, payload: dict[str, Any]):
        super().__init__(payload.get("message") or "confirmation required")
        self.payload = payload

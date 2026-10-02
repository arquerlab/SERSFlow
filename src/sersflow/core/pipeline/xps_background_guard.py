"""Reject combining static XPS baselines with active XPS fit backgrounds."""

from __future__ import annotations

from typing import Any, Iterable

_STATIC_XPS_BASELINE = frozenset({"shirley", "tougaard"})
_ACTIVE_XPS_BG = frozenset({"shirley_bg", "tougaard_bg"})


def _step_enabled(step: Any) -> bool:
    if isinstance(step, dict):
        return bool(step.get("enabled", True))
    return bool(getattr(step, "enabled", True))


def _step_name(step: Any) -> str:
    if isinstance(step, dict):
        return str(step.get("name") or "").strip().lower()
    return str(getattr(step, "name", "") or "").strip().lower()


def _step_params(step: Any) -> dict[str, Any]:
    if isinstance(step, dict):
        p = step.get("params") or {}
        return p if isinstance(p, dict) else {}
    p = getattr(step, "params", None) or {}
    return p if isinstance(p, dict) else {}


def dual_xps_background_conflict(steps: Iterable[Any]) -> str | None:
    """
    Return an error message if both static lmfitxps baseline and active fit BG are enabled.

    Static: baseline step with method shirley/tougaard.
    Active: fitting component_type shirley_bg/tougaard_bg.
    """
    static: list[str] = []
    active: list[str] = []
    for step in steps:
        if not _step_enabled(step):
            continue
        name = _step_name(step)
        params = _step_params(step)
        if name == "baseline":
            method = str(params.get("method") or "").strip().lower()
            if method in _STATIC_XPS_BASELINE:
                static.append(method)
        elif name == "fitting":
            comps = params.get("components") or []
            if not isinstance(comps, list):
                continue
            for row in comps:
                if not isinstance(row, dict):
                    continue
                ct = str(row.get("component_type") or "").strip().lower()
                if ct in _ACTIVE_XPS_BG:
                    active.append(ct)
    if static and active:
        return (
            "Cannot combine static XPS baseline "
            f"({', '.join(sorted(set(static)))}) with active fit background "
            f"({', '.join(sorted(set(active)))}). "
            "Use either a baseline step Shirley/Tougaard or an active shirley_bg/tougaard_bg "
            "in fitting, not both."
        )
    return None


def assert_no_dual_xps_background(pipeline: Any) -> None:
    """Raise ValueError when pipeline mixes static and active XPS backgrounds."""
    steps = getattr(pipeline, "steps", None)
    if steps is None and isinstance(pipeline, dict):
        steps = pipeline.get("steps")
    if not steps:
        return
    msg = dual_xps_background_conflict(steps)
    if msg:
        raise ValueError(msg)

"""Run-level summary of per-spectrum fitting-step status (K2: failed fits must not pass silently)."""

from __future__ import annotations

from typing import Any

MAX_FAILURE_ITEMS = 50

FAILED_STATUSES = ("failed", "not_converged")


def summarize_fit_statuses(
    statuses_by_spectrum: dict[str, list[dict[str, Any]]],
    *,
    max_items: int = MAX_FAILURE_ITEMS,
) -> dict[str, Any]:
    """
    Aggregate ``status_out`` entries from :func:`collect_fitting_features_for_pipeline`.

    Returns ``{"n_fits", "n_ok", "n_failed", "n_not_converged", "n_not_applicable", "items",
    "truncated"}`` where ``items`` lists failed / not-converged fits (spectrum id, step, reason).
    """
    counts = {"ok": 0, "failed": 0, "not_converged": 0, "not_applicable": 0}
    items: list[dict[str, Any]] = []
    n_problem = 0
    for sid in sorted(statuses_by_spectrum):
        for st in statuses_by_spectrum[sid] or []:
            status = str(st.get("status") or "")
            if status in counts:
                counts[status] += 1
            if status in FAILED_STATUSES:
                n_problem += 1
                if len(items) < max_items:
                    items.append(
                        {
                            "spectrum_id": sid,
                            "step_index": st.get("step_index"),
                            "step_id": st.get("step_id"),
                            "xps_region": st.get("xps_region"),
                            "status": status,
                            "reason": st.get("reason"),
                        }
                    )
    return {
        "n_fits": counts["ok"] + counts["failed"] + counts["not_converged"],
        "n_ok": counts["ok"],
        "n_failed": counts["failed"],
        "n_not_converged": counts["not_converged"],
        "n_not_applicable": counts["not_applicable"],
        "items": items,
        "truncated": n_problem > len(items),
    }


def fit_summary_warnings(summary: dict[str, Any] | None) -> list[str]:
    """Human-readable run warnings for a fit summary (empty when every attempted fit succeeded)."""
    if not summary:
        return []
    out: list[str] = []
    n_failed = int(summary.get("n_failed") or 0)
    n_nc = int(summary.get("n_not_converged") or 0)
    n_fits = int(summary.get("n_fits") or 0)
    if n_failed:
        out.append(
            f"{n_failed} of {n_fits} fit(s) FAILED: raw spectrum passed through, fit features are empty "
            "and success=0 (see fit_failures)"
        )
    if n_nc:
        out.append(
            f"{n_nc} of {n_fits} fit(s) did not converge (success=0); parameters kept but check them"
        )
    return out

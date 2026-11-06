"""
Fit history (X1): snapshots of a fitting step's model state, per user and scope (STORE / RECALL / RESET).

A snapshot is the fitting step ``params`` (components with options, p0, bounds, vary, param_links, fit window,
weighting) plus a small summary of the fit (chi2, reduced chi2, RMSE, area % per component). Snapshots made by a
preview fit are de-duplicated by a hash of the model state and only the newest ``MAX_UNPINNED`` unpinned ones are
kept per scope; named (pinned) snapshots are kept until deleted.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from sersflow.infra.sqlite_db import connect
from sersflow.infra.user_access import has_global_access, resolve_owner_user_id

MAX_UNPINNED = 50

# Keys that define the model state (everything else in the step params is presentation).
_STATE_KEYS = (
    "components",
    "p0",
    "bounds_lower",
    "bounds_upper",
    "vary",
    "param_links",
    "fit_min_x",
    "fit_max_x",
    "weighting",
    "xps_region",
    "initial_area_ratios",
)


@dataclass(frozen=True)
class FitSnapshot:
    history_id: str
    owner_user_id: str
    scope_key: str
    label: str
    pinned: bool
    params: dict[str, Any]
    summary: dict[str, Any]
    params_hash: str
    created_at: str

    def public(self, *, include_params: bool = True) -> dict[str, Any]:
        out: dict[str, Any] = {
            "history_id": self.history_id,
            "scope_key": self.scope_key,
            "label": self.label,
            "pinned": self.pinned,
            "summary": self.summary,
            "params_hash": self.params_hash,
            "created_at": self.created_at,
        }
        if include_params:
            out["params"] = self.params
        return out


def ensure_schema() -> None:
    with connect() as con:
        con.executescript(
            """
            CREATE TABLE IF NOT EXISTS fit_history (
              history_id TEXT PRIMARY KEY,
              owner_user_id TEXT NOT NULL,
              scope_key TEXT NOT NULL,
              label TEXT NOT NULL DEFAULT '',
              pinned INTEGER NOT NULL DEFAULT 0,
              params_json TEXT NOT NULL,
              summary_json TEXT NOT NULL,
              params_hash TEXT NOT NULL,
              created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_fit_history_scope
              ON fit_history(owner_user_id, scope_key, created_at DESC);
            """
        )


def state_hash(params: dict[str, Any]) -> str:
    state = {k: params.get(k) for k in _STATE_KEYS if params.get(k) is not None}
    blob = json.dumps(state, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(blob.encode()).hexdigest()


def _row(r: Any) -> FitSnapshot:
    return FitSnapshot(
        history_id=r["history_id"],
        owner_user_id=r["owner_user_id"],
        scope_key=r["scope_key"],
        label=r["label"] or "",
        pinned=bool(r["pinned"]),
        params=json.loads(r["params_json"]),
        summary=json.loads(r["summary_json"] or "{}"),
        params_hash=r["params_hash"],
        created_at=r["created_at"],
    )


def _scoped(owner_user_id: str) -> tuple[str, list[Any]]:
    if has_global_access(owner_user_id):
        return "", []
    return " AND owner_user_id = ?", [resolve_owner_user_id(owner_user_id)]


def add_snapshot(
    *,
    owner_user_id: str,
    scope_key: str,
    params: dict[str, Any],
    summary: dict[str, Any] | None = None,
    label: str = "",
    pinned: bool = False,
) -> tuple[FitSnapshot, bool]:
    """Store a snapshot. Returns (snapshot, created). An unnamed, unpinned snapshot equal to the newest one is a no-op."""
    ensure_schema()
    scope_key = str(scope_key or "").strip()
    if not scope_key:
        raise ValueError("scope_key is required")
    if not isinstance(params, dict) or not params.get("components"):
        raise ValueError("params must be a fitting step params object with components")
    h = state_hash(params)
    owner = resolve_owner_user_id(owner_user_id)
    label = str(label or "").strip()
    pinned = bool(pinned or label)
    with connect() as con:
        newest = con.execute(
            "SELECT * FROM fit_history WHERE owner_user_id = ? AND scope_key = ? ORDER BY created_at DESC LIMIT 1",
            (owner, scope_key),
        ).fetchone()
        if newest is not None and newest["params_hash"] == h and not pinned:
            # Same model state as the newest snapshot: refresh its summary (a refit may have changed the stats).
            if summary:
                con.execute(
                    "UPDATE fit_history SET summary_json = ? WHERE history_id = ?",
                    (json.dumps(summary, default=str), newest["history_id"]),
                )
                newest = con.execute("SELECT * FROM fit_history WHERE history_id = ?", (newest["history_id"],)).fetchone()
            return _row(newest), False
        hid = f"fh_{uuid4().hex}"
        con.execute(
            """
            INSERT INTO fit_history (history_id, owner_user_id, scope_key, label, pinned, params_json, summary_json,
              params_hash, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                hid,
                owner,
                scope_key,
                label,
                1 if pinned else 0,
                json.dumps(params, default=str),
                json.dumps(summary or {}, default=str),
                h,
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        # Cap the unpinned snapshots of this scope.
        old = con.execute(
            "SELECT history_id FROM fit_history WHERE owner_user_id = ? AND scope_key = ? AND pinned = 0 "
            "ORDER BY created_at DESC LIMIT -1 OFFSET ?",
            (owner, scope_key, MAX_UNPINNED),
        ).fetchall()
        for o in old:
            con.execute("DELETE FROM fit_history WHERE history_id = ?", (o["history_id"],))
        row = con.execute("SELECT * FROM fit_history WHERE history_id = ?", (hid,)).fetchone()
    return _row(row), True


def list_snapshots(*, owner_user_id: str, scope_key: str, limit: int = 100) -> list[FitSnapshot]:
    ensure_schema()
    extra, p = _scoped(owner_user_id)
    with connect() as con:
        rows = con.execute(
            f"SELECT * FROM fit_history WHERE scope_key = ?{extra} ORDER BY created_at DESC LIMIT ?",
            (scope_key, *p, max(1, min(500, int(limit)))),
        ).fetchall()
    return [_row(r) for r in rows]


def get_snapshot(history_id: str, *, owner_user_id: str) -> FitSnapshot | None:
    ensure_schema()
    extra, p = _scoped(owner_user_id)
    with connect() as con:
        r = con.execute(f"SELECT * FROM fit_history WHERE history_id = ?{extra}", (history_id, *p)).fetchone()
    return _row(r) if r else None


def update_snapshot(
    history_id: str, *, owner_user_id: str, label: str | None = None, pinned: bool | None = None
) -> FitSnapshot | None:
    snap = get_snapshot(history_id, owner_user_id=owner_user_id)
    if snap is None:
        return None
    new_label = snap.label if label is None else str(label).strip()
    new_pinned = snap.pinned if pinned is None else bool(pinned)
    if new_label:
        new_pinned = True
    with connect() as con:
        con.execute(
            "UPDATE fit_history SET label = ?, pinned = ? WHERE history_id = ?",
            (new_label, 1 if new_pinned else 0, history_id),
        )
    return get_snapshot(history_id, owner_user_id=owner_user_id)


def delete_snapshot(history_id: str, *, owner_user_id: str) -> bool:
    if get_snapshot(history_id, owner_user_id=owner_user_id) is None:
        return False
    with connect() as con:
        con.execute("DELETE FROM fit_history WHERE history_id = ?", (history_id,))
    return True


def clear_unpinned(*, owner_user_id: str, scope_key: str) -> int:
    ensure_schema()
    extra, p = _scoped(owner_user_id)
    with connect() as con:
        cur = con.execute(
            f"DELETE FROM fit_history WHERE scope_key = ? AND pinned = 0{extra}", (scope_key, *p)
        )
        return int(cur.rowcount or 0)


# ------------------------------------------------------------------------------------------------ compare


def _flat_rows(params: dict[str, Any]) -> list[dict[str, Any]]:
    """One row per flat parameter: component id / type, key, value, bounds, vary."""
    from sersflow.core.preprocess.fitting_specs import component_param_specs

    p0 = [float(v) for v in params.get("p0") or []]
    lo = params.get("bounds_lower") or []
    hi = params.get("bounds_upper") or []
    vary = params.get("vary")
    rows: list[dict[str, Any]] = []
    cursor = 0
    for comp in params.get("components") or []:
        specs = component_param_specs(str(comp.get("component_type")), comp.get("degree"))
        for spec in specs:
            if cursor >= len(p0):
                break
            rows.append(
                {
                    "component_id": comp.get("component_id"),
                    "component_type": comp.get("component_type"),
                    "key": spec.key,
                    "value": p0[cursor],
                    "lower": lo[cursor] if cursor < len(lo) else None,
                    "upper": hi[cursor] if cursor < len(hi) else None,
                    "vary": bool(vary[cursor]) if isinstance(vary, list) and cursor < len(vary) else True,
                }
            )
            cursor += 1
    return rows


def compare_snapshots(a: FitSnapshot, b: FitSnapshot) -> dict[str, Any]:
    """Parameter table A vs B (union of component.key rows), plus component set differences and summary stats."""
    ra = {(r["component_id"], r["key"]): r for r in _flat_rows(a.params)}
    rb = {(r["component_id"], r["key"]): r for r in _flat_rows(b.params)}
    keys: list[tuple[Any, Any]] = list(ra)
    keys += [k for k in rb if k not in ra]
    rows = []
    for k in keys:
        x, y = ra.get(k), rb.get(k)
        va = x["value"] if x else None
        vb = y["value"] if y else None
        rows.append(
            {
                "component_id": k[0],
                "component_type": (x or y)["component_type"],
                "key": k[1],
                "a": va,
                "b": vb,
                "delta": (vb - va) if va is not None and vb is not None else None,
                "vary_a": x["vary"] if x else None,
                "vary_b": y["vary"] if y else None,
                "only_in": "a" if y is None else ("b" if x is None else None),
            }
        )
    ids_a = [c.get("component_id") for c in a.params.get("components") or []]
    ids_b = [c.get("component_id") for c in b.params.get("components") or []]
    stat_keys = sorted(set(a.summary) | set(b.summary))
    stats = [
        {
            "name": s,
            "a": a.summary.get(s),
            "b": b.summary.get(s),
        }
        for s in stat_keys
        if isinstance(a.summary.get(s, b.summary.get(s)), (int, float, type(None)))
        and not isinstance(a.summary.get(s, b.summary.get(s)), bool)
    ]
    return {
        "a": {"history_id": a.history_id, "label": a.label, "created_at": a.created_at},
        "b": {"history_id": b.history_id, "label": b.label, "created_at": b.created_at},
        "rows": rows,
        "components_only_in_a": [c for c in ids_a if c not in ids_b],
        "components_only_in_b": [c for c in ids_b if c not in ids_a],
        "window_a": [a.params.get("fit_min_x"), a.params.get("fit_max_x")],
        "window_b": [b.params.get("fit_min_x"), b.params.get("fit_max_x")],
        "stats": stats,
    }

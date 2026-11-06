"""
Reference-spectrum library (M1): measured spectra used as fit components (CasaXPS linear least squares basis).

Per user (user decision). Each entry keeps x / y as saved, a unit-area normalisation factor (so a fitted reference
amplitude IS its area), a SHA-256 of the arrays (stored in fitting steps for reproducibility) and its provenance
(source kind, dataset / spectrum, pipeline steps applied, file name for imports).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

import numpy as np

from sersflow.infra.sqlite_db import connect
from sersflow.infra.user_access import has_global_access, resolve_owner_user_id


@dataclass(frozen=True)
class ReferenceSpectrum:
    reference_id: str
    owner_user_id: str
    name: str
    notes: str
    x: list[float]
    y: list[float]
    area: float
    """Integral of y over its x range (the unit-area normalisation divides y by this)."""
    sha256: str
    source: dict[str, Any]
    technique_family: str
    created_at: str

    def summary(self) -> dict[str, Any]:
        return {
            "reference_id": self.reference_id,
            "owner_user_id": self.owner_user_id,
            "name": self.name,
            "notes": self.notes,
            "n_points": len(self.x),
            "x_min": min(self.x) if self.x else None,
            "x_max": max(self.x) if self.x else None,
            "area": self.area,
            "sha256": self.sha256,
            "source": self.source,
            "technique_family": self.technique_family,
            "created_at": self.created_at,
        }


def ensure_schema() -> None:
    with connect() as con:
        con.executescript(
            """
            CREATE TABLE IF NOT EXISTS reference_spectra (
              reference_id TEXT PRIMARY KEY,
              owner_user_id TEXT NOT NULL,
              name TEXT NOT NULL,
              notes TEXT NOT NULL DEFAULT '',
              x_json TEXT NOT NULL,
              y_json TEXT NOT NULL,
              area REAL NOT NULL,
              sha256 TEXT NOT NULL,
              source_json TEXT NOT NULL,
              technique_family TEXT NOT NULL DEFAULT 'xps',
              created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_reference_spectra_owner ON reference_spectra(owner_user_id, created_at DESC);
            """
        )


def arrays_sha256(x: list[float], y: list[float]) -> str:
    h = hashlib.sha256()
    h.update(np.asarray(x, dtype="<f8").tobytes())
    h.update(np.asarray(y, dtype="<f8").tobytes())
    return h.hexdigest()


def _clean_xy(x: list[float], y: list[float]) -> tuple[list[float], list[float], float]:
    xa = np.asarray(x, dtype=float)
    ya = np.asarray(y, dtype=float)
    if xa.ndim != 1 or xa.shape != ya.shape or xa.size < 3:
        raise ValueError("a reference needs x and y of equal length (at least 3 points)")
    ok = np.isfinite(xa) & np.isfinite(ya)
    xa, ya = xa[ok], ya[ok]
    order = np.argsort(xa)
    xa, ya = xa[order], ya[order]
    if np.any(np.diff(xa) <= 0):
        raise ValueError("reference x values must be distinct")
    trap = getattr(np, "trapezoid", None) or np.trapz
    area = float(trap(ya, xa))
    if not np.isfinite(area) or area <= 0:
        raise ValueError("reference must have a positive area (subtract the background first)")
    return xa.tolist(), ya.tolist(), area


def _row(r: Any) -> ReferenceSpectrum:
    return ReferenceSpectrum(
        reference_id=r["reference_id"],
        owner_user_id=r["owner_user_id"],
        name=r["name"],
        notes=r["notes"] or "",
        x=json.loads(r["x_json"]),
        y=json.loads(r["y_json"]),
        area=float(r["area"]),
        sha256=r["sha256"],
        source=json.loads(r["source_json"] or "{}"),
        technique_family=r["technique_family"],
        created_at=r["created_at"],
    )


def create_reference(
    *,
    owner_user_id: str,
    name: str,
    x: list[float],
    y: list[float],
    source: dict[str, Any],
    notes: str = "",
    technique_family: str = "xps",
) -> ReferenceSpectrum:
    ensure_schema()
    name = str(name or "").strip()
    if not name:
        raise ValueError("reference name is required")
    xs, ys, area = _clean_xy(x, y)
    rid = f"ref_{uuid4().hex}"
    now = datetime.now(timezone.utc).isoformat()
    sha = arrays_sha256(xs, ys)
    with connect() as con:
        con.execute(
            """
            INSERT INTO reference_spectra (reference_id, owner_user_id, name, notes, x_json, y_json, area, sha256,
              source_json, technique_family, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                rid,
                resolve_owner_user_id(owner_user_id),
                name,
                str(notes or ""),
                json.dumps(xs),
                json.dumps(ys),
                area,
                sha,
                json.dumps(source or {}, default=str),
                str(technique_family or "xps"),
                now,
            ),
        )
    got = get_reference_any(rid)
    assert got is not None
    return got


def get_reference_any(reference_id: str) -> ReferenceSpectrum | None:
    """Unscoped read (the fitting engine resolves ids stored in a pipeline the user could already open)."""
    ensure_schema()
    with connect() as con:
        r = con.execute("SELECT * FROM reference_spectra WHERE reference_id = ?", (reference_id,)).fetchone()
    return _row(r) if r else None


def get_reference(reference_id: str, *, owner_user_id: str) -> ReferenceSpectrum | None:
    ref = get_reference_any(reference_id)
    if ref is None:
        return None
    if has_global_access(owner_user_id) or ref.owner_user_id == resolve_owner_user_id(owner_user_id):
        return ref
    return None


def list_references(*, owner_user_id: str, q: str | None = None, limit: int = 200) -> list[ReferenceSpectrum]:
    ensure_schema()
    clauses: list[str] = []
    params: list[Any] = []
    if not has_global_access(owner_user_id):
        clauses.append("owner_user_id = ?")
        params.append(resolve_owner_user_id(owner_user_id))
    if q and str(q).strip():
        clauses.append("name LIKE ?")
        params.append(f"%{str(q).strip()}%")
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    with connect() as con:
        rows = con.execute(
            f"SELECT * FROM reference_spectra {where} ORDER BY created_at DESC LIMIT ?",
            (*params, max(1, min(1000, int(limit)))),
        ).fetchall()
    return [_row(r) for r in rows]


def delete_reference(reference_id: str, *, owner_user_id: str) -> bool:
    ref = get_reference(reference_id, owner_user_id=owner_user_id)
    if ref is None:
        return False
    with connect() as con:
        con.execute("DELETE FROM reference_spectra WHERE reference_id = ?", (reference_id,))
    return True


def update_reference(reference_id: str, *, owner_user_id: str, name: str | None = None, notes: str | None = None) -> ReferenceSpectrum | None:
    ref = get_reference(reference_id, owner_user_id=owner_user_id)
    if ref is None:
        return None
    with connect() as con:
        con.execute(
            "UPDATE reference_spectra SET name = ?, notes = ? WHERE reference_id = ?",
            (str(name).strip() if name else ref.name, ref.notes if notes is None else str(notes), reference_id),
        )
    return get_reference_any(reference_id)

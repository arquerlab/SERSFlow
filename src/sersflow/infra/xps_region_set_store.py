"""Named survey region sets (X2): element-line windows picked from a survey, per user. Quantification (Q1) comes later."""

from __future__ import annotations

import csv
import io
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from sersflow.infra.sqlite_db import connect
from sersflow.infra.user_access import has_global_access, resolve_owner_user_id

_FIELDS = ("label", "element", "line", "be_eV", "be_min_eV", "be_max_eV")


@dataclass(frozen=True)
class RegionSet:
    set_id: str
    owner_user_id: str
    name: str
    notes: str
    regions: list[dict[str, Any]]
    source: dict[str, Any]
    created_at: str

    def public(self) -> dict[str, Any]:
        return {
            "set_id": self.set_id,
            "name": self.name,
            "notes": self.notes,
            "regions": self.regions,
            "n_regions": len(self.regions),
            "source": self.source,
            "created_at": self.created_at,
        }


def ensure_schema() -> None:
    with connect() as con:
        con.executescript(
            """
            CREATE TABLE IF NOT EXISTS xps_region_sets (
              set_id TEXT PRIMARY KEY,
              owner_user_id TEXT NOT NULL,
              name TEXT NOT NULL,
              notes TEXT NOT NULL DEFAULT '',
              regions_json TEXT NOT NULL,
              source_json TEXT NOT NULL,
              created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_xps_region_sets_owner ON xps_region_sets(owner_user_id, created_at DESC);
            """
        )


def clean_regions(regions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for i, r in enumerate(regions or []):
        try:
            lo, hi = float(r["be_min_eV"]), float(r["be_max_eV"])
        except (KeyError, TypeError, ValueError) as e:
            raise ValueError(f"region {i + 1}: be_min_eV and be_max_eV are required numbers") from e
        if not (hi > lo):
            raise ValueError(f"region {i + 1}: be_max_eV must be greater than be_min_eV")
        be = r.get("be_eV")
        clean = {k: r.get(k) for k in _FIELDS}
        clean["be_min_eV"], clean["be_max_eV"] = lo, hi
        clean["be_eV"] = float(be) if be is not None else (lo + hi) / 2.0
        clean["label"] = str(r.get("label") or f"{r.get('element', '')} {r.get('line', '')}".strip() or f"region {i + 1}")
        out.append(clean)
    if not out:
        raise ValueError("a region set needs at least one region")
    return out


def _row(r: Any) -> RegionSet:
    return RegionSet(
        set_id=r["set_id"],
        owner_user_id=r["owner_user_id"],
        name=r["name"],
        notes=r["notes"] or "",
        regions=json.loads(r["regions_json"]),
        source=json.loads(r["source_json"] or "{}"),
        created_at=r["created_at"],
    )


def create_region_set(
    *, owner_user_id: str, name: str, regions: list[dict[str, Any]], source: dict[str, Any] | None = None, notes: str = ""
) -> RegionSet:
    ensure_schema()
    name = str(name or "").strip()
    if not name:
        raise ValueError("name is required")
    cleaned = clean_regions(regions)
    sid = f"rs_{uuid4().hex}"
    with connect() as con:
        con.execute(
            "INSERT INTO xps_region_sets (set_id, owner_user_id, name, notes, regions_json, source_json, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                sid,
                resolve_owner_user_id(owner_user_id),
                name,
                str(notes or ""),
                json.dumps(cleaned),
                json.dumps(source or {}, default=str),
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        row = con.execute("SELECT * FROM xps_region_sets WHERE set_id = ?", (sid,)).fetchone()
    return _row(row)


def get_region_set(set_id: str, *, owner_user_id: str) -> RegionSet | None:
    ensure_schema()
    with connect() as con:
        r = con.execute("SELECT * FROM xps_region_sets WHERE set_id = ?", (set_id,)).fetchone()
    if r is None:
        return None
    rs = _row(r)
    if has_global_access(owner_user_id) or rs.owner_user_id == resolve_owner_user_id(owner_user_id):
        return rs
    return None


def list_region_sets(*, owner_user_id: str) -> list[RegionSet]:
    ensure_schema()
    with connect() as con:
        if has_global_access(owner_user_id):
            rows = con.execute("SELECT * FROM xps_region_sets ORDER BY created_at DESC").fetchall()
        else:
            rows = con.execute(
                "SELECT * FROM xps_region_sets WHERE owner_user_id = ? ORDER BY created_at DESC",
                (resolve_owner_user_id(owner_user_id),),
            ).fetchall()
    return [_row(r) for r in rows]


def delete_region_set(set_id: str, *, owner_user_id: str) -> bool:
    if get_region_set(set_id, owner_user_id=owner_user_id) is None:
        return False
    with connect() as con:
        con.execute("DELETE FROM xps_region_sets WHERE set_id = ?", (set_id,))
    return True


def region_set_csv(rs: RegionSet) -> str:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(["label", "element", "line", "be_eV", "be_min_eV", "be_max_eV", "width_eV"])
    for r in rs.regions:
        w.writerow(
            [r.get("label"), r.get("element"), r.get("line"), r["be_eV"], r["be_min_eV"], r["be_max_eV"],
             round(float(r["be_max_eV"]) - float(r["be_min_eV"]), 6)]
        )
    return buf.getvalue()

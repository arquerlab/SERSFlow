"""
Owner check for measured reference spectra named inside fit components (``reference_id``, M1).

The fitting engine loads a reference by id with no user context (it runs in worker processes), so the id has to
be checked where the request enters the API: before a pipeline is stored / run, and before a direct fit.
"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException

from sersflow.infra.reference_spectra_store import get_reference


def reference_ids_in(obj: Any) -> set[str]:
    """Every ``reference_id`` string found in nested dicts / lists (pipeline step params, fit components)."""
    found: set[str] = set()
    stack = [obj]
    while stack:
        cur = stack.pop()
        if isinstance(cur, dict):
            for key, val in cur.items():
                if key == "reference_id":
                    rid = str(val or "").strip()
                    if rid:
                        found.add(rid)
                elif isinstance(val, (dict, list, tuple)):
                    stack.append(val)
        elif isinstance(cur, (list, tuple)):
            stack.extend(v for v in cur if isinstance(v, (dict, list, tuple)))
    return found


def assert_references_visible(user_id: str, obj: Any) -> None:
    """404 when ``obj`` names a reference spectrum the caller cannot read (unknown ids read the same)."""
    for rid in sorted(reference_ids_in(obj)):
        if get_reference(rid, owner_user_id=user_id) is None:
            raise HTTPException(status_code=404, detail=f"Reference spectrum {rid!r} not found")


def assert_pipeline_references_visible(user_id: str, pipeline: Any) -> None:
    steps = getattr(pipeline, "steps", None) or []
    assert_references_visible(user_id, [getattr(s, "params", None) or {} for s in steps])

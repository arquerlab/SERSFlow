"""
Stable numeric ids for pipeline steps (used by metrics and analysis export).

Kept separate from ``engine`` to avoid import cycles (``steps`` → ``intensity_probes`` → this module).
"""

from __future__ import annotations

import logging
from typing import Any, Sequence

logger = logging.getLogger(__name__)


def _step_id_raw(step: Any) -> str | None:
    if isinstance(step, dict):
        sid = step.get("step_id")
    else:
        sid = getattr(step, "step_id", None)
    if sid is None:
        return None
    t = str(sid).strip()
    return t or None


def assign_pipeline_step_nums(steps_list: Sequence[Any]) -> list[int]:
    """
    Assign a stable short integer id to each pipeline step row for lookups and optional suffixing.

    - If step_id is set and is purely numeric (e.g. \"3\", \"12\"), that value is used.
    - Otherwise uses 1-based index in the pipeline list (j + 1).
    - Duplicate numbers are resolved by bumping the later step to the next free integer (with a warning).
    """
    used: set[int] = set()
    out: list[int] = []
    for j, step in enumerate(steps_list):
        raw = _step_id_raw(step)
        if raw is not None and raw.isdigit():
            n = int(raw)
        else:
            n = j + 1
        if n in used:
            n0 = n
            while n in used:
                n += 1
            logger.warning(
                "Duplicate pipeline step_num %s at index %s; renumbered to %s",
                n0,
                j,
                n,
            )
        used.add(n)
        out.append(n)
    return out

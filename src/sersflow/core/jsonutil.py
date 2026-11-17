"""Small helpers that used to be copied into many modules: timestamps, finite floats, CSV cells."""

from __future__ import annotations

import csv
import io
import math
from datetime import datetime, timezone
from typing import Any, Callable

import numpy as np


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def finite_or_none(v: Any) -> float | None:
    """``float(v)`` when it is a finite number, else None (None, text, NaN, inf)."""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def finite_list(a: np.ndarray | None) -> list[float | None] | None:
    """Array as a JSON-safe list: non-finite values become None. None stays None."""
    if a is None:
        return None
    return [float(v) if np.isfinite(v) else None for v in np.asarray(a, dtype=float)]


def csv_cell(v: Any) -> Any:
    """Empty cell for None and non-finite floats; everything else unchanged."""
    if v is None:
        return ""
    if isinstance(v, float) and not math.isfinite(v):
        return ""
    return v


def rows_to_csv_bytes(headers: list[str], rows: list[dict[str, Any]], fmt: Callable[[Any], Any] = csv_cell) -> bytes:
    """UTF-8 CSV of dict rows in ``headers`` order."""
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(headers)
    for r in rows:
        w.writerow([fmt(r.get(h)) for h in headers])
    return buf.getvalue().encode("utf-8")

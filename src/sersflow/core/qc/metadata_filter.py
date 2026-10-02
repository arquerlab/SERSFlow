"""Evaluate metadata / axis filter clauses for QC and Raw multi-block UIs."""

from __future__ import annotations

from typing import Any, Iterable, Mapping, Sequence


def _as_number(v: Any) -> float | None:
    if v is None or isinstance(v, bool):
        return None
    try:
        n = float(v)
    except (TypeError, ValueError):
        return None
    if n != n:  # NaN
        return None
    return n


def _clause_matches(row: Mapping[str, Any], clause: Mapping[str, Any]) -> bool:
    field = str(clause.get("field") or "").strip()
    if not field:
        return True
    op = str(clause.get("op") or "in").strip()
    raw = row.get(field)

    if op == "in":
        values = clause.get("values")
        if not isinstance(values, (list, tuple)) or not values:
            return False
        allowed = {str(v) for v in values}
        return str(raw) in allowed if raw is not None else False

    num = _as_number(raw)
    target = _as_number(clause.get("value"))
    if num is None or target is None:
        return False
    if op in {"=", "eq", "=="}:
        return num == target
    if op in {"!=", "ne"}:
        return num != target
    if op in {">", "gt"}:
        return num > target
    if op in {">=", "gte"}:
        return num >= target
    if op in {"<", "lt"}:
        return num < target
    if op in {"<=", "lte"}:
        return num <= target
    return False


def evaluate_filters(row: Mapping[str, Any], filters: Sequence[Mapping[str, Any]] | None) -> bool:
    """
    Return True if ``row`` matches all filter clauses (AND).

    Empty / None ``filters`` keeps the row.
    """
    if not filters:
        return True
    for clause in filters:
        if not isinstance(clause, Mapping):
            continue
        if not _clause_matches(row, clause):
            return False
    return True


def select_indices_matching(
    rows_by_index: Mapping[int, Mapping[str, Any]] | Iterable[tuple[int, Mapping[str, Any]]],
    *,
    filters: Sequence[Mapping[str, Any]] | None = None,
) -> list[int]:
    """Return indices whose row dicts pass ``evaluate_filters``."""
    if isinstance(rows_by_index, Mapping):
        items = list(rows_by_index.items())
    else:
        items = list(rows_by_index)
    return [i for i, row in items if evaluate_filters(row, filters)]

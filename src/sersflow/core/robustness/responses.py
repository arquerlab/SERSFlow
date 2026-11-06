"""Responses of a robustness study: quantities read from a fit, plus trend metrics against any x variable.

A response spec is a dict ``{"name": str, "kind": ..., ...}``:

* ``area_pct``   ``{component_id}``               share of the fit's total peak area (%)
* ``area``       ``{component_id}``               peak area
* ``param``      ``{component_id, key}``          a fitted parameter: ``pos`` (position), ``fwhm``, ``amp``, ``m``, ...
* ``group_fraction`` ``{numerator: [ids], denominator: [ids]?}``  sum(area of numerator) / sum(area of denominator)
                  (denominator default = all area-exporting peaks), e.g. Co3+/(Co2+ + Co3+)
* ``ratio``      ``{numerator: spec, denominator: spec}``  ratio of two responses
* ``difference`` ``{a: spec, b: spec}``           a - b

Specs of ``ratio`` / ``difference`` may be the NAME of another response in the same list or an inline spec.
Everything is evaluated from ``(mapping, p)`` of a fit, so the noise Monte Carlo (parameter vectors) uses the same code.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np

from sersflow.core.metrics.fit_uncertainty import area_percentages, component_areas

KINDS = {"area_pct", "area", "param", "group_fraction", "ratio", "difference"}


class ResponseError(ValueError):
    pass


def validate_responses(specs: Any) -> list[dict[str, Any]]:
    if not isinstance(specs, list) or not specs:
        raise ResponseError("at least one response is needed")
    names: set[str] = set()
    out: list[dict[str, Any]] = []
    for s in specs:
        if not isinstance(s, dict):
            raise ResponseError("response specs must be objects")
        name = str(s.get("name") or "").strip()
        if not name:
            raise ResponseError("every response needs a name")
        if name in names:
            raise ResponseError(f"duplicate response name {name!r}")
        names.add(name)
        kind = s.get("kind")
        if kind not in KINDS:
            raise ResponseError(f"response {name!r}: unknown kind {kind!r}; known: {sorted(KINDS)}")
        if kind in ("area_pct", "area") and not s.get("component_id"):
            raise ResponseError(f"response {name!r} needs component_id")
        if kind == "param" and not (s.get("component_id") and s.get("key")):
            raise ResponseError(f"response {name!r} needs component_id and key")
        if kind == "group_fraction" and not s.get("numerator"):
            raise ResponseError(f"response {name!r} needs numerator (list of component ids)")
        if kind == "ratio" and not (s.get("numerator") is not None and s.get("denominator") is not None):
            raise ResponseError(f"response {name!r} needs numerator and denominator")
        if kind == "difference" and not (s.get("a") is not None and s.get("b") is not None):
            raise ResponseError(f"response {name!r} needs a and b")
        out.append(dict(s))
    return out


def _fin(v: float | None) -> float | None:
    if v is None:
        return None
    f = float(v)
    return f if math.isfinite(f) else None


def _component_index(mapping: list[dict[str, Any]], cid: str) -> int:
    for i, m in enumerate(mapping):
        if str(m.get("component_id")) == str(cid):
            return i
    raise ResponseError(f"component {cid!r} not in the fit (has: {[m.get('component_id') for m in mapping]})")


def _param(mapping: list[dict[str, Any]], p: np.ndarray, cid: str, key: str) -> float | None:
    m = mapping[_component_index(mapping, cid)]
    keys = list(m.get("param_keys") or [])
    if key not in keys:
        raise ResponseError(f"component {cid!r} has no parameter {key!r} (has: {keys})")
    s, _e = m["index_range"]
    return _fin(float(np.asarray(p, dtype=float)[int(s) + keys.index(key)]))


def evaluate_one(
    spec: dict[str, Any],
    mapping: list[dict[str, Any]],
    p: np.ndarray,
    *,
    by_name: dict[str, dict[str, Any]],
    _depth: int = 0,
) -> float | None:
    if _depth > 6:
        raise ResponseError("response nesting too deep")
    kind = spec["kind"]
    areas = None
    if kind in ("area_pct", "area", "group_fraction"):
        areas = component_areas(mapping, np.asarray(p, dtype=float))
    if kind == "area":
        a = areas[_component_index(mapping, spec["component_id"])]
        return _fin(a)
    if kind == "area_pct":
        pct = area_percentages(areas)
        return _fin(pct[_component_index(mapping, spec["component_id"])])
    if kind == "param":
        return _param(mapping, p, str(spec["component_id"]), str(spec["key"]))
    if kind == "group_fraction":
        num_ids = [str(i) for i in spec["numerator"]]
        den = spec.get("denominator")
        num = 0.0
        for cid in num_ids:
            a = areas[_component_index(mapping, cid)]
            if a is None or not math.isfinite(a):
                return None
            num += float(a)
        if den:
            tot = 0.0
            for cid in den:
                a = areas[_component_index(mapping, str(cid))]
                if a is None or not math.isfinite(a):
                    return None
                tot += float(a)
        else:
            tot = float(sum(a for a in areas if a is not None and math.isfinite(a)))
        return _fin(num / tot) if tot else None

    def sub(ref: Any) -> float | None:
        s = by_name.get(ref) if isinstance(ref, str) else ref
        if s is None:
            raise ResponseError(f"unknown response reference {ref!r}")
        return evaluate_one(s, mapping, p, by_name=by_name, _depth=_depth + 1)

    if kind == "ratio":
        n, d = sub(spec["numerator"]), sub(spec["denominator"])
        return _fin(n / d) if n is not None and d not in (None, 0.0) else None
    if kind == "difference":
        a, b = sub(spec["a"]), sub(spec["b"])
        return _fin(a - b) if a is not None and b is not None else None
    raise ResponseError(f"unknown kind {kind!r}")


def evaluate_responses(specs: list[dict[str, Any]], mapping: list[dict[str, Any]], p: np.ndarray) -> dict[str, float | None]:
    by_name = {s["name"]: s for s in specs}
    out: dict[str, float | None] = {}
    for s in specs:
        try:
            out[s["name"]] = evaluate_one(s, mapping, p, by_name=by_name)
        except ResponseError:
            out[s["name"]] = None  # component absent in this variant (e.g. a dropped satellite)
    return out


# --------------------------------------------------------------------------------------------------------------
# trend metrics
# --------------------------------------------------------------------------------------------------------------

def _rank(a: np.ndarray) -> np.ndarray:
    order = np.argsort(a, kind="mergesort")
    r = np.empty(a.size, dtype=float)
    r[order] = np.arange(a.size, dtype=float)
    # average ranks for ties
    _u, inv, counts = np.unique(a, return_inverse=True, return_counts=True)
    sums = np.zeros(counts.size)
    np.add.at(sums, inv, r)
    return (sums / counts)[inv]


def spearman(x: np.ndarray, y: np.ndarray) -> float | None:
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    ok = np.isfinite(x) & np.isfinite(y)
    if ok.sum() < 3:
        return None
    rx, ry = _rank(x[ok]), _rank(y[ok])
    if np.std(rx) == 0 or np.std(ry) == 0:
        return None
    return float(np.corrcoef(rx, ry)[0, 1])


def linear_slope(x: np.ndarray, y: np.ndarray) -> float | None:
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    ok = np.isfinite(x) & np.isfinite(y)
    if ok.sum() < 3 or np.ptp(x[ok]) == 0:
        return None
    return float(np.polyfit(x[ok], y[ok], 1)[0])


def trend_metrics(x: np.ndarray, y: np.ndarray) -> dict[str, float | None]:
    """Spearman rho and the sign of the linear slope of y against x."""
    rho = spearman(x, y)
    slope = linear_slope(x, y)
    return {"spearman": rho, "slope": slope, "sign": None if slope is None else float(np.sign(slope))}

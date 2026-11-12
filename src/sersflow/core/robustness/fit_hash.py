"""Canonical description and hashes of what the optimizer receives (``FitProblem``).

The patch-effect check compares optimizer INPUTS, never responses: a factor level whose ``FitProblem`` equals the
nominal one is inert (a bug), whereas a level that changes the input but hardly moves the response is merely
insensitive (a finding).

Three hashes
    ``data_hash``    fit-window x / y / sigma arrays and the weighting actually applied;
    ``config_hash``  model + parameters + settings, EXCLUDING the initial value of free parameters;
    ``start_hash``   the same INCLUDING initial values (and the settings that only seed the start).

``config_hash`` equal but ``start_hash`` different means the level only moves a start value. With multi-start jitter
that is not a model choice (``start_only``).

Rules (stable across processes and machines): SHA-256 over canonical JSON (sorted keys, no whitespace); floats are
rounded to 12 significant digits before hashing; arrays are hashed as float64 rounded to 12 significant digits plus
their shape. Python's ``hash()`` is never used.
"""

from __future__ import annotations

import hashlib
import json
import math
from typing import Any

import numpy as np

from sersflow.core.preprocess.fitting import FitProblem
from sersflow.core.preprocess.fitting_specs import component_param_specs

SIG_DIGITS = 12
FINGERPRINT_VERSION = 1


def round_sig(v: float, digits: int = SIG_DIGITS) -> float | str:
    """Round to ``digits`` significant digits; non-finite values become the strings 'nan' / 'inf' / '-inf'."""
    f = float(v)
    if math.isnan(f):
        return "nan"
    if math.isinf(f):
        return "inf" if f > 0 else "-inf"
    if f == 0.0:
        return 0.0
    return float(f"{f:.{digits - 1}e}")


def normalise(obj: Any) -> Any:
    """JSON-able copy with floats rounded, numpy scalars unwrapped, tuples as lists."""
    if isinstance(obj, bool) or obj is None or isinstance(obj, str):
        return obj
    if isinstance(obj, (int, np.integer)):
        return int(obj)
    if isinstance(obj, (float, np.floating)):
        return round_sig(float(obj))
    if isinstance(obj, np.ndarray):
        return array_digest(obj)
    if isinstance(obj, dict):
        return {str(k): normalise(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [normalise(v) for v in obj]
    return str(obj)


def canonical_json(obj: Any) -> str:
    return json.dumps(normalise(obj), sort_keys=True, separators=(",", ":"))


def sha256_hex(obj: Any) -> str:
    return hashlib.sha256(canonical_json(obj).encode("utf-8")).hexdigest()


def array_digest(a: Any) -> dict[str, Any]:
    """Shape plus a SHA-256 of the float64 values rounded to 12 significant digits (text form, platform independent)."""
    arr = np.asarray(a, dtype=np.float64)
    text = ",".join(f"{v:.{SIG_DIGITS - 1}e}" if np.isfinite(v) else str(float(v)) for v in arr.ravel())
    return {"shape": list(arr.shape), "sha256": hashlib.sha256(text.encode("ascii")).hexdigest()}


def data_hash_of(x: Any, y: Any, sigma: Any = None, weighting: str = "none") -> str:
    return sha256_hex(
        {"x": array_digest(x), "y": array_digest(y), "sigma": None if sigma is None else array_digest(sigma), "weighting": weighting}
    )


def _link_index(links: list[dict[str, Any]] | None) -> dict[tuple[str, str], dict[str, Any]]:
    out: dict[tuple[str, str], dict[str, Any]] = {}
    for lk in links or []:
        out[(str(lk.get("source_component_id")), str(lk.get("source_key")))] = dict(lk)
    return out


def problem_canonical(problem: FitProblem) -> dict[str, Any]:
    """JSON-serialisable description of the optimizer input, split into config and start parts.

    Per parameter: a linked (``param_links``) parameter records only its link (its own value and bounds are ignored
    by the optimizer); a fixed one only its value; a free one its bounds (config) and its initial value (start).
    """
    comps = problem.components
    p0, lo, hi = problem.p0, problem.bounds_lower, problem.bounds_upper
    vary = problem.vary if problem.vary is not None else [True] * len(p0)
    links = _link_index(problem.param_links)
    params: list[dict[str, Any]] = []
    off = 0
    for c in comps:
        keys = [s.key for s in component_param_specs(c.component_type, degree=c.degree)]
        for j, key in enumerate(keys):
            i = off + j
            row: dict[str, Any] = {"component_id": c.component_id, "key": key}
            lk = links.get((c.component_id, key))
            if lk is not None:
                row["link"] = {k: v for k, v in lk.items() if k not in ("value",)}
            elif not bool(vary[i]):
                row["fixed"] = float(p0[i])
            else:
                row["free"] = True
                row["min"] = None if lo[i] is None else float(lo[i])
                row["max"] = None if hi[i] is None else float(hi[i])
                row["init"] = float(p0[i])
            params.append(row)
        off += len(keys)
    model = [
        {"component_id": c.component_id, "type": c.component_type, "degree": c.degree, "options": c.options or {}}
        for c in comps
    ]
    return {
        "model": model,
        "params": params,
        "settings": {
            "technique_family": problem.technique_family,
            "xps_region": problem.xps_region,
            "weighting": problem.weighting,
        },
        # Only seed the starting amplitudes / values; they never change the optimum of a well-posed fit.
        "start_settings": {
            "initial_guess_mode": problem.initial_guess_mode,
            "initial_area_ratios": problem.initial_area_ratios,
        },
    }


def _strip_init(canon: dict[str, Any]) -> dict[str, Any]:
    params = [{k: v for k, v in row.items() if k != "init"} for row in canon["params"]]
    return {"model": canon["model"], "params": params, "settings": canon["settings"]}


def fingerprint(problem: FitProblem) -> dict[str, Any]:
    """Hashes and window summary of one prepared fit."""
    canon = problem_canonical(problem)
    x = np.asarray(problem.x, dtype=float)
    return {
        "version": FINGERPRINT_VERSION,
        "config_hash": sha256_hex(_strip_init(canon)),
        "start_hash": sha256_hex({"config": _strip_init(canon), "init": canon["params"], "start": canon["start_settings"]}),
        "data_hash": data_hash_of(problem.x, problem.y, problem.sigma, problem.weighting),
        "n_points": int(x.size),
        "x_min": float(x.min()) if x.size else None,
        "x_max": float(x.max()) if x.size else None,
    }


def xy_fingerprint(xy: Any) -> dict[str, Any]:
    """Fingerprint of a pre-fit spectrum (before the fit window), for the upstream-effect check."""
    x = np.asarray(xy.x, dtype=float)
    y = np.asarray(xy.y, dtype=float)
    return {
        "n_points": int(x.size),
        "x_min": float(x.min()) if x.size else None,
        "x_max": float(x.max()) if x.size else None,
        "data_hash": data_hash_of(x, y),
    }

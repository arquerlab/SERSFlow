"""Factor / response templates for a robustness study (data generated from the run's own fitting step).

A preset only PROPOSES a study spec - factors with levels, default responses, the x variable - from the nominal
fitting step (and pipeline). The user can edit it before running. Levels are anchored on the nominal settings (first
level of every factor = nominal = what the analyst originally chose), and every constant (window offset, mix offset,
alternative backgrounds, baseline methods) is an option, so nothing is hard-wired to one technique or dataset.

Presets
    ``fit_model_choices``  background type, fit window, line-shape mix, FWHM constraint (any fitting step)
    ``baseline_method``    the method of an upstream ``baseline`` step (any technique)

Responses proposed by default: the area share (%) of every peak of the fit.
"""

from __future__ import annotations

from typing import Any

from sersflow.core.preprocess.fitting import parse_fit_window
from sersflow.core.robustness.patches import _keys, _n_params, is_background_type

PRESETS = {
    "fit_model_choices": "Background type, fit window, line-shape mix and FWHM constraint of the fitting step.",
    "baseline_method": "Method of an upstream baseline step (pipeline step named 'baseline').",
}

_XPS_BACKGROUNDS = ("shirley_bg", "tougaard_u4_bg", "linear_bg")
_VIB_BACKGROUND_DEGREES = (1, 2, 3)
_MIX_KEYS = {"gl": "m", "sgl": "m", "gl_gauss": "m", "a_gl": "m", "pseudo_voigt": "eta"}


def _peaks(step_params: dict[str, Any]) -> list[dict[str, Any]]:
    return [c for c in (step_params.get("components") or []) if not is_background_type(str(c.get("component_type")))]


def default_responses(step_params: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {"name": f"{c['component_id']}_area_pct", "kind": "area_pct", "component_id": str(c["component_id"])}
        for c in _peaks(step_params)
        if str(c.get("component_type", "")).strip().lower() not in ("ds", "gds")
    ]


def _background_factor(step_params: dict[str, Any], opts: dict[str, Any]) -> dict[str, Any] | None:
    comps = step_params.get("components") or []
    bgs = [c for c in comps if is_background_type(str(c.get("component_type")))]
    if len(bgs) != 1:
        return None  # none to swap, or several (ambiguous): left to a hand-written factor
    cur = bgs[0]
    cur_type = str(cur["component_type"]).strip().lower()
    cid = str(cur["component_id"])
    xps = str(step_params.get("technique_family") or "").lower() in ("xps", "xas")
    levels: list[dict[str, Any]] = [{"name": f"{cur_type}" + (f"_deg{cur.get('degree')}" if cur.get("degree") is not None else ""), "patches": []}]
    if xps:
        for t in opts.get("backgrounds") or _XPS_BACKGROUNDS:
            if str(t).lower() != cur_type:
                levels.append(
                    {"name": str(t), "patches": [{"op": "swap_component_type", "select": {"component_ids": [cid]}, "new_type": str(t)}]}
                )
    else:
        for d in opts.get("polynomial_degrees") or _VIB_BACKGROUND_DEGREES:
            if cur_type == "polynomial_background" and cur.get("degree") == d:
                continue
            levels.append(
                {
                    "name": f"polynomial_deg{d}",
                    "patches": [
                        {"op": "swap_component_type", "select": {"component_ids": [cid]}, "new_type": "polynomial_background", "degree": int(d)}
                    ],
                }
            )
    if len(levels) < 2:
        return None
    return {"name": "background", "description": "Background model", "levels": levels}


def _window_factor(step_params: dict[str, Any], opts: dict[str, Any]) -> dict[str, Any] | None:
    lo, hi = parse_fit_window(step_params)
    if lo is None or hi is None:
        return None  # no explicit window to widen / narrow
    delta = float(opts.get("window_delta") or 0.05 * (hi - lo))
    if delta <= 0 or hi - lo <= 2 * delta:
        return None
    return {
        "name": "window",
        "description": f"Fit window edges moved by {delta:g} (x units)",
        "levels": [
            {"name": f"nominal[{lo:g},{hi:g}]", "patches": []},
            {"name": f"wide[{lo - delta:g},{hi + delta:g}]", "patches": [
                {"op": "set_step_param", "key": "fit_min_x", "value": lo - delta},
                {"op": "set_step_param", "key": "fit_max_x", "value": hi + delta},
            ]},
            {"name": f"narrow[{lo + delta:g},{hi - delta:g}]", "patches": [
                {"op": "set_step_param", "key": "fit_min_x", "value": lo + delta},
                {"op": "set_step_param", "key": "fit_max_x", "value": hi - delta},
            ]},
        ],
    }


def _mix_factor(step_params: dict[str, Any], opts: dict[str, Any]) -> dict[str, Any] | None:
    comps = step_params.get("components") or []
    by_type: dict[str, list[dict[str, Any]]] = {}
    for c in comps:
        t = str(c.get("component_type") or "").strip().lower()
        if t in _MIX_KEYS and _MIX_KEYS[t] in _keys(c):
            by_type.setdefault(t, []).append(c)
    if len(by_type) != 1:
        return None  # one mixing parameter family at a time keeps the level meaning clear
    t = next(iter(by_type))
    key = _MIX_KEYS[t]
    scale = 100.0 if key == "m" else 1.0
    delta = float(opts.get("mix_delta") or (10.0 if key == "m" else 0.1))
    lo_cap, hi_cap = (0.0, 100.0) if key == "m" else (0.0, 1.0)
    # nominal value from the first peak (its p0)
    off, nominal = 0, None
    for c in comps:
        if c is by_type[t][0]:
            nominal = float(step_params["p0"][off + _keys(c).index(key)])
            break
        off += _n_params(c)
    if nominal is None:
        return None
    sel = {"component_type": t}
    levels = [{"name": f"{key}=as_recipe", "patches": []}]
    for v in (nominal - delta, nominal + delta):
        v = min(max(v, lo_cap), hi_cap)
        if abs(v - nominal) < 1e-9:
            continue
        levels.append(
            {"name": f"{key}={v:g}(fixed)", "patches": [{"op": "set_component_param", "select": sel, "key": key, "value": v, "vary": False}]}
        )
    if len(levels) < 2:
        return None
    return {"name": "lineshape_mix", "description": f"{t} mixing parameter '{key}' fixed at nominal +/- {delta:g}", "levels": levels}


def _fwhm_factor(step_params: dict[str, Any], opts: dict[str, Any]) -> dict[str, Any] | None:
    peaks = [c for c in _peaks(step_params) if "fwhm" in _keys(c)]
    if len(peaks) < 2:
        return None
    linked = any(str(lk.get("source_key")) == "fwhm" for lk in (step_params.get("param_links") or []))
    sel = {"component_ids": [str(c["component_id"]) for c in peaks]}
    # Which widths are free in the nominal fit? (flat index bookkeeping)
    vary = list(step_params.get("vary") or [])
    free_fwhm = False
    off = 0
    for c in step_params.get("components") or []:
        keys = _keys(c)
        if "fwhm" in keys and not is_background_type(str(c.get("component_type"))):
            free_fwhm = free_fwhm or (not vary or bool(vary[off + keys.index("fwhm")]))
        off += _n_params(c)
    if not linked and not free_fwhm:
        # Recipe-style fit: widths fixed at literature values. The analyst choice is how much freedom they get.
        rel = float(opts.get("fwhm_free_rel") or 0.3)
        return {
            "name": "fwhm_constraint",
            "description": f"FWHM fixed at the recipe values vs free within +/-{rel:.0%} of them",
            "levels": [
                {"name": "fixed_as_recipe", "patches": []},
                {
                    "name": f"free_pm{rel:.0%}",
                    "patches": [
                        {"op": "set_component_param", "select": sel, "key": "fwhm", "vary": True, "lower_rel": 1.0 - rel, "upper_rel": 1.0 + rel}
                    ],
                },
            ],
        }
    if linked:
        return {
            "name": "fwhm_constraint",
            "description": "FWHM links as in the recipe vs fully free",
            "levels": [
                {"name": "as_recipe", "patches": []},
                {"name": "free", "patches": [{"op": "untie_param", "select": sel, "key": "fwhm"}]},
            ],
        }
    return {
        "name": "fwhm_constraint",
        "description": "FWHM free per peak vs one shared FWHM",
        "levels": [
            {"name": "free", "patches": []},
            {"name": "tied", "patches": [{"op": "tie_param", "select": sel, "key": "fwhm"}]},
        ],
    }


def _satellite_factor(step_params: dict[str, Any], opts: dict[str, Any]) -> dict[str, Any] | None:
    """Satellites locked to a main peak by an ``area_ratio`` link (recipe style): locked / unlocked / absent."""
    links = [
        lk
        for lk in (step_params.get("param_links") or [])
        if str(lk.get("mode")) == "area_ratio" and str(lk.get("source_key")) == "amp"
    ]
    ids = sorted({str(lk["source_component_id"]) for lk in links})
    comps = step_params.get("components") or []
    if not ids or len(ids) >= len([c for c in comps if not is_background_type(str(c.get("component_type")))]):
        return None
    sel = {"component_ids": ids}
    return {
        "name": "satellite_treatment",
        "description": f"Components {ids} are area-ratio locked to a main peak",
        "levels": [
            {"name": "locked_as_recipe", "patches": []},
            {"name": "unlocked", "patches": [{"op": "untie_param", "select": sel, "key": "amp"}]},
            {"name": "absent", "patches": [{"op": "drop_components", "select": sel}]},
        ],
    }


def fit_model_choices(step_params: dict[str, Any], opts: dict[str, Any] | None = None) -> dict[str, Any]:
    opts = dict(opts or {})
    notes: list[str] = []
    factors = []
    for name, fn in (
        ("background", _background_factor),
        ("window", _window_factor),
        ("lineshape_mix", _mix_factor),
        ("fwhm_constraint", _fwhm_factor),
        ("satellite_treatment", _satellite_factor),
    ):
        f = fn(step_params, opts)
        if f is None:
            notes.append(f"factor '{name}' not generated for this fitting step (not applicable or ambiguous)")
        else:
            factors.append(f)
    return {
        "factors": factors,
        "responses": default_responses(step_params),
        "notes": notes + [
            "Level 1 of every factor is the nominal setting. Review every level: a level nobody would choose inflates the spread.",
        ],
    }


def baseline_method(pipeline: Any, opts: dict[str, Any] | None = None) -> dict[str, Any]:
    from sersflow.core.preprocess.baseline import BASELINE_METHODS

    opts = dict(opts or {})
    steps = list(getattr(pipeline, "steps", []) or [])
    idxs = [i for i, s in enumerate(steps) if getattr(s, "name", None) == "baseline" and getattr(s, "enabled", True)]
    if not idxs:
        raise ValueError("the pipeline has no enabled 'baseline' step")
    occ = int(opts.get("occurrence") or 1)
    if not 1 <= occ <= len(idxs):
        raise ValueError(f"baseline occurrence {occ} out of range 1..{len(idxs)}")
    step = steps[idxs[occ - 1]]
    cur = str((step.params or {}).get("method", "derpsalsa"))
    methods = [str(m) for m in (opts.get("methods") or [cur, "asls", "arpls", "airpls", "modpoly"])]
    seen: list[str] = []
    for m in methods:
        if m in seen:
            continue
        if m not in BASELINE_METHODS:
            raise ValueError(f"unknown baseline method {m!r}")
        seen.append(m)
    if cur not in seen:
        seen.insert(0, cur)
    # Nominal (current) first.
    seen.sort(key=lambda m: m != cur)
    target = {"step_name": "baseline", "occurrence": occ}
    levels = [
        {"name": m, "patches": [] if m == cur else [{"op": "set_step_param", "target": target, "key": "method", "value": m}]}
        for m in seen
    ]
    if len(levels) < 2:
        raise ValueError("need at least two baseline methods")
    return {
        "factors": [{"name": "baseline_method", "description": "Upstream baseline algorithm (library defaults of each method)", "levels": levels}],
        "responses": [],
        "notes": ["Methods other than the nominal one run with their library defaults for method-specific parameters."],
    }


def build_preset(name: str, *, step_params: dict[str, Any], pipeline: Any, opts: dict[str, Any] | None = None) -> dict[str, Any]:
    if name == "fit_model_choices":
        return fit_model_choices(step_params, opts)
    if name == "baseline_method":
        out = baseline_method(pipeline, opts)
        out["responses"] = default_responses(step_params)
        return out
    raise ValueError(f"unknown preset {name!r}; known: {sorted(PRESETS)}")

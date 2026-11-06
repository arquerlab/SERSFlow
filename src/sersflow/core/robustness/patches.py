"""Pure patches of pipeline-step parameters; a factor level is a list of patches.

A patch is a dict with an ``op`` and an optional ``target`` selecting the pipeline step:

* absent / ``{"step": "fit"}``: the fitting step under study;
* ``{"step_id": "..."}``, ``{"step_index": N}`` or ``{"step_name": "baseline", "occurrence": 1}``: any other
  pipeline step (an UPSTREAM step: baseline, smoothing, normalisation, ...).

Operations on any step
    ``set_step_param``      ``{key, value}`` (dotted key reaches nested dicts)
    ``set_step_enabled``    ``{enabled}``
    ``replace_step_params`` ``{params}`` (e.g. a full recipe-generated parameter set)

Operations on the fitting step only
    ``set_component_param`` ``{select, key, value?, vary?, lower?, upper?, lower_rel?, upper_rel?}`` p0 / vary /
                            bounds of a parameter (``*_rel``: bound = factor x the parameter's own p0)
    ``swap_component_type`` ``{select, new_type, degree?, p0?}`` replace e.g. the background by another type
    ``drop_components``     ``{select}`` remove components (and their links), e.g. a satellite
    ``tie_param``           ``{select, key, mode?, driver?}`` link ``key`` of the selected components to the first
    ``untie_param``         ``{select?, key}`` remove links whose dependent parameter is ``key``

``select`` is ``{"component_ids": [...]}``, ``{"component_type": "gl"}`` (or a list), ``{"role": "peaks" |
"background" | "all"}``; several keys are ANDed.
"""

from __future__ import annotations

import copy
import json
from typing import Any

from sersflow.core.preprocess.fitting_specs import component_param_specs

FIT = "fit"

_FIT_ONLY_OPS = {
    "set_component_param",
    "swap_component_type",
    "drop_components",
    "tie_param",
    "untie_param",
}
_ANY_STEP_OPS = {"set_step_param", "set_step_enabled", "replace_step_params"}
KNOWN_OPS = _FIT_ONLY_OPS | _ANY_STEP_OPS


def is_background_type(component_type: str) -> bool:
    ct = str(component_type or "").strip().lower()
    return ct.endswith("_bg") or ct in {"polynomial_background", "linear_bg"}


def _norm_target(patch: dict[str, Any]) -> dict[str, Any]:
    t = patch.get("target")
    if t in (None, "", FIT):
        return {"step": FIT}
    if isinstance(t, str):
        return {"step_id": t}
    if isinstance(t, dict):
        return dict(t) if t else {"step": FIT}
    raise ValueError(f"invalid patch target: {t!r}")


def is_fit_patch(patch: dict[str, Any]) -> bool:
    return _norm_target(patch).get("step") == FIT


def validate_patch(patch: dict[str, Any]) -> None:
    if not isinstance(patch, dict):
        raise ValueError(f"patch must be an object, got {type(patch).__name__}")
    op = patch.get("op")
    if op not in KNOWN_OPS:
        raise ValueError(f"unknown patch op {op!r}; known: {sorted(KNOWN_OPS)}")
    if op in _FIT_ONLY_OPS and not is_fit_patch(patch):
        raise ValueError(f"patch op {op!r} only applies to the fitting step")
    if op == "set_step_param" and not str(patch.get("key") or "").strip():
        raise ValueError("set_step_param needs a key")
    if op == "set_step_enabled" and "enabled" not in patch:
        raise ValueError("set_step_enabled needs 'enabled'")
    if op == "replace_step_params" and not isinstance(patch.get("params"), dict):
        raise ValueError("replace_step_params needs a params object")
    if op in ("set_component_param", "tie_param", "untie_param") and not str(patch.get("key") or "").strip():
        raise ValueError(f"{op} needs a key")
    if op == "swap_component_type" and not str(patch.get("new_type") or "").strip():
        raise ValueError("swap_component_type needs new_type")


def canonical(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)


# --------------------------------------------------------------------------------------------------------------
# component selection and vector bookkeeping
# --------------------------------------------------------------------------------------------------------------

def _n_params(comp: dict[str, Any]) -> int:
    deg = comp.get("degree")
    return len(component_param_specs(str(comp.get("component_type") or ""), degree=int(deg) if deg is not None else None))


def _keys(comp: dict[str, Any]) -> list[str]:
    deg = comp.get("degree")
    return [p.key for p in component_param_specs(str(comp.get("component_type") or ""), degree=int(deg) if deg is not None else None)]


def _offsets(components: list[dict[str, Any]]) -> list[int]:
    out, off = [], 0
    for c in components:
        out.append(off)
        off += _n_params(c)
    return out


def select_components(components: list[dict[str, Any]], select: dict[str, Any] | None) -> list[int]:
    """Indices of the components matched by ``select`` (all keys ANDed); raises when nothing matches."""
    sel = dict(select or {})
    ids = sel.get("component_ids")
    ctype = sel.get("component_type")
    role = str(sel.get("role") or "all").strip().lower()
    types = None
    if ctype is not None:
        types = {str(t).strip().lower() for t in (ctype if isinstance(ctype, (list, tuple)) else [ctype])}
    idset = None if ids is None else {str(i) for i in ids}
    out: list[int] = []
    for i, c in enumerate(components):
        ct = str(c.get("component_type") or "").strip().lower()
        if idset is not None and str(c.get("component_id")) not in idset:
            continue
        if types is not None and ct not in types:
            continue
        if role == "background" and not is_background_type(ct):
            continue
        if role == "peaks" and is_background_type(ct):
            continue
        out.append(i)
    if not out:
        raise ValueError(f"patch selector matched no component: {select}")
    return out


def _vectors(params: dict[str, Any]) -> tuple[list[Any], list[Any], list[Any], list[bool]]:
    comps = params.get("components") or []
    n = sum(_n_params(c) for c in comps)
    p0 = list(params.get("p0") or [])
    lo = list(params.get("bounds_lower") or [None] * n)
    hi = list(params.get("bounds_upper") or [None] * n)
    vary = [bool(v) for v in (params.get("vary") or [True] * n)]
    if not (len(p0) == len(lo) == len(hi) == len(vary) == n):
        raise ValueError("fitting step has inconsistent p0 / bounds / vary lengths")
    return p0, lo, hi, vary


def _default_vectors(comp: dict[str, Any], p0_override: dict[str, float] | None) -> tuple[list, list, list, list]:
    deg = comp.get("degree")
    specs = component_param_specs(str(comp["component_type"]), degree=int(deg) if deg is not None else None)
    p0, lo, hi, vary = [], [], [], []
    for s in specs:
        v = (p0_override or {}).get(s.key, s.default if s.default is not None else 0.0)
        p0.append(float(v))
        lo.append(s.lower_default)
        hi.append(s.upper_default)
        vary.append(bool((s.ui or {}).get("vary_default", True)))
    return p0, lo, hi, vary


# --------------------------------------------------------------------------------------------------------------
# fit-step operations
# --------------------------------------------------------------------------------------------------------------

def _op_set_component_param(params: dict[str, Any], patch: dict[str, Any]) -> None:
    comps = params.get("components") or []
    p0, lo, hi, vary = _vectors(params)
    key = str(patch["key"])
    offs = _offsets(comps)
    hit = False
    for ci in select_components(comps, patch.get("select")):
        keys = _keys(comps[ci])
        if key not in keys:
            continue
        i = offs[ci] + keys.index(key)
        hit = True
        if "value" in patch:
            p0[i] = float(patch["value"])
            v = float(patch["value"])
            if lo[i] is not None and "lower" not in patch:
                lo[i] = min(float(lo[i]), v)
            if hi[i] is not None and "upper" not in patch:
                hi[i] = max(float(hi[i]), v)
        if "vary" in patch:
            vary[i] = bool(patch["vary"])
        if "lower" in patch:
            lo[i] = None if patch["lower"] is None else float(patch["lower"])
        if "upper" in patch:
            hi[i] = None if patch["upper"] is None else float(patch["upper"])
        # Bounds relative to the (possibly just set) p0 of this very parameter, e.g. lower_rel 0.7 = 70 % of p0.
        if "lower_rel" in patch:
            lo[i] = float(patch["lower_rel"]) * float(p0[i])
        if "upper_rel" in patch:
            hi[i] = float(patch["upper_rel"]) * float(p0[i])
    if not hit:
        raise ValueError(f"no selected component has parameter {key!r}")
    params.update({"p0": p0, "bounds_lower": lo, "bounds_upper": hi, "vary": vary})


def _drop_links_touching(params: dict[str, Any], removed_ids: set[str]) -> None:
    links = params.get("param_links") or []
    kept = []
    for lk in links:
        touched = {str(lk.get("source_component_id") or ""), str(lk.get("target_component_id") or "")}
        expr = str(lk.get("expr") or "")
        if touched & removed_ids or any("{" + rid + "." in expr for rid in removed_ids):
            continue
        kept.append(lk)
    params["param_links"] = kept


def _op_swap_component_type(params: dict[str, Any], patch: dict[str, Any]) -> None:
    comps = [dict(c) for c in (params.get("components") or [])]
    p0, lo, hi, vary = _vectors(params)
    offs = _offsets(comps)
    new_type = str(patch["new_type"]).strip()
    idxs = select_components(comps, patch.get("select"))
    # Replace from the back so earlier offsets stay valid.
    removed: set[str] = set()
    for ci in sorted(idxs, reverse=True):
        old = comps[ci]
        n_old = _n_params(old)
        new = {"component_id": old.get("component_id"), "component_type": new_type}
        if patch.get("degree") is not None:
            new["degree"] = int(patch["degree"])
        for k, v in (patch.get("options") or {}).items():
            new[k] = v
        np0, nlo, nhi, nvary = _default_vectors(new, patch.get("p0"))
        s = offs[ci]
        p0[s : s + n_old] = np0
        lo[s : s + n_old] = nlo
        hi[s : s + n_old] = nhi
        vary[s : s + n_old] = nvary
        comps[ci] = new
        removed.add(str(old.get("component_id")))
        offs = _offsets(comps)
    params.update({"components": comps, "p0": p0, "bounds_lower": lo, "bounds_upper": hi, "vary": vary})
    _drop_links_touching(params, removed)


def _op_drop_components(params: dict[str, Any], patch: dict[str, Any]) -> None:
    comps = [dict(c) for c in (params.get("components") or [])]
    p0, lo, hi, vary = _vectors(params)
    offs = _offsets(comps)
    idxs = set(select_components(comps, patch.get("select")))
    if len(idxs) == len(comps):
        raise ValueError("drop_components would remove every component")
    keep_c, kp0, klo, khi, kv = [], [], [], [], []
    removed: set[str] = set()
    for i, c in enumerate(comps):
        n = _n_params(c)
        s = offs[i]
        if i in idxs:
            removed.add(str(c.get("component_id")))
            continue
        keep_c.append(c)
        kp0 += p0[s : s + n]
        klo += lo[s : s + n]
        khi += hi[s : s + n]
        kv += vary[s : s + n]
    params.update({"components": keep_c, "p0": kp0, "bounds_lower": klo, "bounds_upper": khi, "vary": kv})
    _drop_links_touching(params, removed)
    # Peaks that referenced a dropped component through an option (e.g. SB "of") would be dangling.
    for c in keep_c:
        of = c.get("of")
        if of is not None and str(of) in removed:
            raise ValueError(f"component {c.get('component_id')!r} depends on dropped component {of!r}")


def _op_tie_param(params: dict[str, Any], patch: dict[str, Any]) -> None:
    comps = params.get("components") or []
    key = str(patch["key"])
    mode = str(patch.get("mode") or "equal")
    idxs = [i for i in select_components(comps, patch.get("select")) if key in _keys(comps[i])]
    if len(idxs) < 2:
        return  # nothing to tie (a single component): a no-op level, not an error
    driver = idxs[0]
    if patch.get("driver") is not None:
        wanted = [i for i in idxs if str(comps[i].get("component_id")) == str(patch["driver"])]
        if not wanted:
            raise ValueError(f"tie_param driver {patch['driver']!r} not among the selected components")
        driver = wanted[0]
    links = [dict(lk) for lk in (params.get("param_links") or [])]
    p0, lo, hi, vary = _vectors(params)
    offs = _offsets(comps)
    for i in idxs:
        if i == driver:
            continue
        cid = str(comps[i].get("component_id"))
        links = [lk for lk in links if not (str(lk.get("source_component_id")) == cid and str(lk.get("source_key")) == key)]
        links.append(
            {
                "source_component_id": cid,
                "source_key": key,
                "target_component_id": str(comps[driver].get("component_id")),
                "target_key": key,
                "mode": mode,
                **{k: patch[k] for k in ("scale", "offset", "ratio") if k in patch},
            }
        )
        vary[offs[i] + _keys(comps[i]).index(key)] = False
    params.update({"param_links": links, "vary": vary})


def _op_untie_param(params: dict[str, Any], patch: dict[str, Any]) -> None:
    comps = params.get("components") or []
    key = str(patch["key"])
    ids = None
    if patch.get("select"):
        ids = {str(comps[i].get("component_id")) for i in select_components(comps, patch["select"])}
    p0, lo, hi, vary = _vectors(params)
    offs = _offsets(comps)
    index_of = {str(c.get("component_id")): i for i, c in enumerate(comps)}
    kept = []
    for lk in params.get("param_links") or []:
        src = str(lk.get("source_component_id") or "")
        if str(lk.get("source_key") or "") == key and (ids is None or src in ids):
            ci = index_of.get(src)
            if ci is not None and key in _keys(comps[ci]):
                vary[offs[ci] + _keys(comps[ci]).index(key)] = True
            continue
        kept.append(lk)
    params.update({"param_links": kept, "vary": vary})


_FIT_OPS = {
    "set_component_param": _op_set_component_param,
    "swap_component_type": _op_swap_component_type,
    "drop_components": _op_drop_components,
    "tie_param": _op_tie_param,
    "untie_param": _op_untie_param,
}


# --------------------------------------------------------------------------------------------------------------
# generic step operations
# --------------------------------------------------------------------------------------------------------------

def _set_dotted(d: dict[str, Any], dotted: str, value: Any) -> None:
    parts = dotted.split(".")
    cur = d
    for p in parts[:-1]:
        nxt = cur.get(p)
        if not isinstance(nxt, dict):
            nxt = {}
        cur[p] = nxt
        cur = nxt
    cur[parts[-1]] = copy.deepcopy(value)


def apply_params_patch(params: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    """Apply one params-level patch; returns a new dict (input untouched)."""
    validate_patch(patch)
    out = copy.deepcopy(params)
    op = patch["op"]
    if op == "set_step_param":
        _set_dotted(out, str(patch["key"]), patch.get("value"))
    elif op == "replace_step_params":
        out = copy.deepcopy(patch["params"])
    elif op == "set_step_enabled":
        pass  # enabled flag is not a params key; handled by the caller (see apply_upstream)
    elif op in _FIT_OPS:
        _FIT_OPS[op](out, patch)
    return out


def apply_fit_patches(step_params: dict[str, Any], patches: list[dict[str, Any]]) -> dict[str, Any]:
    out = copy.deepcopy(step_params)
    for p in patches:
        if not is_fit_patch(p):
            raise ValueError("apply_fit_patches got an upstream patch")
        if p.get("op") == "set_step_enabled":
            raise ValueError("the fitting step under study cannot be disabled by a patch")
        out = apply_params_patch(out, p)
    return out


def split_patches(patches: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """(fitting-step patches, upstream patches) in their original order."""
    fit, up = [], []
    for p in patches:
        validate_patch(p)
        (fit if is_fit_patch(p) else up).append(p)
    return fit, up


def upstream_signature(upstream_patches: list[dict[str, Any]]) -> str:
    """Stable key of the upstream part of a cell; cells with an equal key share their pre-fit spectra."""
    return canonical(upstream_patches)


def resolve_step_index(steps: list[Any], target: dict[str, Any], *, get_name, get_id) -> int:
    """Index of the pipeline step a target selects."""
    if "step_index" in target:
        i = int(target["step_index"])
        if not 0 <= i < len(steps):
            raise ValueError(f"step_index {i} out of range 0..{len(steps) - 1}")
        return i
    if target.get("step_id"):
        for i, s in enumerate(steps):
            if str(get_id(s) or "") == str(target["step_id"]):
                return i
        raise ValueError(f"no pipeline step with step_id {target['step_id']!r}")
    if target.get("step_name"):
        occ = int(target.get("occurrence") or 1)
        seen = 0
        for i, s in enumerate(steps):
            if str(get_name(s)) == str(target["step_name"]):
                seen += 1
                if seen == occ:
                    return i
        raise ValueError(f"no pipeline step named {target['step_name']!r} (occurrence {occ})")
    raise ValueError(f"patch target selects no step: {target}")

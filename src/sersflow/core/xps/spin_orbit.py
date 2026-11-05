"""
Spin-orbit doublets (F3).

Every p, d and f core level is a doublet. The two members have (CasaXPS Cookbook p.107/137; Biesinger thesis
Table 1.1):

* an AREA ratio fixed by the degeneracy 2j+1: p 1/2 : 3/2 = 1:2, d 3/2 : 5/2 = 2:3, f 5/2 : 7/2 = 3:4;
* a fixed energy splitting (element and chemical-state specific, taken from the recipe or entered by the user);
* the same line shape and, normally, the same FWHM. Exception: the Ti and V 2p1/2 lines are broadened by the
  Coster-Kronig effect (Biesinger thesis 2.3.2-2.3.3, TiO2 0.99 vs 1.97 eV), so recipes whose table gives both
  widths keep that FWHM ratio instead of equal widths.

Links follow the fitting-step ``param_links`` convention: the *source* (partner, low-j member) follows the *target*
(main, high-j member).
"""

from __future__ import annotations

import copy
import math
import re
from dataclasses import dataclass
from typing import Any

# area(low j) / area(high j) = (2 j_low + 1) / (2 j_high + 1)
SUBSHELL_AREA_RATIO: dict[str, float] = {"p": 1.0 / 2.0, "d": 2.0 / 3.0, "f": 3.0 / 4.0}
# (high j, low j) as "2j" integers: p 3/2 & 1/2, d 5/2 & 3/2, f 7/2 & 5/2
SUBSHELL_J2: dict[str, tuple[int, int]] = {"p": (3, 1), "d": (5, 3), "f": (7, 5)}

_NLJ = re.compile(r"(?P<n>[1-7])(?P<l>[pdf])\s*(?P<j>[1357])\s*(?:/|_)?\s*2(?![0-9])", re.IGNORECASE)


@dataclass(frozen=True)
class NLJ:
    prefix: str
    n: int
    l: str
    j2: int
    """2j (3 for j = 3/2)."""
    suffix: str

    @property
    def is_main(self) -> bool:
        return self.j2 == SUBSHELL_J2[self.l][0]

    @property
    def is_partner(self) -> bool:
        return self.j2 == SUBSHELL_J2[self.l][1]


def parse_nlj(label: str) -> NLJ | None:
    """``"IrCl_2p3/2"`` -> NLJ(prefix="IrCl_", n=2, l="p", j2=3, suffix=""); None without an n-l-j term."""
    s = str(label or "")
    m = _NLJ.search(s)
    if m is None:
        return None
    l_ = m.group("l").lower()
    j2 = int(m.group("j"))
    if j2 not in SUBSHELL_J2[l_]:
        return None
    return NLJ(prefix=s[: m.start()].strip().lower(), n=int(m.group("n")), l=l_, j2=j2, suffix=s[m.end() :].strip().lower())


@dataclass(frozen=True)
class SpinOrbitPair:
    main: int
    """Index of the high-j member (2p3/2, 3d5/2, 4f7/2)."""
    partner: int
    """Index of the low-j member (2p1/2, 3d3/2, 4f5/2)."""
    subshell: str
    area_ratio: float
    """area(partner) / area(main), from 2j+1."""


def spin_orbit_pairs(labels: list[str]) -> list[SpinOrbitPair]:
    """Pairs of labels naming both members of one doublet (same prefix / suffix, e.g. ``4f7/2_sat`` + ``4f5/2_sat``)."""
    parsed = [parse_nlj(lab) for lab in labels]
    pairs: list[SpinOrbitPair] = []
    used: set[int] = set()
    for i, a in enumerate(parsed):
        if a is None or not a.is_main or i in used:
            continue
        for k, b in enumerate(parsed):
            if k == i or k in used or b is None or not b.is_partner:
                continue
            if (a.prefix, a.n, a.l, a.suffix) == (b.prefix, b.n, b.l, b.suffix):
                pairs.append(SpinOrbitPair(i, k, a.l, SUBSHELL_AREA_RATIO[a.l]))
                used.update({i, k})
                break
    return pairs


def subshell_from_text(text: str) -> str | None:
    """Subshell letter from a region / label such as ``Co_2p3/2`` or ``Ir 4f`` (None when absent)."""
    nlj = parse_nlj(text)
    if nlj is not None:
        return nlj.l
    m = re.search(r"[1-7]([pdf])(?![a-z])", str(text or ""), re.IGNORECASE)
    return m.group(1).lower() if m else None


def width_and_shape_keys(param_keys: list[str]) -> tuple[list[str], list[str]]:
    """(width keys, shape keys) of a peak: ``fwhm`` when present (else every ``fwhm*``), shape = the rest."""
    keys = [k for k in param_keys if k not in ("pos", "amp")]
    if "fwhm" in keys:
        widths = ["fwhm"]
    else:
        widths = [k for k in keys if k.startswith("fwhm")]
    return widths, [k for k in keys if k not in widths]


def doublet_links(
    *,
    main_id: str,
    partner_id: str,
    param_keys: list[str],
    area_ratio: float | None,
    splitting_eV: float | None,
    fwhm_ratio: float | None = None,
    link_shape: bool = True,
) -> list[dict[str, Any]]:
    """
    Links that hold ``partner_id`` to ``main_id`` as a spin-orbit doublet (both components of the same type).

    pos: offset ``splitting_eV`` (skipped when None); widths: equal, or ``scale`` = ``fwhm_ratio`` when it differs from
    1 by more than 2 %; shape parameters: equal when ``link_shape``; amp: ``area_ratio`` (skipped when None).
    """
    links: list[dict[str, Any]] = []

    def link(key: str, mode: str, **extra: float) -> None:
        links.append(
            {
                "source_component_id": partner_id,
                "source_key": key,
                "target_component_id": main_id,
                "target_key": key,
                "mode": mode,
                **{k: float(v) for k, v in extra.items()},
            }
        )

    if splitting_eV is not None and math.isfinite(float(splitting_eV)):
        link("pos", "offset", offset=float(splitting_eV))
    widths, shapes = width_and_shape_keys(param_keys)
    for k in widths:
        r = fwhm_ratio if (fwhm_ratio is not None and k == "fwhm") else None
        if r is not None and math.isfinite(r) and r > 0 and abs(r - 1.0) > 0.02:
            link(k, "scale", scale=float(r))
        else:
            link(k, "equal")
    if link_shape:
        for k in shapes:
            link(k, "equal")
    if area_ratio is not None and "amp" in param_keys:
        link("amp", "area_ratio", ratio=float(area_ratio))
    return links


def partner_component_id(main_id: str, subshell: str, used: set[str], n: int | None = None) -> str:
    """``2p3_2`` -> ``2p1_2``; ``peak_1`` -> ``peak_1_2p1_2`` (``n`` = 2) style id, unique in ``used``."""
    hi, lo = SUBSHELL_J2[subshell]
    low = {u.lower() for u in used}
    cand = None
    m = re.search(rf"([1-7]{subshell})({hi})([_/]?)(2)", main_id, re.IGNORECASE)
    if m is not None:
        cand = main_id[: m.start(2)] + str(lo) + main_id[m.end(2) :]
    if cand is None or cand.lower() in low:
        cand = f"{main_id}_{n if n else ''}{subshell}{lo}_2"
    base, k = cand, 2
    while cand.lower() in low:
        cand = f"{base}_{k}"
        k += 1
    return cand


def add_spin_orbit_partner(
    step_params: dict[str, Any],
    component_id: str,
    *,
    splitting_eV: float,
    subshell: str,
    partner_id: str | None = None,
    lock_area: bool = True,
    link_shape: bool = True,
    fwhm_ratio: float | None = None,
) -> tuple[dict[str, Any], str]:
    """
    Return a copy of fitting ``step_params`` with a spin-orbit partner of ``component_id`` appended.

    The partner is the same line shape seeded at pos + ``splitting_eV`` with the theoretical area (height scaled
    through the area-per-height factors), linked as a doublet (``doublet_links``). Returns (params, partner_id).
    """
    from sersflow.core.metrics.fitting_features import _param_keys_for_component
    from sersflow.core.preprocess.fitting_specs import AREA_EXPORT_COMPONENT_TYPES
    from sersflow.core.preprocess.peak_area import area_per_height

    sub = str(subshell or "").strip().lower()
    if sub not in SUBSHELL_AREA_RATIO:
        raise ValueError(f"subshell must be p, d or f (got {subshell!r})")
    split = float(splitting_eV)
    if not math.isfinite(split) or split <= 0:
        raise ValueError("splitting_eV must be a positive number of eV (partner at higher binding energy)")
    out = copy.deepcopy(dict(step_params))
    comps = [c for c in (out.get("components") or []) if isinstance(c, dict)]
    n_tot = sum(len(_param_keys_for_component(c)) for c in comps)
    p0 = list(out.get("p0") or [])
    lo = list(out.get("bounds_lower") or [None] * n_tot)
    hi = list(out.get("bounds_upper") or [None] * n_tot)
    vary = list(out.get("vary") or [True] * n_tot)
    if not (len(p0) == len(lo) == len(hi) == len(vary) == n_tot):
        raise ValueError("fitting params have inconsistent p0 / bounds / vary lengths")
    cursor = 0
    main = None
    for c in comps:
        keys = _param_keys_for_component(c)
        if str(c.get("component_id")) == component_id:
            main = (c, keys, cursor)
        cursor += len(keys)
    if main is None:
        raise ValueError(f"unknown component_id {component_id!r}")
    comp, keys, s = main
    ctype = str(comp.get("component_type") or "").strip().lower()
    if ctype not in AREA_EXPORT_COMPONENT_TYPES:
        raise ValueError(f"component {component_id!r} ({ctype}) is not a peak with a finite area")
    used = {str(c.get("component_id")) for c in comps}
    nlj = parse_nlj(component_id) or parse_nlj(str(out.get("xps_region") or ""))
    pid = partner_id or partner_component_id(component_id, sub, used, nlj.n if nlj else None)
    if pid in used:
        raise ValueError(f"component_id {pid!r} already exists")

    ratio = SUBSHELL_AREA_RATIO[sub]
    vals = {k: float(p0[s + j]) for j, k in enumerate(keys)}
    new_vals = dict(vals)
    new_vals["pos"] = vals["pos"] + split
    widths, _shapes = width_and_shape_keys(keys)
    if fwhm_ratio is not None and "fwhm" in widths:
        new_vals["fwhm"] = vals["fwhm"] * float(fwhm_ratio)
    amp = vals.get("amp", 0.0)
    if amp > 0:
        new_vals["amp"] = amp * ratio * area_per_height(ctype, vals) / area_per_height(ctype, new_vals)
    for j, k in enumerate(keys):
        p0.append(float(new_vals[k]))
        lo_v, hi_v = lo[s + j], hi[s + j]
        if k == "pos":
            lo_v = None if lo_v is None else float(lo_v) + split
            hi_v = None if hi_v is None else float(hi_v) + split
        lo.append(lo_v)
        hi.append(hi_v)
        vary.append(bool(vary[s + j]))
    new_comp = {k: v for k, v in comp.items() if k != "component_id"}
    new_comp = {"component_id": pid, **new_comp}
    out["components"] = [*list(out.get("components") or []), new_comp]
    out.update({"p0": p0, "bounds_lower": lo, "bounds_upper": hi, "vary": vary})
    links = [
        lk
        for lk in (out.get("param_links") or [])
        if not (isinstance(lk, dict) and lk.get("source_component_id") == pid)
    ]
    links.extend(
        doublet_links(
            main_id=component_id,
            partner_id=pid,
            param_keys=keys,
            area_ratio=ratio if lock_area else None,
            splitting_eV=split,
            fwhm_ratio=fwhm_ratio,
            link_shape=link_shape,
        )
    )
    out["param_links"] = links
    ratios = str(out.get("initial_area_ratios") or "").strip()
    if ratios:
        out.pop("initial_area_ratios", None)  # one ratio per peak; a new peak invalidates the list
    return out, pid


def add_spin_orbit_partners_for_all_peaks(
    step_params: dict[str, Any],
    *,
    splitting_eV: float,
    subshell: str,
    lock_area: bool = True,
    link_shape: bool = True,
) -> tuple[dict[str, Any], list[str]]:
    """Partner for every finite-area peak (satellites included), e.g. the 2p1/2 copy of a 2p3/2-only recipe."""
    from sersflow.core.preprocess.fitting_specs import AREA_EXPORT_COMPONENT_TYPES

    out = step_params
    created: list[str] = []
    for c in list(step_params.get("components") or []):
        if not isinstance(c, dict):
            continue
        if str(c.get("component_type") or "").strip().lower() not in AREA_EXPORT_COMPONENT_TYPES:
            continue
        out, pid = add_spin_orbit_partner(
            out,
            str(c.get("component_id")),
            splitting_eV=splitting_eV,
            subshell=subshell,
            lock_area=lock_area,
            link_shape=link_shape,
        )
        created.append(pid)
    return out, created

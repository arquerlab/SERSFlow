"""
Apply packaged XPS compound-fit recipes to SERSFlow fitting step params.

Returns a pipeline-shaped fitting payload (components, p0, bounds, vary, param_links)
that the frontend can migrate into the Fitting editor.
"""

from __future__ import annotations

import math
import re
from typing import Any

from sersflow.core.preprocess.fitting_specs import component_param_specs
from sersflow.core.preprocess.peak_area import (
    area_per_height,
    casaxps_la_m_to_fwhm_g,
    height_scale_for_area_ratio,
)
from sersflow.core.xps.fitting_recipes import (
    CompoundFit,
    get_compound_fit,
    list_method_defaults,
    load_fitting_recipes_catalog,
)
from sersflow.core.xps.lineshape_kinds import (
    SUPPORTED_COMPONENT_KINDS,
    normalize_lineshape_kind,
)

_SAFE = re.compile(r"[^a-zA-Z0-9_]+")


def _sanitize_id(label: str, fallback: str) -> str:
    t = _SAFE.sub("_", str(label or "").strip()).strip("_")
    return t or fallback


def _unique_ids(labels: list[str]) -> list[str]:
    used: set[str] = set()
    out: list[str] = []
    for i, lab in enumerate(labels):
        base = _sanitize_id(lab, f"p{i + 1}")
        cand = base
        n = 2
        while cand.lower() in used:
            cand = f"{base}_{n}"
            n += 1
        used.add(cand.lower())
        out.append(cand)
    return out


def _normalize_region(region: str) -> str:
    return re.sub(r"_+", "", str(region or "").strip())


def _prefer_pass_energy(
    fit: CompoundFit,
    requested: int | None,
    *,
    preferred_from_acquisition: int | None = None,
) -> int:
    pes = list(fit.pass_energies) if fit.pass_energies else [10, 20]
    if requested is not None:
        return int(requested)
    if preferred_from_acquisition is not None:
        pref = int(preferred_from_acquisition)
        if pref in pes:
            return pref
        # Closest available PE
        return min(pes, key=lambda x: abs(int(x) - pref))
    if 20 in pes:
        return 20
    return int(pes[0]) if pes else 10


def _fwhm_for_peak(peak: dict[str, Any], pe: int, warnings: list[str]) -> float:
    key = f"fwhm_{pe}"
    raw = peak.get(key)
    if isinstance(raw, (int, float)) and math.isfinite(float(raw)) and float(raw) > 0:
        return float(raw)
    for alt in (10, 20, 5, 40):
        if alt == pe:
            continue
        alt_key = f"fwhm_{alt}"
        v = peak.get(alt_key)
        if isinstance(v, (int, float)) and math.isfinite(float(v)) and float(v) > 0:
            warnings.append(f"missing {key}; used {alt_key}")
            return float(v)
    warnings.append(f"missing FWHM for pass energy {pe}; using 1.0")
    return 1.0


def _pos_bounds(be: float, be_std: float | None) -> tuple[float, float]:
    if be_std is not None and math.isfinite(be_std) and be_std > 0:
        half = max(0.5, 5.0 * float(be_std))
    else:
        half = 1.5
    return be - half, be + half


def _lineshape_kind(peak: dict[str, Any], warnings: list[str]) -> str:
    """
    Map recipe lineshape kind onto a registered component type.

    Soft-fails (with warnings) for missing / unknown kinds so apply still returns
    a usable GL seed rather than aborting the whole recipe.
    """
    label = str(peak.get("label") or peak.get("index") or "?")
    ls = peak.get("lineshape")
    if isinstance(ls, dict):
        kind = normalize_lineshape_kind(str(ls.get("kind") or ""))
        if kind in SUPPORTED_COMPONENT_KINDS:
            return kind
        if kind:
            warnings.append(
                f"peak {label}: unknown lineshape kind '{kind}'; using gl "
                "(relative areas/widths still applied)"
            )
            return "gl"
    warnings.append(
        f"peak {label}: missing lineshape; using gl with default m=30 "
        "(recipe did not specify GL/LA/…)"
    )
    return "gl"


def _lineshape_params(peak: dict[str, Any]) -> dict[str, Any]:
    ls = peak.get("lineshape")
    if isinstance(ls, dict) and isinstance(ls.get("params"), dict):
        return dict(ls["params"])
    return {}


def _default_row_values(component_type: str) -> dict[str, float]:
    specs = component_param_specs(component_type)
    out: dict[str, float] = {}
    for p in specs:
        if p.default is not None and math.isfinite(float(p.default)):
            out[p.key] = float(p.default)
        elif p.key == "amp":
            out[p.key] = 1.0
        elif p.key == "pos":
            out[p.key] = 0.0
        elif p.key.startswith("fwhm"):
            out[p.key] = 1.0
        elif p.key == "m":
            out[p.key] = 30.0
        elif p.key in ("alpha", "beta", "eta"):
            out[p.key] = 0.5 if p.key == "eta" else 1.0
        else:
            out[p.key] = 0.0
    return out


def _chapter_from_table(source_table: str | None) -> int | None:
    if not source_table:
        return None
    head = str(source_table).split(".", 1)[0]
    try:
        return int(head)
    except ValueError:
        return None


def _should_include_shirley(fit: CompoundFit, include_background: bool) -> bool:
    if not include_background:
        return False
    chapter = _chapter_from_table(fit.source_table)
    methods = list_method_defaults(chapter=chapter) if chapter is not None else list_method_defaults()
    if not methods:
        catalog = load_fitting_recipes_catalog()
        methods = list(catalog.method_defaults)
    for m in methods:
        bg = (m.background or "").strip().lower()
        if bg == "shirley":
            return True
    return True  # default XPS practice when unspecified


def _find_so_pair(labels: list[str]) -> tuple[int, int] | None:
    i3 = i1 = None
    for i, lab in enumerate(labels):
        low = lab.lower().replace(" ", "")
        if "2p3/2" in low or "2p32" in low:
            i3 = i
        if "2p1/2" in low or "2p12" in low:
            i1 = i
    if i3 is not None and i1 is not None and i3 != i1:
        return i3, i1
    return None


def _peak_param_values(
    *,
    ctype: str,
    ls_params: dict[str, Any],
    be: float,
    fwhm: float,
    amp: float,
) -> dict[str, float]:
    values: dict[str, float] = dict(_default_row_values(ctype))
    values["pos"] = be
    values["amp"] = float(amp)
    if "fwhm" in values:
        values["fwhm"] = fwhm
    if ctype == "gl":
        m = ls_params.get("m")
        if isinstance(m, (int, float)) and math.isfinite(float(m)):
            values["m"] = float(np_clip_m(m))
    if ctype == "la":
        for k in ("alpha", "beta"):
            v = ls_params.get(k)
            if isinstance(v, (int, float)) and math.isfinite(float(v)):
                values[k] = float(v)
        m = ls_params.get("m")
        if isinstance(m, (int, float)) and math.isfinite(float(m)) and "fwhm_g" in values:
            values["fwhm_g"] = casaxps_la_m_to_fwhm_g(float(m), fwhm)
    if ctype == "a_gl":
        m = ls_params.get("m")
        if isinstance(m, (int, float)) and math.isfinite(float(m)):
            values["m"] = float(np_clip_m(m))
        for k in ("a", "n"):
            v = ls_params.get(k)
            if isinstance(v, (int, float)) and math.isfinite(float(v)):
                values[k] = float(v)
        m_asym = ls_params.get("m_asym")
        if isinstance(m_asym, (int, float)) and math.isfinite(float(m_asym)):
            values["m_asym"] = max(0.0, float(m_asym))
    return values


def _is_fermi_edge_recipe(peaks: list[dict[str, Any]]) -> bool:
    if not peaks:
        return False
    for peak in peaks:
        ls = peak.get("lineshape")
        kind = ""
        if isinstance(ls, dict):
            kind = normalize_lineshape_kind(str(ls.get("kind") or ""))
        if kind != "fermi_edge":
            return False
    return True


def _apply_fermi_edge_recipe(
    fit: CompoundFit,
    peaks: list[dict[str, Any]],
    warnings: list[str],
) -> dict[str, Any]:
    """Build a single-component Fermi-edge fitting step (no Shirley / peak FWHM logic)."""
    labels = [str(p.get("label") or f"fermi{i + 1}") for i, p in enumerate(peaks)]
    ids = _unique_ids(labels)
    components: list[dict[str, Any]] = []
    p0: list[float] = []
    bounds_lower: list[float | None] = []
    bounds_upper: list[float | None] = []
    vary: list[bool] = []

    specs = component_param_specs("fermi_edge")
    for i, peak in enumerate(peaks):
        ls_params = _lineshape_params(peak)
        components.append({"component_id": ids[i], "component_type": "fermi_edge"})
        defaults = _default_row_values("fermi_edge")
        # Amplitude: auto by default (≤0 sentinel); optional override from recipe params.
        amp_raw = ls_params.get("amplitude", ls_params.get("amp"))
        if isinstance(amp_raw, (int, float)) and math.isfinite(float(amp_raw)) and float(amp_raw) > 0:
            defaults["amplitude"] = float(amp_raw)
        else:
            defaults["amplitude"] = 0.0
        center_raw = peak.get("be_eV", ls_params.get("center"))
        if isinstance(center_raw, (int, float)) and math.isfinite(float(center_raw)):
            defaults["center"] = float(center_raw)
        sigma_raw = ls_params.get("sigma")
        if isinstance(sigma_raw, (int, float)) and math.isfinite(float(sigma_raw)):
            defaults["sigma"] = float(sigma_raw)
        temp_raw = ls_params.get("temperature_K", ls_params.get("temperature"))
        if isinstance(temp_raw, (int, float)) and math.isfinite(float(temp_raw)):
            defaults["temperature_K"] = float(temp_raw)

        for s in specs:
            val = float(defaults.get(s.key, 0.0))
            p0.append(val)
            if s.key == "temperature_K":
                bounds_lower.append(None)
                bounds_upper.append(None)
                vary.append(False)
            else:
                bounds_lower.append(s.lower_default)
                bounds_upper.append(s.upper_default)
                vary.append(True)

    region = str(fit.region or "").strip() or "valence_band"
    out: dict[str, Any] = {
        "output_mode": "fit",
        "fill_opacity": 0.15,
        "initial_guess_mode": "default",
        "xps_region": region.replace("_", " "),
        "components": components,
        "p0": p0,
        "bounds_lower": bounds_lower,
        "bounds_upper": bounds_upper,
        "vary": vary,
        "param_links": [],
        "recipe_id": fit.id,
        "recipe_pass_energy": None,
        "warnings": warnings,
    }
    return out


def apply_compound_fit_to_fitting_params(
    fit: CompoundFit,
    *,
    pass_energy: int | None = None,
    include_background: bool = True,
    preferred_pass_energy: int | None = None,
) -> dict[str, Any]:
    warnings: list[str] = []
    peaks = list(fit.peaks)
    if not peaks:
        raise ValueError(f"recipe {fit.id} has no peaks")

    for note in fit.footnotes or []:
        text = str(note or "").strip()
        if text:
            warnings.append(f"footnote: {text}")
    if fit.source_table:
        warnings.append(f"provenance: {fit.source_table}" + (f" p.{fit.pdf_page}" if fit.pdf_page else ""))

    if _is_fermi_edge_recipe(peaks):
        return _apply_fermi_edge_recipe(fit, peaks, warnings)

    pe = _prefer_pass_energy(
        fit, pass_energy, preferred_from_acquisition=preferred_pass_energy
    )
    if fit.pass_energies and pe not in fit.pass_energies:
        allowed = ", ".join(str(x) for x in fit.pass_energies)
        raise ValueError(f"pass_energy {pe} not in recipe pass_energies [{allowed}]")

    labels = [str(p.get("label") or f"p{i + 1}") for i, p in enumerate(peaks)]
    ids = _unique_ids(labels)

    # Relative areas from area_pct (None = unspecified)
    areas: list[float | None] = []
    for p in peaks:
        ap = p.get("area_pct")
        if isinstance(ap, (int, float)) and math.isfinite(float(ap)) and float(ap) > 0:
            areas.append(float(ap))
        else:
            areas.append(None)

    components: list[dict[str, Any]] = []
    p0: list[float] = []
    bounds_lower: list[float | None] = []
    bounds_upper: list[float | None] = []
    param_keys_per: list[list[str]] = []
    peak_value_rows: list[dict[str, float]] = []
    peak_ctypes: list[str] = []

    if _should_include_shirley(fit, include_background):
        bg_type = "shirley_bg"
        bg_specs = component_param_specs(bg_type)
        components.append({"component_id": "bg", "component_type": bg_type})
        keys = [s.key for s in bg_specs]
        param_keys_per.append(keys)
        defaults = _default_row_values(bg_type)
        for k in keys:
            p0.append(defaults.get(k, 0.0))
            spec = next(s for s in bg_specs if s.key == k)
            bounds_lower.append(spec.lower_default)
            bounds_upper.append(spec.upper_default)

    fwhm_vals: list[float] = []
    # First pass: build shape/width seeds with amp=1; then convert area_pct → height.
    for peak in peaks:
        ctype = _lineshape_kind(peak, warnings)
        ls_params = _lineshape_params(peak)
        be = float(peak.get("be_eV") or 0.0)
        fwhm = _fwhm_for_peak(peak, pe, warnings)
        fwhm_vals.append(fwhm)
        values = _peak_param_values(
            ctype=ctype, ls_params=ls_params, be=be, fwhm=fwhm, amp=1.0
        )
        peak_ctypes.append(ctype)
        peak_value_rows.append(values)

    factors = [area_per_height(ct, vals) for ct, vals in zip(peak_ctypes, peak_value_rows)]
    if any(a is not None for a in areas):
        ref_i = next((i for i, a in enumerate(areas) if a is not None), 0)
        a_ref = float(areas[ref_i] if areas[ref_i] is not None else 1.0)
        f_ref = factors[ref_i]
        for i, a in enumerate(areas):
            if a is None:
                peak_value_rows[i]["amp"] = 1.0
            else:
                peak_value_rows[i]["amp"] = height_scale_for_area_ratio(
                    area_i=float(a),
                    area_0=a_ref,
                    factor_i=factors[i],
                    factor_0=f_ref,
                )
        warnings.append(
            "area_pct converted to peak heights using analytical/approx Area/amp "
            f"factors (ref peak index {ref_i + 1})"
        )
    else:
        for row in peak_value_rows:
            row["amp"] = 1.0

    for i, peak in enumerate(peaks):
        ctype = peak_ctypes[i]
        values = peak_value_rows[i]
        be = float(values["pos"])
        be_std_raw = peak.get("be_std_eV")
        be_std = float(be_std_raw) if isinstance(be_std_raw, (int, float)) else None
        fwhm = fwhm_vals[i]
        components.append({"component_id": ids[i], "component_type": ctype})
        specs = component_param_specs(ctype)
        keys = [s.key for s in specs]
        param_keys_per.append(keys)
        lo_pos, hi_pos = _pos_bounds(be, be_std)

        for s in specs:
            k = s.key
            val = float(values.get(k, 0.0))
            p0.append(val)
            if k == "pos":
                bounds_lower.append(lo_pos)
                bounds_upper.append(hi_pos)
            elif k == "fwhm":
                bounds_lower.append(1e-6)
                bounds_upper.append(float(max(8.0, 5.0 * fwhm)))
            elif k == "amp":
                bounds_lower.append(0.0)
                bounds_upper.append(None)
            elif k == "m":
                bounds_lower.append(0.0)
                bounds_upper.append(100.0)
            else:
                bounds_lower.append(s.lower_default)
                bounds_upper.append(s.upper_default)

    peak_offset = 1 if components and components[0].get("component_type") == "shirley_bg" else 0
    peak_comp_ids = [c["component_id"] for c in components[peak_offset:]]

    param_links: list[dict[str, Any]] = []
    driven: set[tuple[str, str]] = set()

    def add_link(
        source_id: str,
        source_key: str,
        target_id: str,
        target_key: str,
        mode: str,
        *,
        scale: float | None = None,
        offset: float | None = None,
    ) -> None:
        link: dict[str, Any] = {
            "source_component_id": source_id,
            "source_key": source_key,
            "target_component_id": target_id,
            "target_key": target_key,
            "mode": mode,
        }
        if mode == "scale" and scale is not None:
            link["scale"] = float(scale)
        if mode == "offset" and offset is not None:
            link["offset"] = float(offset)
        param_links.append(link)
        driven.add((source_id, source_key))

    so = _find_so_pair(labels)
    so_split = fit.raw.get("spin_orbit_split_eV")
    if isinstance(so_split, (int, float)) and math.isfinite(float(so_split)) and so is None:
        warnings.append(
            f"recipe has spin_orbit_split_eV={so_split} but no 2p3/2+2p1/2 peak pair "
            "was found in labels; SO constraints were not applied"
        )
    if so is not None and isinstance(so_split, (int, float)) and math.isfinite(float(so_split)):
        i3, i1 = so
        id3, id1 = peak_comp_ids[i3], peak_comp_ids[i1]
        add_link(id1, "pos", id3, "pos", "offset", offset=float(so_split))
        # Theoretical 2p branching is 2:1 in *area*. Convert to height via Area/amp factors.
        amp_scale = height_scale_for_area_ratio(
            area_i=1.0,
            area_0=2.0,
            factor_i=factors[i1],
            factor_0=factors[i3],
        )
        add_link(id1, "amp", id3, "amp", "scale", scale=amp_scale)
        add_link(id1, "fwhm", id3, "fwhm", "equal")
    else:
        for i, peak in enumerate(peaks):
            if i == 0:
                continue
            dvp = peak.get("delta_vs_prev_eV")
            if isinstance(dvp, (int, float)) and math.isfinite(float(dvp)):
                add_link(
                    peak_comp_ids[i],
                    "pos",
                    peak_comp_ids[i - 1],
                    "pos",
                    "offset",
                    offset=float(dvp),
                )
        if any(a is not None for a in areas):
            ref_i = next((j for j, a in enumerate(areas) if a is not None), 0)
            a_ref = areas[ref_i]
            if a_ref is not None and a_ref > 0:
                for i, a in enumerate(areas):
                    if i == ref_i or a is None:
                        continue
                    scale = height_scale_for_area_ratio(
                        area_i=float(a),
                        area_0=float(a_ref),
                        factor_i=factors[i],
                        factor_0=factors[ref_i],
                    )
                    add_link(
                        peak_comp_ids[i],
                        "amp",
                        peak_comp_ids[ref_i],
                        "amp",
                        "scale",
                        scale=scale,
                    )

    for i, peak in enumerate(peaks):
        if i == 0:
            continue
        delta = peak.get("delta_eV")
        vs = str(peak.get("delta_vs") or "").strip().lower()
        if not (isinstance(delta, (int, float)) and math.isfinite(float(delta))):
            continue
        src_idx = i - 1
        if vs in {"peak_1", "peak1", "main", "p1"}:
            src_idx = 0
        elif vs.startswith("peak_"):
            try:
                src_idx = max(0, int(vs.split("_", 1)[1]) - 1)
            except ValueError:
                src_idx = i - 1
        if src_idx == i or src_idx < 0 or src_idx >= len(peak_comp_ids):
            continue
        already = any(
            link.get("target_component_id") == peak_comp_ids[i]
            and link.get("target_key") == "pos"
            and link.get("mode") == "offset"
            for link in param_links
        )
        if already:
            continue
        add_link(
            peak_comp_ids[i],
            "pos",
            peak_comp_ids[src_idx],
            "pos",
            "offset",
            offset=float(delta),
        )

    for i, peak in enumerate(peaks):
        eq = str(peak.get("equal_fwhm_to") or "").strip().lower()
        if not eq:
            cons = peak.get("constraints") or []
            if isinstance(cons, list) and any(
                "equal fwhm" in str(c).lower() or "fwhm equal" in str(c).lower() for c in cons
            ):
                eq = "peak_1"
            else:
                continue
        src_idx = 0
        if eq.startswith("peak_"):
            try:
                src_idx = max(0, int(eq.split("_", 1)[1]) - 1)
            except ValueError:
                src_idx = 0
        if src_idx == i or src_idx >= len(peak_comp_ids):
            continue
        key = (peak_comp_ids[i], "fwhm")
        if key not in driven:
            add_link(peak_comp_ids[i], "fwhm", peak_comp_ids[src_idx], "fwhm", "equal")

    if len(fwhm_vals) > 1 and all(abs(v - fwhm_vals[0]) < 1e-9 for v in fwhm_vals):
        for i in range(1, len(peak_comp_ids)):
            key = (peak_comp_ids[i], "fwhm")
            if key not in driven:
                add_link(peak_comp_ids[i], "fwhm", peak_comp_ids[0], "fwhm", "equal")

    vary_out: list[bool] = []
    for comp, keys in zip(components, param_keys_per):
        cid = str(comp["component_id"])
        for k in keys:
            vary_out.append((cid, k) not in driven)

    return {
        "recipe_id": fit.id,
        "recipe_pass_energy": pe,
        "xps_region": _normalize_region(fit.region),
        "components": components,
        "p0": p0,
        "bounds_lower": bounds_lower,
        "bounds_upper": bounds_upper,
        "vary": vary_out,
        "param_links": param_links,
        "initial_guess_mode": "auto",
        "warnings": warnings,
    }


def np_clip_m(m: float) -> float:
    return max(0.0, min(100.0, float(m)))


def apply_recipe_id(
    recipe_id: str,
    *,
    pass_energy: int | None = None,
    include_background: bool = True,
    preferred_pass_energy: int | None = None,
) -> dict[str, Any]:
    fit = get_compound_fit(recipe_id)
    if fit is None:
        raise KeyError(f"Unknown fitting recipe id: {recipe_id}")
    return apply_compound_fit_to_fitting_params(
        fit,
        pass_energy=pass_energy,
        include_background=include_background,
        preferred_pass_energy=preferred_pass_energy,
    )

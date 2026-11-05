"""
Apply packaged XPS compound-fit recipes to SERSFlow fitting step params.

Returns a pipeline-shaped fitting payload (components, p0, bounds, vary, param_links)
that the frontend can migrate into the Fitting editor.
"""

from __future__ import annotations

import math
import re
from typing import Any

from sersflow.core.preprocess.fitting_specs import AREA_EXPORT_COMPONENT_TYPES, component_param_specs
from sersflow.core.preprocess.param_expressions import expression_refs, remap_expression_ids
from sersflow.core.xps.spin_orbit import (
    add_spin_orbit_partners_for_all_peaks,
    doublet_links,
    spin_orbit_pairs,
    subshell_from_text,
)
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
    return _resolve_pass_energy(fit, requested, preferred_from_acquisition)[0]


def _resolve_pass_energy(
    fit: CompoundFit,
    requested: int | None,
    preferred_from_acquisition: int | None,
) -> tuple[int, dict[str, Any]]:
    """
    Pick the recipe pass energy (PE) and describe how it was chosen.

    ``source`` is one of: ``request`` (explicit pass_energy), ``acquisition`` (dataset PE has a
    column), ``acquisition_closest`` (dataset PE has no column; nearest recipe PE used),
    ``default`` (no hint; 20 eV or the first recipe PE).
    """
    pes = [int(x) for x in (fit.pass_energies or [])] or [10, 20]
    info: dict[str, Any] = {
        "requested": int(requested) if requested is not None else None,
        "acquisition": int(preferred_from_acquisition) if preferred_from_acquisition is not None else None,
        "available": list(pes),
    }
    if requested is not None:
        pe, source = int(requested), "request"
    elif preferred_from_acquisition is not None:
        pref = int(preferred_from_acquisition)
        if pref in pes:
            pe, source = pref, "acquisition"
        else:
            pe, source = min(pes, key=lambda x: abs(int(x) - pref)), "acquisition_closest"
    elif 20 in pes:
        pe, source = 20, "default"
    else:
        pe, source = int(pes[0]), "default"
    info["used"] = pe
    info["source"] = source
    return pe, info


def _fwhm_for_peak(
    peak: dict[str, Any], pe: int, fallbacks: list[dict[str, Any]] | None = None
) -> float:
    """FWHM from the ``fwhm_<pe>`` column; records any fallback column in ``fallbacks``."""
    key = f"fwhm_{pe}"
    label = str(peak.get("label") or peak.get("index") or "?")
    raw = peak.get(key)
    if isinstance(raw, (int, float)) and math.isfinite(float(raw)) and float(raw) > 0:
        return float(raw)
    for alt in (10, 20, 5, 40):
        if alt == pe:
            continue
        alt_key = f"fwhm_{alt}"
        v = peak.get(alt_key)
        if isinstance(v, (int, float)) and math.isfinite(float(v)) and float(v) > 0:
            if fallbacks is not None:
                fallbacks.append({"peak": label, "requested_column": key, "used_column": alt_key})
            return float(v)
    if fallbacks is not None:
        fallbacks.append({"peak": label, "requested_column": key, "used_column": None})
    return 1.0


def pass_energy_warning(info: dict[str, Any]) -> str | None:
    """One human-readable warning summarising a pass-energy fallback (None when exact)."""
    if not info.get("fallback"):
        return None
    parts: list[str] = []
    if info.get("source") == "acquisition_closest":
        parts.append(
            f"dataset pass energy {info.get('acquisition')} eV has no FWHM column in this recipe; "
            f"used {info.get('used')} eV (available: {', '.join(str(x) for x in info.get('available') or [])})"
        )
    fbs = info.get("fwhm_fallbacks") or []
    if fbs:
        used_cols = sorted({str(f.get("used_column")) for f in fbs if f.get("used_column")})
        n_default = sum(1 for f in fbs if not f.get("used_column"))
        msg = f"{len(fbs)} peak(s) lack fwhm_{info.get('used')}"
        if used_cols:
            msg += f"; used {', '.join(used_cols)}"
        if n_default:
            msg += f"; {n_default} set to 1.0 eV"
        parts.append(msg)
    return "pass energy: " + "; ".join(parts) if parts else None


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
    """
    Return ``(i_2p3/2, i_2p1/2)`` when peak *labels* name both SO components.

    Only recipes that literally label peaks ``2p3/2`` / ``2p1/2`` (or 2p32/2p12)
    qualify — e.g. Sc/Ti doublets in Biesinger Tables 2.x. Multiplet packs that
    use ``peak_1``…``peak_N`` (Co 2p3/2 Table 3.5, etc.) return None even when
    the region name contains ``2p3/2``.
    """
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
    if ctype in ("gl", "sgl", "gl_gauss"):
        m = ls_params.get("m")
        if isinstance(m, (int, float)) and math.isfinite(float(m)):
            values["m"] = float(np_clip_m(m))
    if ctype == "gl_gauss":
        n = ls_params.get("fwhm_g", ls_params.get("n"))
        if isinstance(n, (int, float)) and math.isfinite(float(n)):
            values["fwhm_g"] = max(0.0, float(n))
    if ctype == "la":
        for k in ("alpha", "beta"):
            v = ls_params.get(k)
            if isinstance(v, (int, float)) and math.isfinite(float(v)):
                values[k] = float(v)
        m = ls_params.get("m")
        if isinstance(m, (int, float)) and math.isfinite(float(m)) and "fwhm_g" in values:
            values["fwhm_g"] = casaxps_la_m_to_fwhm_g(float(m), fwhm)
    if ctype == "lf":
        # CasaXPS LF(alpha, beta, w, m): alpha, beta and w carry over (w is in eV, the
        # tail-damping width). The Gaussian index m has no documented eV scale, so it is
        # not translated (fwhm_g keeps the spec default).
        for k in ("alpha", "beta", "w"):
            v = ls_params.get(k)
            if isinstance(v, (int, float)) and math.isfinite(float(v)):
                values[k] = float(v)
    if ctype in ("a_gl", "a_sgl"):
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

    # Prefer the "all valence bands" gate — literal "valence band" rarely exists as a region label.
    region_raw = str(fit.region or "").strip().lower().replace(" ", "_")
    if not region_raw or region_raw in ("valence_band", "valence", "vb"):
        xps_region = "all valence bands"
    else:
        xps_region = str(fit.region or "").strip().replace("_", " ")
    out: dict[str, Any] = {
        "output_mode": "fit",
        "fill_opacity": 0.15,
        "initial_guess_mode": "default",
        "xps_region": xps_region,
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


# Component types whose area/height ratio area_ratio links can evaluate (see fitting_lmfit): every
# finite-area peak since F3.
_AREA_RATIO_TYPES = AREA_EXPORT_COMPONENT_TYPES


def apply_compound_fit_to_fitting_params(
    fit: CompoundFit,
    *,
    pass_energy: int | None = None,
    include_background: bool = True,
    preferred_pass_energy: int | None = None,
    lock_satellites: bool = True,
    lock_spin_orbit: bool = True,
    spin_orbit_partner_splitting_eV: float | None = None,
    spin_orbit_partner_subshell: str | None = None,
) -> dict[str, Any]:
    """
    Fitting-step params for a recipe.

    F3 spin-orbit doublets: when the recipe labels both members (``2p3/2`` + ``2p1/2``, ``4f7/2`` + ``4f5/2``, ...)
    they are linked as a doublet: fixed splitting, FWHM equal (or the recipe table's ratio, e.g. Ti/V 2p1/2
    Coster-Kronig broadening), equal line shape when the recipe gives the same one, and (``lock_spin_orbit``, unless
    the recipe sets ``spin_orbit_area_lock: false``) the theoretical 2j+1 AREA ratio. One-member recipes (Co/Ni/Fe
    2p3/2 multiplets) stay single unless ``spin_orbit_partner_splitting_eV`` is given: then every peak gets a
    partner at +splitting (subshell from the region, or ``spin_orbit_partner_subshell``).
    """
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

    pe, pe_info = _resolve_pass_energy(fit, pass_energy, preferred_pass_energy)
    fwhm_fallbacks: list[dict[str, Any]] = []
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
        fwhm = _fwhm_for_peak(peak, pe, fwhm_fallbacks)
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
            "area_pct used only as initial amplitude seed (amplitudes free to vary)"
        )
    else:
        for row in peak_value_rows:
            row["amp"] = 1.0

    # Spin-orbit: seed the low-j member's height from the theoretical area ratio when the recipe gives no areas.
    so_pairs = spin_orbit_pairs(labels)
    if so_pairs and not any(a is not None for a in areas):
        for pr in so_pairs:
            amp_scale = height_scale_for_area_ratio(
                area_i=pr.area_ratio,
                area_0=1.0,
                factor_i=factors[pr.partner],
                factor_0=factors[pr.main],
            )
            peak_value_rows[pr.partner]["amp"] = float(peak_value_rows[pr.main]["amp"]) * float(amp_scale)

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
        ratio: float | None = None,
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
        if mode == "area_ratio" and ratio is not None:
            link["ratio"] = float(ratio)
        param_links.append(link)
        driven.add((source_id, source_key))

    so = _find_so_pair(labels)
    so_split = fit.raw.get("spin_orbit_split_eV")
    if isinstance(so_split, (int, float)) and math.isfinite(float(so_split)) and so is None:
        warnings.append(
            f"recipe has spin_orbit_split_eV={so_split} but no 2p3/2+2p1/2 peak pair "
            "was found in labels; SO constraints were not applied"
        )
    # Spin-orbit splitting of a single labelled doublet (Sc/Ti/V tables): the position offset. FWHM, shape and
    # area links of every labelled doublet are added below (F3), after the recipe's own equal-FWHM rules.
    if so is not None and isinstance(so_split, (int, float)) and math.isfinite(float(so_split)):
        i3, i1 = so
        id3, id1 = peak_comp_ids[i3], peak_comp_ids[i1]
        add_link(id1, "pos", id3, "pos", "offset", offset=float(so_split))
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
        # A peak position can follow only one link (the doublet splitting added above wins).
        already = (peak_comp_ids[i], "pos") in driven
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

    # F3 spin-orbit doublets of every labelled pair (2p3/2 + 2p1/2, 3d5/2 + 3d3/2, 4f7/2 + 4f5/2, prefixed or
    # suffixed alike: IrCl_2p3/2, 4f7/2_sat). Literature: Biesinger thesis Table 1.1 and 2.3; CasaXPS Cookbook p.137.
    lock_so = bool(lock_spin_orbit) and fit.raw.get("spin_orbit_area_lock") is not False
    n_so_locked = 0
    for pr in so_pairs:
        im, ip = pr.main, pr.partner
        mid, pid = peak_comp_ids[im], peak_comp_ids[ip]
        keys = param_keys_per[peak_offset + ip]
        same_type = peak_ctypes[im] == peak_ctypes[ip]
        if (pid, "pos") not in driven:
            add_link(pid, "pos", mid, "pos", "offset", offset=float(peak_value_rows[ip]["pos"] - peak_value_rows[im]["pos"]))
        fw_m = _table_fwhm(peaks[im], pe)
        fw_p = _table_fwhm(peaks[ip], pe)
        fwhm_ratio = fw_p / fw_m if (fw_m and fw_p) else None
        same_shape = same_type and _lineshape_params(peaks[im]) == _lineshape_params(peaks[ip])
        for lk in doublet_links(
            main_id=mid,
            partner_id=pid,
            param_keys=keys if same_type else ["pos", "amp"],
            area_ratio=pr.area_ratio if lock_so else None,
            splitting_eV=None,
            fwhm_ratio=fwhm_ratio,
            link_shape=same_shape,
        ):
            if (lk["source_component_id"], lk["source_key"]) in driven:
                continue
            add_link(
                lk["source_component_id"],
                lk["source_key"],
                lk["target_component_id"],
                lk["target_key"],
                lk["mode"],
                scale=lk.get("scale"),
                offset=lk.get("offset"),
                ratio=lk.get("ratio"),
            )
            if lk["mode"] == "area_ratio":
                n_so_locked += 1
            if lk["mode"] == "scale" and lk["source_key"] == "fwhm":
                why = " (2p1/2 Coster-Kronig broadening)" if fwhm_ratio and fwhm_ratio > 1.3 else ""
                warnings.append(f"{pid} FWHM held at {fwhm_ratio:.2f} x {mid} FWHM, the recipe table ratio{why}")
        if not same_type:
            warnings.append(f"{mid}/{pid}: different line shapes in the recipe; FWHM and shape not linked")
    if n_so_locked:
        warnings.append(
            f"{n_so_locked} spin-orbit area ratio(s) locked at the theoretical value (p 1:2, d 2:3, f 3:4); "
            "remove the amp link or use lock_spin_orbit=false to free them"
        )
    elif so_pairs and not lock_so:
        warnings.append("spin-orbit area ratios NOT locked (lock_spin_orbit=false or recipe spin_orbit_area_lock=false)")

    # Satellites (shake-up lines flagged ``"satellite": true`` in the recipe) have a
    # literature intensity relative to the main line, so their amplitude is locked to
    # the first non-satellite peak by default. Edit/remove the amp link to unlock.
    if lock_satellites:
        sat_idx = [i for i, p in enumerate(peaks) if p.get("satellite") is True and areas[i] is not None]
        ref_idx = next(
            (i for i, p in enumerate(peaks) if p.get("satellite") is not True and areas[i] is not None),
            None,
        )
        if sat_idx and ref_idx is not None:
            peak_comp_types = [str(c.get("component_type") or "").strip().lower() for c in components[peak_offset:]]
            n_height_fallback = 0
            for i in sat_idx:
                if (peak_comp_ids[i], "amp") in driven:
                    continue  # e.g. 4f5/2 satellite already held at 3:4 of the 4f7/2 satellite (doublet)
                if peak_comp_types[i] in _AREA_RATIO_TYPES and peak_comp_types[ref_idx] in _AREA_RATIO_TYPES:
                    # The link keeps the literature AREA ratio whatever fwhm / shape the fit settles on.
                    add_link(
                        peak_comp_ids[i],
                        "amp",
                        peak_comp_ids[ref_idx],
                        "amp",
                        "area_ratio",
                        ratio=float(areas[i]) / float(areas[ref_idx]),
                    )
                else:
                    n_height_fallback += 1
                    add_link(
                        peak_comp_ids[i],
                        "amp",
                        peak_comp_ids[ref_idx],
                        "amp",
                        "scale",
                        scale=height_scale_for_area_ratio(
                            area_i=float(areas[i]),
                            area_0=float(areas[ref_idx]),
                            factor_i=factors[i],
                            factor_0=factors[ref_idx],
                        ),
                    )
            warnings.append(
                "satellite area ratio(s) locked to the main peak via area_ratio links "
                "(edit or remove the link to unlock; lock_satellites=false disables)"
            )
            if n_height_fallback:
                warnings.append(
                    f"{n_height_fallback} satellite(s) use a fixed-height amp scale link "
                    "(line shape not supported by area_ratio)"
                )
        elif sat_idx:
            warnings.append("satellite peaks flagged but no area_pct reference peak; ratios not locked")

    _FWHM_KEYS = frozenset({"fwhm", "fwhm_g", "fwhm_l", "fwhm_lorentz", "fwhm_gauss"})
    _SHAPE_KEYS = frozenset({"m", "eta", "alpha", "beta", "a", "n", "m_asym"})

    vary_out: list[bool] = []
    for comp, keys in zip(components, param_keys_per):
        cid = str(comp["component_id"])
        ctype = str(comp.get("component_type") or "")
        is_peak = not _is_background_component(ctype)
        for k in keys:
            if is_peak and k in _FWHM_KEYS:
                # Recipe FWHM is a fixed instrument/resolution seed by default.
                vary_out.append(False)
            elif is_peak and k in _SHAPE_KEYS:
                # CasaXPS lineshape mix (e.g. GL(30) → m=30) stays fixed.
                vary_out.append(False)
            else:
                vary_out.append((cid, k) not in driven)

    if any(
        (not _is_background_component(str(c.get("component_type") or "")))
        and any(k in _FWHM_KEYS for k in keys)
        for c, keys in zip(components, param_keys_per)
    ):
        warnings.append("peak FWHM parameters are fixed (vary=false) from the recipe")
    if any(
        (not _is_background_component(str(c.get("component_type") or "")))
        and any(k in _SHAPE_KEYS for k in keys)
        for c, keys in zip(components, param_keys_per)
    ):
        warnings.append("peak lineshape mix parameters are fixed (vary=false) from the recipe")

    pe_info["fwhm_fallbacks"] = fwhm_fallbacks
    pe_info["fallback"] = bool(fwhm_fallbacks) or pe_info.get("source") == "acquisition_closest"
    pe_info["recipe_id"] = fit.id
    pe_warn = pass_energy_warning(pe_info)
    if pe_warn:
        warnings.insert(0, pe_warn)

    out: dict[str, Any] = {
        "recipe_id": fit.id,
        "recipe_pass_energy": pe,
        "pass_energy_resolution": pe_info,
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
    if areas and all(a is not None for a in areas):
        out["initial_area_ratios"] = ":".join(f"{float(a):g}" for a in areas)
    if spin_orbit_partner_splitting_eV is not None:
        out = _add_partner_block(
            out,
            fit,
            labels,
            splitting_eV=float(spin_orbit_partner_splitting_eV),
            subshell=spin_orbit_partner_subshell,
            lock_area=lock_so,
        )
    return out


def _table_fwhm(peak: dict[str, Any], pe: int) -> float | None:
    """FWHM printed in the recipe for this pass energy (no fallback column); None when absent."""
    raw = peak.get(f"fwhm_{pe}")
    if isinstance(raw, (int, float)) and math.isfinite(float(raw)) and float(raw) > 0:
        return float(raw)
    return None


def _add_partner_block(
    out: dict[str, Any],
    fit: CompoundFit,
    labels: list[str],
    *,
    splitting_eV: float,
    subshell: str | None,
    lock_area: bool,
) -> dict[str, Any]:
    """F3 option: the low-j copy of a one-member recipe (e.g. Co 2p1/2 for a Co 2p3/2 multiplet recipe)."""
    if spin_orbit_pairs(labels):
        raise ValueError(f"recipe {fit.id} already has both spin-orbit members; no partner block is needed")
    sub = (subshell or subshell_from_text(fit.region) or "").strip().lower()
    if sub not in ("p", "d", "f"):
        raise ValueError(
            f"cannot tell the subshell of region {fit.region!r}; pass spin_orbit_partner_subshell (p, d or f)"
        )
    warn = list(out.get("warnings") or [])
    new, created = add_spin_orbit_partners_for_all_peaks(
        {k: v for k, v in out.items() if k != "warnings"},
        splitting_eV=splitting_eV,
        subshell=sub,
        lock_area=lock_area,
    )
    ratio = {"p": "1:2", "d": "2:3", "f": "3:4"}[sub]
    warn.append(
        f"added {len(created)} spin-orbit partner peak(s) at +{splitting_eV:g} eV (user splitting), "
        f"area {ratio}{' locked' if lock_area else ' seeded only'}, FWHM and line shape equal to each main peak. "
        "Widen the fit window to include them; the partner copies the 2p3/2 multiplet as a whole, which is an "
        "approximation for multiplet-split ions"
    )
    new["warnings"] = warn
    new["spin_orbit_partner"] = {"splitting_eV": splitting_eV, "subshell": sub, "component_ids": created}
    return new


def np_clip_m(m: float) -> float:
    return max(0.0, min(100.0, float(m)))


_TRAILING_NUM = re.compile(r"^(.*?)([-_ ]?)(\d+)$")


def _is_background_component(component_type: str) -> bool:
    ct = str(component_type or "").strip().lower()
    return ct.endswith("_bg") or ct in {"shirley_bg", "tougaard_bg", "slope_bg"}


def unique_component_id(label: str, used: set[str], *, fallback: str = "p") -> str:
    """
    Return a component id unique against ``used`` (case-insensitive).

    When the base already ends with a number (e.g. Peak_1), increment that number.
    Otherwise append ``_2``, ``_3``, …
    """
    base = _sanitize_id(label, fallback)
    low_used = {u.lower() for u in used}

    def take(cand: str) -> str:
        used.add(cand)
        low_used.add(cand.lower())
        return cand

    if base.lower() not in low_used:
        return take(base)

    m = _TRAILING_NUM.match(base)
    if m:
        prefix, sep, num_s = m.group(1), m.group(2) or "_", m.group(3)
        n = int(num_s) + 1
        while True:
            cand = f"{prefix}{sep}{n}" if prefix else f"{fallback}{n}"
            if cand.lower() not in low_used:
                return take(cand)
            n += 1

    n = 2
    while True:
        cand = f"{base}_{n}"
        if cand.lower() not in low_used:
            return take(cand)
        n += 1


def _component_param_count(comp: dict[str, Any]) -> int:
    ctype = str(comp.get("component_type") or "").strip()
    deg_raw = comp.get("degree")
    degree = int(deg_raw) if deg_raw is not None else None
    return len(component_param_specs(ctype, degree=degree))


def _slice_component_vectors(
    components: list[dict[str, Any]],
    p0: list[Any],
    lo: list[Any],
    hi: list[Any],
    vary: list[Any] | None,
) -> list[dict[str, Any]]:
    """Split flat vectors into per-component bundles."""
    out: list[dict[str, Any]] = []
    off = 0
    for comp in components:
        n = _component_param_count(comp)
        if off + n > len(p0) or off + n > len(lo) or off + n > len(hi):
            raise ValueError(
                f"vector length mismatch while slicing component {comp.get('component_id')!r}"
            )
        row_vary: list[bool] | None = None
        if isinstance(vary, list) and vary:
            if off + n > len(vary):
                raise ValueError(
                    f"vary length mismatch while slicing component {comp.get('component_id')!r}"
                )
            row_vary = [bool(v) for v in vary[off : off + n]]
        out.append(
            {
                "component": dict(comp),
                "p0": [float(x) for x in p0[off : off + n]],
                "bounds_lower": [None if v is None else float(v) for v in lo[off : off + n]],
                "bounds_upper": [None if v is None else float(v) for v in hi[off : off + n]],
                "vary": row_vary if row_vary is not None else [True] * n,
            }
        )
        off += n
    if off != len(p0):
        raise ValueError(f"p0 length mismatch: consumed {off}, got {len(p0)}")
    return out


def merge_fitting_recipe_params(
    base: dict[str, Any],
    added: dict[str, Any],
    *,
    skip_background_from_added: bool = True,
) -> dict[str, Any]:
    """
    Merge a second recipe-apply payload into an existing fitting params dict.

    Keeps baseline(s) from ``base``. From ``added``, appends non-background components
    (peaks / fermi_edge / …), renames colliding component ids, remaps param_links,
    and concatenates ``recipe_ids``.
    """
    base_comps = list(base.get("components") or [])
    added_comps = list(added.get("components") or [])
    if not base_comps:
        raise ValueError("base fitting params require components")
    if not added_comps:
        raise ValueError("added fitting params require components")

    base_rows = _slice_component_vectors(
        base_comps,
        list(base.get("p0") or []),
        list(base.get("bounds_lower") or []),
        list(base.get("bounds_upper") or []),
        list(base["vary"]) if isinstance(base.get("vary"), list) else None,
    )
    added_rows = _slice_component_vectors(
        added_comps,
        list(added.get("p0") or []),
        list(added.get("bounds_lower") or []),
        list(added.get("bounds_upper") or []),
        list(added["vary"]) if isinstance(added.get("vary"), list) else None,
    )

    used: set[str] = set()
    for row in base_rows:
        cid = str(row["component"].get("component_id") or "").strip()
        if cid:
            used.add(cid)

    id_map: dict[str, str] = {}
    id_map_lower: dict[str, str] = {}
    kept_added: list[dict[str, Any]] = []
    for row in added_rows:
        ctype = str(row["component"].get("component_type") or "").strip()
        if skip_background_from_added and _is_background_component(ctype):
            continue
        old_id = str(row["component"].get("component_id") or "").strip() or "p"
        new_id = unique_component_id(old_id, used)
        id_map[old_id] = new_id
        id_map_lower[old_id.lower()] = new_id
        comp = dict(row["component"])
        comp["component_id"] = new_id
        kept_added.append({**row, "component": comp})

    if not kept_added:
        raise ValueError("added recipe contributed no non-background components to merge")

    components: list[dict[str, Any]] = [dict(r["component"]) for r in base_rows] + [
        dict(r["component"]) for r in kept_added
    ]
    p0: list[float] = []
    bounds_lower: list[float | None] = []
    bounds_upper: list[float | None] = []
    vary: list[bool] = []
    for r in base_rows + kept_added:
        p0.extend(r["p0"])
        bounds_lower.extend(r["bounds_lower"])
        bounds_upper.extend(r["bounds_upper"])
        vary.extend(r["vary"])

    def remap_cid(cid: str) -> str:
        if cid in id_map:
            return id_map[cid]
        low = cid.lower()
        if low in id_map_lower:
            return id_map_lower[low]
        return cid

    def remap_links(links: list[Any]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        known = {str(c.get("component_id") or "") for c in components}
        for link in links:
            if not isinstance(link, dict):
                continue
            mapped = dict(link)
            mapped["source_component_id"] = remap_cid(str(link.get("source_component_id") or ""))
            sid = str(mapped.get("source_component_id") or "")
            if str(link.get("mode") or "").strip().lower() == "expr":
                # F4: ids live inside the {id.key} references of the expression.
                refs = expression_refs(str(link.get("expr") or ""))
                mapped["expr"] = remap_expression_ids(
                    str(link.get("expr") or ""), {cid: remap_cid(cid) for cid, _k in refs}
                )
                if sid not in known or any(remap_cid(cid) not in known for cid, _k in refs):
                    continue
                out.append(mapped)
                continue
            mapped["target_component_id"] = remap_cid(str(link.get("target_component_id") or ""))
            tid = str(mapped.get("target_component_id") or "")
            if sid not in known or tid not in known:
                continue
            out.append(mapped)
        return out

    base_links = list(base.get("param_links") or []) if isinstance(base.get("param_links"), list) else []
    added_links = list(added.get("param_links") or []) if isinstance(added.get("param_links"), list) else []
    # Base links keep original ids; only remap added links.
    param_links = [dict(x) for x in base_links if isinstance(x, dict)] + remap_links(added_links)

    def recipe_ids_of(payload: dict[str, Any]) -> list[str]:
        out: list[str] = []
        seen: set[str] = set()
        raw = payload.get("recipe_ids")
        if isinstance(raw, list):
            for x in raw:
                t = str(x or "").strip()
                if t and t not in seen:
                    seen.add(t)
                    out.append(t)
        rid = str(payload.get("recipe_id") or "").strip()
        if rid and rid not in seen:
            out.append(rid)
        return out

    recipe_ids = recipe_ids_of(base) + [r for r in recipe_ids_of(added) if r not in set(recipe_ids_of(base))]

    warnings: list[str] = []
    for src in (base, added):
        w = src.get("warnings")
        if isinstance(w, list):
            warnings.extend(str(x) for x in w if str(x).strip())
    orig_added_ids = {str(r["component"].get("component_id") or "") for r in added_rows}
    for old, new in id_map.items():
        if old in orig_added_ids and old != new:
            warnings.append(f"renamed component {old!r} -> {new!r}")

    out: dict[str, Any] = {
        "components": components,
        "p0": p0,
        "bounds_lower": bounds_lower,
        "bounds_upper": bounds_upper,
        "vary": vary,
        "param_links": param_links,
        "initial_guess_mode": base.get("initial_guess_mode") or added.get("initial_guess_mode") or "auto",
        "warnings": warnings,
    }
    base_ratios = str(base.get("initial_area_ratios") or "").strip()
    added_ratios = str(added.get("initial_area_ratios") or "").strip()
    if base_ratios and added_ratios:
        out["initial_area_ratios"] = f"{base_ratios}:{added_ratios}"
    elif added_ratios:
        out["initial_area_ratios"] = added_ratios
    elif base_ratios:
        out["initial_area_ratios"] = base_ratios
    if recipe_ids:
        out["recipe_id"] = recipe_ids[0]
        out["recipe_ids"] = recipe_ids
    # Prefer last-applied pass energy when present.
    pe = added.get("recipe_pass_energy")
    if pe is None:
        pe = base.get("recipe_pass_energy")
    out["recipe_pass_energy"] = pe
    pe_res = added.get("pass_energy_resolution") or base.get("pass_energy_resolution")
    if isinstance(pe_res, dict):
        out["pass_energy_resolution"] = pe_res
    region = str(base.get("xps_region") or "").strip() or str(added.get("xps_region") or "").strip()
    if region:
        out["xps_region"] = region
    return out


def apply_recipe_id(
    recipe_id: str,
    *,
    pass_energy: int | None = None,
    include_background: bool = True,
    preferred_pass_energy: int | None = None,
    lock_satellites: bool = True,
    lock_spin_orbit: bool = True,
    spin_orbit_partner_splitting_eV: float | None = None,
    spin_orbit_partner_subshell: str | None = None,
) -> dict[str, Any]:
    fit = get_compound_fit(recipe_id)
    if fit is None:
        raise KeyError(f"Unknown fitting recipe id: {recipe_id}")
    out = apply_compound_fit_to_fitting_params(
        fit,
        pass_energy=pass_energy,
        include_background=include_background,
        preferred_pass_energy=preferred_pass_energy,
        lock_satellites=lock_satellites,
        lock_spin_orbit=lock_spin_orbit,
        spin_orbit_partner_splitting_eV=spin_orbit_partner_splitting_eV,
        spin_orbit_partner_subshell=spin_orbit_partner_subshell,
    )
    rid = str(out.get("recipe_id") or recipe_id).strip()
    if rid:
        out["recipe_ids"] = [rid]
    return out


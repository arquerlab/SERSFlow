"""Shared block-map helpers for multi-spectrum uploads (VMS, NXS, future formats)."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Mapping

from sersflow.core.io.xps_field_catalog import XPS_STRUCTURAL_FILTER_KEYS
from sersflow.core.labels.normalize import build_search_text, standardize_segment

logger = logging.getLogger(__name__)

# Historical persistence key; access only via helpers.
BLOCK_SPECTRA_KEY = "vms_spectra"

INTERNAL_LABEL_KEYS = frozenset(
    {
        BLOCK_SPECTRA_KEY,
        "vms_spectrum_mode",
        "xps_regions_filter",
        "nxs_skipped_count",
        "nxs_skipped_regions",
    }
)

# Filter/plot catalog keys ∪ loader-only structural meta (must stay a superset of the catalog).
_LOADER_ONLY_STRUCTURAL_KEYS = frozenset(
    {
        "technique",
        "acquired_at",
        "experiment_id",
        "analyser_work_function_eV",
        "x_label",
        "x_axis_converted_from",
        "pass_energy_eV",
        "step_time",
        "total_steps",
        "total_time",
        "number_of_iterations",
        "nxs_region_key",
        "nxs_spectrum_name",
        "nxs_skipped_count",
        "nxs_skipped_regions",
    }
)

STRUCTURAL_BLOCK_KEYS = frozenset(XPS_STRUCTURAL_FILTER_KEYS | _LOADER_ONLY_STRUCTURAL_KEYS)

EXPERIMENTAL_BLOCK_KEYS = frozenset(
    {
        "sample",
        "gas",
        "ph",
        "current_density_A_cm2",
        "potential_V",
        "potential_ref",
        "laser_nm",
        "laser_power_pct",
        "electrolyte",
        "concentration_M",
    }
)

# Vibrational / Raman only — omit from XPS filter catalogs.
LASER_FILTER_KEYS = ("laser_nm", "laser_power_pct")

# Application-specific: only show when at least one spectrum has the key.
OPTIONAL_APP_FILTER_KEYS = frozenset({"gas", "ph"})

# If any of these is present, expose all three as filter fields.
ELECTROCHEM_FILTER_TRIO = ("current_density_A_cm2", "potential_V", "potential_ref")

# Show when present (any technique).
CORE_EXPERIMENTAL_FILTER_KEYS = ("sample", "electrolyte", "concentration_M")


def select_experimental_filter_keys(
    *,
    technique_family: str | None,
    present_keys: set[str] | frozenset[str],
) -> list[str]:
    """
    Decide which experimental label keys to offer as filter fields.

    - laser_* : vibrational only, and only if present
    - gas / ph : only if present
    - current_density / potential_V / potential_ref : all three if any one is present
    - sample / electrolyte / concentration_M : only if present
    """
    present = {str(k) for k in present_keys}
    family = str(technique_family or "").strip().lower()
    out: list[str] = []

    for k in CORE_EXPERIMENTAL_FILTER_KEYS:
        if k in present:
            out.append(k)

    for k in sorted(OPTIONAL_APP_FILTER_KEYS):
        if k in present:
            out.append(k)

    if any(k in present for k in ELECTROCHEM_FILTER_TRIO):
        out.extend(ELECTROCHEM_FILTER_TRIO)

    if family != "xps":
        for k in LASER_FILTER_KEYS:
            if k in present:
                out.append(k)

    return out


_MULTI_SUFFIXES = frozenset({".vms", ".nxs", ".nx5"})


def is_multi_spectrum_path(path: str | Path) -> bool:
    """
    True when the path's format declares multi-block / enrich support.

    Falls back to a historical suffix set if the format registry is unavailable.
    """
    try:
        from sersflow.core.io.formats import get_format_for_suffix

        spec = get_format_for_suffix(Path(path).suffix)
        if spec is None:
            return Path(path).suffix.lower() in _MULTI_SUFFIXES
        if spec.enrich is not None:
            return True
        return "multi_block" in spec.all_capabilities()
    except Exception:
        return Path(path).suffix.lower() in _MULTI_SUFFIXES


def get_block_spectra(labels: Mapping[str, Any] | None) -> dict[str, dict[str, Any]]:
    """Return a copy of the per-block map, or ``{}`` if absent/invalid."""
    if not isinstance(labels, Mapping):
        return {}
    raw = labels.get(BLOCK_SPECTRA_KEY)
    if not isinstance(raw, dict):
        return {}
    out: dict[str, dict[str, Any]] = {}
    for k, v in raw.items():
        if isinstance(v, dict):
            out[str(k)] = dict(v)
    return out


def set_block_spectra(labels: dict[str, Any], block_map: Mapping[str, Mapping[str, Any]] | None) -> dict[str, Any]:
    """Set ``vms_spectra`` on ``labels`` (mutates and returns ``labels``)."""
    if not block_map:
        labels.pop(BLOCK_SPECTRA_KEY, None)
        return labels
    cleaned: dict[str, dict[str, Any]] = {}
    for k, v in block_map.items():
        if isinstance(v, Mapping):
            cleaned[str(k)] = dict(v)
    labels[BLOCK_SPECTRA_KEY] = cleaned
    return labels


def experimental_only(block: Mapping[str, Any] | None) -> dict[str, Any]:
    if not isinstance(block, Mapping):
        return {}
    return {k: v for k, v in block.items() if k in EXPERIMENTAL_BLOCK_KEYS and v is not None}


def structural_only(block: Mapping[str, Any] | None) -> dict[str, Any]:
    if not isinstance(block, Mapping):
        return {}
    return {k: v for k, v in block.items() if k in STRUCTURAL_BLOCK_KEYS}


def merge_block_structural_preserving_experimental(
    *,
    previous: Mapping[str, Any] | None,
    fresh_structural: Mapping[str, Any],
) -> dict[str, Any]:
    """Keep prior experimental keys; overlay fresh structural meta."""
    prev_exp = experimental_only(previous)
    struct: dict[str, Any] = {}
    for k, v in dict(fresh_structural).items():
        if k in EXPERIMENTAL_BLOCK_KEYS:
            continue
        if v is not None or k in STRUCTURAL_BLOCK_KEYS:
            struct[k] = v
    return {**prev_exp, **struct}


def path_labels_without_internal(labels: Mapping[str, Any] | None) -> dict[str, Any]:
    if not isinstance(labels, Mapping):
        return {}
    return {k: v for k, v in labels.items() if k not in INTERNAL_LABEL_KEYS}


def _join_search_parts(*parts: Any) -> str:
    segs: list[str] = []
    for p in parts:
        if p is None:
            continue
        s = str(p).strip()
        if not s:
            continue
        segs.append(standardize_segment(s))
    return "__".join(segs)


def build_vms_block_search_text(
    *,
    path: Path,
    meta: Mapping[str, Any],
    block: Any | None = None,
    parent_levels: int = 3,
) -> str:
    """Search text for a VAMAS block: path context + name/id/comments/params."""
    path_text = build_search_text(path, parent_levels=parent_levels)
    # Do not include experiment_id / sample identifier here: values like "05mA" are
    # sample names and would be mis-parsed as current density by label extractors.
    # Enrich sets ``sample`` from meta.experiment_id explicitly.
    parts: list[Any] = [path_text, meta.get("block_name")]
    if block is not None:
        parts.append(getattr(block, "source_label", None))
        extras = getattr(block, "extra_fields", None) or {}
        if isinstance(extras, dict):
            comments = extras.get("block_comments")
            if isinstance(comments, (list, tuple)):
                parts.extend(comments)
            elif comments:
                parts.append(comments)
            params = extras.get("additional_params")
            if isinstance(params, list):
                for ap in params:
                    if not isinstance(ap, dict):
                        continue
                    parts.extend([ap.get("label"), ap.get("unit"), ap.get("value")])
    return _join_search_parts(*parts)


def build_nxs_block_search_text(
    *,
    path: Path,
    meta: Mapping[str, Any],
    parent_levels: int = 3,
) -> str:
    """Search text for an NXS block: path + region/spectrum names."""
    path_text = build_search_text(path, parent_levels=parent_levels)
    return _join_search_parts(
        path_text,
        meta.get("nxs_region_key") or meta.get("xps_region"),
        meta.get("nxs_spectrum_name") or meta.get("block_name"),
        meta.get("block_name"),
    )


def build_block_search_text_for_meta(
    *,
    path: Path,
    meta: Mapping[str, Any],
    parent_levels: int = 3,
) -> str:
    """Pick search-text builder from the registered format id when known."""
    format_id = ""
    try:
        from sersflow.core.io.formats import get_format_for_path

        format_id = get_format_for_path(path).id
    except Exception:
        format_id = ""
    if format_id == "nexus_xps" or (
        not format_id and path.suffix.lower() in {".nxs", ".nx5"}
    ):
        return build_nxs_block_search_text(path=path, meta=meta, parent_levels=parent_levels)
    if format_id == "vamas" or (not format_id and path.suffix.lower() == ".vms"):
        return build_vms_block_search_text(path=path, meta=meta, block=None, parent_levels=parent_levels)
    return _join_search_parts(
        build_search_text(path, parent_levels=parent_levels),
        meta.get("block_name"),
        meta.get("xps_region"),
    )


def build_block_spectra_for_path(
    path: Path,
    *,
    parent_levels: int = 3,
    previous_labels: Mapping[str, Any] | None = None,
) -> dict[str, dict[str, Any]] | None:
    """
    Build full block map for a multi-spectrum file, or ``None`` if not multi.

    Uses the format registry loader + enrich (single load).
    """
    path = Path(path)
    try:
        from sersflow.core.io.formats import get_format_for_path

        fmt = get_format_for_path(path)
        ds = fmt.loader(path)
        if fmt.enrich is None:
            return None
        er = fmt.enrich(path, ds, dict(previous_labels) if previous_labels else None)
        return er.block_map
    except Exception:
        logger.exception("build_block_spectra_for_path: failed to enrich %s", path)
        return None


def lift_nxs_skip_summary_to_labels(
    labels: dict[str, Any],
    block_map: Mapping[str, Mapping[str, Any]] | None,
) -> dict[str, Any]:
    """Copy NXS skipped-region summary from block 0 meta onto path-level labels."""
    if not block_map:
        return labels
    b0 = block_map.get("0") if isinstance(block_map, Mapping) else None
    if not isinstance(b0, Mapping):
        return labels
    count = b0.get("nxs_skipped_count")
    if count is None:
        return labels
    try:
        n = int(count)
    except (TypeError, ValueError):
        return labels
    if n <= 0:
        return labels
    out = dict(labels)
    out["nxs_skipped_count"] = n
    regions = b0.get("nxs_skipped_regions")
    if isinstance(regions, list):
        out["nxs_skipped_regions"] = list(regions)
    return out


def attach_block_spectra_to_labels(
    labels: dict[str, Any] | None,
    path: Path,
    *,
    parent_levels: int = 3,
    previous_labels: Mapping[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, dict[str, Any]] | None]:
    """
    Build block map for ``path``, merge into labels, and lift NXS skip summary.

    Returns ``(labels, block_map)``. ``block_map`` is ``None`` when the file is not multi-spectrum.
    """
    prev = previous_labels if previous_labels is not None else labels
    block_map = build_block_spectra_for_path(path, parent_levels=parent_levels, previous_labels=prev)
    out = dict(labels or {})
    if not block_map:
        return out, None
    set_block_spectra(out, block_map)
    out = lift_nxs_skip_summary_to_labels(out, block_map)
    return out, block_map

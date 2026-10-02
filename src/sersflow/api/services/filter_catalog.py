"""Build filter-field catalogs for metadata_filter QC and related UIs."""

from __future__ import annotations

from typing import Any

from sersflow.api.services.spectrum_context import labels_for_spectrum, load_spectrum_contexts
from sersflow.infra.datasets_store import DatasetRecord, iter_spectrum_axes_page
from sersflow.infra.upload_labels_store import fetch_upload_labels_for_paths, with_connection

from sersflow.core.io.formats import list_formats
from sersflow.core.io.formats.packs import (
    AXIS_FIELD_CATALOG,
    EXPERIMENTAL_FIELD_LABELS,
)
from sersflow.core.io.multi_block_labels import (
    ELECTROCHEM_FILTER_TRIO,
    EXPERIMENTAL_BLOCK_KEYS,
    INTERNAL_LABEL_KEYS,
    select_experimental_filter_keys,
)

_INTERNAL_LABEL_KEYS = INTERNAL_LABEL_KEYS

_EXPERIMENTAL_LABELS: dict[str, tuple[str, str]] = dict(EXPERIMENTAL_FIELD_LABELS)

assert set(_EXPERIMENTAL_LABELS) == set(EXPERIMENTAL_BLOCK_KEYS)

_AXIS_CATALOG = list(AXIS_FIELD_CATALOG)


def _as_number(v: Any) -> float | None:
    if v is None or isinstance(v, bool):
        return None
    try:
        n = float(v)
    except (TypeError, ValueError):
        return None
    if n != n:
        return None
    return n


def _collect_row_values(dataset: DatasetRecord) -> list[dict[str, Any]]:
    paths = sorted({str(s.relative_path) for s in dataset.spectra if s.relative_path})
    con = with_connection()
    try:
        labels_by_path = fetch_upload_labels_for_paths(con, paths)
    finally:
        con.close()

    axes_by_sid: dict[str, dict[str, Any]] = {}
    offset = 0
    while True:
        page, total = iter_spectrum_axes_page(dataset_id=dataset.dataset_id, limit=500, offset=offset)
        for it in page:
            sid = str(it.get("spectrum_id") or "")
            if sid:
                axes_by_sid[sid] = it
        offset += len(page)
        if offset >= total or not page:
            break

    rows: list[dict[str, Any]] = []
    for ctx in load_spectrum_contexts(dataset.spectra, labels_by_path=labels_by_path):
        flat = dict(ctx.labels)
        axes = axes_by_sid.get(ctx.spectrum_id) or {}
        for k in ("axis_map_x", "axis_map_y", "axis_time_s", "file_kind"):
            if k in axes and axes[k] is not None:
                flat[k] = axes[k]
        rows.append(flat)
    return rows


def _planned_fields_from_packs(*, caps: list[str], family: str) -> list[tuple[str, str, str]]:
    """Build planned (key, label, kind) from format capability packs."""
    planned: list[tuple[str, str, str]] = []
    seen_keys: set[str] = set()
    cap_set = set(caps)
    for fmt in list_formats():
        fmt_caps = set(fmt.all_capabilities())
        if cap_set:
            if not fmt_caps.intersection(cap_set):
                continue
        else:
            if family == "xps":
                if fmt.technique not in ("xps", "sniff"):
                    continue
            elif fmt.technique == "xps":
                continue
        for fdef in fmt.all_filter_fields():
            if fdef.key in seen_keys:
                continue
            # Without caps, skip XPS structural on vibrational datasets.
            if not cap_set and family != "xps" and fdef.source == "structural":
                continue
            # Axis fields are appended separately with presence rules.
            if fdef.source == "axis":
                continue
            # Experimental keys go through select_experimental_filter_keys.
            if fdef.source == "experimental":
                continue
            seen_keys.add(fdef.key)
            planned.append((fdef.key, fdef.label, fdef.kind))
    return planned


def build_filter_fields_catalog(dataset: DatasetRecord) -> list[dict[str, Any]]:
    """Return technique-aware field descriptors with values or min/max."""
    rows = _collect_row_values(dataset)
    family = str(getattr(dataset.metadata, "technique_family", None) or "vibrational")
    caps = list(getattr(dataset.metadata, "capabilities", None) or [])

    key_presence: dict[str, None] = {}
    for row in rows:
        for k in row:
            if k in _INTERNAL_LABEL_KEYS:
                continue
            key_presence[str(k)] = None

    planned: list[tuple[str, str, str]] = list(_planned_fields_from_packs(caps=caps, family=family))

    for key in select_experimental_filter_keys(technique_family=family, present_keys=set(key_presence)):
        if any(key == p[0] for p in planned):
            continue
        label, kind = _EXPERIMENTAL_LABELS[key]
        planned.append((key, label, kind))

    planned.extend(_AXIS_CATALOG)
    for k in sorted(key_presence.keys()):
        if any(k == p[0] for p in planned):
            continue
        if k in EXPERIMENTAL_BLOCK_KEYS:
            continue
        planned.append((k, k, "auto"))

    electrochem_force = set(ELECTROCHEM_FILTER_TRIO) & {p[0] for p in planned}

    fields: list[dict[str, Any]] = []
    for key, label, kind_hint in planned:
        values: list[str] = []
        seen: set[str] = set()
        nums: list[float] = []
        present = False
        for row in rows:
            if key not in row or row[key] is None:
                continue
            present = True
            n = _as_number(row[key])
            if kind_hint == "numeric":
                if n is not None:
                    nums.append(n)
            else:
                s = str(row[key])
                if s not in seen:
                    seen.add(s)
                    values.append(s)
        # Electrochem trio: include companions even when empty so all three appear together.
        if not present and key not in electrochem_force:
            continue
        if kind_hint == "numeric":
            if not nums:
                continue
            fields.append({"id": key, "label": label, "kind": "numeric", "min": min(nums), "max": max(nums)})
        elif kind_hint == "auto" and nums and not values:
            fields.append({"id": key, "label": label, "kind": "numeric", "min": min(nums), "max": max(nums)})
        elif kind_hint == "categorical" or values or key in electrochem_force:
            fields.append(
                {
                    "id": key,
                    "label": label,
                    "kind": "categorical",
                    "values": sorted(values)[:200],
                }
            )
        elif nums:
            fields.append({"id": key, "label": label, "kind": "numeric", "min": min(nums), "max": max(nums)})
    return fields


def list_xps_regions_for_dataset(dataset: DatasetRecord) -> list[dict[str, Any]]:
    """Aggregate xps_region counts from upload_labels.vms_spectra joined on record_index."""
    counts: dict[str, int] = {}
    paths = sorted({str(s.relative_path) for s in dataset.spectra if s.relative_path})
    con = with_connection()
    try:
        labels_by_path = fetch_upload_labels_for_paths(con, paths)
    finally:
        con.close()
    for s in dataset.spectra:
        lab = labels_by_path.get(str(s.relative_path)) or {}
        flat = labels_for_spectrum(lab, record_index=s.record_index)
        region = str(flat.get("xps_region") or "").strip()
        if not region:
            continue
        counts[region] = counts.get(region, 0) + 1
    return [{"region": k, "count": counts[k]} for k in sorted(counts.keys())]

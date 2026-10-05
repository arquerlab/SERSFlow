"""Enrich helpers shared by multi-spectrum formats."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sersflow.core.io.formats.types import EnrichResult
from sersflow.core.io.multi_block_labels import (
    EXPERIMENTAL_BLOCK_KEYS,
    experimental_only,
    get_block_spectra,
    build_block_search_text_for_meta,
    build_vms_block_search_text,
    lift_nxs_skip_summary_to_labels,
    set_block_spectra,
)
from sersflow.core.labels.api import extract_labels_from_text
from sersflow.core.models.datasets import Dataset, MultiSpectrumDataset

# Experimental keys we try to scrape from the VAMAS sample identifier string.
_SAMPLE_ID_EXPERIMENTAL_KEYS = frozenset(
    {
        "gas",
        "ph",
        "current_density_A_cm2",
        "potential_V",
        "potential_ref",
        "electrolyte",
        "concentration_M",
    }
)


def _merge_labels_from_sample_identifier(
    experimental: dict[str, Any],
    *,
    experiment_id: str,
    prev_block: dict[str, Any] | None,
    path_hint: str,
) -> None:
    """
    Keep ``sample`` as the full VAMAS identifier, and additionally scrape current /
    gas / pH / electrolyte / potential tokens when they appear in that string.
    """
    exp_id = str(experiment_id or "").strip()
    if not exp_id:
        return
    prev = prev_block or {}
    prev_sample = str(prev.get("sample") or "").strip()
    experimental["sample"] = prev_sample or exp_id

    scraped = extract_labels_from_text(exp_id, path_hint=path_hint)
    for key in _SAMPLE_ID_EXPERIMENTAL_KEYS:
        prev_val = prev.get(key)
        if prev_val is not None and str(prev_val).strip() != "":
            experimental[key] = prev_val
            continue
        if key in scraped:
            experimental[key] = scraped[key]


def enrich_multi_spectrum(
    path: Path,
    dataset: Dataset,
    previous_labels: dict[str, Any] | None = None,
    *,
    parent_levels: int = 3,
    format_id: str | None = None,
) -> EnrichResult:
    """
    Build block map + labels for a multi-spectrum file without a second load when
    ``dataset`` is already the loaded MultiSpectrumDataset.

    Uses dataset.meta for search text (no format re-parse).
    """
    path = Path(path)
    labels = dict(previous_labels or {})
    if not isinstance(dataset, MultiSpectrumDataset):
        return EnrichResult(labels=labels, block_map=None, dataset=dataset)

    fid = format_id
    if fid is None:
        try:
            from sersflow.core.io.formats import get_format_for_path

            fid = get_format_for_path(path).id
        except Exception:
            fid = ""

    prev_map = get_block_spectra(previous_labels)
    use_vms_search = fid == "vamas"

    block_map: dict[str, dict[str, Any]] = {}
    for i, meta in enumerate(dataset.meta or ()):
        md = dict(meta or {})
        if use_vms_search:
            search = build_vms_block_search_text(
                path=path,
                meta=md,
                block=None,
                parent_levels=parent_levels,
            )
        else:
            search = build_block_search_text_for_meta(path=path, meta=md, parent_levels=parent_levels)
        prev_block = prev_map.get(str(i))
        experimental = extract_labels_from_text(
            search,
            previous_labels=experimental_only(prev_block) or None,
            path_hint=f"{path}#{i}",
        )
        # ISO 14976 sample identifier (below region, before date):
        # keep as sample, and scrape current/gas/pH/electrolyte/potential when present.
        if use_vms_search:
            _merge_labels_from_sample_identifier(
                experimental,
                experiment_id=str(md.get("experiment_id") or ""),
                prev_block=prev_block if isinstance(prev_block, dict) else None,
                path_hint=f"{path}#{i}",
            )
        merged_struct = {k: v for k, v in md.items() if k not in EXPERIMENTAL_BLOCK_KEYS}
        block_map[str(i)] = {**merged_struct, **experimental}

    set_block_spectra(labels, block_map)
    labels = lift_nxs_skip_summary_to_labels(labels, block_map)

    # Prefer per-block VAMAS acquisition times over client file mtime for path-level acquired_utc.
    acquired_times = [
        str(b.get("acquired_at")).strip()
        for b in block_map.values()
        if isinstance(b, dict) and b.get("acquired_at")
    ]
    acquired_times = [t for t in acquired_times if t]
    if acquired_times:
        labels["acquired_utc"] = min(acquired_times)

    return EnrichResult(labels=labels, block_map=block_map, dataset=dataset)

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
        merged_struct = {k: v for k, v in md.items() if k not in EXPERIMENTAL_BLOCK_KEYS}
        block_map[str(i)] = {**merged_struct, **experimental}

    set_block_spectra(labels, block_map)
    labels = lift_nxs_skip_summary_to_labels(labels, block_map)
    return EnrichResult(labels=labels, block_map=block_map, dataset=dataset)

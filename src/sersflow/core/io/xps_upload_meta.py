"""XPS-oriented upload metadata helpers (regions from multi-block files)."""

from __future__ import annotations

from sersflow.core.models.datasets import MultiSpectrumDataset, SpectrumDataset, SeriesDataset, MapDataset


def dataset_xps_regions(
    ds: SpectrumDataset | SeriesDataset | MapDataset | MultiSpectrumDataset,
) -> list[str]:
    """Distinct sorted ``xps_region`` tokens from a multi-block (VAMAS) dataset."""
    if not isinstance(ds, MultiSpectrumDataset):
        return []
    seen: set[str] = set()
    out: list[str] = []
    for m in ds.meta or ():
        if not isinstance(m, dict):
            continue
        region = str(m.get("xps_region") or "").strip()
        if region and region not in seen:
            seen.add(region)
            out.append(region)
    return sorted(out)

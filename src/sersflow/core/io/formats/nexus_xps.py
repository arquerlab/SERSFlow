"""NeXus XPS (.nxs / .nx5) format."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sersflow.core.io.formats.enrich import enrich_multi_spectrum
from sersflow.core.io.formats.packs import MULTI_BLOCK_XPS, NXS_SKIP_SUMMARY
from sersflow.core.io.formats.registry import register_format
from sersflow.core.io.formats.types import EnrichResult, FormatSpec
from sersflow.core.io.read_nxs import read_file_nxs
from sersflow.core.models.datasets import Dataset


def _enrich(path: Path, dataset: Dataset, previous_labels: dict[str, Any] | None) -> EnrichResult:
    return enrich_multi_spectrum(path, dataset, previous_labels, format_id="nexus_xps")


register_format(
    FormatSpec(
        id="nexus_xps",
        label="NeXus XPS (HDF5)",
        suffixes=(".nxs", ".nx5"),
        technique="xps",
        dataset_kinds=frozenset({"multi"}),
        packs=(MULTI_BLOCK_XPS, NXS_SKIP_SUMMARY),
        loader=read_file_nxs,
        docs=(
            "Diamond-style NeXus XPS HDF5. Regions without binding_energy are skipped; "
            "skip counts are surfaced on upload labels."
        ),
        enrich=_enrich,
    )
)

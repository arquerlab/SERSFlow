"""VAMAS / CasaXPS (.vms) format."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sersflow.core.io.formats.enrich import enrich_multi_spectrum
from sersflow.core.io.formats.packs import MULTI_BLOCK_XPS
from sersflow.core.io.formats.registry import register_format
from sersflow.core.io.formats.types import EnrichResult, FormatSpec
from sersflow.core.io.read_vms import read_file_vms
from sersflow.core.models.datasets import Dataset


def _enrich(path: Path, dataset: Dataset, previous_labels: dict[str, Any] | None) -> EnrichResult:
    return enrich_multi_spectrum(path, dataset, previous_labels, format_id="vamas")


register_format(
    FormatSpec(
        id="vamas",
        label="VAMAS / CasaXPS",
        suffixes=(".vms",),
        technique="xps",
        dataset_kinds=frozenset({"multi"}),
        packs=(MULTI_BLOCK_XPS,),
        loader=read_file_vms,
        docs=(
            "ISO 14976 / CasaXPS VAMAS transfer. Each block becomes an entry in a "
            "MultiSpectrumDataset with xps_region and spectrum_role metadata."
        ),
        enrich=_enrich,
    )
)

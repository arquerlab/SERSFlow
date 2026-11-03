"""SPECS Prodigy (.sle) XPS format."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sersflow.core.io.formats.enrich import enrich_multi_spectrum
from sersflow.core.io.formats.packs import MULTI_BLOCK_XPS, NXS_SKIP_SUMMARY
from sersflow.core.io.formats.registry import register_format
from sersflow.core.io.formats.types import EnrichResult, FormatSpec
from sersflow.core.io.read_sle import read_file_sle
from sersflow.core.models.datasets import Dataset


def _enrich(path: Path, dataset: Dataset, previous_labels: dict[str, Any] | None) -> EnrichResult:
    return enrich_multi_spectrum(path, dataset, previous_labels, format_id="specs_sle")


register_format(
    FormatSpec(
        id="specs_sle",
        label="SPECS Prodigy XPS / NEXAFS (SQLite)",
        suffixes=(".sle",),
        technique="xps",
        dataset_kinds=frozenset({"multi"}),
        packs=(MULTI_BLOCK_XPS, NXS_SKIP_SUMMARY),
        loader=read_file_sle,
        docs=(
            "SpecsLab Prodigy .sle (SQLite). Fixed-analyzer-transmission scans are rebuilt from the "
            "detector channels with the stored energy-shift calibration (XPS). Constant-final-state "
            "scans become XAS TEY/PEY blocks (meta.technique=XAS) on a photon-energy axis. Other scan "
            "modes are skipped and counted on upload labels."
        ),
        enrich=_enrich,
    )
)

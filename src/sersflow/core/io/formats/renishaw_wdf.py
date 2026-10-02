"""Renishaw WDF format."""

from __future__ import annotations

from sersflow.core.io.formats.packs import MAP_OR_SERIES_RAMAN
from sersflow.core.io.formats.registry import register_format
from sersflow.core.io.formats.types import FormatSpec
from sersflow.core.io.read_wdf import read_file_wdf

register_format(
    FormatSpec(
        id="renishaw_wdf",
        label="Renishaw WDF",
        suffixes=(".wdf",),
        technique="vibrational",
        dataset_kinds=frozenset({"spectrum", "series", "map"}),
        packs=(MAP_OR_SERIES_RAMAN,),
        loader=read_file_wdf,
        docs="Renishaw WiRE WDF Raman maps, series, and single spectra.",
        enrich=None,
    )
)

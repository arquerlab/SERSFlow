"""ASCII XY (.txt) format."""

from __future__ import annotations

from sersflow.core.io.formats.packs import SINGLE_XY
from sersflow.core.io.formats.registry import register_format
from sersflow.core.io.formats.types import FormatSpec
from sersflow.core.io.read_txt import read_file_txt

register_format(
    FormatSpec(
        id="ascii_xy",
        label="ASCII XY table",
        suffixes=(".txt",),
        technique="sniff",
        dataset_kinds=frozenset({"spectrum", "series"}),
        packs=(SINGLE_XY,),
        loader=read_file_txt,
        docs=(
            "Delimited text with an x/y header row. Technique is sniffed from the "
            "x-axis label (wavenumber → vibrational; Binding energy/BE → XPS)."
        ),
        enrich=None,
    )
)

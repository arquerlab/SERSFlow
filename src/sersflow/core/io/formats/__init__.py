"""File format registry: load instructions + UI treatments + filter schemas."""

from __future__ import annotations

from sersflow.core.io.formats.registry import (
    FORMAT_REGISTRY,
    get_format_for_path,
    get_format_for_suffix,
    list_formats,
    register_format,
    supported_suffixes,
)
from sersflow.core.io.formats.types import (
    CapabilityPack,
    EnrichResult,
    FilterFieldDef,
    FormatSpec,
    UiTreatment,
)

# Side-effect: register builtins
from sersflow.core.io.formats import builtins as _builtins  # noqa: F401

__all__ = [
    "CapabilityPack",
    "EnrichResult",
    "FilterFieldDef",
    "FORMAT_REGISTRY",
    "FormatSpec",
    "UiTreatment",
    "get_format_for_path",
    "get_format_for_suffix",
    "list_formats",
    "register_format",
    "supported_suffixes",
]

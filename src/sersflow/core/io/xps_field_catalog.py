"""Shared field catalogs for filters and multi-plot UIs (re-exports from format packs)."""

from __future__ import annotations

from typing import Any

from sersflow.core.io.formats.packs import (
    AXIS_FIELD_CATALOG,
    EXPERIMENTAL_FIELD_LABELS,
    XPS_STRUCTURAL_FIELD_CATALOG,
    XPS_STRUCTURAL_FILTER_KEYS,
)

__all__ = [
    "AXIS_FIELD_CATALOG",
    "EXPERIMENTAL_FIELD_LABELS",
    "XPS_STRUCTURAL_FIELD_CATALOG",
    "XPS_STRUCTURAL_FILTER_KEYS",
    "xps_structural_fields_public",
]


def xps_structural_fields_public() -> list[dict[str, Any]]:
    return [{"key": k, "label": lab, "kind": kind} for k, lab, kind in XPS_STRUCTURAL_FIELD_CATALOG]

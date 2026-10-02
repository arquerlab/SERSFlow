"""Shared spectrum label resolution and batch context loading."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence

from sersflow.core.io.multi_block_labels import INTERNAL_LABEL_KEYS, get_block_spectra
from sersflow.infra.upload_labels_store import fetch_upload_labels_for_paths, with_connection


def labels_for_spectrum(labels: Mapping[str, Any] | None, *, record_index: int | None) -> dict[str, Any]:
    """
    Resolve path-level upload labels, expanding multi-spectrum per-block metadata when present.

    Public counterpart of the former observation_export helper.
    """
    if not labels:
        return {}
    base = {k: v for k, v in labels.items() if k not in INTERNAL_LABEL_KEYS}
    blocks = get_block_spectra(labels)
    if blocks and record_index is not None:
        block = blocks.get(str(record_index))
        if isinstance(block, dict):
            return {**base, **block}
    return base


@dataclass(frozen=True)
class SpectrumContext:
    spectrum_id: str
    relative_path: str
    record_index: int | None
    labels: dict[str, Any]


def load_spectrum_contexts(
    spectra: Sequence[Any],
    *,
    labels_by_path: Mapping[str, Mapping[str, Any]] | None = None,
) -> list[SpectrumContext]:
    """
    Build per-spectrum label contexts for QC / filter / session preview.

    When ``labels_by_path`` is omitted, loads upload labels for all unique relative paths.
    """
    paths = sorted({str(getattr(s, "relative_path", "") or "") for s in spectra if getattr(s, "relative_path", None)})
    if labels_by_path is None:
        con = with_connection()
        try:
            fetched = fetch_upload_labels_for_paths(con, paths)
        finally:
            con.close()
        labels_by_path = fetched

    out: list[SpectrumContext] = []
    for s in spectra:
        rel = str(getattr(s, "relative_path", "") or "")
        ri = getattr(s, "record_index", None)
        ri_int = int(ri) if ri is not None and str(ri).strip() != "" else None
        sid = str(getattr(s, "spectrum_id", "") or "")
        lab = labels_for_spectrum(labels_by_path.get(rel) or {}, record_index=ri_int)
        out.append(
            SpectrumContext(
                spectrum_id=sid,
                relative_path=rel,
                record_index=ri_int,
                labels=lab,
            )
        )
    return out

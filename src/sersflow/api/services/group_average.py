"""Materialise group averages as derived spectra (blob file + catalog record + ref)."""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any, Sequence

import numpy as np

from sersflow.api.schemas.datasets import SpectrumRef
from sersflow.api.services.spectrum_context import load_spectrum_contexts
from sersflow.core.preprocess.group_average import (
    SPECTRUM_ROLE_GROUP_MEAN,
    AveragedGroup,
    GroupAverageParams,
    GroupMember,
    PlannedGroup,
    group_average,
)
from sersflow.core.spectrum import XY
from sersflow.infra.blob_store import store_blob_from_file
from sersflow.infra.derived_spectra_store import (
    DerivedSpectrumRecord,
    derived_relative_path,
    upsert_derived_spectrum,
)
from sersflow.infra.upload_labels_store import upsert_upload_labels, with_connection

DERIVED_SOURCE = "group_average"


class DerivedSpectrumRef(SpectrumRef):
    """A catalog-registered group average. Carries its labels so the engine does not need a source file."""

    source: str = DERIVED_SOURCE
    spectrum_labels: dict[str, Any] = {}
    member_spectrum_ids: list[str] = []


def _x_header(labels: dict[str, Any]) -> str:
    return str(labels.get("x_label") or "x").replace("\t", " ").replace("\n", " ")


def _write_xy_txt(xy: XY, *, x_header: str, path: Path) -> None:
    x = np.asarray(xy.x, dtype=float)
    y = np.asarray(xy.y, dtype=float)
    with path.open("w", encoding="utf-8", newline="\n") as f:
        f.write(f"{x_header}\tIntensity\n")
        for xv, yv in zip(x, y):
            f.write(f"{float(xv):.9g}\t{float(yv):.9g}\n")


def materialize_group(
    group: AveragedGroup, *, dataset_id: str, rule: dict[str, Any], x_header: str
) -> DerivedSpectrumRef:
    """Write the averaged curve to the blob store, register it in the catalog, return a usable ref."""
    with tempfile.TemporaryDirectory(prefix="sersflow_grp_") as tmp:
        p = Path(tmp) / "group_average.txt"
        _write_xy_txt(group.xy, x_header=x_header, path=p)
        stored = store_blob_from_file(p)

    labels = dict(group.labels)
    labels["spectrum_role"] = SPECTRUM_ROLE_GROUP_MEAN
    # Label key for the existing path-level label joins (exports, filters); not a file on disk.
    rel = derived_relative_path(group.spectrum_id)
    con = with_connection()
    try:
        upsert_upload_labels(con, relative_path=rel, labels=labels)
    finally:
        con.close()
    upsert_derived_spectrum(
        DerivedSpectrumRecord(
            spectrum_id=group.spectrum_id,
            dataset_id=dataset_id,
            kind=SPECTRUM_ROLE_GROUP_MEAN,
            blob_id=stored.blob_id,
            blob_relative_path=stored.blob_relative_path,
            labels=labels,
            member_spectrum_ids=list(group.member_ids),
            group_key=dict(group.key),
            rule=dict(rule),
        )
    )
    return derived_ref_from_record(
        DerivedSpectrumRecord(
            spectrum_id=group.spectrum_id,
            dataset_id=dataset_id,
            kind=SPECTRUM_ROLE_GROUP_MEAN,
            blob_id=stored.blob_id,
            blob_relative_path=stored.blob_relative_path,
            labels=labels,
            member_spectrum_ids=list(group.member_ids),
            group_key=dict(group.key),
            rule=dict(rule),
        )
    )


def derived_ref_from_record(rec: DerivedSpectrumRecord) -> DerivedSpectrumRef:
    return DerivedSpectrumRef(
        spectrum_id=rec.spectrum_id,
        relative_path=derived_relative_path(rec.spectrum_id),
        blob_id=rec.blob_id,
        blob_relative_path=rec.blob_relative_path,
        original_relative_path=rec.blob_relative_path,
        spectrum_labels=dict(rec.labels),
        member_spectrum_ids=list(rec.member_spectrum_ids),
    )


def average_refs(
    *,
    dataset_id: str,
    refs: Sequence[Any],
    finals: dict[str, XY],
    params: GroupAverageParams,
    planned: Sequence[PlannedGroup] | None = None,
) -> tuple[list[DerivedSpectrumRef], list[str]]:
    """
    Group the processed spectra ``finals`` (keyed by spectrum_id) and return derived refs + warnings.

    Labels come from the same source the QC / filter code uses (upload labels per path + block).
    """
    contexts = {c.spectrum_id: c for c in load_spectrum_contexts(list(refs))}
    members = [
        GroupMember(spectrum_id=str(r.spectrum_id), xy=finals[str(r.spectrum_id)], labels=contexts[str(r.spectrum_id)].labels)
        for r in refs
        if str(r.spectrum_id) in finals and str(r.spectrum_id) in contexts
    ]
    groups = group_average(members, params, dataset_id=dataset_id, planned=planned)
    rule = params.rule_dict()
    derived: list[DerivedSpectrumRef] = []
    warnings: list[str] = []
    for g in groups:
        first = contexts.get(g.member_ids[0])
        x_header = _x_header(dict(first.labels) if first else {})
        derived.append(materialize_group(g, dataset_id=dataset_id, rule=rule, x_header=x_header))
        warnings.extend(f"{g.spectrum_id}: {w}" for w in g.warnings)
    return derived, warnings

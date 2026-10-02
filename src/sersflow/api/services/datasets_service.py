from __future__ import annotations

from pathlib import Path
from typing import Any

from sersflow.api.schemas.datasets import DatasetCreateRequest, SpectrumRef
from sersflow.api.services.ownership import OwnershipError, assert_paths_owner
from sersflow.api.services.uploads import resolve_existing_upload
from sersflow.core.io.formats import get_format_for_path
from sersflow.core.io.load_file import load_dataset
from sersflow.core.io.multi_block_labels import (
    get_block_spectra,
    merge_block_structural_preserving_experimental,
    set_block_spectra,
)
from sersflow.core.io.read_vms import filter_indices_by_xps_regions, filter_meta_indices
from sersflow.core.io.technique import assert_homogeneous_technique_families
from sersflow.core.ids import spectrum_id_from_ref
from sersflow.core.models.datasets import Dataset, MapDataset, MultiSpectrumDataset, SeriesDataset, SpectrumDataset
from sersflow.infra.datasets_store import DatasetRecord, create_dataset
from sersflow.infra.upload_labels_store import fetch_upload_labels_for_paths, upsert_upload_labels, with_connection


def _persist_multi_spectrum_labels(
    *,
    relative_path: str,
    meta_by_index: dict[str, dict[str, Any]],
    vms_spectrum_mode: str,
    xps_regions_filter: list[str] | None = None,
) -> None:
    """
    Update upload_labels for kept blocks without discarding other blocks in the file.

    Creating a small region/mode subset must not shrink ``vms_spectra`` — the upload
    picker needs the full block map for XPS region selection.
    """
    from sersflow.core.io.formats import get_format_for_path
    from sersflow.core.io.multi_block_labels import is_multi_spectrum_path
    from sersflow.core.io.upload_registry import resolve_uploaded_path, upload_root

    con = with_connection()
    try:
        existing = fetch_upload_labels_for_paths(con, [relative_path]).get(relative_path) or {}
        labels = dict(existing)
        prev_blocks = get_block_spectra(labels)

        # Prefer a full on-disk rebuild so subset dataset creates cannot leave a tiny map.
        base_blocks = dict(prev_blocks)
        try:
            p = resolve_uploaded_path(upload_root(), relative_path)
            if p.exists() and is_multi_spectrum_path(p):
                fmt = get_format_for_path(p)
                ds = load_dataset(p)
                if fmt.enrich is not None:
                    er = fmt.enrich(p, ds, labels)
                    labels = er.labels
                    if er.block_map:
                        base_blocks = dict(er.block_map)
        except Exception:
            # Fall back to previous map / kept-only overlay below.
            pass

        merged: dict[str, dict[str, Any]] = dict(base_blocks)
        for idx, fresh in meta_by_index.items():
            key = str(idx)
            merged[key] = merge_block_structural_preserving_experimental(
                previous=merged.get(key) or prev_blocks.get(key),
                fresh_structural=dict(fresh or {}),
            )
        set_block_spectra(labels, merged)
        labels["vms_spectrum_mode"] = vms_spectrum_mode
        if xps_regions_filter:
            labels["xps_regions_filter"] = list(xps_regions_filter)
        else:
            labels.pop("xps_regions_filter", None)
        # Convenience: if the file truly has only one spectrum, flatten keys at top level.
        if len(merged) == 1:
            only = next(iter(merged.values()))
            for k, v in only.items():
                if v is not None:
                    labels[k] = v
        upsert_upload_labels(con, relative_path=relative_path, labels=labels)
    finally:
        con.close()


# Backwards-compatible alias
_persist_vms_spectrum_labels = _persist_multi_spectrum_labels


def create_dataset_from_uploads(
    payload: DatasetCreateRequest,
    *,
    owner_user_id: str,
) -> tuple[DatasetRecord, list[dict[str, str]]]:
    """
    Build a dataset from upload paths. Each path is loaded independently; failures are recorded
    so one bad file does not block the rest (large multi-select / Select all).
    """
    spectra: list[SpectrumRef] = []
    skipped: list[dict[str, str]] = []
    mode = payload.vms_spectrum_mode
    regions = [str(r).strip() for r in (payload.xps_regions or []) if str(r).strip()] or None

    try:
        assert_paths_owner(owner_user_id, list(payload.relative_paths))
    except OwnershipError as e:
        raise ValueError(f"Upload not accessible: {e}") from e

    loaded: list[tuple[str, Path, Dataset]] = []
    for rel in payload.relative_paths:
        try:
            p = resolve_existing_upload(rel, owner_user_id=owner_user_id)
            ds = load_dataset(p)
            loaded.append((rel, p, ds))
        except Exception as e:
            skipped.append({"relative_path": rel, "reason": str(e)})

    if loaded:
        try:
            family = assert_homogeneous_technique_families([p for _, p, _ in loaded])
        except ValueError as e:
            raise ValueError(str(e)) from e
        caps: set[str] = set()
        for _rel, p, _ds in loaded:
            try:
                caps |= set(get_format_for_path(p).all_capabilities())
            except ValueError:
                continue
        meta = payload.metadata.model_copy(
            update={"technique_family": family, "capabilities": sorted(caps)}
        )
    else:
        meta = payload.metadata

    for rel, _p, ds in loaded:
        try:
            if isinstance(ds, SpectrumDataset):
                spectra.append(
                    SpectrumRef(
                        spectrum_id=spectrum_id_from_ref(relative_path=rel, record_index=None),
                        relative_path=rel,
                        record_index=None,
                    )
                )
                continue

            if isinstance(ds, MultiSpectrumDataset):
                keep = filter_meta_indices(ds.meta, mode)
                keep = filter_indices_by_xps_regions(ds.meta, keep, regions)
                wanted = None
                if payload.record_indices and rel in payload.record_indices:
                    raw_idxs = payload.record_indices.get(rel) or []
                    wanted = {int(i) for i in raw_idxs if int(i) >= 0}
                if wanted is not None:
                    keep = [i for i in keep if i in wanted]
                if not keep:
                    reason = "No multi-spectrum blocks matched vms_spectrum_mode"
                    if regions:
                        reason += f" / xps_regions={regions!r}"
                    if wanted is not None:
                        reason += " / record_indices"
                    skipped.append({"relative_path": rel, "reason": reason})
                    continue
                meta_by_index: dict[str, dict[str, Any]] = {}
                for i in keep:
                    spectra.append(
                        SpectrumRef(
                            spectrum_id=spectrum_id_from_ref(relative_path=rel, record_index=i),
                            relative_path=rel,
                            record_index=i,
                        )
                    )
                    meta_by_index[str(i)] = dict(ds.meta[i] or {})
                try:
                    _persist_multi_spectrum_labels(
                        relative_path=rel,
                        meta_by_index=meta_by_index,
                        vms_spectrum_mode=mode,
                        xps_regions_filter=regions,
                    )
                except Exception as e:
                    skipped.append(
                        {
                            "relative_path": rel,
                            "reason": f"Loaded spectra but failed to persist multi-spectrum labels: {e}",
                        }
                    )
                continue

            if isinstance(ds, (SeriesDataset, MapDataset)):
                n = int(ds.spectra.shape[0])
                for i in range(n):
                    spectra.append(
                        SpectrumRef(
                            spectrum_id=spectrum_id_from_ref(relative_path=rel, record_index=i),
                            relative_path=rel,
                            record_index=i,
                        )
                    )
                continue

            skipped.append({"relative_path": rel, "reason": f"Unsupported dataset type from loader: {type(ds)}"})
        except Exception as e:
            skipped.append({"relative_path": rel, "reason": str(e)})

    if not spectra:
        parts = [f"{s['relative_path']}: {s['reason']}" for s in skipped[:25]]
        tail = ""
        if len(skipped) > 25:
            tail = f" … and {len(skipped) - 25} more"
        raise ValueError(
            "No spectra could be loaded from the selected files. "
            + ("; ".join(parts) if parts else "No paths given.")
            + tail
        )

    rec = create_dataset(metadata=meta, spectra=spectra, owner_user_id=owner_user_id)
    return rec, skipped

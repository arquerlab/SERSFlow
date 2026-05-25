from __future__ import annotations

from sersflow.api.schemas.datasets import DatasetCreateRequest, SpectrumRef
from sersflow.api.services.uploads import resolve_existing_upload
from sersflow.core.io.load_file import load_dataset
from sersflow.core.ids import spectrum_id_from_ref
from sersflow.core.models.datasets import MapDataset, SeriesDataset, SpectrumDataset
from sersflow.infra.datasets_store import DatasetRecord, create_dataset


def create_dataset_from_uploads(payload: DatasetCreateRequest) -> tuple[DatasetRecord, list[dict[str, str]]]:
    """
    Build a dataset from upload paths. Each path is loaded independently; failures are recorded
    so one bad file does not block the rest (large multi-select / Select all).
    """
    spectra: list[SpectrumRef] = []
    skipped: list[dict[str, str]] = []

    for rel in payload.relative_paths:
        try:
            p = resolve_existing_upload(rel)
            ds = load_dataset(p)

            if isinstance(ds, SpectrumDataset):
                spectra.append(
                    SpectrumRef(
                        spectrum_id=spectrum_id_from_ref(relative_path=rel, record_index=None),
                        relative_path=rel,
                        record_index=None,
                    )
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

    rec = create_dataset(metadata=payload.metadata, spectra=spectra)
    return rec, skipped


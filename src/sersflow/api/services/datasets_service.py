from __future__ import annotations

from sersflow.api.schemas.datasets import DatasetCreateRequest, SpectrumRef
from sersflow.api.services.uploads import resolve_existing_upload
from sersflow.core.io.load_file import load_dataset
from sersflow.core.ids import spectrum_id_from_ref
from sersflow.core.models.datasets import MapDataset, SeriesDataset, SpectrumDataset
from sersflow.infra.datasets_store import DatasetRecord, create_dataset


def create_dataset_from_uploads(payload: DatasetCreateRequest) -> DatasetRecord:
    spectra: list[SpectrumRef] = []
    for rel in payload.relative_paths:
        # Validates path traversal + existence using existing upload resolver.
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

        raise TypeError(f"Unsupported dataset type from loader: {type(ds)}")
    return create_dataset(metadata=payload.metadata, spectra=spectra)


from __future__ import annotations

from sersflow.api.schemas.datasets import DatasetCreateRequest, SpectrumRef
from sersflow.api.services.uploads import resolve_existing_upload
from sersflow.core.ids import spectrum_id_from_ref
from sersflow.infra.datasets_store import DatasetRecord, create_dataset


def create_dataset_from_uploads(payload: DatasetCreateRequest) -> DatasetRecord:
    spectra: list[SpectrumRef] = []
    for rel in payload.relative_paths:
        # Validates path traversal + existence using existing upload resolver.
        resolve_existing_upload(rel)
        spectra.append(SpectrumRef(spectrum_id=spectrum_id_from_ref(relative_path=rel), relative_path=rel))
    return create_dataset(metadata=payload.metadata, spectra=spectra)


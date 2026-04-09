from __future__ import annotations

import os
from pathlib import Path

from sersflow.api.schemas.datasets import DatasetMetadata, SpectrumRef
from sersflow.infra.datasets_store import create_dataset, get_dataset, list_datasets


def test_datasets_store_create_get_list(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("SERSFLOW_DB_PATH", str(tmp_path / "test.db"))

    md = DatasetMetadata(name="t", tags=["a"])
    spectra = [
        SpectrumRef(spectrum_id="sp_1", relative_path="uploads/x/a.txt"),
        SpectrumRef(spectrum_id="sp_2", relative_path="uploads/x/b.txt"),
    ]
    rec = create_dataset(metadata=md, spectra=spectra)
    assert rec.dataset_id.startswith("ds_")

    got = get_dataset(rec.dataset_id)
    assert got is not None
    assert got.dataset_id == rec.dataset_id
    assert got.metadata.name == "t"
    assert len(got.spectra) == 2

    items = list_datasets(limit=10, offset=0)
    assert any(x.dataset_id == rec.dataset_id for x in items)


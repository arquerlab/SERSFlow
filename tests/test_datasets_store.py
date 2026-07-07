from __future__ import annotations

from pathlib import Path

import pytest

from sersflow.api.schemas.datasets import DatasetCreateRequest, DatasetMetadata, SpectrumRef
from sersflow.infra.datasets_store import create_dataset, get_dataset, list_datasets


def test_dataset_create_request_default_name_when_missing() -> None:
    req_empty = DatasetCreateRequest(relative_paths=["batch/a.txt"], metadata=DatasetMetadata())
    assert req_empty.metadata.name is not None
    assert str(req_empty.metadata.name).startswith("Unnamed dataset ")

    req_ws = DatasetCreateRequest(relative_paths=["batch/a.txt"], metadata=DatasetMetadata(name="   "))
    assert req_ws.metadata.name is not None
    assert str(req_ws.metadata.name).startswith("Unnamed dataset ")

    req_named = DatasetCreateRequest(relative_paths=["batch/a.txt"], metadata=DatasetMetadata(name="  Cu run  "))
    assert req_named.metadata.name == "Cu run"


def test_datasets_store_create_get_list(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("SERSFLOW_DB_PATH", str(tmp_path / "test.db"))

    md = DatasetMetadata(name="t", tags=["a"])
    spectra = [
        SpectrumRef(spectrum_id="sp_1", relative_path="batch/a.txt"),
        SpectrumRef(spectrum_id="sp_2", relative_path="batch/b.txt"),
    ]
    rec = create_dataset(owner_user_id="dev", metadata=md, spectra=spectra)
    assert rec.dataset_id.startswith("ds_")

    got = get_dataset(rec.dataset_id, owner_user_id="dev")
    assert got is not None
    assert got.dataset_id == rec.dataset_id
    assert got.metadata.name == "t"
    assert len(got.spectra) == 2

    items = list_datasets(owner_user_id="dev", limit=10, offset=0)
    assert any(x.dataset_id == rec.dataset_id for x in items)


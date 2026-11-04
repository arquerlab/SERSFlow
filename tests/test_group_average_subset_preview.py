"""Subset previews: raw views show the subset spectra, views at/after Aggregate Spectra show complete groups."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

from sersflow.api.main import app
from sersflow.api.schemas.datasets import DatasetCreateRequest, DatasetMetadata
from sersflow.api.schemas.pipeline import Pipeline, PipelineStep
from sersflow.api.services.datasets_service import create_dataset_from_uploads
from sersflow.infra.upload_labels_store import upsert_upload_labels, with_connection

# id, current density, region, level
_SPECTRA = [
    ("sp_1", 10.0, "C1s", 1.0),
    ("sp_2", 10.0, "C1s", 3.0),
    ("sp_3", 20.0, "C1s", 5.0),
    ("sp_4", 20.0, "C1s", 7.0),
    ("sp_5", 10.0, "O1s", 9.0),
    ("sp_6", 20.0, "O1s", 11.0),
]


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("SERSFLOW_DB_PATH", str(tmp_path / "sess.db"))
    monkeypatch.setenv("SERSFLOW_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("SERSFLOW_AUTH_DISABLED", "1")
    upload_root = tmp_path / ".sersflow_uploads"
    monkeypatch.setenv("SERSFLOW_UPLOAD_DIR", str(upload_root))
    (upload_root / "g1").mkdir(parents=True, exist_ok=True)
    return TestClient(app), upload_root


def _dataset(upload_root: Path):
    rels = []
    con = with_connection()
    try:
        for sid, cur, region, level in _SPECTRA:
            f = upload_root / "g1" / f"{sid}.txt"
            f.write_text(f"wn\tint\n100\t{level}\n200\t{level * 2}\n300\t{level}\n", encoding="utf-8")
            rel = f"g1/{sid}.txt"
            upsert_upload_labels(con, relative_path=rel, labels={"current_density": cur, "xps_region": region})
            rels.append(rel)
    finally:
        con.close()
    rec, skipped = create_dataset_from_uploads(
        DatasetCreateRequest(relative_paths=rels, metadata=DatasetMetadata(name="grp")), owner_user_id="dev"
    )
    assert not skipped and len(rec.spectra) == 6
    return rec


def _session(api, rec, indices: list[int]) -> str:
    pipe = Pipeline(
        steps=[
            PipelineStep(name="crop", params={"min_x": 100.0, "max_x": 300.0}, step_id="1"),
            PipelineStep(
                name="group_average",
                params={"method": "by_label", "group_by": ["current_density"], "reducer": "mean"},
                step_id="2",
            ),
            PipelineStep(name="crop", params={"min_x": 150.0, "max_x": 300.0}, step_id="3"),
        ]
    )
    r = api.post("/sessions", json={"dataset_id": rec.dataset_id, "pipeline": pipe.model_dump()})
    assert r.status_code == 200, r.text
    sid = r.json()["session"]["session_id"]
    r = api.post(f"/sessions/{sid}/subset", json={"kind": "indices", "indices": indices})
    assert r.status_code == 200, r.text
    return sid


def _run(api, sid: str, **body):
    r = api.post(f"/sessions/{sid}/run", json={"scope": "subset", "return": {"kind": "final"}, **body})
    assert r.status_code == 200, r.text
    return r.json()["items"]


def test_subset_previews_raw_before_and_complete_groups_after(client) -> None:
    api, upload_root = client
    rec = _dataset(upload_root)
    ids = [s.spectrum_id for s in rec.spectra]
    by_name = {f"sp_{i + 1}": ids[i] for i in range(6)}
    # Subset: sp_1, sp_4, sp_5 (positions 0, 3, 4), as in the example.
    sid = _session(api, rec, [0, 3, 4])

    # Before the aggregate step (raw / crop): the subset's own spectra, nothing aggregated.
    raw = _run(api, sid, up_to_step="__source__")
    assert {it["spectrum_id"] for it in raw} == {by_name["sp_1"], by_name["sp_4"], by_name["sp_5"]}

    # After the aggregate step: the groups those spectra belong to (C1s@10, C1s@20, O1s@10), complete.
    final = _run(api, sid)
    assert len(final) == 3
    assert all(it["spectrum_id"].startswith("grp_") for it in final)
    by_members = {frozenset(it["derived"]["member_spectrum_ids"]): it for it in final}
    assert set(by_members) == {
        frozenset({by_name["sp_1"], by_name["sp_2"]}),  # sp_2 is not in the subset but completes the group
        frozenset({by_name["sp_3"], by_name["sp_4"]}),
        frozenset({by_name["sp_5"]}),
    }
    c1s_10 = by_members[frozenset({by_name["sp_1"], by_name["sp_2"]})]
    assert c1s_10["derived"]["n_members"] == 2
    assert np.isclose(c1s_10["y"][0], 4.0)  # mean(2, 6) at wn=200, complete group not just sp_1


def test_view_at_a_step_before_the_group_is_raw(client) -> None:
    api, upload_root = client
    rec = _dataset(upload_root)
    sid = _session(api, rec, [0, 3, 4])
    r = api.post(
        f"/sessions/{sid}/run",
        json={"scope": "subset", "return": {"kind": "intermediates", "steps": ["crop__1"]}},
    )
    assert r.status_code == 200, r.text
    items = r.json()["items"]
    assert len(items) == 3
    assert not any(it["spectrum_id"].startswith("grp_") for it in items)

    r = api.post(
        f"/sessions/{sid}/run",
        json={"scope": "subset", "return": {"kind": "intermediates", "steps": ["crop__3"]}},
    )
    assert r.status_code == 200, r.text
    after = r.json()["items"]
    assert len(after) == 3 and all(it["spectrum_id"].startswith("grp_") for it in after)


def test_same_group_from_two_subset_spectra_appears_once(client) -> None:
    api, upload_root = client
    rec = _dataset(upload_root)
    sid = _session(api, rec, [0, 1])  # sp_1 and sp_2 are both in C1s@10
    final = _run(api, sid)
    assert len(final) == 1 and final[0]["derived"]["n_members"] == 2


def test_derived_ref_round_trips_through_pipeline_run(client) -> None:
    """Baseline / fitting previews after the group feed the aggregated refs back into /pipeline/run."""
    api, upload_root = client
    rec = _dataset(upload_root)
    sid = _session(api, rec, [0, 3, 4])
    final = _run(api, sid, up_to_step="__raw__")
    refs = [it["derived"]["ref"] for it in final]
    assert len(refs) == 3 and all(r["blob_relative_path"] for r in refs)

    r = api.post(
        "/pipeline/run",
        json={
            "inputs": refs,
            "pipeline": {"steps": [{"name": "crop", "params": {"min_x": 150.0, "max_x": 300.0}, "enabled": True}]},
            "return": {"kind": "final"},
        },
    )
    assert r.status_code == 200, r.text
    items = r.json()["items"]
    assert {it["spectrum_id"] for it in items} == {x["spectrum_id"] for x in refs}
    assert all(it["x"] and min(it["x"]) >= 150.0 for it in items)

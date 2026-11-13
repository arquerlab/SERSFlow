"""Cross-user isolation regressions (security audit, phase A): one user must not reach another user's data."""

from __future__ import annotations

import hashlib
import json
import zipfile
from io import BytesIO
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from sersflow.api.main import app
from sersflow.api.schemas.datasets import DatasetMetadata, SpectrumRef
from sersflow.api.schemas.pipeline import Pipeline
from sersflow.api.schemas.sessions import SubsetStrategy
from sersflow.api.services.ownership import invalidate_registry_cache
from sersflow.core.io.upload_registry import append_upload_registry, make_registry_item, upload_root
from sersflow.infra.auth_store import create_user, get_user_by_username
from sersflow.infra.blob_store import data_root
from sersflow.infra.datasets_store import create_dataset, get_dataset_internal
from sersflow.infra.reference_spectra_store import create_reference
from sersflow.infra.sessions_store import create_session, get_session
from sersflow.infra.upload_labels_store import fetch_upload_labels_for_paths, upsert_upload_labels, with_connection

SPECTRUM = "wn\tint\n100\t1\n200\t2\n300\t3\n"


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.delenv("SERSFLOW_AUTH_DISABLED", raising=False)
    monkeypatch.setenv("SERSFLOW_AUTH_SECRET", "test-secret-key-for-auth-tests-only")
    monkeypatch.setenv("SERSFLOW_DB_PATH", str(tmp_path / "auth.db"))
    monkeypatch.setenv("SERSFLOW_UPLOAD_DIR", str(tmp_path / "uploads"))
    monkeypatch.setenv("SERSFLOW_DATA_DIR", str(tmp_path / "data"))
    invalidate_registry_cache()
    return TestClient(app)


def _users() -> tuple[str, str]:
    create_user(username="alice", password="pass-a")
    create_user(username="bob", password="pass-b")
    alice, bob = get_user_by_username("alice"), get_user_by_username("bob")
    assert alice is not None and bob is not None
    return alice.user_id, bob.user_id


def _login(client: TestClient, username: str, password: str) -> None:
    r = client.post("/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text


def _upload(owner_user_id: str, rel: str, text: str = SPECTRUM) -> str:
    root = upload_root()
    (root / rel).parent.mkdir(parents=True, exist_ok=True)
    (root / rel).write_text(text, encoding="utf-8")
    batch, _, name = rel.partition("/")
    append_upload_registry(
        root,
        [make_registry_item(batch_id=batch, filename=name, size_bytes=len(text), owner_user_id=owner_user_id).to_dict()],
    )
    invalidate_registry_cache()
    return rel


def _dataset(owner_user_id: str, rel: str, sid: str = "s1"):
    return create_dataset(
        owner_user_id=owner_user_id,
        metadata=DatasetMetadata(name=f"ds-{sid}"),
        spectra=[SpectrumRef(spectrum_id=sid, relative_path=rel)],
    )


def _package(manifest: dict, files: dict[str, bytes]) -> bytes:
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("manifest.json", json.dumps(manifest))
        for name, data in files.items():
            zf.writestr(name, data)
    return buf.getvalue()


def _import(client: TestClient, package: bytes):
    return client.post("/datasets/import", files={"file": ("p.sersflow-dataset.zip", package, "application/zip")})


@pytest.mark.auth
def test_import_cannot_attach_another_users_upload(client: TestClient) -> None:
    alice_id, _ = _users()
    rel = _upload(alice_id, "batch-alice/secret.txt")
    manifest = {
        "schema_version": "sersflow.dataset.v1",
        "dataset": {"metadata": {"name": "steal"}},
        "blobs": {},
        "spectra": [{"spectrum_id": "s1", "relative_path": rel}],
    }
    _login(client, "bob", "pass-b")
    r = _import(client, _package(manifest, {}))
    assert r.status_code == 400, r.text
    assert client.get("/datasets").json()["items"] == []


@pytest.mark.auth
def test_import_ignores_manifest_blob_location_and_foreign_paths(client: TestClient) -> None:
    alice_id, _ = _users()
    rel = _upload(alice_id, "batch-alice/secret.txt")
    con = with_connection()
    try:
        upsert_upload_labels(con, relative_path=rel, labels={"sample": "alice"})
    finally:
        con.close()

    payload = b"wn\tint\n1\t1\n2\t2\n"
    blob_id = hashlib.sha256(payload).hexdigest()
    manifest = {
        "schema_version": "sersflow.dataset.v1",
        "dataset": {"metadata": {"name": "odd"}},
        "blobs": {
            blob_id: {"blob_id": blob_id, "blob_relative_path": "planted/elsewhere.txt", "zip_path": "blobs/x.txt"}
        },
        "spectra": [
            {
                "spectrum_id": "s1",
                "relative_path": rel,
                "blob_id": blob_id,
                # A spectrum row may not choose where its data is read from either.
                "blob_relative_path": "../uploads/" + rel,
            }
        ],
        "labels": {rel: {"sample": "overwritten-by-bob"}},
    }
    _login(client, "bob", "pass-b")
    r = _import(client, _package(manifest, {"blobs/x.txt": payload}))
    assert r.status_code == 200, r.text

    assert not (data_root() / "planted").exists()
    rec = get_dataset_internal(r.json()["dataset"]["dataset_id"])
    assert rec is not None
    ref = rec.spectra[0]
    assert ref.blob_relative_path == f"blobs/{blob_id[:2]}/{blob_id}.txt"
    assert ref.relative_path != rel and ref.relative_path.startswith("imported/")
    assert (ref.original_relative_path or "").startswith("imported/")

    con = with_connection()
    try:
        labels = fetch_upload_labels_for_paths(con, [rel, ref.relative_path])
    finally:
        con.close()
    assert labels[rel]["sample"] == "alice"
    assert labels[ref.relative_path]["sample"] == "overwritten-by-bob"

    # "Restore uploads" on the imported dataset must copy bob's blob, not reactivate alice's file.
    r = client.post(f"/datasets/{rec.dataset_id}/restore-uploads")
    assert r.status_code == 200, r.text
    body = r.json()
    assert not body["reactivated"] and not body["already_active"]
    assert all(item["relative_path"] != rel for item in body["restored"])


@pytest.mark.auth
def test_purge_preview_lists_only_own_uploads(client: TestClient) -> None:
    alice_id, bob_id = _users()
    _upload(alice_id, "batch-alice/secret.txt")
    mine = _upload(bob_id, "batch-bob/mine.txt")
    _login(client, "bob", "pass-b")
    r = client.post("/io/purge/preview", json={"hidden_only": False})
    assert r.status_code == 200, r.text
    assert [item["relative_path"] for item in r.json()["items"]] == [mine]


@pytest.mark.auth
def test_pipeline_run_rejects_another_users_blob(client: TestClient) -> None:
    alice_id, bob_id = _users()
    alice_ds = _dataset(alice_id, _upload(alice_id, "batch-alice/secret.txt"), "a1")
    mine = _upload(bob_id, "batch-bob/mine.txt", "wn\tint\n10\t5\n20\t6\n")
    bob_ds = _dataset(bob_id, mine, "b1")
    alice_blob = alice_ds.spectra[0].blob_relative_path
    bob_blob = bob_ds.spectra[0].blob_relative_path
    assert alice_blob and bob_blob and alice_blob != bob_blob

    _login(client, "bob", "pass-b")
    for path in ("/pipeline/run", "/metrics/compute"):
        body: dict = {"inputs": [{"spectrum_id": "x", "relative_path": mine, "blob_relative_path": alice_blob}]}
        if path == "/pipeline/run":
            body["return"] = {"kind": "final"}
        else:
            body["metrics"] = ["mean"]
        r = client.post(path, json=body)
        assert r.status_code == 404, (path, r.text)

    ok = client.post(
        "/pipeline/run",
        json={
            "inputs": [{"spectrum_id": "b1", "relative_path": mine, "blob_relative_path": bob_blob}],
            "return": {"kind": "final"},
        },
    )
    assert ok.status_code == 200, ok.text
    assert ok.json()["items"][0]["x"] == [10.0, 20.0]


@pytest.mark.auth
def test_delete_foreign_dataset_keeps_its_sessions(client: TestClient) -> None:
    alice_id, _ = _users()
    ds = _dataset(alice_id, _upload(alice_id, "batch-alice/secret.txt"))
    sess = create_session(dataset_id=ds.dataset_id, pipeline=Pipeline(steps=[]), subset=SubsetStrategy(kind="all"))
    _login(client, "bob", "pass-b")
    r = client.delete(f"/datasets/{ds.dataset_id}")
    assert r.status_code == 404
    assert get_session(sess.session_id) is not None


@pytest.mark.auth
def test_fit_rejects_another_users_reference_spectrum(client: TestClient) -> None:
    alice_id, bob_id = _users()
    x = [float(i) for i in range(20)]
    y = [1.0 + (i % 5) for i in range(20)]
    theirs = create_reference(owner_user_id=alice_id, name="alice-ref", x=x, y=y, source={})
    mine = create_reference(owner_user_id=bob_id, name="bob-ref", x=x, y=y, source={})

    def fit(reference_id: str):
        return client.post(
            "/fitting/fit",
            json={
                "target": {"kind": "inline", "x": x, "y": y},
                "components": [
                    {"component_id": "r1", "component_type": "reference_spectrum", "reference_id": reference_id}
                ],
                "p0": [1.0, 0.0],
                "fit": False,
                "technique_family": "xps",
            },
        )

    _login(client, "bob", "pass-b")
    assert fit(theirs.reference_id).status_code == 404
    assert fit(mine.reference_id).status_code != 404

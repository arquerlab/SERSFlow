from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from sersflow.api.main import app
from sersflow.api.services.ownership import invalidate_registry_cache
from sersflow.core.io.upload_registry import make_registry_item, upload_root, write_upload_registry
from sersflow.infra.auth_store import create_user, get_user_by_username


@pytest.fixture
def auth_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.delenv("SERSFLOW_AUTH_DISABLED", raising=False)
    monkeypatch.setenv("SERSFLOW_AUTH_SECRET", "test-secret-key-for-auth-tests-only")
    monkeypatch.setenv("SERSFLOW_DB_PATH", str(tmp_path / "auth.db"))
    monkeypatch.setenv("SERSFLOW_UPLOAD_DIR", str(tmp_path / "uploads"))
    monkeypatch.setenv("SERSFLOW_DATA_DIR", str(tmp_path / "data"))
    return tmp_path


@pytest.fixture
def auth_client(auth_env: Path) -> TestClient:
    return TestClient(app)


def _login(client: TestClient, username: str, password: str) -> None:
    r = client.post("/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text


def _register_owned_upload(*, owner_user_id: str, rel: str = "batch-a/file.txt") -> str:
    root = upload_root()
    root.mkdir(parents=True, exist_ok=True)
    (root / rel).parent.mkdir(parents=True, exist_ok=True)
    (root / rel).write_text("x", encoding="utf-8")
    write_upload_registry(
        root,
        [
            make_registry_item(
                batch_id=rel.split("/")[0],
                filename=rel.split("/")[-1],
                size_bytes=1,
                owner_user_id=owner_user_id,
            ).to_dict()
        ],
    )
    invalidate_registry_cache()
    return rel


@pytest.mark.auth
def test_protected_route_requires_cookie(auth_client: TestClient) -> None:
    r = auth_client.get("/datasets")
    assert r.status_code == 401


@pytest.mark.auth
def test_login_and_list_datasets(auth_client: TestClient) -> None:
    create_user(username="alice", password="pass-a")
    _login(auth_client, "alice", "pass-a")
    r = auth_client.get("/datasets")
    assert r.status_code == 200
    assert r.json()["items"] == []


@pytest.mark.auth
def test_cross_user_plot_isolation(auth_client: TestClient) -> None:
    create_user(username="alice", password="pass-a")
    create_user(username="bob", password="pass-b")
    alice = get_user_by_username("alice")
    assert alice is not None

    rel = _register_owned_upload(owner_user_id=alice.user_id)

    _login(auth_client, "bob", "pass-b")
    r = auth_client.post("/plot/spectrum", json={"relative_path": rel})
    assert r.status_code == 404


@pytest.mark.auth
def test_cross_user_fitting_path_isolation(auth_client: TestClient) -> None:
    create_user(username="alice", password="pass-a")
    create_user(username="bob", password="pass-b")
    alice = get_user_by_username("alice")
    assert alice is not None
    rel = _register_owned_upload(owner_user_id=alice.user_id)

    _login(auth_client, "bob", "pass-b")
    r = auth_client.post(
        "/fitting/fit",
        json={
            "target": {"kind": "spectrum_ref", "spectrum": {"spectrum_id": "s1", "relative_path": rel}},
            "components": [{"component_id": "g1", "component_type": "gaussian"}],
        },
    )
    assert r.status_code == 404


@pytest.mark.auth
def test_cross_user_pipeline_path_isolation(auth_client: TestClient) -> None:
    create_user(username="alice", password="pass-a")
    create_user(username="bob", password="pass-b")
    alice = get_user_by_username("alice")
    assert alice is not None
    rel = _register_owned_upload(owner_user_id=alice.user_id)

    _login(auth_client, "bob", "pass-b")
    r = auth_client.post(
        "/pipeline/run",
        json={
            "inputs": [{"spectrum_id": "s1", "relative_path": rel}],
            "return": {"kind": "final"},
        },
    )
    assert r.status_code == 404


@pytest.mark.auth
def test_cross_user_metrics_path_isolation(auth_client: TestClient) -> None:
    create_user(username="alice", password="pass-a")
    create_user(username="bob", password="pass-b")
    alice = get_user_by_username("alice")
    assert alice is not None
    rel = _register_owned_upload(owner_user_id=alice.user_id)

    _login(auth_client, "bob", "pass-b")
    r = auth_client.post(
        "/metrics/compute",
        json={
            "inputs": [{"spectrum_id": "s1", "relative_path": rel}],
            "metrics": ["mean"],
        },
    )
    assert r.status_code == 404


@pytest.mark.auth
def test_cross_user_dataset_isolation(auth_client: TestClient) -> None:
    from sersflow.api.schemas.datasets import DatasetMetadata, SpectrumRef
    from sersflow.infra.datasets_store import create_dataset

    create_user(username="alice", password="pass-a")
    create_user(username="bob", password="pass-b")
    alice = get_user_by_username("alice")
    assert alice is not None

    rec = create_dataset(
        owner_user_id=alice.user_id,
        metadata=DatasetMetadata(name="secret"),
        spectra=[SpectrumRef(spectrum_id="s1", relative_path="a/b.txt")],
    )

    _login(auth_client, "bob", "pass-b")
    r = auth_client.get(f"/datasets/{rec.dataset_id}")
    assert r.status_code == 404


@pytest.mark.auth
def test_get_dataset_internal_only_in_workers() -> None:
    allowed = {
        "src/sersflow/infra/datasets_store.py",
        "src/sersflow/api/services/analysis_runner.py",
        "src/sersflow/api/services/matrix_export_runner.py",
        "src/sersflow/api/services/ownership.py",
    }
    root = Path(__file__).resolve().parents[1]
    offenders: list[str] = []
    for path in root.glob("src/**/*.py"):
        rel = path.relative_to(root).as_posix()
        if rel in allowed:
            continue
        text = path.read_text(encoding="utf-8")
        if "get_dataset_internal" in text:
            offenders.append(rel)
    assert offenders == []


@pytest.mark.auth
def test_cross_user_session_isolation(auth_client: TestClient) -> None:
    from sersflow.api.schemas.datasets import DatasetMetadata, SpectrumRef
    from sersflow.api.schemas.pipeline import Pipeline
    from sersflow.api.schemas.sessions import SubsetStrategy
    from sersflow.infra.datasets_store import create_dataset
    from sersflow.infra.sessions_store import create_session

    create_user(username="alice", password="pass-a")
    create_user(username="bob", password="pass-b")
    alice = get_user_by_username("alice")
    assert alice is not None

    rec = create_dataset(
        owner_user_id=alice.user_id,
        metadata=DatasetMetadata(name="secret"),
        spectra=[SpectrumRef(spectrum_id="s1", relative_path="a/b.txt")],
    )
    sess = create_session(
        dataset_id=rec.dataset_id,
        pipeline=Pipeline(steps=[]),
        subset=SubsetStrategy(kind="all"),
    )

    _login(auth_client, "bob", "pass-b")
    r = auth_client.get(f"/sessions/{sess.session_id}")
    assert r.status_code == 404


@pytest.mark.auth
def test_cross_user_analysis_run_isolation(auth_client: TestClient) -> None:
    from sersflow.api.schemas.datasets import DatasetMetadata, SpectrumRef
    from sersflow.infra.analysis_store import create_run_pending
    from sersflow.infra.datasets_store import create_dataset

    create_user(username="alice", password="pass-a")
    create_user(username="bob", password="pass-b")
    alice = get_user_by_username("alice")
    assert alice is not None

    rec = create_dataset(
        owner_user_id=alice.user_id,
        metadata=DatasetMetadata(name="secret"),
        spectra=[SpectrumRef(spectrum_id="s1", relative_path="a/b.txt")],
    )
    run_id = create_run_pending(
        dataset_id=rec.dataset_id,
        session_id=None,
        pipeline_hash="abc",
        subset_hash="def",
        pipeline_json=None,
        label=None,
        pinned=False,
        client_job_key=None,
        params=None,
    )

    _login(auth_client, "bob", "pass-b")
    r = auth_client.get(f"/analysis/runs/{run_id}")
    assert r.status_code == 404


@pytest.mark.auth
def test_cross_user_matrix_job_isolation(auth_client: TestClient) -> None:
    from sersflow.api.schemas.datasets import DatasetMetadata, SpectrumRef
    from sersflow.infra.datasets_store import create_dataset
    from sersflow.infra.explore_store import create_matrix_job_pending

    create_user(username="alice", password="pass-a")
    create_user(username="bob", password="pass-b")
    alice = get_user_by_username("alice")
    assert alice is not None

    rec = create_dataset(
        owner_user_id=alice.user_id,
        metadata=DatasetMetadata(name="secret"),
        spectra=[SpectrumRef(spectrum_id="s1", relative_path="a/b.txt")],
    )
    jid = create_matrix_job_pending(
        dataset_id=rec.dataset_id,
        session_id=None,
        pipeline_hash="abc",
        pipeline_json=None,
        subset_hash="def",
        up_to_step=None,
    )

    _login(auth_client, "bob", "pass-b")
    r = auth_client.get(f"/explore/matrix-jobs/{jid}")
    assert r.status_code == 404


@pytest.mark.auth
def test_import_assigns_owner(auth_client: TestClient, auth_env: Path) -> None:
    from sersflow.api.schemas.datasets import DatasetMetadata, SpectrumRef
    from sersflow.api.services.dataset_export import export_dataset_package
    from sersflow.infra.datasets_store import create_dataset, get_dataset

    create_user(username="alice", password="pass-a")
    create_user(username="bob", password="pass-b")
    alice = get_user_by_username("alice")
    bob = get_user_by_username("bob")
    assert alice is not None and bob is not None

    upload_root_dir = auth_env / "uploads"
    upload_root_dir.mkdir(parents=True, exist_ok=True)
    rel = "batch1/a.txt"
    p = upload_root_dir / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("wn\tint\n100\t1\n200\t2\n", encoding="utf-8")
    write_upload_registry(
        upload_root_dir,
        [make_registry_item(batch_id="batch1", filename="a.txt", size_bytes=p.stat().st_size, owner_user_id=alice.user_id).to_dict()],
    )
    invalidate_registry_cache()

    rec = create_dataset(
        owner_user_id=alice.user_id,
        metadata=DatasetMetadata(name="exportable"),
        spectra=[SpectrumRef(spectrum_id="s1", relative_path=rel)],
    )
    package, _ = export_dataset_package(rec.dataset_id, owner_user_id=alice.user_id)

    _login(auth_client, "bob", "pass-b")
    r = auth_client.post(
        "/datasets/import",
        files={"file": ("pkg.sersflow-dataset.zip", package, "application/zip")},
    )
    assert r.status_code == 200, r.text
    imported_id = r.json()["dataset"]["dataset_id"]
    assert get_dataset(imported_id, owner_user_id=bob.user_id) is not None
    assert get_dataset(imported_id, owner_user_id=alice.user_id) is None


@pytest.mark.auth
def test_superuser_can_access_other_user_dataset(auth_client: TestClient) -> None:
    from sersflow.api.schemas.datasets import DatasetMetadata, SpectrumRef
    from sersflow.infra.auth_store import create_user, set_superuser
    from sersflow.infra.datasets_store import create_dataset

    create_user(username="alice", password="pass-a")
    admin = create_user(username="admin", password="pass-admin", is_superuser=True)
    alice = get_user_by_username("alice")
    assert alice is not None and admin.is_superuser

    rec = create_dataset(
        owner_user_id=alice.user_id,
        metadata=DatasetMetadata(name="alice-secret"),
        spectra=[SpectrumRef(spectrum_id="s1", relative_path="a/b.txt")],
    )

    _login(auth_client, "admin", "pass-admin")
    r = auth_client.get(f"/datasets/{rec.dataset_id}")
    assert r.status_code == 200
    assert r.json()["dataset"]["metadata"]["name"] == "alice-secret"


@pytest.mark.auth
def test_superuser_can_access_other_user_upload(auth_client: TestClient) -> None:
    create_user(username="alice", password="pass-a")
    create_user(username="admin", password="pass-admin", is_superuser=True)
    alice = get_user_by_username("alice")
    assert alice is not None

    root = upload_root()
    root.mkdir(parents=True, exist_ok=True)
    rel = "batch-a/spec.txt"
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("wn\tint\n100\t1\n200\t2\n", encoding="utf-8")
    write_upload_registry(
        root,
        [
            make_registry_item(
                batch_id="batch-a",
                filename="spec.txt",
                size_bytes=p.stat().st_size,
                owner_user_id=alice.user_id,
            ).to_dict()
        ],
    )
    invalidate_registry_cache()

    _login(auth_client, "admin", "pass-admin")
    r = auth_client.get(f"/plot/series-info?relative_path={rel}&max_points=5")
    assert r.status_code == 200


@pytest.mark.auth
def test_grant_superuser_cli(auth_env: Path) -> None:
    from sersflow.infra.auth_store import create_user, get_user_by_username, set_superuser

    create_user(username="bob", password="pass-b")
    bob = get_user_by_username("bob")
    assert bob is not None
    assert bob.is_superuser is False
    updated = set_superuser(username="bob", superuser=True)
    assert updated.is_superuser is True


@pytest.mark.auth
def test_superuser_act_as_user_sees_only_that_user_data(auth_client: TestClient) -> None:
    from sersflow.api.data_scope import ACT_AS_COOKIE
    from sersflow.api.schemas.datasets import DatasetMetadata, SpectrumRef
    from sersflow.infra.auth_store import create_user
    from sersflow.infra.datasets_store import create_dataset

    create_user(username="alice", password="pass-a")
    create_user(username="bob", password="pass-b")
    admin = create_user(username="admin", password="pass-admin", is_superuser=True)
    alice = get_user_by_username("alice")
    bob = get_user_by_username("bob")
    assert alice is not None and bob is not None

    alice_ds = create_dataset(
        owner_user_id=alice.user_id,
        metadata=DatasetMetadata(name="alice-set"),
        spectra=[SpectrumRef(spectrum_id="s1", relative_path="a/1.txt")],
    )
    bob_ds = create_dataset(
        owner_user_id=bob.user_id,
        metadata=DatasetMetadata(name="bob-set"),
        spectra=[SpectrumRef(spectrum_id="s1", relative_path="b/1.txt")],
    )

    _login(auth_client, "admin", "pass-admin")
    auth_client.cookies.set(ACT_AS_COOKIE, alice.user_id)

    r_alice = auth_client.get(f"/datasets/{alice_ds.dataset_id}")
    r_bob = auth_client.get(f"/datasets/{bob_ds.dataset_id}")
    assert r_alice.status_code == 200
    assert r_bob.status_code == 404


@pytest.mark.auth
def test_superuser_act_as_all_sees_everyone(auth_client: TestClient) -> None:
    from sersflow.api.data_scope import ACT_AS_ALL, ACT_AS_COOKIE
    from sersflow.api.schemas.datasets import DatasetMetadata, SpectrumRef
    from sersflow.infra.auth_store import create_user
    from sersflow.infra.datasets_store import create_dataset

    create_user(username="alice", password="pass-a")
    create_user(username="bob", password="pass-b")
    create_user(username="admin", password="pass-admin", is_superuser=True)
    alice = get_user_by_username("alice")
    bob = get_user_by_username("bob")
    assert alice is not None and bob is not None

    alice_ds = create_dataset(
        owner_user_id=alice.user_id,
        metadata=DatasetMetadata(name="alice-set"),
        spectra=[SpectrumRef(spectrum_id="s1", relative_path="a/1.txt")],
    )
    bob_ds = create_dataset(
        owner_user_id=bob.user_id,
        metadata=DatasetMetadata(name="bob-set"),
        spectra=[SpectrumRef(spectrum_id="s1", relative_path="b/1.txt")],
    )

    _login(auth_client, "admin", "pass-admin")
    auth_client.cookies.set(ACT_AS_COOKIE, ACT_AS_ALL)

    assert auth_client.get(f"/datasets/{alice_ds.dataset_id}").status_code == 200
    assert auth_client.get(f"/datasets/{bob_ds.dataset_id}").status_code == 200


@pytest.mark.auth
def test_assign_orphans_dry_run(auth_env: Path) -> None:
    from sersflow.api.schemas.datasets import DatasetMetadata, SpectrumRef
    from sersflow.infra.datasets_store import create_dataset, ensure_schema
    from sersflow.infra.migration_store import assign_orphans
    from sersflow.infra.sqlite_db import connect

    user = create_user(username="apinilla", password="x")
    rec = create_dataset(
        owner_user_id=user.user_id,
        metadata=DatasetMetadata(name="mine"),
        spectra=[SpectrumRef(spectrum_id="s1", relative_path="x/y.txt")],
    )
    ensure_schema()
    with connect() as con:
        con.execute("UPDATE datasets SET owner_user_id = NULL WHERE dataset_id = ?", (rec.dataset_id,))
    report = assign_orphans(owner_user_id=user.user_id, dry_run=True)
    assert report.datasets_updated >= 1

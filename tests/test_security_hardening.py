"""Security hardening regressions (audit phase B): sessions, sign-in throttle, limits, artifact cleanup."""

from __future__ import annotations

import hashlib
import json
import zipfile
from io import BytesIO
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from sersflow.api.main import app
from sersflow.api.routers.auth import reset_login_throttle
from sersflow.api.services.ownership import invalidate_registry_cache
from sersflow.cli.admin import main as admin_main
from sersflow.infra.auth_store import create_user, invalidate_session_state_cache, set_disabled, set_password


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.delenv("SERSFLOW_AUTH_DISABLED", raising=False)
    monkeypatch.setenv("SERSFLOW_AUTH_SECRET", "test-secret-key-for-auth-tests-only")
    monkeypatch.setenv("SERSFLOW_DB_PATH", str(tmp_path / "auth.db"))
    monkeypatch.setenv("SERSFLOW_UPLOAD_DIR", str(tmp_path / "uploads"))
    monkeypatch.setenv("SERSFLOW_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("SERSFLOW_ARTIFACTS_DIR", str(tmp_path / "artifacts"))
    invalidate_registry_cache()
    invalidate_session_state_cache()
    reset_login_throttle()
    return TestClient(app)


def _login(client: TestClient, username: str = "alice", password: str = "pass-a"):
    return client.post("/auth/login", json={"username": username, "password": password})


class _PipedStdin:
    """Minimal non-tty stdin for the admin CLI."""

    def __init__(self, text: str) -> None:
        self._lines = text.splitlines(keepends=True)

    def isatty(self) -> bool:
        return False

    def readline(self) -> str:
        return self._lines.pop(0) if self._lines else ""


@pytest.mark.auth
def test_password_change_signs_existing_sessions_out(client: TestClient) -> None:
    create_user(username="alice", password="pass-a")
    assert _login(client).status_code == 200
    assert client.get("/datasets").status_code == 200

    set_password(username="alice", password="new-pass")
    assert client.get("/datasets").status_code == 401  # the old cookie is dead
    assert _login(client).status_code == 401  # and so is the old password
    assert _login(client, password="new-pass").status_code == 200
    assert client.get("/datasets").status_code == 200


@pytest.mark.auth
def test_disabled_user_is_locked_out_until_enabled(client: TestClient) -> None:
    create_user(username="alice", password="pass-a")
    assert _login(client).status_code == 200
    set_disabled(username="alice", disabled=True)
    assert client.get("/datasets").status_code == 401
    assert _login(client).status_code == 401
    set_disabled(username="alice", disabled=False)
    assert _login(client).status_code == 200


@pytest.mark.auth
def test_admin_cli_reads_password_from_stdin(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("sys.stdin", _PipedStdin("first-pass\n"))
    assert admin_main(["create-user", "carol"]) == 0
    assert _login(client, "carol", "first-pass").status_code == 200
    monkeypatch.setattr("sys.stdin", _PipedStdin("second-pass\n"))
    assert admin_main(["set-password", "carol"]) == 0
    assert client.get("/datasets").status_code == 401
    assert _login(client, "carol", "second-pass").status_code == 200
    assert admin_main(["disable-user", "carol"]) == 0
    assert _login(client, "carol", "second-pass").status_code == 401


@pytest.mark.auth
def test_sign_in_is_throttled_after_repeated_failures(client: TestClient) -> None:
    create_user(username="alice", password="pass-a")
    for _ in range(10):
        assert _login(client, password="wrong").status_code == 401
    blocked = _login(client)  # even the right password has to wait now
    assert blocked.status_code == 429
    assert int(blocked.headers["retry-after"]) > 0
    create_user(username="bob", password="pass-b")  # another username is not affected
    assert _login(client, "bob", "pass-b").status_code == 200


@pytest.mark.auth
def test_api_docs_need_a_session_and_headers_are_set(client: TestClient) -> None:
    for path in ("/docs", "/redoc", "/openapi.json"):
        assert client.get(path).status_code == 401, path
    create_user(username="alice", password="pass-a")
    assert _login(client).status_code == 200
    r = client.get("/openapi.json")
    assert r.status_code == 200
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["x-frame-options"] == "SAMEORIGIN"


@pytest.mark.auth
def test_cookie_is_secure_when_the_request_came_over_https(client: TestClient) -> None:
    create_user(username="alice", password="pass-a")
    plain = _login(client)
    assert "secure" not in plain.headers["set-cookie"].lower()
    forwarded = client.post(
        "/auth/login", json={"username": "alice", "password": "pass-a"}, headers={"X-Forwarded-Proto": "https"}
    )
    assert "secure" in forwarded.headers["set-cookie"].lower()


@pytest.mark.auth
def test_origin_check_is_opt_in(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    create_user(username="alice", password="pass-a")
    body = {"username": "alice", "password": "pass-a"}
    evil = {"Origin": "https://evil.example"}
    assert client.post("/auth/login", json=body, headers=evil).status_code == 200
    monkeypatch.setenv("SERSFLOW_ALLOWED_ORIGINS", "https://pces01.example")
    assert client.post("/auth/login", json=body, headers=evil).status_code == 403
    assert client.post("/auth/login", json=body, headers={"Origin": "https://PCES01.example"}).status_code == 200
    assert _login(client).status_code == 200  # no Origin header (API clients, MCP): never blocked


def _plain_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SERSFLOW_DB_PATH", str(tmp_path / "db.sqlite"))
    monkeypatch.setenv("SERSFLOW_UPLOAD_DIR", str(tmp_path / "uploads"))
    monkeypatch.setenv("SERSFLOW_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("SERSFLOW_ARTIFACTS_DIR", str(tmp_path / "artifacts"))
    invalidate_registry_cache()


def test_upload_larger_than_the_limit_is_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _plain_env(tmp_path, monkeypatch)
    monkeypatch.setenv("SERSFLOW_MAX_UPLOAD_MB", "1")
    client = TestClient(app)
    big = b"wn\tint\n" + b"1\t1\n" * 400_000  # ~1.6 MB
    r = client.post("/io/upload", files=[("files", ("big.txt", big, "text/plain"))])
    assert r.status_code == 413, r.text
    assert list((tmp_path / "uploads").rglob("big.txt")) == []
    small = client.post("/io/upload", files=[("files", ("ok.txt", b"wn\tint\n1\t1\n2\t2\n", "text/plain"))])
    assert small.status_code == 200, small.text


def test_import_refuses_oversized_archive_member(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _plain_env(tmp_path, monkeypatch)
    monkeypatch.setenv("SERSFLOW_MAX_UPLOAD_MB", "1")
    payload = b"0" * (3 * 1024 * 1024)  # 3 MB of one byte: a few KB once deflated
    blob_id = hashlib.sha256(payload).hexdigest()
    manifest = {
        "schema_version": "sersflow.dataset.v1",
        "dataset": {"metadata": {"name": "bomb"}},
        "blobs": {blob_id: {"blob_id": blob_id, "blob_relative_path": "blobs/x.txt", "zip_path": "blobs/x.txt"}},
        "spectra": [{"spectrum_id": "s1", "relative_path": "a/x.txt", "blob_id": blob_id}],
    }
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("manifest.json", json.dumps(manifest))
        zf.writestr("blobs/x.txt", payload)
    package = buf.getvalue()
    assert len(package) < 1024 * 1024  # the upload itself is under the limit; only the inflated member is not
    r = TestClient(app).post("/datasets/import", files={"file": ("p.zip", package, "application/zip")})
    assert r.status_code in (400, 413), r.text
    assert "limit" in r.text
    assert not (tmp_path / "data" / "blobs").exists()


def test_deleting_runs_removes_their_job_artifacts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from sersflow.infra import analysis_store as store
    from sersflow.infra.sqlite_db import connect

    _plain_env(tmp_path, monkeypatch)
    store.ensure_schema()
    now = "2026-01-01T00:00:00+00:00"
    with connect() as con:
        info = con.execute("PRAGMA table_info(analysis_runs)").fetchall()
        required = [r["name"] for r in info if r["notnull"] and r["dflt_value"] is None]
        for run_id in ("run_a", "run_b"):
            values = {c: "x" for c in required}
            values.update(run_id=run_id, dataset_id="ds_1", created_at=now)
            names = list(values)
            con.execute(
                f"INSERT INTO analysis_runs({','.join(names)}) VALUES ({','.join('?' for _ in names)})",
                [values[c] for c in names],
            )
        for job_id, run_id in (("job_a", "run_a"), ("job_b", "run_b")):
            con.execute(
                """
                INSERT INTO fit_curve_jobs(job_id, run_id, fitting_step_num, content, format, status, created_at, updated_at)
                VALUES (?,?,?,?,?,?,?,?)
                """,
                (job_id, run_id, 1, "curves", "csv", "completed", now, now),
            )
    jobs_dir = tmp_path / "artifacts" / "fit_curve_jobs"
    for job_id in ("job_a", "job_b"):
        (jobs_dir / job_id).mkdir(parents=True)
        (jobs_dir / job_id / "out.zip").write_bytes(b"zip")

    assert store.delete_run(run_id="run_a") is True
    assert not (jobs_dir / "job_a").exists()
    assert (jobs_dir / "job_b" / "out.zip").exists()
    assert store.delete_runs_for_dataset(dataset_id="ds_1") == 1
    assert not (jobs_dir / "job_b").exists()


def test_artifact_cleanup_never_leaves_the_artifacts_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from sersflow.infra.artifact_cleanup import remove_artifact_dirs

    monkeypatch.setenv("SERSFLOW_ARTIFACTS_DIR", str(tmp_path / "artifacts"))
    (tmp_path / "artifacts" / "keep").mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    assert remove_artifact_dirs(["../outside", "", ".", str(outside), "missing"]) == 0
    assert outside.exists() and (tmp_path / "artifacts").exists()
    assert remove_artifact_dirs(["keep"]) == 1


def test_expressions_refuse_huge_integer_powers_and_deep_nesting() -> None:
    from sersflow.core.preprocess.param_expressions import parse_expression

    for ok in ("({A.fwhm}**2 + {B.fwhm}**2)**0.5", "{A.pos} + 2**10", "{A.amp} * 0.5", "{A.pos} * 1e30"):
        parse_expression(ok)
    for bad in ("{A.pos} + ((9**9999)**9999)**9999", "(9**64)**64 + {A.pos}", "9**(60+4)", "(" * 3000 + "1" + ")" * 3000):
        with pytest.raises(ValueError):
            parse_expression(bad)


def test_sle_counts_refuse_decompression_bombs(monkeypatch: pytest.MonkeyPatch) -> None:
    import zlib

    from sersflow.core.io import read_sle

    good = zlib.compress(b"\x00\x00\x80\x3f" * 8)
    assert read_sle._decode_counts(good).tolist() == [1.0] * 8
    monkeypatch.setattr(read_sle, "_MAX_COUNTS_BYTES", 1024)
    with pytest.raises(ValueError):
        read_sle._decode_counts(zlib.compress(b"\x00" * 100_000))


def test_matrix_npz_is_loaded_without_pickle(tmp_path: Path) -> None:
    import numpy as np

    from sersflow.api.services.explore_export import load_matrix_npz

    new = tmp_path / "new.npz"
    np.savez_compressed(new, Y=np.ones((2, 3)), x=np.arange(3.0), spectrum_ids=np.array(["a", "b"], dtype=str))
    legacy = tmp_path / "legacy.npz"
    np.savez_compressed(legacy, Y=np.ones((2, 3)), x=np.arange(3.0), spectrum_ids=np.array(["a", "b"], dtype=object))
    for path in (new, legacy):
        data = load_matrix_npz(path)
        assert [str(v) for v in data["spectrum_ids"].ravel().tolist()] == ["a", "b"]
        assert data["Y"].shape == (2, 3)

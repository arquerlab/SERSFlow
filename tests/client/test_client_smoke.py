from __future__ import annotations

import tempfile
from pathlib import Path

import httpx
import pytest

pytest.importorskip("httpx", reason='Install client extra: pip install ".[client]"')


def test_health_json() -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/health"
        return httpx.Response(200, json={"status": "ok"})

    transport = httpx.MockTransport(handle)
    from sersflow.client import SersflowClient

    with SersflowClient("http://test", transport=transport) as c:
        assert c.meta.health() == {"status": "ok"}


def test_upload_multipart_basenames_only() -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == "/io/upload"
        body = getattr(request, "content", None) if hasattr(request, "content") else b""
        if body is None:
            body = b""
        if isinstance(body, bytes):
            text = body.decode("utf-8", errors="replace")
            assert 'name="files"' in text
            assert text.count('name="files"') >= 2
            assert 'filename="a.txt"' in text
            assert 'filename="b.txt"' in text
        return httpx.Response(200, text="Uploaded 2 file(s) to batch fedcba98 (1.000 MB).")

    transport = httpx.MockTransport(handle)
    from sersflow.client import SersflowClient

    with tempfile.TemporaryDirectory() as tmp:
        p1 = Path(tmp) / "a.txt"
        p2 = Path(tmp) / "b.txt"
        p1.write_bytes(b"x")
        sub = Path(tmp) / "sub"
        sub.mkdir()
        nested = sub / "b.txt"
        nested.write_bytes(b"y")

        with SersflowClient("http://test", transport=transport) as c:
            res = c.io.upload_files([p1, nested])
        assert res.batch_id == "fedcba98"
        assert res.files_saved == 2


def test_sersflow_api_error_detail() -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"detail": "bad request"})

    transport = httpx.MockTransport(handle)
    from sersflow.client import SersflowApiError, SersflowClient

    with SersflowClient("http://test", transport=transport) as c:
        with pytest.raises(SersflowApiError) as ei:
            c.meta.check_server()
    assert ei.value.status_code == 400
    assert ei.value.detail == "bad request"


def test_export_features_streams_to_file() -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert str(request.url).endswith("/export") or "/export?" in str(request.url)
        return httpx.Response(200, content=b"id,v\n1,2\n")

    transport = httpx.MockTransport(handle)
    from sersflow.client import SersflowClient

    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "out.csv"
        with SersflowClient("http://test", transport=transport) as c:
            c.analysis.export_features_to_file("r_demo", out, layout="wide")
        assert out.read_bytes() == b"id,v\n1,2\n"


def test_wait_for_analysis_job_raises_on_failure() -> None:
    statuses = iter(["failed"])

    def job_handle(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/analysis/jobs/j1"
        st = next(statuses)
        return httpx.Response(
            200,
            json={
                "job_id": "j1",
                "run_id": "run1",
                "status": st,
                "progress_done": 0,
                "progress_total": 0,
                "error": "boom",
                "created_at": "t",
                "updated_at": "t",
            },
        )

    transport = httpx.MockTransport(job_handle)
    from sersflow.client import SersflowClient, TerminalJobFailedError

    with SersflowClient("http://test", transport=transport) as c:
        with pytest.raises(TerminalJobFailedError):
            c.analysis.wait_for_analysis_job("j1", timeout_s=1.0, poll_interval_s=0.05)


def test_iter_export_features_concat_equals_stream() -> None:
    payload = b"spectrum_id,I_1\na,1.0\n"

    def handle(request: httpx.Request) -> httpx.Response:
        assert "/analysis/runs/rx/export" in str(request.url)
        return httpx.Response(200, content=payload)

    transport = httpx.MockTransport(handle)
    from sersflow.client import SersflowClient

    with SersflowClient("http://test", transport=transport) as c:
        got = b"".join(c.analysis.iter_export_features("rx", layout="wide"))
    assert got == payload


def test_wait_for_matrix_job_completed() -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/explore/matrix-jobs/mj1"
        return httpx.Response(
            200,
            json={
                "matrix_job_id": "mj1",
                "status": "completed",
                "dataset_id": "ds1",
                "npz_path": "/tmp/x.npz",
                "manifest": {"k": 1},
                "error": None,
                "created_at": "t0",
                "finished_at": "t1",
            },
        )

    transport = httpx.MockTransport(handle)
    from sersflow.client import SersflowClient

    with SersflowClient("http://test", transport=transport) as c:
        out = c.explore.wait_for_matrix_job("mj1", timeout_s=2.0, poll_interval_s=0.05)
    assert out["status"] == "completed"


def test_export_matrix_streams_to_file() -> None:
    payload = b"spectrum_id,100\ns1,1.0\n"

    def handle(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.path == "/explore/matrix-jobs/mj1/export.csv"
        return httpx.Response(200, content=payload)

    transport = httpx.MockTransport(handle)
    from sersflow.client import SersflowClient

    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "matrix.csv"
        with SersflowClient("http://test", transport=transport) as c:
            c.explore.export_matrix_to_file("mj1", out)
        assert out.read_bytes() == payload


def test_export_pca_csv_streams_to_file() -> None:
    payload = b"spectrum_id,PC1\ns1,1.0\n"

    def handle(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.path == "/explore/runs/exp1/export/scores.csv"
        return httpx.Response(200, content=payload)

    transport = httpx.MockTransport(handle)
    from sersflow.client import SersflowClient

    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "scores.csv"
        with SersflowClient("http://test", transport=transport) as c:
            c.explore.export_pca_csv_to_file("exp1", "scores", out)
        assert out.read_bytes() == payload


def test_pipelines_list_technique_family_param() -> None:
    seen: dict[str, str] = {}

    def handle(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/pipelines"
        seen.update(dict(request.url.params))
        return httpx.Response(200, json={"items": [], "count": 0})

    transport = httpx.MockTransport(handle)
    from sersflow.client import SersflowClient

    with SersflowClient("http://test", transport=transport) as c:
        c.pipelines.list(technique_family="xps")
    assert seen.get("technique_family") == "xps"


def test_xps_apply_and_chemical_states() -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/xps/chemical-states":
            return httpx.Response(
                200, json={"source": {}, "entries": [], "entry_count": 0, "sections": []}
            )
        if request.url.path.endswith("/apply"):
            return httpx.Response(
                200,
                json={
                    "recipe_id": "r1",
                    "recipe_pass_energy": 20,
                    "xps_region": "C1s",
                    "components": [],
                    "p0": [],
                    "bounds_lower": [],
                    "bounds_upper": [],
                    "vary": [],
                    "param_links": [],
                    "warnings": [],
                },
            )
        return httpx.Response(404)

    transport = httpx.MockTransport(handle)
    from sersflow.client import SersflowClient

    with SersflowClient("http://test", transport=transport) as c:
        assert c.xps.chemical_states(element="C")["entry_count"] == 0
        applied = c.xps.apply_fitting_recipe("r1", pass_energy=20)
        assert applied["xps_region"] == "C1s"


def test_meta_formats_and_pipeline_steps() -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/meta/formats":
            return httpx.Response(200, json={"items": [{"id": "vamas", "technique_family": "xps"}]})
        if request.url.path == "/meta/pipeline-steps":
            assert "technique_family" in dict(request.url.params)
            return httpx.Response(200, json={"items": [{"id": "fitting"}]})
        return httpx.Response(404)

    transport = httpx.MockTransport(handle)
    from sersflow.client import SersflowClient

    with SersflowClient("http://test", transport=transport) as c:
        assert c.meta.formats()["items"][0]["id"] == "vamas"
        assert c.meta.pipeline_steps(technique_family="xps")["items"][0]["id"] == "fitting"


def test_plot_series_value_and_matrix_import() -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/plot/series-value":
            assert dict(request.url.params) == {"relative_path": "a.txt", "index": "3"}
            return httpx.Response(200, json={"index": 3, "value": 1.2})
        if request.url.path == "/explore/matrix-jobs/import":
            return httpx.Response(200, json={"matrix_job_id": "mj1", "status": "completed"})
        return httpx.Response(404)

    transport = httpx.MockTransport(handle)
    from sersflow.client import SersflowClient

    with tempfile.TemporaryDirectory() as tmp:
        csv_path = Path(tmp) / "m.csv"
        csv_path.write_text("id,x\n1,2\n", encoding="utf-8")
        with SersflowClient("http://test", transport=transport) as c:
            assert c.plot.series_value("a.txt", 3)["value"] == 1.2
            assert c.explore.import_matrix_job("ds1", csv_path).matrix_job_id == "mj1"

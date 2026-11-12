"""Patch-effect check at the API boundary: plan table, 422 / 409 gates, echoed spec, record hash fields."""

from __future__ import annotations

import io
import json
import os
import zipfile

import pytest

pytest.importorskip("lmfitxps")
os.environ.setdefault("SERSFLOW_ENV", "test")

from test_robustness_job import FACTORS, RESPONSES, _body, _run  # noqa: E402
from test_run_provenance_api import _wait_job  # noqa: E402

from sersflow.api.schemas.robustness_schema import SCHEMA_HEADER, robustness_schema_hash  # noqa: E402

INERT_FACTOR = {
    "name": "dummy",
    "levels": [{"name": "nominal", "patches": []}, {"name": "nothing", "patches": []}],
}
TYPO_FACTOR = {
    "name": "typo",
    "levels": [
        {"name": "nominal", "patches": []},
        {"name": "bad", "patches": [{"op": "set_component_param", "select": {"component_ids": ["A"]}, "key": "posx", "value": 290.2}]},
    ],
}


def _plan(client, run_id, idx, **kw):
    return client.post(f"/analysis/runs/{run_id}/robustness-plan", json=_body(idx, **kw))


def test_plan_reports_the_check_echoes_the_spec_and_the_schema_hash(tmp_path, monkeypatch):
    client, run_id, idx = _run(tmp_path, monkeypatch)
    r = _plan(client, run_id, idx, n_starts=2)
    assert r.status_code == 200, r.text
    plan = r.json()
    pc = plan["patch_check"]
    assert pc["n_errors"] == 0
    assert {(row["factor"], row["status"]) for row in pc["rows"]} <= {("background", "ok"), ("window", "ok"), ("fwhm", "ok")}
    assert all(row["n_spectra"] == 3 and row["details"] for row in pc["rows"])
    assert plan["received_spec"]["n_starts"] == 2 and plan["received_spec"]["factors"] == FACTORS
    assert len(plan["spec_hash"]) == 64 and plan["robustness_schema_hash"] == robustness_schema_hash()


def test_inert_level_gives_422_with_the_table_and_the_run_refuses(tmp_path, monkeypatch):
    client, run_id, idx = _run(tmp_path, monkeypatch)
    body = {**_body(idx), "factors": [*FACTORS, INERT_FACTOR]}
    r = client.post(f"/analysis/runs/{run_id}/robustness-plan", json=body)
    assert r.status_code == 422
    rows = {(x["factor"], x["level"]): x["status"] for x in r.json()["detail"]["patch_check"]["rows"]}
    assert rows[("dummy", "nothing")] == "inert"
    run = client.post(f"/analysis/runs/{run_id}/robustness-jobs", json=body)
    assert run.status_code == 422 and "patch-effect" in run.json()["detail"]["error"]
    # explicit override: the plan answers and the job starts
    assert client.post(f"/analysis/runs/{run_id}/robustness-plan", json={**body, "allow_inert": True}).status_code == 200


def test_misspelled_target_is_unresolved(tmp_path, monkeypatch):
    client, run_id, idx = _run(tmp_path, monkeypatch)
    r = client.post(f"/analysis/runs/{run_id}/robustness-plan", json={**_body(idx), "factors": [TYPO_FACTOR]})
    assert r.status_code == 422
    row = r.json()["detail"]["patch_check"]["rows"][0]
    assert row["status"] == "unresolved_target" and any("posx" in n for n in row["notes"])


def test_unknown_key_is_rejected_not_ignored(tmp_path, monkeypatch):
    client, run_id, idx = _run(tmp_path, monkeypatch)
    r = client.post(f"/analysis/runs/{run_id}/robustness-plan", json={**_body(idx), "constraintz": []})
    assert r.status_code == 422
    r2 = client.post("/analysis/robustness-jobs/nope/reanalyse", json={"respones": []})
    assert r2.status_code == 422


def test_schema_hash_mismatch_is_409(tmp_path, monkeypatch):
    client, run_id, idx = _run(tmp_path, monkeypatch)
    ok = client.post(
        f"/analysis/runs/{run_id}/robustness-plan", json=_body(idx), headers={SCHEMA_HEADER: robustness_schema_hash()}
    )
    assert ok.status_code == 200
    stale = client.post(f"/analysis/runs/{run_id}/robustness-plan", json=_body(idx), headers={SCHEMA_HEADER: "0" * 64})
    assert stale.status_code == 409 and "out of date" in stale.json()["detail"]


def test_records_and_export_carry_the_hash_fields(tmp_path, monkeypatch):
    client, run_id, idx = _run(tmp_path, monkeypatch)
    r = client.post(f"/analysis/runs/{run_id}/robustness-jobs", json=_body(idx))
    assert r.status_code == 202, r.text
    job = _wait_job(client, r.json()["job_id"], timeout_s=240)
    assert job["status"] == "completed", job
    dl = client.get(f"/analysis/fit-curve-jobs/{job['job_id']}/download")
    zf = zipfile.ZipFile(io.BytesIO(dl.content))
    assert "patch_check.json" in zf.namelist()
    recs = [json.loads(line) for line in zf.read("robustness_records.jsonl").decode().splitlines() if line.strip()]
    assert len(recs) == 24
    for rec in recs:
        for k in ("prefit_data_hash", "fit_config_hash", "fit_start_hash", "n_points_fit", "fit_x_min", "fit_x_max", "patch_check_version"):
            assert rec.get(k) is not None, k
    # cells that differ in the fit window differ in n_points_fit; identical cells share their config hash
    assert len({r_["n_points_fit"] for r_ in recs}) > 1
    assert json.loads(zf.read("provenance.json"))["spec_hash"]


def test_mcp_tools_expose_every_request_field_and_verify_the_echo():
    from sersflow.api.schemas.analysis import RobustnessJobCreateRequest
    from sersflow.mcp.tools.analysis import _verify_received_spec

    req = RobustnessJobCreateRequest(factors=FACTORS, responses=RESPONSES, constraints=[{"exclude_when": {"x": ["y"]}}])
    sent = json.loads(json.dumps(req.model_dump(exclude_none=True)))
    _verify_received_spec(req, {"received_spec": sent})
    dropped = {k: v for k, v in sent.items() if k != "constraints"}  # a stale server dropping an argument
    with pytest.raises(ValueError, match="constraints"):
        _verify_received_spec(req, {"received_spec": dropped})
    with pytest.raises(ValueError, match="echo"):
        _verify_received_spec(req, {})


def test_retro_audit_endpoint_and_cli_report_a_stored_study(tmp_path, monkeypatch, capsys):
    client, run_id, idx = _run(tmp_path, monkeypatch)
    r = client.post(f"/analysis/runs/{run_id}/robustness-jobs", json=_body(idx))
    assert r.status_code == 202, r.text
    job = _wait_job(client, r.json()["job_id"], timeout_s=240)
    assert job["status"] == "completed", job
    a = client.post(f"/analysis/robustness-jobs/{job['job_id']}/check-patches")
    assert a.status_code == 200, a.text
    audit = a.json()
    assert audit["n_errors"] == 0 and audit["n_cells"] == 8 and audit["written_to"] == "patch_check_audit.json"
    ra = audit["records_audit"]
    assert ra["n_records_with_hashes"] == 24 and ra["n_distinct_inputs"] <= 24
    from sersflow.cli.admin import main

    assert main(["robustness-check-patches", job["job_id"]]) == 0
    assert "errors=0" in capsys.readouterr().out
    assert client.post("/analysis/robustness-jobs/nope/check-patches").status_code == 404


def test_every_request_field_is_a_parameter_of_the_mcp_tools():
    """A request field missing from a tool signature is silently dropped by the MCP layer (the `constraints` bug)."""
    import inspect

    from sersflow.api.schemas.analysis import RobustnessJobCreateRequest
    from sersflow.mcp.tools import analysis as tools

    captured: dict[str, object] = {}

    class _Stub:
        def tool(self, name=None, **_kw):
            def deco(fn):
                captured[name or fn.__name__] = fn
                return fn

            return deco

    tools.register(_Stub(), object())
    fields = set(RobustnessJobCreateRequest.model_fields)
    for tool in ("post_analysis_robustness_plan", "post_analysis_robustness_jobs"):
        params = set(inspect.signature(captured[tool]).parameters)
        assert fields <= params, (tool, sorted(fields - params))

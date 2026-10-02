"""Regression tests for format/step registry cutover finish."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from sersflow.api.main import app
from sersflow.api.schemas.pipeline import Pipeline, PipelineStep
from sersflow.api.services.filter_catalog import _planned_fields_from_packs
from sersflow.api.services.technique_guard import prepare_pipeline_for_run
from sersflow.core.io.formats.packs import XPS_STRUCTURAL_FILTER_KEYS
from sersflow.core.pipeline.engine import run_pipeline
from sersflow.core.pipeline.library import get_step


def test_meta_pipeline_steps_contract_for_fe_defaults():
    """FE must build palette/defaults from this payload (no TS step matrix)."""
    client = TestClient(app)
    r = client.get("/meta/pipeline-steps", params={"technique_family": "vibrational"})
    assert r.status_code == 200
    items = r.json()["items"]
    assert items
    crop = next(it for it in items if it["id"] == "crop")
    assert "ui" in crop
    assert "label" in crop
    assert crop.get("has_impl") is True
    meta = next(it for it in items if it["id"] == "metadata_filter")
    assert meta["category"] == "geometry"
    assert meta.get("has_impl") is True


def test_engine_unknown_step_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("SERSFLOW_UPLOAD_DIR", str(tmp_path))
    (tmp_path / "b").mkdir()
    (tmp_path / "b" / "s.txt").write_text("wn\tint\n100\t1\n200\t2\n", encoding="utf-8")
    ref = SimpleNamespace(spectrum_id="s1", relative_path="b/s.txt", record_index=None)

    with pytest.raises(ValueError, match="Unknown pipeline step"):
        run_pipeline(
            inputs=[ref],
            pipeline=Pipeline(steps=[PipelineStep(name="not_a_real_step", params={})]),
            cache=None,
            strict=True,
        )

    assert get_step("metadata_filter") is not None
    assert get_step("metadata_filter").impl is not None


def test_prepare_pipeline_rejects_dual_xps_background():
    pipe = Pipeline(
        technique_family="xps",
        steps=[
            PipelineStep(name="baseline", params={"method": "shirley"}, enabled=True),
            PipelineStep(
                name="fitting",
                params={
                    "components": [{"component_id": "bg", "component_type": "shirley_bg"}],
                    "p0": [0.03, 0.0],
                    "bounds_lower": [0.0, None],
                    "bounds_upper": [None, None],
                },
                enabled=True,
            ),
        ],
    )
    with pytest.raises(HTTPException) as ei:
        prepare_pipeline_for_run(pipe, "xps", context="test")
    assert ei.value.status_code == 400
    assert "Cannot combine" in str(ei.value.detail)


def test_pipeline_run_rejects_technique_mismatch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("SERSFLOW_UPLOAD_DIR", str(tmp_path))
    (tmp_path / "u").mkdir()
    (tmp_path / "u" / "s.txt").write_text("wn\tint\n100\t1\n200\t2\n", encoding="utf-8")
    client = TestClient(app)
    payload = {
        "inputs": [{"spectrum_id": "s1", "relative_path": "u/s.txt", "record_index": None}],
        "pipeline": {
            "technique_family": "xps",
            "steps": [{"name": "crop", "params": {"min_x": 100.0, "max_x": 200.0}, "enabled": True}],
        },
        "return": {"kind": "final"},
    }
    r = client.post("/pipeline/run", json=payload)
    assert r.status_code == 400


def test_filter_planned_fields_prefer_caps_from_packs():
    """When capabilities are present, planned structural fields come from matching packs."""
    planned = _planned_fields_from_packs(caps=["multi_block", "xps_regions"], family="vibrational")
    keys = {k for k, _, _ in planned}
    assert "xps_region" in keys
    assert keys <= XPS_STRUCTURAL_FILTER_KEYS


def test_filter_planned_fields_xps_family_without_caps():
    planned = _planned_fields_from_packs(caps=[], family="xps")
    keys = {k for k, _, _ in planned}
    assert "xps_region" in keys
    assert "block_name" in keys


def test_filter_planned_fields_vibrational_skips_xps_structural():
    planned = _planned_fields_from_packs(caps=[], family="vibrational")
    keys = {k for k, _, _ in planned}
    assert "xps_region" not in keys


def test_xps_field_catalog_is_packs_reexport():
    from sersflow.core.io import xps_field_catalog as xfc
    from sersflow.core.io.formats import packs

    assert xfc.XPS_STRUCTURAL_FIELD_CATALOG == packs.XPS_STRUCTURAL_FIELD_CATALOG
    assert xfc.EXPERIMENTAL_FIELD_LABELS == packs.EXPERIMENTAL_FIELD_LABELS

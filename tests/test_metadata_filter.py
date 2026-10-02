from __future__ import annotations

from pathlib import Path

import pytest

from sersflow.api.schemas.datasets import DatasetCreateRequest, DatasetMetadata
from sersflow.api.schemas.pipeline import Pipeline, PipelineStep
from sersflow.api.services.datasets_service import create_dataset_from_uploads
from sersflow.api.services.filter_catalog import build_filter_fields_catalog, list_xps_regions_for_dataset
from sersflow.api.services.pipeline_qc import is_qc_step, pipeline_without_qc_steps
from sersflow.core.pipeline.engine import EngineConfig, run_pipeline, run_pipeline_with_intermediates
from sersflow.core.qc.metadata_filter import evaluate_filters
from sersflow.core.spectrum import EMPTY_XY
from tests.test_vms_loader import write_mixed_region_vms


def test_evaluate_filters_empty_keeps() -> None:
    assert evaluate_filters({"xps_region": "C1s"}, None) is True
    assert evaluate_filters({"xps_region": "C1s"}, []) is True


def test_evaluate_filters_categorical_in() -> None:
    row = {"xps_region": "C1s", "spectrum_role": "average"}
    assert evaluate_filters(row, [{"field": "xps_region", "op": "in", "values": ["C1s", "O1s"]}]) is True
    assert evaluate_filters(row, [{"field": "xps_region", "op": "in", "values": ["O1s"]}]) is False
    assert evaluate_filters(row, [{"field": "xps_region", "op": "in", "values": []}]) is False


def test_evaluate_filters_numeric_and() -> None:
    row = {"excitation_energy_eV": 1486.6, "replicate_index": 2}
    assert (
        evaluate_filters(
            row,
            [
                {"field": "excitation_energy_eV", "op": ">=", "value": 1400},
                {"field": "replicate_index", "op": "=", "value": 2},
            ],
        )
        is True
    )
    assert (
        evaluate_filters(
            row,
            [
                {"field": "excitation_energy_eV", "op": ">=", "value": 1400},
                {"field": "replicate_index", "op": "=", "value": 3},
            ],
        )
        is False
    )


def test_pipeline_without_qc_keeps_metadata_filter() -> None:
    pipe = Pipeline(
        steps=[
            PipelineStep(name="crop", params={"min_x": 0, "max_x": 1}),
            PipelineStep(name="metadata_filter", params={"filters": []}),
            PipelineStep(name="low_signal_filter", params={"threshold": 0}),
        ]
    )
    stripped = pipeline_without_qc_steps(pipe)
    assert [s.name for s in stripped.steps] == ["crop", "metadata_filter"]
    assert is_qc_step(PipelineStep(name="metadata_filter", params={})) is False
    assert is_qc_step(PipelineStep(name="low_signal_filter", params={"threshold": 0})) is True


def test_metadata_filter_engine_mask_and_input_from_initial(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SERSFLOW_DB_PATH", str(tmp_path / "mf.db"))
    monkeypatch.setenv("SERSFLOW_DATA_DIR", str(tmp_path / "data"))
    upload_root = tmp_path / "uploads"
    monkeypatch.setenv("SERSFLOW_UPLOAD_DIR", str(upload_root))
    upload_root.mkdir(parents=True, exist_ok=True)

    batch = "mfeng"
    dest = upload_root / batch / "mixed.vms"
    dest.parent.mkdir(parents=True, exist_ok=True)
    write_mixed_region_vms(dest)
    rel = f"{batch}/mixed.vms"

    rec, skipped = create_dataset_from_uploads(
        DatasetCreateRequest(
            relative_paths=[rel],
            metadata=DatasetMetadata(name="mf-engine"),
            vms_spectrum_mode="all",
        ),
        owner_user_id="dev",
    )
    assert not skipped
    assert len(rec.spectra) == 5
    regions = list_xps_regions_for_dataset(rec)
    region_names = {str(r.get("region") if isinstance(r, dict) else r) for r in regions}
    assert "C1s" in region_names and "O1s" in region_names

    catalog = build_filter_fields_catalog(rec)
    assert any(f.get("id") == "xps_region" for f in catalog)

    # Branch 1: keep C1s from previous/initial.
    pipe_c1s = Pipeline(
        technique_family="xps",
        steps=[
            PipelineStep(
                name="metadata_filter",
                params={"action": "keep", "filters": [{"field": "xps_region", "op": "in", "values": ["C1s"]}]},
            ),
        ],
    )
    out_c1s = run_pipeline(
        inputs=list(rec.spectra),
        pipeline=pipe_c1s,
        config=EngineConfig(cache_namespace="mf-c1s"),
        strict=True,
    )
    kept_c1s = [sid for sid, xy in out_c1s.items() if xy.x.size > 0]
    empty_c1s = [sid for sid, xy in out_c1s.items() if xy.x.size == 0]
    assert len(kept_c1s) == 3
    assert len(empty_c1s) == 2

    # Multi-region: C1s mask then O1s mask from initial — O1s branch must see full initial.
    pipe_multi = Pipeline(
        technique_family="xps",
        steps=[
            PipelineStep(
                name="metadata_filter",
                step_id="mf-c1s",
                params={"action": "keep", "filters": [{"field": "xps_region", "op": "in", "values": ["C1s"]}]},
            ),
            PipelineStep(
                name="metadata_filter",
                step_id="mf-o1s",
                params={"action": "keep", "filters": [{"field": "xps_region", "op": "in", "values": ["O1s"]}]},
                input_from="initial",
            ),
        ],
    )
    finals, inter = run_pipeline_with_intermediates(
        inputs=list(rec.spectra),
        pipeline=pipe_multi,
        collect_steps={"metadata_filter__1", "metadata_filter__2"},
        config=EngineConfig(cache_namespace="mf-multi"),
        strict=True,
    )
    # Final = after O1s mask from initial → only O1s non-empty.
    assert sum(1 for xy in finals.values() if xy.x.size > 0) == 2
    after1 = 0
    after2 = 0
    for steps in inter.values():
        xy1 = steps.get("metadata_filter__1")
        if xy1 is not None and xy1.x.size > 0:
            after1 += 1
        xy2 = steps.get("metadata_filter__2")
        if xy2 is not None and xy2.x.size > 0:
            after2 += 1
    assert after1 == 3
    assert after2 == 2

    assert EMPTY_XY.x.size == 0

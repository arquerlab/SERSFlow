from __future__ import annotations

from pathlib import Path

import pytest

from sersflow.api.schemas.pipeline import Pipeline, PipelineStep
from sersflow.infra.pipelines_store import (
    create_pipeline,
    delete_pipeline,
    get_pipeline,
    get_pipeline_by_name,
    list_pipelines,
    update_pipeline,
)


def test_pipelines_store_create_list_get_delete(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SERSFLOW_DB_PATH", str(tmp_path / "test.db"))

    p = Pipeline(steps=[PipelineStep(name="noise_savgol", params={"window_length": 5, "polyorder": 2})])
    rec = create_pipeline(name="  my pipe  ", pipeline=p)
    assert rec.pipeline_id.startswith("pl_")
    assert rec.name == "my pipe"

    by_name = get_pipeline_by_name("my pipe")
    assert by_name is not None
    assert by_name.pipeline_id == rec.pipeline_id

    got = get_pipeline(rec.pipeline_id)
    assert got is not None
    assert got.name == "my pipe"
    assert len(got.pipeline.steps) == 1
    assert got.pipeline.steps[0].name == "noise_savgol"

    items = list_pipelines(limit=10, offset=0)
    assert any(x.pipeline_id == rec.pipeline_id for x in items)

    assert delete_pipeline(rec.pipeline_id) is True
    assert get_pipeline(rec.pipeline_id) is None


def test_pipelines_store_default_name_when_empty(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SERSFLOW_DB_PATH", str(tmp_path / "test.db"))

    rec = create_pipeline(name="", pipeline=Pipeline(steps=[]))
    assert rec.name.startswith("Unnamed pipeline ")
    rec2 = create_pipeline(name="   ", pipeline=Pipeline(steps=[]))
    assert rec2.name.startswith("Unnamed pipeline ")
    assert rec2.pipeline_id != rec.pipeline_id


def test_pipelines_store_duplicate_name_conflict(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SERSFLOW_DB_PATH", str(tmp_path / "test.db"))

    create_pipeline(name="dup", pipeline=Pipeline(steps=[]))
    with pytest.raises(ValueError, match="already exists"):
        create_pipeline(name="dup", pipeline=Pipeline(steps=[PipelineStep(name="crop", params={})]))


def test_pipelines_store_overwrite_same_name(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SERSFLOW_DB_PATH", str(tmp_path / "test.db"))

    first = create_pipeline(name="x", pipeline=Pipeline(steps=[PipelineStep(name="crop", params={"a": 1})]))
    second = create_pipeline(
        name="x",
        pipeline=Pipeline(steps=[PipelineStep(name="normalize", params={"method": "max"})]),
        overwrite=True,
    )
    assert second.pipeline_id == first.pipeline_id
    assert second.created_at == first.created_at
    assert second.updated_at >= first.updated_at
    assert len(second.pipeline.steps) == 1
    assert second.pipeline.steps[0].name == "normalize"


def test_pipelines_store_update_rename_and_steps(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SERSFLOW_DB_PATH", str(tmp_path / "test.db"))

    rec = create_pipeline(name="a", pipeline=Pipeline(steps=[]))
    updated = update_pipeline(
        pipeline_id=rec.pipeline_id,
        name="b",
        pipeline=Pipeline(steps=[PipelineStep(name="baseline", params={"method": "asls"})]),
    )
    assert updated is not None
    assert updated.name == "b"
    assert updated.pipeline.steps[0].name == "baseline"

    create_pipeline(name="c", pipeline=Pipeline(steps=[]))
    with pytest.raises(ValueError, match="already exists"):
        update_pipeline(pipeline_id=rec.pipeline_id, name="c")


def test_pipelines_store_update_requires_field(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SERSFLOW_DB_PATH", str(tmp_path / "test.db"))

    rec = create_pipeline(name="only", pipeline=Pipeline(steps=[]))
    with pytest.raises(ValueError, match="At least one"):
        update_pipeline(pipeline_id=rec.pipeline_id, name=None, pipeline=None)


def test_pipelines_store_roundtrips_baseline_point_reference(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SERSFLOW_DB_PATH", str(tmp_path / "test.db"))

    pipeline = Pipeline(
        steps=[
            PipelineStep(
                name="baseline",
                params={"method": "mor", "half_window": 30},
                step_id="base-step",
            ),
            PipelineStep(
                name="normalize",
                params={"method": "baseline_point", "baseline_step_id": "base-step", "point_x": 1000.0},
                step_id="norm-step",
            ),
        ]
    )

    rec = create_pipeline(name="baseline point", pipeline=pipeline)
    got = get_pipeline(rec.pipeline_id)

    assert got is not None
    assert got.pipeline.steps[1].params["baseline_step_id"] == "base-step"
    assert got.pipeline.steps[1].params["point_x"] == 1000.0

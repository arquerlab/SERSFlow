from __future__ import annotations

from pathlib import Path

from sersflow.api.schemas.pipeline import Pipeline, PipelineStep
from sersflow.api.services.pipeline_export import export_pipeline_package, import_pipeline_package
from sersflow.infra.pipelines_store import create_pipeline, get_pipeline


def test_pipeline_export_import_roundtrip_preserves_step_wiring(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("SERSFLOW_DB_PATH", str(tmp_path / "pipelines.db"))
    pipeline = Pipeline(
        steps=[
            PipelineStep(name="crop", params={"min_x": 100, "max_x": 1000}, step_id="1"),
            PipelineStep(
                name="normalize",
                params={"method": "max"},
                step_id="2",
                input_from="after_step",
                after_step_id="1",
            ),
        ]
    )
    rec = create_pipeline(owner_user_id="dev", name="share me", pipeline=pipeline)
    pkg = export_pipeline_package(rec)
    assert pkg.schema_version == "sersflow.pipeline.v1"
    assert pkg.pipeline.steps[1].input_from == "after_step"
    assert pkg.pipeline.steps[1].after_step_id == "1"

    imported = import_pipeline_package(name="share me imported", pipeline=pkg.pipeline, owner_user_id="dev")
    got = get_pipeline(imported.pipeline_id, owner_user_id="dev")
    assert got is not None
    assert got.pipeline.model_dump(mode="json") == pipeline.model_dump(mode="json")

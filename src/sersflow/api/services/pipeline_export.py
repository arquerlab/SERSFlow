from __future__ import annotations

from datetime import datetime, timezone

from sersflow.api.schemas.pipeline import Pipeline
from sersflow.api.schemas.pipelines import PipelineExportPackage
from sersflow.core.pipeline.lineshape_migration import (
    PIPELINE_SCHEMA_V1,
    PIPELINE_SCHEMA_V2,
    migrate_legacy_gl,
)
from sersflow.infra.pipelines_store import PipelineLibraryRecord, create_pipeline

# v2 (K1): a fitting component ``gl`` is the CasaXPS PRODUCT GL(m); v1 ``gl`` was the sum (now ``sgl``).
PIPELINE_SCHEMA_VERSION = PIPELINE_SCHEMA_V2


def pipeline_for_schema(pipeline: Pipeline, schema_version: str) -> tuple[Pipeline, int]:
    """Upgrade a packaged pipeline to the current schema. Returns (pipeline, n_components_renamed)."""
    if schema_version != PIPELINE_SCHEMA_V1:
        return pipeline, 0
    data = pipeline.model_dump()
    n = migrate_legacy_gl(data)
    return (Pipeline.model_validate(data) if n else pipeline), n


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def export_pipeline_package(record: PipelineLibraryRecord) -> PipelineExportPackage:
    return PipelineExportPackage(
        schema_version=PIPELINE_SCHEMA_VERSION,
        created_by="SpecFlow",
        exported_at=_utc_now_iso(),
        name=record.name,
        pipeline=record.pipeline,
        technique_family=getattr(record, "technique_family", None)
        or getattr(record.pipeline, "technique_family", None)
        or "vibrational",
        source_pipeline_id=record.pipeline_id,
    )


def import_pipeline_package(
    *,
    name: str | None,
    pipeline: Pipeline,
    owner_user_id: str,
    technique_family: str | None = None,
) -> PipelineLibraryRecord:
    return create_pipeline(
        name=name or "Imported pipeline",
        pipeline=pipeline,
        owner_user_id=owner_user_id,
        overwrite=False,
        technique_family=technique_family or getattr(pipeline, "technique_family", None),
    )

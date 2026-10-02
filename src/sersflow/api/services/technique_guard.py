"""Shared technique_family checks for API routers/services."""

from __future__ import annotations

from fastapi import HTTPException

from sersflow.api.schemas.pipeline import Pipeline
from sersflow.core.io.technique import (
    TechniqueFamily,
    assert_matching_technique_families,
    normalize_technique_family,
)


def dataset_technique_family(metadata: object | None) -> TechniqueFamily:
    raw = getattr(metadata, "technique_family", None) if metadata is not None else None
    return normalize_technique_family(raw, default="vibrational")


def require_matching_technique_families(
    dataset_family: str | None,
    pipeline_family: str | None,
    *,
    context: str = "dataset and pipeline",
) -> TechniqueFamily:
    try:
        return assert_matching_technique_families(
            dataset_family, pipeline_family, context=context
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


def align_or_require_pipeline_technique(
    pipeline: Pipeline,
    dataset_family: str | None,
    *,
    context: str = "dataset and pipeline",
    allow_empty_align: bool = False,
) -> Pipeline:
    """
    Ensure pipeline.technique_family matches the dataset.

    When ``allow_empty_align`` is True and the pipeline has no steps, rewrite the
    pipeline family to the dataset family (session bootstrap with ``{steps: []}``).
    """
    ds = normalize_technique_family(dataset_family, default="vibrational")
    if allow_empty_align and not pipeline.steps:
        if pipeline.technique_family != ds:
            return pipeline.model_copy(update={"technique_family": ds})
        return pipeline
    require_matching_technique_families(ds, pipeline.technique_family, context=context)
    return pipeline


def prepare_pipeline_for_run(
    pipeline: Pipeline,
    dataset_family: str | None,
    *,
    context: str = "dataset and pipeline",
    allow_empty_align: bool = False,
) -> Pipeline:
    """
    Align technique families and reject dual XPS static+active backgrounds.
    """
    from sersflow.core.pipeline.xps_background_guard import assert_no_dual_xps_background

    aligned = align_or_require_pipeline_technique(
        pipeline,
        dataset_family,
        context=context,
        allow_empty_align=allow_empty_align,
    )
    try:
        assert_no_dual_xps_background(aligned)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return aligned

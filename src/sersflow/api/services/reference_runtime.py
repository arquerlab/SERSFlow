from __future__ import annotations

from typing import Iterable

from sersflow.api.schemas.datasets import SpectrumRef
from sersflow.api.schemas.pipeline import Pipeline
from sersflow.core.pipeline.engine import EngineConfig, run_pipeline
from sersflow.infra.datasets_store import DatasetRecord


def reference_spectrum_ids(pipeline: Pipeline) -> set[str]:
    ids: set[str] = set()
    for step in pipeline.steps:
        if not step.enabled or step.name != "reference_transform":
            continue
        sid = str(step.params.get("reference_spectrum_id") or "").strip()
        if sid:
            ids.add(sid)
    return ids


def filter_reference_spectra(refs: Iterable[SpectrumRef], pipeline: Pipeline) -> list[SpectrumRef]:
    exclude = reference_spectrum_ids(pipeline)
    if not exclude:
        return list(refs)
    return [ref for ref in refs if ref.spectrum_id not in exclude]


def _find_spectrum(dataset: DatasetRecord, spectrum_id: str) -> SpectrumRef:
    for ref in dataset.spectra:
        if ref.spectrum_id == spectrum_id:
            return ref
    raise ValueError(f"reference_spectrum_id {spectrum_id!r} does not match any dataset spectrum")


def _find_step_index_by_id(pipeline: Pipeline, step_id: str, *, before_index: int) -> int:
    for i, step in enumerate(pipeline.steps[:before_index]):
        if (step.step_id or "").strip() == step_id:
            return i
    raise ValueError(f"reference_step_id {step_id!r} must refer to an earlier pipeline step")


def hydrate_reference_transforms(
    pipeline: Pipeline,
    dataset: DatasetRecord,
    *,
    cache_namespace: str = "reference",
) -> Pipeline:
    """
    Return a runtime-only pipeline whose reference_transform steps include resolved reference XY arrays.

    The stored pipeline keeps only ids/stage params. Hydration runs each selected reference spectrum through
    the same pipeline up to the requested earlier step, then injects _reference_x/_reference_y into the
    transform params used by the execution engine.
    """
    steps = [step.model_copy(deep=True) for step in pipeline.steps]
    runtime = Pipeline(steps=steps)
    for i, step in enumerate(runtime.steps):
        if not step.enabled or step.name != "reference_transform":
            continue
        params = dict(step.params or {})
        ref_sid = str(params.get("reference_spectrum_id") or "").strip()
        if not ref_sid:
            raise ValueError("reference_transform requires reference_spectrum_id")
        ref = _find_spectrum(dataset, ref_sid)
        stage = str(params.get("reference_stage", "raw")).strip().lower()
        if stage in ("raw", "initial"):
            prefix = Pipeline(steps=[])
        elif stage == "after_step":
            ref_step_id = str(params.get("reference_step_id") or "").strip()
            if not ref_step_id:
                raise ValueError("reference_transform requires reference_step_id when reference_stage='after_step'")
            target_index = _find_step_index_by_id(runtime, ref_step_id, before_index=i)
            prefix = Pipeline(steps=[s.model_copy(deep=True) for s in runtime.steps[: target_index + 1]])
        else:
            raise ValueError("reference_transform reference_stage must be raw or after_step")

        final = run_pipeline(
            inputs=[ref],
            pipeline=prefix,
            cache=None,
            config=EngineConfig(cache_namespace=f"{cache_namespace}:reference:{i}"),
            strict=True,
        )
        xy = final.get(ref.spectrum_id)
        if xy is None or xy.x.size == 0 or xy.y.size == 0:
            raise ValueError(f"reference spectrum {ref_sid!r} produced no data")
        params["_reference_x"] = xy.x.astype(float).tolist()
        params["_reference_y"] = xy.y.astype(float).tolist()
        step.params = params
    return runtime

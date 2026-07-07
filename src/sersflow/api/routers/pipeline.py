from __future__ import annotations

from typing import Any, cast

from fastapi import APIRouter, HTTPException, Request

from sersflow.api.deps import current_user_id
from sersflow.api.services.ownership import OwnershipError, assert_paths_owner, paths_from_pipeline_inputs

from sersflow.api.schemas.pipeline import (
    PipelineRunFinalResponse,
    PipelineRunMetricsResponse,
    PipelineRunRequest,
    PipelineSweepRequest,
    PipelineSweepResponse,
    ReturnFinal,
    ReturnMetricsOnly,
)
from sersflow.core.metrics.compute import compute_metrics
from sersflow.core.pipeline.cache import InProcessLRUCache
from sersflow.core.pipeline.engine import EngineConfig, run_pipeline
from sersflow.core.preprocess.baseline import baseline_method_metadata


router = APIRouter(prefix="/pipeline", tags=["Pipeline"])

_cache = InProcessLRUCache(max_items=4096)


@router.get("/baseline-methods")
def baseline_methods_endpoint() -> dict[str, Any]:
    return baseline_method_metadata()


@router.post("/run", response_model=PipelineRunMetricsResponse | PipelineRunFinalResponse)
def run_pipeline_endpoint(payload: PipelineRunRequest, request: Request) -> dict[str, Any]:
    user_id = current_user_id(request)
    try:
        assert_paths_owner(user_id, paths_from_pipeline_inputs(payload.inputs))
        cfg = EngineConfig(cache_namespace=payload.cache_namespace or "default")
        final = run_pipeline(
            inputs=payload.inputs,
            pipeline=payload.pipeline,
            cache=_cache,
            config=cfg,
            up_to_step=payload.up_to_step,
            strict=True,
        )

        if isinstance(payload.return_, ReturnFinal):
            items = [
                {"spectrum_id": sid, "x": xy.x.astype(float).tolist(), "y": xy.y.astype(float).tolist()}
                for sid, xy in final.items()
            ]
            return {"items": items}

        ret_metrics = cast(ReturnMetricsOnly, payload.return_)
        items = []
        for sid, xy in final.items():
            ms = compute_metrics(xy, ret_metrics.metrics)
            items.append(
                {
                    "spectrum_id": sid,
                    "metrics": [{"name": r.name, "value": r.value, "unit": r.unit} for r in ms],
                }
            )
        return {"items": items}
    except OwnershipError:
        raise HTTPException(status_code=404, detail="Uploaded file not found") from None
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=f"Uploaded file not found: {e}") from e
    except (ValueError, IndexError) as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/sweep", response_model=PipelineSweepResponse)
def sweep_pipeline_endpoint(payload: PipelineSweepRequest, request: Request) -> dict[str, Any]:
    """
    Run a simple parameter sweep over a single step.

    Intended for exploration mode; bounded to avoid accidental huge sweeps.
    """
    user_id = current_user_id(request)
    try:
        assert_paths_owner(user_id, paths_from_pipeline_inputs(payload.inputs))
        step_name = payload.sweep.step
        grid = payload.sweep.grid
        if not grid:
            raise ValueError("sweep.grid must not be empty")

        keys = list(grid.keys())
        values_lists = [grid[k] for k in keys]
        combos = 1
        for vs in values_lists:
            combos *= max(1, len(vs))
        if combos > 500:
            raise ValueError("Sweep too large (max 500 combinations)")
        if len(payload.inputs) > 200:
            raise ValueError("Too many inputs for sweep (max 200)")

        # Find the step index to override
        base_steps = payload.base_pipeline.steps
        idx = next((i for i, s in enumerate(base_steps) if s.name == step_name), None)
        if idx is None:
            raise ValueError(f"Step not found in base_pipeline: {step_name}")

        results = []
        best = None
        best_val = None

        def aggregate(arr):
            if payload.objective.aggregate == "mean":
                return float(sum(arr) / len(arr))
            arr2 = sorted(arr)
            mid = len(arr2) // 2
            return float(arr2[mid]) if len(arr2) % 2 == 1 else float((arr2[mid - 1] + arr2[mid]) / 2.0)

        # Cartesian product without importing itertools to keep it explicit and small.
        def rec_build(i, current):
            if i == len(keys):
                yield dict(current)
                return
            k = keys[i]
            for v in grid[k]:
                current.append((k, v))
                yield from rec_build(i + 1, current)
                current.pop()

        for params in rec_build(0, []):
            # override step params
            steps = [s.model_copy(deep=True) for s in base_steps]
            steps[idx].params.update(params)
            sweep_pipeline = payload.base_pipeline.model_copy()
            sweep_pipeline.steps = steps

            cfg = EngineConfig(cache_namespace=payload.cache_namespace or "sweep")
            finals = run_pipeline(inputs=payload.inputs, pipeline=sweep_pipeline, cache=_cache, config=cfg, strict=True)
            vals = []
            for xy in finals.values():
                res = compute_metrics(xy, [payload.objective.metric])[0]
                if res.value is not None:
                    vals.append(float(res.value))
            obj = aggregate(vals) if vals else None

            r = {"params": params, "objective": obj}
            results.append(r)
            if obj is not None and (best_val is None or obj > best_val):
                best_val = obj
                best = r

        return {"results": results, "best": best}
    except OwnershipError:
        raise HTTPException(status_code=404, detail="Uploaded file not found") from None
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=f"Uploaded file not found: {e}") from e
    except (ValueError, IndexError) as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


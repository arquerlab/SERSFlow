from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from sersflow.api.schemas.metrics import MetricsComputeRequest, MetricsComputeResponse
from sersflow.api.schemas.pipeline import Pipeline
from sersflow.core.metrics.compute import compute_metrics
from sersflow.core.pipeline.cache import InProcessLRUCache
from sersflow.core.pipeline.engine import EngineConfig, run_pipeline


router = APIRouter(prefix="/metrics", tags=["metrics"])

_cache = InProcessLRUCache(max_items=4096)


@router.post("/compute", response_model=MetricsComputeResponse)
def metrics_compute(payload: MetricsComputeRequest) -> dict[str, Any]:
    try:
        pipeline = payload.pipeline or Pipeline(steps=[])
        cfg = EngineConfig(cache_namespace=payload.cache_namespace or "default")
        final = run_pipeline(inputs=payload.inputs, pipeline=pipeline, cache=_cache, config=cfg)
        items = []
        for sid, xy in final.items():
            ms = compute_metrics(xy, payload.metrics)
            items.append({"spectrum_id": sid, "metrics": [{"name": r.name, "value": r.value, "unit": r.unit} for r in ms]})
        return {"items": items}
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=f"Uploaded file not found: {e}") from e
    except (ValueError, IndexError) as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


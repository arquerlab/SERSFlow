from __future__ import annotations

import math
import random
from typing import Any

import numpy as np

from sersflow.api.schemas.metrics import DatasetMetricsRequest
from sersflow.api.schemas.pipeline import Pipeline
from sersflow.api.schemas.sessions import SubsetStrategy
from sersflow.core.metrics.compute import compute_metrics
from sersflow.core.pipeline.cache import InProcessLRUCache
from sersflow.core.pipeline.engine import EngineConfig, run_pipeline
from sersflow.core.pipeline.hashing import canonical_json, sha256_hex
from sersflow.infra.datasets_store import DatasetRecord, get_dataset


_cache = InProcessLRUCache(max_items=4096)


def pipeline_hash(pipeline: Pipeline) -> str:
    return sha256_hex(canonical_json(pipeline.model_dump()))


def subset_hash(subset: SubsetStrategy) -> str:
    return sha256_hex(canonical_json(subset.model_dump()))


def resolve_subset_indices(*, dataset: DatasetRecord, subset: SubsetStrategy, pipeline: Pipeline) -> list[int]:
    n_total = len(dataset.spectra)
    if subset.kind == "all":
        return list(range(n_total))

    if subset.kind == "indices":
        indices = subset.indices or []
        if not indices:
            raise ValueError("indices must be provided for kind='indices'")
        if any((i < 0 or i >= n_total) for i in indices):
            raise ValueError("indices contains out-of-range values")
        return list(dict.fromkeys(indices))

    if subset.kind == "random":
        if subset.n is None or subset.n <= 0:
            raise ValueError("n must be provided for kind='random'")
        k = min(int(subset.n), n_total)
        rng = random.Random(subset.seed)
        return rng.sample(range(n_total), k=k)

    if subset.kind in {"top_n", "outliers"}:
        if subset.metric is None:
            raise ValueError("metric must be provided for metric-based subset selection")
        if subset.n is None or subset.n <= 0:
            raise ValueError("n must be provided for metric-based subset selection")
        metric_name = subset.metric

        cfg = EngineConfig(cache_namespace="metric_select")
        final = run_pipeline(inputs=dataset.spectra, pipeline=pipeline, cache=_cache, config=cfg)
        values: list[tuple[int, float]] = []
        for i, sref in enumerate(dataset.spectra):
            xy = final.get(sref.spectrum_id)
            if xy is None:
                continue
            res = compute_metrics(xy, [metric_name])[0]
            if res.value is None or math.isnan(res.value):
                continue
            values.append((i, float(res.value)))

        if not values:
            return []

        if subset.kind == "top_n":
            direction = subset.direction or "max"
            reverse = direction == "max"
            values.sort(key=lambda t: t[1], reverse=reverse)
            return [i for i, _ in values[: int(subset.n)]]

        # outliers: simple z-score threshold
        arr = np.array([v for _, v in values], dtype=float)
        mu = float(np.mean(arr))
        sigma = float(np.std(arr)) or 1.0
        thr = float(subset.zscore_threshold or 3.0)
        scored = []
        for (idx, v) in values:
            z = abs((v - mu) / sigma)
            if z >= thr:
                scored.append((idx, z))
        scored.sort(key=lambda t: t[1], reverse=True)
        return [i for i, _ in scored[: int(subset.n)]]

    raise ValueError(f"Unknown subset kind: {subset.kind}")


def get_dataset_or_404(dataset_id: str) -> DatasetRecord:
    rec = get_dataset(dataset_id)
    if rec is None:
        raise KeyError("dataset not found")
    return rec


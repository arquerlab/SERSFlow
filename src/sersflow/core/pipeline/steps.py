from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

import numpy as np

from sersflow.core.pipeline.hashing import canonical_json
from sersflow.core.spectrum import XY


Transform = Callable[[XY, dict[str, Any]], XY]


@dataclass(frozen=True)
class StepImpl:
    name: str
    impl_version: str
    transform: Transform


def _crop(xy: XY, params: dict[str, Any]) -> XY:
    min_x = float(params["min_x"])
    max_x = float(params["max_x"])
    x = xy.x
    y = xy.y
    mask = (x >= min_x) & (x <= max_x)
    return XY(x=x[mask], y=y[mask])


def _normalize(xy: XY, params: dict[str, Any]) -> XY:
    method = str(params.get("method", "max"))
    y = xy.y.astype(float, copy=False)
    if method == "max":
        denom = float(np.max(y)) if y.size else 1.0
    elif method == "mean":
        denom = float(np.mean(y)) if y.size else 1.0
    elif method == "median":
        denom = float(np.median(y)) if y.size else 1.0
    else:
        raise ValueError(f"Unknown normalization method: {method}")
    if denom == 0.0:
        denom = 1.0
    return XY(x=xy.x, y=y / denom)


DEFAULT_STEPS: dict[str, StepImpl] = {
    "crop": StepImpl(name="crop", impl_version="1", transform=_crop),
    "normalize": StepImpl(name="normalize", impl_version="1", transform=_normalize),
}


def params_fingerprint(step_name: str, params: dict[str, Any], impl_version: str) -> str:
    return canonical_json({"step": step_name, "params": params, "impl_version": impl_version})


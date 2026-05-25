from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
from fastapi import APIRouter, HTTPException

from sersflow.api.schemas.fitting import (
    FittingModelsResponse,
    FitInlineSeries,
    FitRequest,
    FitResponse,
    FitSpectrumRef,
)
from sersflow.api.services.uploads import resolve_existing_upload
from sersflow.core.io.load_file import load_dataset
from sersflow.core.preprocess.fitting import FitComponent, FitProblem, fit_curve
from sersflow.core.preprocess.fitting_specs import build_component_function, list_component_types


router = APIRouter(prefix="/fitting", tags=["Fitting"])


@router.get("/models", response_model=FittingModelsResponse)
def list_fitting_models() -> dict[str, Any]:
    comps = [c.to_public_dict() for c in list_component_types()]
    return {"components": comps}


def _resolve_target(target: FitInlineSeries | FitSpectrumRef) -> tuple[np.ndarray, np.ndarray]:
    if isinstance(target, FitInlineSeries):
        x = np.asarray(target.x, dtype=float)
        y = np.asarray(target.y, dtype=float)
        return x, y

    # SpectrumRef target
    try:
        p = resolve_existing_upload(target.spectrum.relative_path)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Uploaded file not found")

    try:
        ds = load_dataset(Path(p))
        idx = target.spectrum.record_index or 0
        kind = getattr(ds, "kind", None)
        if kind == "spectrum":
            return np.asarray(ds.x, dtype=float), np.asarray(ds.y, dtype=float)  # type: ignore[attr-defined]
        if kind in {"series", "map"}:
            x = np.asarray(ds.x, dtype=float)  # type: ignore[attr-defined]
            spectra = np.asarray(ds.spectra, dtype=float)  # type: ignore[attr-defined]
            if idx < 0 or idx >= spectra.shape[0]:
                raise ValueError(f"record_index out of range: {idx} (max {spectra.shape[0]-1})")
            y = spectra[idx, :]
            return x, y
        raise ValueError(f"Unsupported dataset kind for fitting: {kind}")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/fit", response_model=FitResponse)
def fit_endpoint(payload: FitRequest) -> dict[str, Any]:
    try:
        x, y = _resolve_target(payload.target)

        components = [
            FitComponent(component_type=c.component_type, component_id=c.component_id, degree=c.degree)
            for c in payload.components
        ]

        # Determine expected parameter count from component specs
        total = 0
        per_comp_param_keys: list[list[str]] = []
        for c in payload.components:
            _f, params = build_component_function(c.component_type, degree=c.degree)
            total += len(params)
            per_comp_param_keys.append([p.key for p in params])

        if not payload.p0:
            raise ValueError("p0 is required (use /fitting/models to build the correct length/order)")
        if len(payload.bounds.lower) != total or len(payload.bounds.upper) != total:
            raise ValueError("bounds.lower/upper must match total parameter count")

        prob = FitProblem(
            x=x,
            y=y,
            components=components,
            p0=list(payload.p0),
            bounds_lower=list(payload.bounds.lower),
            bounds_upper=list(payload.bounds.upper),
            initial_guess_mode=str(payload.initial_guess_mode),
        )
        res = fit_curve(prob)

        # Unflatten params into per-component dicts
        comps_out = []
        for idx, m in enumerate(res.mapping):
            s, e = m["index_range"]
            keys = m["param_keys"]
            vals = res.p_opt[s:e].astype(float).tolist()
            yc = res.component_y_hat[idx].astype(float).tolist() if payload.return_curve else None
            comps_out.append(
                {
                    "component_id": m["component_id"],
                    "component_type": m["component_type"],
                    "degree": m.get("degree"),
                    "param_keys": keys,
                    "params": {k: float(v) for k, v in zip(keys, vals)},
                    "y_hat": yc,
                }
            )

        return {
            "params_vector": res.p_opt.astype(float).tolist(),
            "components": comps_out,
            "y_hat": res.y_hat.astype(float).tolist() if payload.return_curve else None,
        }
    except HTTPException:
        raise
    except (ValueError, IndexError) as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


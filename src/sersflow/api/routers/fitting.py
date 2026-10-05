from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
from fastapi import APIRouter, HTTPException, Request

from sersflow.api.deps import current_user_id
from sersflow.api.services.ownership import OwnershipError

from sersflow.api.schemas.fitting import (
    FittingModelsResponse,
    FitInlineSeries,
    FitRequest,
    FitResponse,
    FitSpectrumRef,
)
from sersflow.api.services.fit_diagnostics_public import diagnostics_to_public
from sersflow.api.services.uploads import resolve_existing_upload
from sersflow.core.io.load_file import load_dataset
from sersflow.core.preprocess.fitting import expand_fit_curves_to_full, fit_curve, fit_problem_from_step_params
from sersflow.core.preprocess.fitting_specs import list_component_types
from sersflow.core.spectrum import XY


router = APIRouter(prefix="/fitting", tags=["Fitting"])


@router.get("/models", response_model=FittingModelsResponse)
def list_fitting_models() -> dict[str, Any]:
    comps = [c.to_public_dict() for c in list_component_types()]
    return {"components": comps}


def _resolve_target(target: FitInlineSeries | FitSpectrumRef, *, owner_user_id: str) -> tuple[np.ndarray, np.ndarray]:
    if isinstance(target, FitInlineSeries):
        x = np.asarray(target.x, dtype=float)
        y = np.asarray(target.y, dtype=float)
        return x, y

    # SpectrumRef target
    try:
        p = resolve_existing_upload(target.spectrum.relative_path, owner_user_id=owner_user_id)
    except OwnershipError:
        raise HTTPException(status_code=404, detail="Uploaded file not found") from None

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
        if kind == "multi":
            xs = getattr(ds, "xs", ())
            ys = getattr(ds, "ys", ())
            if idx < 0 or idx >= len(xs):
                raise ValueError(f"record_index out of range: {idx} (max {len(xs)-1})")
            return np.asarray(xs[idx], dtype=float), np.asarray(ys[idx], dtype=float)
        raise ValueError(f"Unsupported dataset kind for fitting: {kind}")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/fit", response_model=FitResponse)
def fit_endpoint(payload: FitRequest, request: Request) -> dict[str, Any]:
    user_id = current_user_id(request)
    try:
        x, y = _resolve_target(payload.target, owner_user_id=user_id)
        xy = XY(x=np.asarray(x, dtype=float), y=np.asarray(y, dtype=float))

        if not payload.p0:
            raise ValueError("p0 is required (use /fitting/models to build the correct length/order)")

        step_params: dict[str, Any] = {
            "components": [
                {
                    "component_id": c.component_id,
                    "component_type": c.component_type,
                    **({"degree": c.degree} if c.degree is not None else {}),
                }
                for c in payload.components
            ],
            "p0": list(payload.p0),
            "bounds_lower": list(payload.bounds.lower),
            "bounds_upper": list(payload.bounds.upper),
            "initial_guess_mode": str(payload.initial_guess_mode),
            "technique_family": str(payload.technique_family or "vibrational"),
        }
        if payload.vary is not None:
            step_params["vary"] = list(payload.vary)
        if payload.param_links:
            step_params["param_links"] = list(payload.param_links)
        if payload.xps_region is not None and str(payload.xps_region).strip():
            step_params["xps_region"] = str(payload.xps_region).strip()
        if payload.fit_min_x is not None:
            step_params["fit_min_x"] = float(payload.fit_min_x)
        if payload.fit_max_x is not None:
            step_params["fit_max_x"] = float(payload.fit_max_x)
        if payload.initial_area_ratios is not None and str(payload.initial_area_ratios).strip():
            step_params["initial_area_ratios"] = str(payload.initial_area_ratios).strip()

        prob = fit_problem_from_step_params(xy, step_params)
        if prob is None:
            raise ValueError("empty spectrum (or empty fit window)")
        res = fit_curve(prob)

        y_hat_full, comps_full = expand_fit_curves_to_full(
            xy, step_params, res.y_hat, res.component_y_hat, outside="nan"
        )
        y_in = xy.y.astype(float)
        residual = y_in - y_hat_full
        # NaN residual outside the window so plots do not draw a flat zero band.
        residual = np.where(np.isfinite(y_hat_full), residual, np.nan)

        comps_out = []
        for idx, m in enumerate(res.mapping):
            s, e = m["index_range"]
            keys = m["param_keys"]
            vals = res.p_opt[s:e].astype(float).tolist()
            yc = comps_full[idx].astype(float).tolist() if payload.return_curve else None
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
            "y_hat": y_hat_full.astype(float).tolist() if payload.return_curve else None,
            "residual": residual.astype(float).tolist() if payload.return_curve else None,
            "diagnostics": diagnostics_to_public(res.diagnostics),
        }
    except HTTPException:
        raise
    except (ValueError, IndexError) as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


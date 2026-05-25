from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Response

from sersflow.api.schemas.plot import (
    MapInfoResponse,
    MapPointsPlotRequest,
    PlotFigureResponse,
    PlotKindsResponse,
    SeriesHeatmapRequest,
    SeriesInfoResponse,
    SeriesPointsPlotRequest,
    SpectrumPlotRequest,
)
from sersflow.core.io.load_file import load_dataset
from sersflow.api.services.uploads import resolve_existing_upload
from sersflow.core.models.datasets import MapDataset, SeriesDataset
from sersflow.core.plot.service import (
    default_title_from_path,
    map_grid_info,
    plot_map_points as plot_map_points_figure,
    plot_series_heatmap as plot_series_heatmap_figure,
    plot_series_points as plot_series_points_figure,
    plot_spectrum as plot_spectrum_figure,
    series_axis_preview,
    series_axis_value,
)


router = APIRouter(prefix="/plot", tags=["Plot"])


@router.get("/kinds", response_model=PlotKindsResponse)
def list_plot_kinds() -> dict[str, Any]:
    return {"kinds": ["spectrum", "series_heatmap"]}


@router.post("/spectrum", response_model=PlotFigureResponse)
def plot_spectrum(payload: SpectrumPlotRequest) -> dict[str, Any]:
    try:
        p = resolve_existing_upload(payload.relative_path)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Uploaded file not found")

    try:
        ds = load_dataset(Path(p))
        title = payload.title or default_title_from_path(payload.relative_path)
        fig = plot_spectrum_figure(ds, spectrum_index=0, title=title)
        return {"figure": fig}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/series-heatmap", response_model=PlotFigureResponse)
def plot_series_heatmap(payload: SeriesHeatmapRequest) -> dict[str, Any]:
    try:
        p = resolve_existing_upload(payload.relative_path)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Uploaded file not found")

    try:
        ds = load_dataset(Path(p))
        if not isinstance(ds, SeriesDataset):
            raise ValueError("Not a series dataset")
        title = payload.title or default_title_from_path(payload.relative_path)
        fig = plot_series_heatmap_figure(ds, title=title)
        return {"figure": fig}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.get("/series-info", response_model=SeriesInfoResponse)
def series_info(relative_path: str, max_points: int = 500) -> dict[str, Any]:
    try:
        p = resolve_existing_upload(relative_path)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Uploaded file not found")

    try:
        ds = load_dataset(Path(p))
        if not isinstance(ds, SeriesDataset):
            return {"is_series": False, "axis": [], "count": 0}
        axis, count = series_axis_preview(ds, max_points=max_points)
        return {"is_series": True, "axis": axis, "count": count}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/series-points", response_model=PlotFigureResponse)
def plot_series_points(payload: SeriesPointsPlotRequest) -> dict[str, Any]:
    try:
        p = resolve_existing_upload(payload.relative_path)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Uploaded file not found")

    try:
        ds = load_dataset(Path(p))
        if not isinstance(ds, SeriesDataset):
            raise ValueError("Not a series dataset")
        title = payload.title or default_title_from_path(payload.relative_path)
        fig = plot_series_points_figure(ds, indices=payload.indices, title=title)
        return {"figure": fig}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.get("/series-value")
def series_value(relative_path: str, index: int) -> dict[str, Any]:
    try:
        p = resolve_existing_upload(relative_path)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Uploaded file not found")

    try:
        ds = load_dataset(Path(p))
        if not isinstance(ds, SeriesDataset):
            raise ValueError("Not a series dataset")
        v = series_axis_value(ds, index=index)
        return {"value": v}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.get("/map-info", response_model=MapInfoResponse)
def map_info(relative_path: str, max_dim: int = 80) -> dict[str, Any]:
    try:
        p = resolve_existing_upload(relative_path)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Uploaded file not found")

    try:
        ds = load_dataset(Path(p))
        if not isinstance(ds, MapDataset):
            return {"is_map": False, "x": [], "y": [], "index_grid": [], "count": 0}
        xs, ys, grid, count = map_grid_info(ds, max_dim=max_dim)
        return {"is_map": True, "x": xs, "y": ys, "index_grid": grid, "count": count}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.get("/map-preview-image")
def map_preview_image(relative_path: str) -> Response:
    try:
        p = resolve_existing_upload(relative_path)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Uploaded file not found")
    if p.suffix.lower() != ".wdf":
        raise HTTPException(status_code=404, detail="No embedded preview for this file type")

    try:
        from renishawWiRE import WDFReader  # type: ignore
        from PIL import Image  # type: ignore
        import io

        reader = WDFReader(str(p))
        img = getattr(reader, "img", None)
        if img is None:
            raise HTTPException(status_code=404, detail="No embedded image found")

        if isinstance(img, io.BytesIO):
            img.seek(0)
            im = Image.open(img).convert("RGBA")
        else:
            arr = np.asarray(img)
            if arr.dtype == object:
                arr = np.array(arr.tolist(), dtype=np.uint8)
            if arr.ndim == 2:
                im = Image.fromarray(arr.astype(np.uint8), mode="L").convert("RGBA")
            elif arr.ndim == 3:
                im = Image.fromarray(arr.astype(np.uint8)).convert("RGBA")
            else:
                raise HTTPException(status_code=404, detail="Unsupported embedded image format")

        out = io.BytesIO()
        im.save(out, format="PNG")
        return Response(content=out.getvalue(), media_type="image/png")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=404, detail=f"No embedded image available: {e}") from e


@router.post("/map-points", response_model=PlotFigureResponse)
def plot_map_points(payload: MapPointsPlotRequest) -> dict[str, Any]:
    try:
        p = resolve_existing_upload(payload.relative_path)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Uploaded file not found")

    try:
        ds = load_dataset(Path(p))
        if not isinstance(ds, MapDataset):
            raise ValueError("Not a map dataset")
        title = payload.title or default_title_from_path(payload.relative_path)
        fig = plot_map_points_figure(ds, indices=payload.indices, title=title)
        return {"figure": fig}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


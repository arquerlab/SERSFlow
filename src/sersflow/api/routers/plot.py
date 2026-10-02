from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request, Response
import numpy as np

from sersflow.api.deps import current_user_id
from sersflow.api.services.ownership import OwnershipError

from sersflow.api.schemas.plot import (
    MapInfoResponse,
    MapPointsPlotRequest,
    MultiInfoResponse,
    MultiPointsPlotRequest,
    PlotFigureResponse,
    PlotKindsResponse,
    SeriesHeatmapRequest,
    SeriesInfoResponse,
    SeriesPointsPlotRequest,
    SpectrumPlotRequest,
)
from sersflow.core.io.load_file import load_dataset
from sersflow.core.io.formats import get_format_for_path, list_formats
from sersflow.core.io.formats.packs import EXPERIMENTAL_FIELD_LABELS
from sersflow.core.io.multi_block_labels import (
    ELECTROCHEM_FILTER_TRIO,
    EXPERIMENTAL_BLOCK_KEYS,
    get_block_spectra,
    select_experimental_filter_keys,
)
from sersflow.api.services.uploads import resolve_existing_upload
from sersflow.core.models.datasets import MapDataset, MultiSpectrumDataset, SeriesDataset
from sersflow.infra.upload_labels_store import fetch_upload_labels_for_paths, with_connection
from sersflow.core.plot.service import (
    default_title_from_path,
    map_grid_info,
    plot_map_points as plot_map_points_figure,
    plot_multi_points as plot_multi_points_figure,
    plot_series_heatmap as plot_series_heatmap_figure,
    plot_series_points as plot_series_points_figure,
    plot_spectrum as plot_spectrum_figure,
    series_axis_preview,
    series_axis_value,
)


router = APIRouter(prefix="/plot", tags=["Plot"])


def _upload_path(request: Request, relative_path: str) -> Path:
    user_id = current_user_id(request)
    try:
        return resolve_existing_upload(relative_path, owner_user_id=user_id)
    except OwnershipError:
        raise HTTPException(status_code=404, detail="Uploaded file not found") from None
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Uploaded file not found") from None


@router.get("/kinds", response_model=PlotKindsResponse)
def list_plot_kinds() -> dict[str, Any]:
    return {"kinds": ["spectrum", "series_heatmap"]}


@router.post("/spectrum", response_model=PlotFigureResponse)
def plot_spectrum(payload: SpectrumPlotRequest, request: Request) -> dict[str, Any]:
    try:
        p = _upload_path(request, payload.relative_path)
    except HTTPException:
        raise

    try:
        ds = load_dataset(Path(p))
        title = payload.title or default_title_from_path(payload.relative_path)
        plot_mode = "xy"
        x_title = None
        y_title = None
        try:
            ui = get_format_for_path(p).merged_ui()
            plot_mode = ui.plot_mode
            x_title = ui.default_x_label
            y_title = ui.default_y_label
        except ValueError:
            pass
        # Format plot_mode: map prefers map-grid overview; xy/multi stay spectrum traces.
        if plot_mode == "map" and isinstance(ds, MapDataset):
            fig = plot_map_points_figure(ds, indices=[0], title=title)
            return {"figure": fig}
        kwargs: dict[str, Any] = {"spectrum_index": 0, "title": title}
        if x_title:
            kwargs["x_title"] = x_title
        if y_title:
            kwargs["y_title"] = y_title
        fig = plot_spectrum_figure(ds, **kwargs)
        return {"figure": fig}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/series-heatmap", response_model=PlotFigureResponse)
def plot_series_heatmap(payload: SeriesHeatmapRequest, request: Request) -> dict[str, Any]:
    try:
        p = _upload_path(request, payload.relative_path)
    except HTTPException:
        raise

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
def series_info(relative_path: str, request: Request, max_points: int = 500) -> dict[str, Any]:
    try:
        p = _upload_path(request, relative_path)
    except HTTPException:
        raise

    try:
        ds = load_dataset(Path(p))
        if not isinstance(ds, SeriesDataset):
            return {"is_series": False, "axis": [], "count": 0}
        axis, count = series_axis_preview(ds, max_points=max_points)
        return {"is_series": True, "axis": axis, "count": count}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/series-points", response_model=PlotFigureResponse)
def plot_series_points(payload: SeriesPointsPlotRequest, request: Request) -> dict[str, Any]:
    try:
        p = _upload_path(request, payload.relative_path)
    except HTTPException:
        raise

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
def series_value(relative_path: str, index: int, request: Request) -> dict[str, Any]:
    try:
        p = _upload_path(request, relative_path)
    except HTTPException:
        raise

    try:
        ds = load_dataset(Path(p))
        if not isinstance(ds, SeriesDataset):
            raise ValueError("Not a series dataset")
        v = series_axis_value(ds, index=index)
        return {"value": v}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.get("/map-info", response_model=MapInfoResponse)
def map_info(relative_path: str, request: Request, max_dim: int = 80) -> dict[str, Any]:
    try:
        p = _upload_path(request, relative_path)
    except HTTPException:
        raise

    try:
        ds = load_dataset(Path(p))
        if not isinstance(ds, MapDataset):
            return {"is_map": False, "x": [], "y": [], "index_grid": [], "count": 0}
        xs, ys, grid, count = map_grid_info(ds, max_dim=max_dim)
        return {"is_map": True, "x": xs, "y": ys, "index_grid": grid, "count": count}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.get("/map-preview-image")
def map_preview_image(relative_path: str, request: Request, crop_to_map: bool = False) -> Response:
    try:
        p = _upload_path(request, relative_path)
    except HTTPException:
        raise
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

        if crop_to_map:
            cropbox = getattr(reader, "img_cropbox", None)
            if cropbox is not None:
                left, top, right, bottom = (int(value) for value in cropbox)
                width, height = im.size
                left = max(0, min(left, width))
                right = max(0, min(right, width))
                top = max(0, min(top, height))
                bottom = max(0, min(bottom, height))
                if right > left and bottom > top:
                    im = im.crop((left, top, right, bottom))

        out = io.BytesIO()
        im.save(out, format="PNG")
        return Response(content=out.getvalue(), media_type="image/png")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=404, detail=f"No embedded image available: {e}") from e


@router.post("/map-points", response_model=PlotFigureResponse)
def plot_map_points(payload: MapPointsPlotRequest, request: Request) -> dict[str, Any]:
    try:
        p = _upload_path(request, payload.relative_path)
    except HTTPException:
        raise

    try:
        ds = load_dataset(Path(p))
        if not isinstance(ds, MapDataset):
            raise ValueError("Not a map dataset")
        title = payload.title or default_title_from_path(payload.relative_path)
        fig = plot_map_points_figure(ds, indices=payload.indices, title=title)
        return {"figure": fig}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e)) from e



def _multi_field_catalog(blocks: list[dict[str, Any]], *, technique_family: str = "xps") -> list[dict[str, Any]]:
    present: set[str] = set()
    for b in blocks:
        for k, v in b.items():
            if v is None or k == "index":
                continue
            present.add(str(k))

    keys: list[tuple[str, str, str]] = []
    seen: set[str] = set()
    for fmt in list_formats():
        if technique_family == "xps" and fmt.technique != "xps" and fmt.technique != "sniff":
            continue
        if technique_family != "xps" and fmt.technique == "xps":
            continue
        for fdef in fmt.all_filter_fields():
            if fdef.source != "structural":
                continue
            if fdef.key in seen:
                continue
            seen.add(fdef.key)
            keys.append((fdef.key, fdef.label, fdef.kind))

    experimental_labels = dict(EXPERIMENTAL_FIELD_LABELS)
    for key in select_experimental_filter_keys(technique_family=technique_family, present_keys=present):
        label, kind = experimental_labels[key]
        keys.append((key, label, kind))

    electrochem_force = set(ELECTROCHEM_FILTER_TRIO) & {k for k, _, _ in keys}
    fields: list[dict[str, Any]] = []
    for key, label, kind in keys:
        if kind == "categorical":
            vals: list[str] = []
            seen: set[str] = set()
            for b in blocks:
                v = b.get(key)
                if v is None:
                    continue
                s = str(v)
                if s not in seen:
                    seen.add(s)
                    vals.append(s)
            if vals or key in electrochem_force:
                fields.append({"id": key, "label": label, "kind": "categorical", "values": sorted(vals)})
        else:
            nums: list[float] = []
            for b in blocks:
                try:
                    n = float(b.get(key))  # type: ignore[arg-type]
                except (TypeError, ValueError):
                    continue
                if n == n:
                    nums.append(n)
            if nums:
                fields.append(
                    {
                        "id": key,
                        "label": label,
                        "kind": "numeric",
                        "min": min(nums),
                        "max": max(nums),
                    }
                )
    return fields


_EXPERIMENTAL_MERGE_KEYS = tuple(sorted(EXPERIMENTAL_BLOCK_KEYS))


def _as_optional_float(v: Any) -> float | None:
    if v is None or isinstance(v, bool):
        return None
    try:
        n = float(v)
    except (TypeError, ValueError):
        return None
    if n != n:
        return None
    return n


@router.get("/multi-info", response_model=MultiInfoResponse)
def multi_info(relative_path: str, request: Request) -> dict[str, Any]:
    try:
        p = _upload_path(request, relative_path)
    except HTTPException:
        raise
    try:
        ds = load_dataset(Path(p))
        if not isinstance(ds, MultiSpectrumDataset):
            return {"is_multi": False, "count": 0, "blocks": [], "fields": []}
        label_map: dict[str, dict[str, Any]] = {}
        try:
            con = with_connection()
            try:
                lab = fetch_upload_labels_for_paths(con, [relative_path]).get(relative_path) or {}
            finally:
                con.close()
            label_map = get_block_spectra(lab)
            path_exp = {k: lab.get(k) for k in _EXPERIMENTAL_MERGE_KEYS if lab.get(k) is not None}
        except Exception:
            path_exp = {}
        blocks: list[dict[str, Any]] = []
        for i, m in enumerate(ds.meta):
            md = dict(m or {})
            block_lab = label_map.get(str(i)) or {}
            # Path experimental defaults, then structural file meta, then per-block labels (block wins).
            merged_exp: dict[str, Any] = dict(path_exp)
            for k in _EXPERIMENTAL_MERGE_KEYS:
                if k in block_lab and block_lab[k] is not None:
                    merged_exp[k] = block_lab[k]
            row: dict[str, Any] = {
                "index": i,
                "xps_region": md.get("xps_region"),
                "spectrum_role": md.get("spectrum_role"),
                "xps_species": md.get("xps_species"),
                "xps_transition": md.get("xps_transition"),
                "block_name": md.get("block_name") or block_lab.get("block_name"),
                "replicate_index": md.get("replicate_index"),
                "excitation_energy_eV": md.get("excitation_energy_eV"),
                "technique": md.get("technique"),
                "acquired_at": md.get("acquired_at"),
                "sample": merged_exp.get("sample"),
                "gas": merged_exp.get("gas"),
                "ph": _as_optional_float(merged_exp.get("ph")),
                "current_density_A_cm2": _as_optional_float(merged_exp.get("current_density_A_cm2")),
                "potential_V": _as_optional_float(merged_exp.get("potential_V")),
                "potential_ref": merged_exp.get("potential_ref"),
                "electrolyte": merged_exp.get("electrolyte"),
                "concentration_M": _as_optional_float(merged_exp.get("concentration_M")),
                "laser_nm": _as_optional_float(merged_exp.get("laser_nm")),
                "laser_power_pct": _as_optional_float(merged_exp.get("laser_power_pct")),
            }
            # String-coerce sample/gas/etc when stored as non-str
            for sk in ("sample", "gas", "potential_ref", "electrolyte"):
                if row[sk] is not None and not isinstance(row[sk], str):
                    row[sk] = str(row[sk])
            blocks.append(row)
        return {
            "is_multi": True,
            "count": len(blocks),
            "blocks": blocks,
            "fields": _multi_field_catalog(blocks, technique_family="xps"),
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/multi-points", response_model=PlotFigureResponse)
def plot_multi_points(payload: MultiPointsPlotRequest, request: Request) -> dict[str, Any]:
    try:
        p = _upload_path(request, payload.relative_path)
    except HTTPException:
        raise
    try:
        ds = load_dataset(Path(p))
        if not isinstance(ds, MultiSpectrumDataset):
            raise ValueError("Not a multi-spectrum (VAMAS) dataset")
        title = payload.title or default_title_from_path(payload.relative_path)
        fig = plot_multi_points_figure(ds, indices=payload.indices, title=title, max_traces=30)
        return {"figure": fig}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


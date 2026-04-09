from __future__ import annotations

from typing import Any, Iterable

import numpy as np


def _as_1d(a: Any) -> np.ndarray:
    arr = np.asarray(a)
    if arr.ndim != 1:
        raise ValueError(f"Expected 1D array, got shape {arr.shape}")
    return arr


def _as_2d(a: Any) -> np.ndarray:
    arr = np.asarray(a)
    if arr.ndim != 2:
        raise ValueError(f"Expected 2D array, got shape {arr.shape}")
    return arr


def spectrum_figure_json(
    *,
    x: Any,
    y: Any,
    title: str = "Spectrum",
    x_title: str = "Raman Shift (cm$^{-1}$)",
    y_title: str = "Intensity (counts)",
) -> dict[str, Any]:
    x1 = _as_1d(x).astype(float, copy=False)
    y1 = _as_1d(y).astype(float, copy=False)
    if x1.shape != y1.shape:
        raise ValueError(f"x and y must have the same shape, got {x1.shape} vs {y1.shape}")

    return {
        "data": [
            {
                "type": "scatter",
                "mode": "lines",
                "x": x1.tolist(),
                "y": y1.tolist(),
                "name": title,
            }
        ],
        "layout": {
            "xaxis": {
                "title": {"text": x_title},
                "showline": True,
                "mirror": True,
                "showgrid": False,
                "ticks": "outside",
                "ticklen": 6,
                "tickwidth": 1,
            },
            "yaxis": {
                "title": {"text": y_title},
                "showline": True,
                "mirror": True,
                "showgrid": False,
                "ticks": "outside",
                "ticklen": 6,
                "tickwidth": 1,
            },
            "legend": {"orientation": "h", "yanchor": "top", "y": -0.25, "xanchor": "center", "x": 0.5},
            "margin": {"l": 60, "r": 20, "t": 20, "b": 95},
        },
    }


def overlay_figure_json(
    *,
    x: Any,
    ys: Iterable[Any],
    labels: Iterable[str] | None = None,
    title: str = "Overlay",
    x_title: str = "Raman Shift (cm$^{-1}$)",
    y_title: str = "Intensity (counts)",
) -> dict[str, Any]:
    x1 = _as_1d(x).astype(float, copy=False)
    ys_list = list(ys)
    labels_list = list(labels) if labels is not None else [f"trace_{i+1}" for i in range(len(ys_list))]
    if len(labels_list) != len(ys_list):
        raise ValueError("labels length must match ys length")

    data = []
    for y, label in zip(ys_list, labels_list, strict=False):
        y1 = _as_1d(y).astype(float, copy=False)
        if y1.shape != x1.shape:
            raise ValueError(f"All traces must share the same x shape. Expected {x1.shape}, got {y1.shape}")
        data.append({"type": "scatter", "mode": "lines", "x": x1.tolist(), "y": y1.tolist(), "name": label})

    return {
        "data": data,
        "layout": {
            "xaxis": {
                "title": {"text": x_title},
                "showline": True,
                "mirror": True,
                "showgrid": False,
                "ticks": "outside",
                "ticklen": 6,
                "tickwidth": 1,
            },
            "yaxis": {
                "title": {"text": y_title},
                "showline": True,
                "mirror": True,
                "showgrid": False,
                "ticks": "outside",
                "ticklen": 6,
                "tickwidth": 1,
            },
            "legend": {"orientation": "h", "yanchor": "top", "y": -0.25, "xanchor": "center", "x": 0.5},
            "margin": {"l": 60, "r": 20, "t": 20, "b": 95},
        },
    }


def series_heatmap_figure_json(
    *,
    x: Any,
    series_axis: Any,
    z: Any,
    title: str = "Series heatmap",
    x_title: str = "Raman Shift (cm$^{-1}$)",
    y_title: str = "Series axis",
    z_title: str = "Intensity (counts)",
) -> dict[str, Any]:
    x1 = _as_1d(x).astype(float, copy=False)
    y1 = _as_1d(series_axis).astype(float, copy=False)
    z2 = _as_2d(z).astype(float, copy=False)

    if z2.shape != (y1.size, x1.size):
        raise ValueError(
            f"z must have shape (len(series_axis), len(x)). Expected {(y1.size, x1.size)}, got {z2.shape}"
        )

    return {
        "data": [
            {
                "type": "heatmap",
                "x": x1.tolist(),
                "y": y1.tolist(),
                "z": z2.tolist(),
                "colorbar": {"title": {"text": z_title}},
            }
        ],
        "layout": {
            "xaxis": {
                "title": {"text": x_title},
                "showline": True,
                "mirror": True,
                "showgrid": False,
                "ticks": "outside",
                "ticklen": 6,
                "tickwidth": 1,
            },
            "yaxis": {
                "title": {"text": y_title},
                "showline": True,
                "mirror": True,
                "showgrid": False,
                "ticks": "outside",
                "ticklen": 6,
                "tickwidth": 1,
            },
            "margin": {"l": 60, "r": 20, "t": 20, "b": 75},
        },
    }


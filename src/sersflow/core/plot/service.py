from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import numpy as np

from sersflow.core.models.datasets import Dataset, MapDataset, SeriesDataset, SpectrumDataset
from sersflow.core.plot.figure_json import (
    RAMAN_SHIFT_AXIS_TITLE,
    overlay_figure_json,
    series_heatmap_figure_json,
    spectrum_figure_json,
)


@dataclass(frozen=True)
class OverlayTrace:
    label: str
    y: np.ndarray


def pick_1d_spectrum(dataset: Dataset, *, spectrum_index: int) -> np.ndarray:
    """
    Normalize different dataset kinds into a single y-vector for spectrum plotting.

    - SpectrumDataset -> its y
    - SeriesDataset -> spectra[spectrum_index]
    - MapDataset -> spectra[spectrum_index]
    """
    i = int(spectrum_index)
    if i < 0:
        raise ValueError("spectrum_index must be >= 0")

    if isinstance(dataset, SpectrumDataset):
        return dataset.y
    if isinstance(dataset, (SeriesDataset, MapDataset)):
        if i >= dataset.spectra.shape[0]:
            raise ValueError(f"spectrum_index out of range (max {dataset.spectra.shape[0]-1})")
        return dataset.spectra[i, :]
    raise TypeError(f"Unsupported dataset type: {type(dataset)}")


def plot_spectrum(
    dataset: Dataset,
    *,
    spectrum_index: int = 0,
    title: str = "Spectrum",
    x_title: str = RAMAN_SHIFT_AXIS_TITLE,
    y_title: str = "Intensity (counts)",
) -> dict:
    y = pick_1d_spectrum(dataset, spectrum_index=spectrum_index)
    return spectrum_figure_json(x=dataset.x, y=y, title=title, x_title=x_title, y_title=y_title)


def plot_overlay(
    datasets: Iterable[tuple[str, Dataset]],
    *,
    spectrum_index: int = 0,
    title: str = "Overlay",
    x_title: str = RAMAN_SHIFT_AXIS_TITLE,
    y_title: str = "Intensity (counts)",
) -> dict:
    items = list(datasets)
    if not items:
        raise ValueError("No datasets provided for overlay")

    x0 = items[0][1].x
    ys: list[np.ndarray] = []
    labels: list[str] = []
    for label, ds in items:
        if np.asarray(ds.x).shape != np.asarray(x0).shape or not np.allclose(ds.x, x0, equal_nan=True):
            raise ValueError("All inputs must share the same x-axis for overlay")
        ys.append(pick_1d_spectrum(ds, spectrum_index=spectrum_index))
        labels.append(label)
    return overlay_figure_json(x=x0, ys=ys, labels=labels, title=title, x_title=x_title, y_title=y_title)


def plot_series_heatmap(
    dataset: SeriesDataset,
    *,
    title: str = "Series heatmap",
    x_title: str = RAMAN_SHIFT_AXIS_TITLE,
    y_title: str | None = None,
    z_title: str = "Intensity (counts)",
) -> dict:
    if y_title is None:
        if dataset.axis_name == "time_s":
            y_title = "Time (s)"
        elif dataset.axis_name == "z":
            y_title = "Depth (z)"
        else:
            y_title = dataset.axis_name
    return series_heatmap_figure_json(
        x=dataset.x,
        series_axis=dataset.axis,
        z=dataset.spectra,
        title=title,
        x_title=x_title,
        y_title=y_title,
        z_title=z_title,
    )


def series_axis_preview(dataset: SeriesDataset, *, max_points: int = 500) -> tuple[list[float], int]:
    n = int(dataset.axis.size)
    mp = int(max_points)
    if mp < 1:
        mp = 1
    mp = min(mp, 5000)
    if n <= mp:
        return dataset.axis.astype(float, copy=False).tolist(), n
    idx = np.linspace(0, n - 1, mp, dtype=int)
    return dataset.axis[idx].astype(float, copy=False).tolist(), n


def series_axis_value(dataset: SeriesDataset, *, index: int) -> float:
    i = int(index)
    if i < 0 or i >= dataset.axis.size:
        raise ValueError(f"Index out of range: {i} (0..{dataset.axis.size-1})")
    return float(dataset.axis[i])


def plot_series_points(
    dataset: SeriesDataset,
    *,
    indices: list[int],
    title: str = "Series points",
    x_title: str = RAMAN_SHIFT_AXIS_TITLE,
    y_title: str = "Intensity (counts)",
) -> dict:
    n = int(dataset.spectra.shape[0])
    dedup: list[int] = []
    seen: set[int] = set()
    for i in indices:
        ii = int(i)
        if ii < 0 or ii >= n:
            raise ValueError(f"Index out of range: {ii} (0..{n-1})")
        if ii in seen:
            continue
        seen.add(ii)
        dedup.append(ii)
    ys = [dataset.spectra[i, :] for i in dedup]
    labels = [f"{float(dataset.axis[i]):.1f}" for i in dedup]
    return overlay_figure_json(x=dataset.x, ys=ys, labels=labels, title=title, x_title=x_title, y_title=y_title)


def map_grid_info(dataset: MapDataset, *, max_dim: int = 80) -> tuple[list[float], list[float], list[list[int | None]], int]:
    n = int(dataset.spectra.shape[0])
    xs = np.unique(dataset.xpos.astype(float, copy=False))
    ys = np.unique(dataset.ypos.astype(float, copy=False))
    xs.sort()
    ys.sort()

    md = int(max_dim)
    if md < 2:
        md = 2
    md = min(md, 200)

    if xs.size > md:
        idx = np.linspace(0, xs.size - 1, md, dtype=int)
        xs = xs[idx]
    if ys.size > md:
        idx = np.linspace(0, ys.size - 1, md, dtype=int)
        ys = ys[idx]

    x_to_i = {float(v): i for i, v in enumerate(xs.tolist())}
    y_to_i = {float(v): i for i, v in enumerate(ys.tolist())}

    grid: list[list[int | None]] = [[None for _ in range(int(xs.size))] for __ in range(int(ys.size))]
    for idx_pt, (xv, yv) in enumerate(zip(dataset.xpos.astype(float), dataset.ypos.astype(float), strict=False)):
        xi = x_to_i.get(float(xv))
        yi = y_to_i.get(float(yv))
        if xi is None or yi is None:
            continue
        grid[yi][xi] = int(idx_pt)
    return xs.astype(float, copy=False).tolist(), ys.astype(float, copy=False).tolist(), grid, n


def plot_map_points(
    dataset: MapDataset,
    *,
    indices: list[int],
    title: str = "Map points",
    x_title: str = RAMAN_SHIFT_AXIS_TITLE,
    y_title: str = "Intensity (counts)",
) -> dict:
    n = int(dataset.spectra.shape[0])
    dedup: list[int] = []
    seen: set[int] = set()
    for i in indices:
        ii = int(i)
        if ii < 0 or ii >= n:
            raise ValueError(f"Index out of range: {ii} (0..{n-1})")
        if ii in seen:
            continue
        seen.add(ii)
        dedup.append(ii)

    ys = [dataset.spectra[i, :] for i in dedup]
    labels = [f"x={float(dataset.xpos[i]):g}, y={float(dataset.ypos[i]):g}" for i in dedup]
    return overlay_figure_json(x=dataset.x, ys=ys, labels=labels, title=title, x_title=x_title, y_title=y_title)


def default_title_from_path(relative_path: str) -> str:
    try:
        return Path(relative_path).name
    except Exception:
        return str(relative_path)


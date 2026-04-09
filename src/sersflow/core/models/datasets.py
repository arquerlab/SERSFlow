from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Union

import numpy as np


def _as_1d(a: object, *, name: str) -> np.ndarray:
    arr = np.asarray(a)
    if arr.ndim != 1:
        raise ValueError(f"{name} must be 1D, got shape={arr.shape}")
    return arr


def _as_2d(a: object, *, name: str) -> np.ndarray:
    arr = np.asarray(a)
    if arr.ndim != 2:
        raise ValueError(f"{name} must be 2D, got shape={arr.shape}")
    return arr


@dataclass(frozen=True)
class SpectrumDataset:
    kind: Literal["spectrum"]
    x: np.ndarray
    y: np.ndarray

    def __post_init__(self) -> None:
        x1 = _as_1d(self.x, name="x")
        y1 = _as_1d(self.y, name="y")
        if x1.shape != y1.shape:
            raise ValueError(f"x and y must have same shape, got {x1.shape} vs {y1.shape}")
        object.__setattr__(self, "x", x1)
        object.__setattr__(self, "y", y1)


@dataclass(frozen=True)
class SeriesDataset:
    kind: Literal["series"]
    x: np.ndarray
    spectra: np.ndarray
    axis: np.ndarray
    axis_name: str

    def __post_init__(self) -> None:
        x1 = _as_1d(self.x, name="x")
        spectra2 = _as_2d(self.spectra, name="spectra")
        axis1 = _as_1d(self.axis, name="axis")
        if spectra2.shape[1] != x1.size:
            raise ValueError(
                f"spectra second dimension must match len(x). spectra={spectra2.shape} len(x)={x1.size}"
            )
        if axis1.size != spectra2.shape[0]:
            raise ValueError(
                f"axis length must match spectra rows. axis={axis1.size} spectra_rows={spectra2.shape[0]}"
            )
        object.__setattr__(self, "x", x1)
        object.__setattr__(self, "spectra", spectra2)
        object.__setattr__(self, "axis", axis1)


@dataclass(frozen=True)
class MapDataset:
    kind: Literal["map"]
    x: np.ndarray
    spectra: np.ndarray
    xpos: np.ndarray
    ypos: np.ndarray

    def __post_init__(self) -> None:
        x1 = _as_1d(self.x, name="x")
        spectra2 = _as_2d(self.spectra, name="spectra")
        xpos1 = _as_1d(self.xpos, name="xpos")
        ypos1 = _as_1d(self.ypos, name="ypos")
        if spectra2.shape[1] != x1.size:
            raise ValueError(
                f"spectra second dimension must match len(x). spectra={spectra2.shape} len(x)={x1.size}"
            )
        if xpos1.size != spectra2.shape[0] or ypos1.size != spectra2.shape[0]:
            raise ValueError(
                f"xpos/ypos length must match spectra rows. spectra_rows={spectra2.shape[0]} xpos={xpos1.size} ypos={ypos1.size}"
            )
        object.__setattr__(self, "x", x1)
        object.__setattr__(self, "spectra", spectra2)
        object.__setattr__(self, "xpos", xpos1)
        object.__setattr__(self, "ypos", ypos1)


Dataset = Union[SpectrumDataset, SeriesDataset, MapDataset]


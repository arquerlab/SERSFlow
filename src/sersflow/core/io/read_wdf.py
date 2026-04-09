from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
from renishawWiRE import WDFReader
from renishawWiRE.types import DataType

from sersflow.core.models.datasets import MapDataset, SeriesDataset, SpectrumDataset


def read_file_wdf(file_path: Path) -> SpectrumDataset | SeriesDataset | MapDataset:
    """Load a WDF file and return a typed dataset."""
    reader = WDFReader(file_path)
    mt = reader.measurement_type
    mt_value = mt.value if hasattr(mt, "value") else mt
    mt_int = int(mt_value)

    if mt_int == 1:
        x = np.asarray(reader.xdata)
        spectra = np.asarray(reader.spectra)
        # WDFReader may expose spectra as (n_x,) for single spectrum, or (n_spectra, n_x).
        if spectra.ndim == 2:
            y = spectra[0, :]
        else:
            y = spectra
        return SpectrumDataset(kind="spectrum", x=x, y=y)
    if mt_int == 2:
        axis_name, axis = get_wdf_series_axis(reader)
        x = np.asarray(reader.xdata)
        spectra = np.asarray(reader.spectra)
        # Equipment bug: some acquisitions report negative time points.
        if axis_name == "time_s":
            axis = np.asarray(axis, dtype=float)
            spectra = np.asarray(spectra)
            keep = axis >= 0
            if keep.ndim == 1 and spectra.ndim == 2 and keep.size == spectra.shape[0] and not bool(np.all(keep)):
                axis = axis[keep]
                spectra = spectra[keep, :]
        return SeriesDataset(kind="series", x=x, spectra=spectra, axis=axis, axis_name=axis_name)
    if mt_int == 3:
        xdata = np.asarray(reader.xdata)
        spectra = np.asarray(reader.spectra)
        xpos = np.asarray(reader.xpos)
        ypos = np.asarray(reader.ypos)

        if xpos.ndim > 1:
            xpos = xpos.reshape(-1)
        if ypos.ndim > 1:
            ypos = ypos.reshape(-1)

        if spectra.ndim == 2:
            spectra_2d = spectra
        elif spectra.ndim == 3:
            if spectra.shape[-1] == xdata.size:
                spectra_2d = spectra.reshape(-1, spectra.shape[-1])
            elif spectra.shape[0] == xdata.size:
                spectra_2d = np.moveaxis(spectra, 0, -1).reshape(-1, spectra.shape[0])
            else:
                raise ValueError(f"Unsupported mapping spectra shape: {spectra.shape} (xdata={xdata.shape})")
        else:
            raise ValueError(f"Unsupported mapping spectra ndim: {spectra.ndim} (shape={spectra.shape})")

        n_points = int(spectra_2d.shape[0])
        if xpos.size != n_points or ypos.size != n_points:
            xpos = np.arange(n_points, dtype=float)
            ypos = np.zeros(n_points, dtype=float)

        return MapDataset(kind="map", x=xdata, spectra=spectra_2d, xpos=xpos, ypos=ypos)
    raise ValueError(f"Unknown measurement type: {mt} (value={mt_value})")


def get_wdf_series_axis(reader: WDFReader) -> tuple[str, np.ndarray]:
    """
    Extract the navigation axis for a WiRE \"Series\" measurement.

    Returns:
        (axis_name, axis_values)
        axis_name is one of: \"time_s\", \"z\", or \"index\"
    """
    origin_rows = getattr(reader, "origin_list_header", []) or []

    for row in origin_rows:
        if len(row) >= 5 and row[1] == DataType.Time:
            arr = np.asarray(row[4], dtype="float64")
            return "time_s", arr

    for row in origin_rows:
        if len(row) < 5:
            continue
        label = str(row[3] or "").strip().lower()
        if "time" in label:
            arr = np.asarray(row[4], dtype="float64")
            if arr.size and (arr[0] != 0.0):
                arr = arr - arr[0]
            return "time_s", arr

    z = np.asarray(getattr(reader, "zpos", []), dtype="float64")
    if z.size and not np.allclose(z, z[0]):
        return "z", z

    spectra = np.asarray(reader.spectra)
    n = int(getattr(reader, "count", 0)) or (spectra.shape[0] if spectra.ndim == 2 else 1)
    return "index", np.arange(n, dtype="int64")


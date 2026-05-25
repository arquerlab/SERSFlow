from __future__ import annotations

from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd

from sersflow.core.models.datasets import MapDataset, SeriesDataset, SpectrumDataset


def read_file_txt(file_path: Path) -> SpectrumDataset | SeriesDataset | MapDataset:
    """
    Load a TXT file and return a typed dataset.

    Supported formats (tab-separated, with header):
    - 2 columns: spectrum (wn, int)
    - 3 columns: series/time-resolved (time, wn, int)
    - 4 columns: map (x, y, wn, int)
    """
    count_columns, delimiter = infer_txt_layout(file_path)
    if count_columns == 2:
        x, y = load_spectrum_txt(file_path, delimiter=delimiter)
        return SpectrumDataset(kind="spectrum", x=x, y=y)
    if count_columns == 3:
        x, spectra, axis = load_tr_txt(file_path, delimiter=delimiter)
        # Equipment bug: some acquisitions report negative time points.
        axis = np.asarray(axis)
        spectra = np.asarray(spectra)
        keep = axis >= 0
        if keep.ndim == 1 and keep.size == spectra.shape[0] and not bool(np.all(keep)):
            axis = axis[keep]
            spectra = spectra[keep, :]
        return SeriesDataset(kind="series", x=x, spectra=spectra, axis=axis, axis_name="time_s")
    if count_columns == 4:
        x, spectra, xpos, ypos = load_map_txt(file_path, delimiter=delimiter)
        return MapDataset(kind="map", x=x, spectra=spectra, xpos=xpos, ypos=ypos)
    raise ValueError(
        f"Unknown TXT layout: inferred {count_columns} columns using delimiter={delimiter!r}. "
        f"Expected 2 (spectrum), 3 (series), or 4 (map). File: {file_path}"
    )


def load_map_txt(
    file_path: Path, *, delimiter: str = "\t"
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Load a Raman mapping txt file and normalize coordinate/intensity columns."""
    df = pd.read_csv(file_path, sep=delimiter, header=0, usecols=[0, 1, 2, 3], dtype="float32")
    df.columns = ["x", "y", "wn", "int"]

    # Ensure consistent ordering
    df = df.sort_values(["x", "y", "wn"], kind="mergesort")

    # xdata (wn axis) once
    xdata = df["wn"].drop_duplicates().to_numpy()

    # spectra matrix: rows are points (x,y), cols are wn
    wide = df.pivot(index=["x", "y"], columns="wn", values="int")

    xpos = wide.index.get_level_values("x").to_numpy()
    ypos = wide.index.get_level_values("y").to_numpy()
    spectra = wide.to_numpy(dtype="float32")  # shape: (n_points, n_wn)
    return xdata, spectra, xpos, ypos


def load_tr_txt(file_path: Path, *, delimiter: str = "\t") -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Load a time resolved txt file and normalize coordinate/intensity columns."""
    df = pd.read_csv(file_path, sep=delimiter, header=0, usecols=[0, 1, 2], dtype="float32")
    df.columns = ["time", "wn", "int"]

    # Ensure consistent ordering
    df = df.sort_values(["time", "wn"], kind="mergesort")

    # xdata (wn axis) once
    xdata = df["wn"].drop_duplicates().to_numpy()

    # spectra matrix: rows are time points, cols are wn
    wide = df.pivot(index="time", columns="wn", values="int")
    time_s = wide.index.to_numpy(dtype="float32")
    spectra = wide.to_numpy(dtype="float32")  # shape: (n_time, n_wn)
    return xdata, spectra, time_s


def load_spectrum_txt(file_path: Path, *, delimiter: str = "\t") -> tuple[np.ndarray, np.ndarray]:
    """Load a spectrum txt file and normalize coordinate/intensity columns."""
    df = pd.read_csv(file_path, sep=delimiter, header=0, usecols=[0, 1], dtype="float32")
    df.columns = ["wn", "int"]
    return df["wn"].to_numpy(dtype="float32"), df["int"].to_numpy(dtype="float32")


def _count_columns_txt_with_delimiter(
    file_path: str | Path,
    *,
    delimiter: str = "\t",
    sample_lines: int = 3,
    encoding: str = "utf-8",
) -> int:
    """
    Estimate the *real* number of columns by sampling a few non-empty data lines.
    - Skips the first non-empty line (assumed header).
    - Splits by `delimiter`.
    - Ignores empty trailing fields caused by extra delimiters.
    - Returns the most common column count in the sample.
    """
    file_path = Path(file_path)
    counts: Counter[int] = Counter()
    with file_path.open("r", encoding=encoding, errors="replace") as f:
        saw_header = False
        for line in f:
            s = line.strip()
            if not s:
                continue
            if not saw_header:
                saw_header = True
                continue  # skip header
            parts = s.split(delimiter)
            while parts and parts[-1].strip() == "":
                parts.pop()
            if parts:
                counts[len(parts)] += 1
                if sum(counts.values()) >= sample_lines:
                    break
    if not counts:
        raise ValueError(f"Could not infer column count from data lines in: {file_path}")
    return counts.most_common(1)[0][0]


def infer_txt_layout(
    file_path: str | Path,
    *,
    sample_lines: int = 5,
    encoding: str = "utf-8",
) -> tuple[int, str]:
    """
    Infer delimiter and column count for supported TXT layouts.

    We keep strict layout rules (2/3/4 columns) but accept common separators:
    - tab, comma, semicolon, whitespace
    """
    file_path = Path(file_path)
    candidates: list[tuple[str, str]] = [
        ("\t", "tab"),
        (",", "comma"),
        (";", "semicolon"),
        (r"\s+", "whitespace"),
    ]

    scored: list[tuple[int, int, str]] = []
    # Score = (how many sampled lines agree on the modal column count, preference for 2/3/4, delimiter)
    for delim, _name in candidates:
        try:
            # We need both the modal count and how strongly it dominates.
            counts: Counter[int] = Counter()
            with file_path.open("r", encoding=encoding, errors="replace") as f:
                saw_header = False
                for line in f:
                    s = line.strip()
                    if not s:
                        continue
                    if not saw_header:
                        saw_header = True
                        continue
                    parts = s.split(delim) if delim != r"\s+" else s.split()
                    if not parts:
                        continue
                    counts[len(parts)] += 1
                    if sum(counts.values()) >= sample_lines:
                        break
            if not counts:
                continue
            modal_cols, modal_hits = counts.most_common(1)[0]
            layout_bonus = 100 if modal_cols in (2, 3, 4) else 0
            scored.append((modal_hits * 10 + layout_bonus, modal_cols, delim))
        except Exception:
            continue

    if not scored:
        raise ValueError(f"Could not infer delimiter/column count from: {file_path}")

    scored.sort(reverse=True)
    _score, cols, delim = scored[0]
    return int(cols), ("\t" if delim == "\t" else ("," if delim == "," else (";" if delim == ";" else r"\s+")))


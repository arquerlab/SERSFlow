from __future__ import annotations

from pathlib import Path

from sersflow.core.io.read_txt import read_file_txt
from sersflow.core.io.read_wdf import read_file_wdf
from sersflow.core.models.datasets import Dataset


def load_dataset(file_path: Path) -> Dataset:
    """
    Identify the filetype of a file and load it as a typed dataset.
    """
    file_path = Path(file_path)
    suffix = file_path.suffix.lower()
    if suffix == ".txt":
        return read_file_txt(file_path)
    if suffix == ".wdf":
        return read_file_wdf(file_path)
    raise ValueError(f"Unsupported file type: {suffix} ({file_path})")


# Backwards-compatible alias (will be removed once legacy paths are deleted)
read_file_generic = load_dataset


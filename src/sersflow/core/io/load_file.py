from __future__ import annotations

from pathlib import Path

from sersflow.core.io.formats import get_format_for_path
from sersflow.core.models.datasets import Dataset


def load_dataset(file_path: Path) -> Dataset:
    """
    Identify the filetype via the format registry and load it as a typed dataset.
    """
    file_path = Path(file_path)
    spec = get_format_for_path(file_path)
    return spec.loader(file_path)


# Backwards-compatible alias (will be removed once legacy paths are deleted)
read_file_generic = load_dataset

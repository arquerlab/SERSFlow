from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from sersflow.core.io.load_file import load_dataset
from sersflow.core.io.read_nxs import read_file_nxs, read_nxs_blocks
from sersflow.core.io.technique import infer_technique_family
from sersflow.core.models.datasets import MultiSpectrumDataset


h5py = pytest.importorskip("h5py")


def _write_synthetic_nxs(path: Path, *, regions: list[tuple[str, int]]) -> None:
    """
    regions: list of (region_key, n_individual) where n_individual is count of spectrum_1..N.
    Always writes spectrum (average) plus spectrum_1..n_individual.
    number_of_iterations = n_individual + 1 (diamond_analysis convention).
    """
    with h5py.File(path, "w") as f:
        entry = f.create_group("entry")
        inst = entry.create_group("instrument")
        for region_key, n_ind in regions:
            data = entry.create_group(region_key)
            be = np.linspace(290.0, 280.0, 11)
            data.create_dataset("binding_energy", data=be)
            data.create_dataset("excitation_energy", data=1486.6)
            data.create_dataset("spectrum", data=np.linspace(1.0, 2.0, 11))
            for i in range(1, n_ind + 1):
                data.create_dataset(f"spectrum_{i}", data=np.linspace(float(i), float(i) + 1.0, 11))
            ig = inst.create_group(region_key)
            ig.create_dataset("number_of_iterations", data=n_ind + 1)
            ig.create_dataset("step_time", data=0.1)
            ig.create_dataset("total_steps", data=11)
            ig.create_dataset("total_time", data=1.1)


def test_nxs_loader_two_regions_avg_plus_two_individuals(tmp_path: Path) -> None:
    path = tmp_path / "sample.nxs"
    # C1s and O1s sorted → C1s first; each: spectrum + spectrum_1 + spectrum_2 → 6 blocks
    _write_synthetic_nxs(path, regions=[("O1s", 2), ("C1s", 2)])
    ds = read_file_nxs(path)
    assert isinstance(ds, MultiSpectrumDataset)
    assert len(ds.xs) == 6
    assert len(ds.meta) == 6

    roles = [m.get("spectrum_role") for m in ds.meta]
    regions = [m.get("xps_region") for m in ds.meta]
    names = [m.get("block_name") for m in ds.meta]

    assert regions == ["C1s", "C1s", "C1s", "O1s", "O1s", "O1s"]
    assert roles == ["average", "individual", "individual", "average", "individual", "individual"]
    assert names[0] == "C1s_spectrum"
    assert names[1] == "C1s_spectrum_1"
    assert names[5] == "O1s_spectrum_2"

    # Stable re-read
    ds2 = load_dataset(path)
    assert [m.get("block_name") for m in ds2.meta] == names
    assert infer_technique_family(path) == "xps"


def test_nxs_empty_raises(tmp_path: Path) -> None:
    path = tmp_path / "empty.nxs"
    with h5py.File(path, "w") as f:
        f.create_group("entry")
    with pytest.raises(ValueError, match="no usable"):
        read_file_nxs(path)
    assert read_nxs_blocks(path) == []


def test_nxs_skips_region_without_binding_energy(tmp_path: Path) -> None:
    path = tmp_path / "partial.nxs"
    with h5py.File(path, "w") as f:
        entry = f.create_group("entry")
        bad = entry.create_group("junk")
        bad.create_dataset("spectrum", data=np.ones(5))
        good = entry.create_group("C1s")
        good.create_dataset("binding_energy", data=np.linspace(290, 280, 5))
        good.create_dataset("spectrum", data=np.ones(5))
    blocks = read_nxs_blocks(path)
    assert len(blocks) == 1
    assert blocks[0]["meta"]["xps_region"] == "C1s"

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from sersflow.api.services.observation_export import _labels_for_spectrum
from sersflow.core.io.multi_block_labels import (
    BLOCK_SPECTRA_KEY,
    EXPERIMENTAL_BLOCK_KEYS,
    STRUCTURAL_BLOCK_KEYS,
    build_block_spectra_for_path,
    experimental_only,
    get_block_spectra,
    merge_block_structural_preserving_experimental,
    set_block_spectra,
)
from sersflow.core.labels.api import extract_labels_from_text
from sersflow.core.models.datasets import MultiSpectrumDataset


h5py = pytest.importorskip("h5py")


def test_select_experimental_filter_keys_rules() -> None:
    from sersflow.core.io.multi_block_labels import select_experimental_filter_keys

    xps = select_experimental_filter_keys(
        technique_family="xps",
        present_keys={"sample", "laser_nm", "potential_V", "gas"},
    )
    assert "sample" in xps
    assert "gas" in xps
    assert "potential_V" in xps
    assert "potential_ref" in xps
    assert "current_density_A_cm2" in xps
    assert "laser_nm" not in xps

    bare = select_experimental_filter_keys(technique_family="xps", present_keys={"sample"})
    assert bare == ["sample"]
    assert "potential_V" not in bare

    vib = select_experimental_filter_keys(
        technique_family="vibrational",
        present_keys={"laser_nm", "laser_power_pct", "sample"},
    )
    assert "laser_nm" in vib
    assert "laser_power_pct" in vib

    labels: dict = {"sample": "A"}
    assert get_block_spectra(labels) == {}
    set_block_spectra(labels, {"0": {"xps_region": "C1s", "current_density_A_cm2": 0.05}})
    assert BLOCK_SPECTRA_KEY in labels
    blocks = get_block_spectra(labels)
    assert blocks["0"]["xps_region"] == "C1s"
    set_block_spectra(labels, None)
    assert BLOCK_SPECTRA_KEY not in labels


def test_merge_preserves_experimental() -> None:
    prev = {
        "xps_region": "old",
        "current_density_A_cm2": 0.05,
        "potential_V": -0.2,
        "sample": "Cu",
    }
    fresh = {"xps_region": "C1s", "spectrum_role": "average", "block_name": "C1s_avg"}
    merged = merge_block_structural_preserving_experimental(previous=prev, fresh_structural=fresh)
    assert merged["xps_region"] == "C1s"
    assert merged["spectrum_role"] == "average"
    assert merged["current_density_A_cm2"] == 0.05
    assert merged["potential_V"] == -0.2
    assert merged["sample"] == "Cu"
    assert experimental_only(merged).keys() <= EXPERIMENTAL_BLOCK_KEYS
    assert "block_name" in STRUCTURAL_BLOCK_KEYS


def test_labels_for_spectrum_overlays_block() -> None:
    labels = {
        "sample": "path_sample",
        "gas": "CO2",
        "vms_spectra": {
            "0": {"xps_region": "C1s", "current_density_A_cm2": 0.05},
            "1": {"xps_region": "O1s", "current_density_A_cm2": 0.1},
        },
    }
    m0 = _labels_for_spectrum(labels, record_index=0)
    assert m0["sample"] == "path_sample"
    assert m0["xps_region"] == "C1s"
    assert m0["current_density_A_cm2"] == 0.05
    assert "vms_spectra" not in m0
    m1 = _labels_for_spectrum(labels, record_index=1)
    assert m1["xps_region"] == "O1s"
    assert m1["current_density_A_cm2"] == 0.1


def test_extract_labels_from_text_ocp_and_current() -> None:
    ocp = extract_labels_from_text("Cu__OCP__C1s")
    assert ocp.get("potential_ref") == "OCP"
    assert ocp.get("potential_V") == 0.0
    assert ocp.get("current_density_A_cm2") == 0.0
    cur = extract_labels_from_text("Cu__05mA_cm2__C1s")
    assert cur.get("current_density_A_cm2") == pytest.approx(0.005)


def _write_nxs(path: Path) -> None:
    with h5py.File(path, "w") as f:
        entry = f.create_group("entry")
        data = entry.create_group("C1s")
        data.create_dataset("binding_energy", data=np.linspace(290, 280, 5))
        data.create_dataset("spectrum", data=np.ones(5))
        data.create_dataset("spectrum_1", data=np.ones(5) * 2)
        inst = entry.create_group("instrument")
        ig = inst.create_group("C1s")
        ig.create_dataset("number_of_iterations", data=2)


def test_build_block_spectra_for_nxs_path(tmp_path: Path) -> None:
    path = tmp_path / "05mA_OCP_sample.nxs"
    _write_nxs(path)
    block_map = build_block_spectra_for_path(path)
    assert block_map is not None
    assert set(block_map.keys()) == {"0", "1"}
    assert block_map["0"]["spectrum_role"] == "average"
    assert block_map["1"]["spectrum_role"] == "individual"
    # Path tokens feed experimental extract
    assert block_map["0"].get("current_density_A_cm2") is not None or block_map["0"].get("potential_ref") is not None


def test_build_block_spectra_non_multi_returns_none(tmp_path: Path) -> None:
    path = tmp_path / "plain.txt"
    path.write_text("Wavenumber\tIntensity\n500\t1\n", encoding="utf-8")
    assert build_block_spectra_for_path(path) is None


def test_vms_extract_from_block_name_via_adapter(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Unit-level: VMS search text builder includes block name tokens for extract."""
    from sersflow.core.io.multi_block_labels import build_vms_block_search_text

    path = tmp_path / "folder" / "run.vms"
    path.parent.mkdir(parents=True)
    path.write_text("placeholder", encoding="utf-8")
    meta = {"block_name": "C1s_05mA_OCP"}
    block = SimpleNamespace(
        experiment_id="exp",
        source_label="Al",
        extra_fields={"block_comments": ["gas_CO2"], "additional_params": [{"label": "I", "unit": "mA", "value": "10"}]},
    )
    text = build_vms_block_search_text(path=path, meta=meta, block=block, parent_levels=2)
    assert "05mA" in text or "05ma" in text.lower()
    labs = extract_labels_from_text(text)
    assert labs.get("current_density_A_cm2") is not None or "OCP" in text.upper()

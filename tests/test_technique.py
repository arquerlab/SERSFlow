from __future__ import annotations

from pathlib import Path

import pytest

from sersflow.core.io.technique import (
    assert_homogeneous_technique_families,
    infer_technique_family,
)


def test_infer_wdf_is_vibrational(tmp_path: Path) -> None:
    p = tmp_path / "sample.wdf"
    p.write_bytes(b"")
    assert infer_technique_family(p) == "vibrational"


def test_infer_vms_is_xps(tmp_path: Path) -> None:
    p = tmp_path / "sample.vms"
    p.write_bytes(b"")
    assert infer_technique_family(p) == "xps"


def test_infer_txt_binding_energy_is_xps(tmp_path: Path) -> None:
    p = tmp_path / "xps.txt"
    p.write_text("Binding energy\tIntensity\n100\t1\n", encoding="utf-8")
    assert infer_technique_family(p) == "xps"


def test_infer_txt_be_token_is_xps(tmp_path: Path) -> None:
    p = tmp_path / "xps_be.txt"
    p.write_text("BE,counts\n90,1\n", encoding="utf-8")
    assert infer_technique_family(p) == "xps"


def test_infer_txt_wavenumber_is_vibrational(tmp_path: Path) -> None:
    p = tmp_path / "raman.txt"
    p.write_text("Wavenumber\tIntensity\n500\t1\n", encoding="utf-8")
    assert infer_technique_family(p) == "vibrational"


def test_infer_txt_wn_is_vibrational(tmp_path: Path) -> None:
    p = tmp_path / "raman_wn.txt"
    p.write_text("wn Intensity\n500 1\n", encoding="utf-8")
    assert infer_technique_family(p) == "vibrational"


def test_infer_txt_unknown_header_raises(tmp_path: Path) -> None:
    p = tmp_path / "mystery.txt"
    p.write_text("foo\tbar\n1\t2\n", encoding="utf-8")
    with pytest.raises(ValueError, match="Cannot infer technique"):
        infer_technique_family(p)


def test_infer_nxs_is_xps(tmp_path: Path) -> None:
    p = tmp_path / "sample.nxs"
    p.write_bytes(b"")
    assert infer_technique_family(p) == "xps"


def test_infer_nx5_is_xps(tmp_path: Path) -> None:
    p = tmp_path / "sample.nx5"
    p.write_bytes(b"")
    assert infer_technique_family(p) == "xps"


def test_homogeneous_rejects_mixed_families(tmp_path: Path) -> None:
    vib = tmp_path / "a.wdf"
    vib.write_bytes(b"")
    xps = tmp_path / "b.vms"
    xps.write_bytes(b"")
    with pytest.raises(ValueError, match="Cannot mix"):
        assert_homogeneous_technique_families([vib, xps])


def test_homogeneous_same_family_ok(tmp_path: Path) -> None:
    a = tmp_path / "a.wdf"
    b = tmp_path / "b.wdf"
    a.write_bytes(b"")
    b.write_bytes(b"")
    assert assert_homogeneous_technique_families([a, b]) == "vibrational"

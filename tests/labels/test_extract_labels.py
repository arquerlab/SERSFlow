from __future__ import annotations

from pathlib import Path

import pytest

from sersflow.core.labels import extract_labels
from sersflow.core.labels.extractors.compound import extract_compound_and_concentration
from sersflow.core.labels.extractors.current import extract_current
from sersflow.core.labels.extractors.laser import extract_laser_power_percent, extract_laser_wavelength_nm
from sersflow.core.labels.extractors.potential import extract_potential
from sersflow.core.labels.normalize import build_search_text


def _p(*parts: str) -> Path:
    return Path(*parts)


@pytest.mark.parametrize(
    ("path", "expected_nm", "expected_pct"),
    [
        (_p("Mount_test_50%laser_785nm_acc15s.txt"), 785, 50.0),
        (_p("run_50_%_785_nm_misc.txt"), 785, 50.0),
        (_p("no_laser_here.txt"), None, None),
    ],
)
def test_laser_percent_and_nm(path: Path, expected_nm: int | None, expected_pct: float | None) -> None:
    st = build_search_text(path, parent_levels=0)
    assert extract_laser_wavelength_nm(st) == expected_nm
    assert extract_laser_power_percent(st) == expected_pct


def test_wavelength_not_parsed_as_nanomolar_concentration() -> None:
    path = _p("sample_633_nm_only_KHCO3_1M.txt")
    conc = extract_compound_and_concentration(build_search_text(path, parent_levels=0))
    assert conc is not None
    assert conc["compound"] == "KHCO3"
    assert conc["unit"] == "M"


def test_current_density_cm2_not_truncated() -> None:
    path = _p("Cu_1_mAcm-2_repeat.txt")
    st = build_search_text(path, parent_levels=0)
    val, is_density = extract_current(st)
    assert is_density is True
    assert val == pytest.approx(0.001)


def test_split_current_density_tokens() -> None:
    path = _p("x_0_50_mA_cm2_end.txt")
    st = build_search_text(path, parent_levels=0)
    val, is_density = extract_current(st)
    assert is_density is True
    assert val == pytest.approx(0.0005)


def test_rhe_potential_maps_to_vrhe() -> None:
    path = _p("scan_-0d8RHE_map.txt")
    st = build_search_text(path, parent_levels=0)
    pot = extract_potential(st)
    assert pot is not None
    assert pot[0] == pytest.approx(-0.8)
    assert pot[1] == "VRHE"


def test_ocp_sets_zero_current_and_ocp_potential() -> None:
    path = _p("batch_OCP_passive.txt")
    labels = extract_labels(path, parent_levels=0)
    assert labels.get("current_density_A_cm2") == 0.0
    assert labels.get("potential_ref") == "OCP"
    assert labels.get("potential_V") == 0.0


def test_extract_labels_full_dict_keys() -> None:
    path = _p(
        "CuAq_785nm_0d05p_2s_25aqq_-0d05VRHE_-1mA_1M_KHCO3_pH2_CO2_map.txt",
    )
    labels = extract_labels(path, parent_levels=0)
    assert labels.get("sample") == "CuAq"
    assert labels.get("laser_nm") == 785
    assert labels.get("laser_power_pct") == pytest.approx(0.05)
    assert labels.get("potential_V") == pytest.approx(-0.05)
    assert labels.get("potential_ref") == "VRHE"
    assert labels.get("current_density_A_cm2") == pytest.approx(-0.001)
    assert labels.get("electrolyte") == "KHCO3"
    assert labels.get("concentration_M") == pytest.approx(1.0)
    assert labels.get("gas") == "CO2"
    assert labels.get("ph") == pytest.approx(2.0)


def test_sample_prefix_not_electrolyte_compound() -> None:
    path = _p("Cu_300_0d5M_K2SO4_misc.txt")
    labels = extract_labels(path, parent_levels=0)
    assert labels.get("sample") == "Cu_300"
    assert labels.get("electrolyte") == "K2SO4"
    assert labels.get("concentration_M") == pytest.approx(0.5)


def test_warns_bulk_current_named_as_density(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level("WARNING")
    path = _p("run_-1mA_no_density_unit.txt")
    labels = extract_labels(path, parent_levels=0)
    assert labels.get("current_density_A_cm2") == pytest.approx(-0.001)
    assert any("bulk current" in r.getMessage().lower() for r in caplog.records)


def test_warns_previous_bulk_flag_now_density(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level("WARNING")
    path = _p("Cu_1_mAcm-2_repeat.txt")
    extract_labels(path, parent_levels=0, previous_labels={"current_is_density": False})
    assert any("interpretation changed" in r.getMessage().lower() for r in caplog.records)


def test_parent_folder_context_ph_and_electrolyte() -> None:
    path = _p("parent", "pH2", "k2so4", "file.txt")
    labels = extract_labels(path, parent_levels=3)
    assert labels.get("ph") == pytest.approx(2.0)
    assert labels.get("electrolyte") == "K2SO4"


def test_vagagcl_converted_to_rhe_with_ph() -> None:
    path = _p("pH2_-0d5VAgAgCl_map.txt")
    labels = extract_labels(path, parent_levels=0)
    assert labels.get("ph") == pytest.approx(2.0)
    assert labels.get("potential_ref") == "VRHE"
    expected = -0.5 + 0.197 + 0.05916 * 2.0
    assert labels.get("potential_V") == pytest.approx(expected)


def test_vagagcl_omitted_without_ph(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level("WARNING")
    path = _p("run_-0d5VAgAgCl_noph.txt")
    labels = extract_labels(path, parent_levels=0)
    assert labels.get("potential_V") is None
    assert any("cannot convert to rhe" in r.getMessage().lower() for r in caplog.records)


def test_plain_v_stored_with_ref_v() -> None:
    path = _p("Cu_-0d365V_only.txt")
    labels = extract_labels(path, parent_levels=0)
    assert labels.get("potential_V") == pytest.approx(-0.365)
    assert labels.get("potential_ref") == "V"

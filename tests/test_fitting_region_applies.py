from __future__ import annotations

from sersflow.core.pipeline.engine import (
    ALL_VALENCE_BANDS_REGION,
    fitting_region_applies,
    is_valence_band_region_name,
)


def test_is_valence_band_region_name() -> None:
    assert is_valence_band_region_name("valence band")
    assert is_valence_band_region_name("VB valence")
    assert is_valence_band_region_name("VB")
    assert is_valence_band_region_name("vb")
    assert is_valence_band_region_name("Fermi edge")
    assert is_valence_band_region_name("fermi_edge")
    assert not is_valence_band_region_name("C1s")
    assert not is_valence_band_region_name("")
    assert not is_valence_band_region_name(None)


def test_fitting_region_applies_exact() -> None:
    assert fitting_region_applies(step_params={"xps_region": "C1s"}, spectrum_xps_region="C1s")
    assert fitting_region_applies(step_params={"xps_region": "c1s"}, spectrum_xps_region="C1s")
    assert not fitting_region_applies(step_params={"xps_region": "O1s"}, spectrum_xps_region="C1s")


def test_fitting_region_applies_all_valence_bands() -> None:
    params = {"xps_region": ALL_VALENCE_BANDS_REGION}
    assert fitting_region_applies(step_params=params, spectrum_xps_region="valence band")
    assert fitting_region_applies(step_params=params, spectrum_xps_region="Valence Band Max")
    assert fitting_region_applies(step_params=params, spectrum_xps_region="Fermi edge")
    assert fitting_region_applies(step_params=params, spectrum_xps_region="fermi_level")
    assert fitting_region_applies(step_params=params, spectrum_xps_region="VB")
    assert fitting_region_applies(step_params=params, spectrum_xps_region="vb")
    assert not fitting_region_applies(step_params=params, spectrum_xps_region="C1s")
    assert not fitting_region_applies(step_params=params, spectrum_xps_region="O1s")


def test_fitting_region_applies_missing_is_compat() -> None:
    assert fitting_region_applies(step_params={}, spectrum_xps_region="C1s")
    assert fitting_region_applies(step_params={"xps_region": "C1s"}, spectrum_xps_region=None)
    assert fitting_region_applies(step_params={"xps_region": ""}, spectrum_xps_region="C1s")

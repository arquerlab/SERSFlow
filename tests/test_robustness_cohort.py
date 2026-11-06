"""Regression: the robustness study must keep the full cohort for the x-axis calibration.

A cohort x_axis_calibration measures spectra the fit does not use (XPS valence-band Fermi edge -> Co 2p). The study
filters the cohort to the spectra of the fitted region; if the filtered list loses the full cohort, the calibration has
no reference band, sets every shift to 0 and the study fits uncalibrated data (RMSE twice that of the pipeline run).
"""
from __future__ import annotations

import os
from types import SimpleNamespace

os.environ.setdefault("SERSFLOW_ENV", "test")

from sersflow.api.services.fitting_preview import cohort_inputs  # noqa: E402
from sersflow.api.services.robustness_runner import applicable_spectra  # noqa: E402


def _ref(sid: str) -> SimpleNamespace:
    return SimpleNamespace(
        spectrum_id=sid,
        relative_path=f"{sid}.vms",
        record_index=0,
        blob_id=None,
        blob_relative_path=None,
        original_relative_path=None,
        spectrum_labels=None,
    )


def test_applicable_spectra_keeps_full_cohort_for_calibration():
    refs = [_ref("co_a"), _ref("vb_a"), _ref("co_b"), _ref("vb_b")]
    labels = {
        "co_a": {"xps_region": "Co2p"},
        "vb_a": {"xps_region": "ValencebandCo2p"},
        "co_b": {"xps_region": "Co2p"},
        "vb_b": {"xps_region": "ValencebandCo2p"},
    }
    out = applicable_spectra(refs, labels, {"xps_region": "Co2p"})
    assert [r.spectrum_id for r in out] == ["co_a", "co_b"]
    cohort = cohort_inputs(out)
    assert cohort is not None
    assert [c["spectrum_id"] for c in cohort] == ["co_a", "vb_a", "co_b", "vb_b"]


def test_applicable_spectra_of_a_subset_keeps_the_original_cohort():
    refs = [_ref("co_a"), _ref("vb_a"), _ref("co_b"), _ref("vb_b")]
    labels = {
        "co_a": {"xps_region": "Co2p"},
        "co_b": {"xps_region": "Co2p"},
        "vb_a": {"xps_region": "ValencebandCo2p"},
        "vb_b": {"xps_region": "ValencebandCo2p"},
    }
    first = applicable_spectra(refs, labels, {"xps_region": "Co2p"})
    again = applicable_spectra(first, labels, {"xps_region": "Co2p"})
    assert [c["spectrum_id"] for c in cohort_inputs(again)] == ["co_a", "vb_a", "co_b", "vb_b"]

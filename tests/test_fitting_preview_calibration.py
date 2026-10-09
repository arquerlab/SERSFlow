"""Fit preview / fit-curve export must keep calibration reference fittings enabled."""

from __future__ import annotations

from sersflow.api.schemas.pipeline import Pipeline
from sersflow.api.services.fitting_preview import _pipeline_steps_without_fitting

VB_ID = "17fe1f9a-642b-46a2-afbd-9906f195f12f"


def _xps_pipeline(cal_method: str = "grouped_reference_band") -> Pipeline:
    return Pipeline.model_validate(
        {
            "technique_family": "xps",
            "steps": [
                {"name": "fitting", "step_id": VB_ID, "params": {"xps_region": "all valence bands"}},
                {
                    "name": "x_axis_calibration",
                    "step_id": "cal",
                    "params": {"method": cal_method, "fitting_step_id": VB_ID, "offset": 0},
                },
                {"name": "fitting", "step_id": "o1s", "params": {"xps_region": "O1s"}},
                {"name": "fitting", "step_id": "co2p", "params": {"xps_region": "Co2p"}},
            ],
        }
    )


def _enabled(steps: list[dict]) -> dict[str, bool]:
    return {s["step_id"]: s["enabled"] for s in steps}


def test_reference_fitting_kept_for_later_fit():
    out = _enabled(_pipeline_steps_without_fitting(_xps_pipeline(), fitting_idx=2))
    assert out == {VB_ID: True, "cal": True, "o1s": False, "co2p": False}


def test_unreferenced_earlier_fittings_still_disabled():
    out = _enabled(_pipeline_steps_without_fitting(_xps_pipeline(), fitting_idx=3))
    assert out == {VB_ID: True, "cal": True, "o1s": False, "co2p": False}


def test_valence_band_fit_itself_disables_everything():
    out = _enabled(_pipeline_steps_without_fitting(_xps_pipeline(), fitting_idx=0))
    assert not any(out.values())


def test_fixed_offset_calibration_does_not_keep_fitting():
    out = _enabled(_pipeline_steps_without_fitting(_xps_pipeline("fixed_offset"), fitting_idx=2))
    assert out[VB_ID] is False

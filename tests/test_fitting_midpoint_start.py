from __future__ import annotations

import numpy as np
import pytest

from sersflow.core.preprocess import fitting_models as fm
from sersflow.core.preprocess.fitting import FitComponent, FitProblem, fit_curve


def _fit(true_pos: float, start: float, lo: float, hi: float) -> float:
    pytest.importorskip("lmfitxps")
    x = np.linspace(774.0, 791.0, 260)
    rng = np.random.default_rng(1)
    y = fm.gl(x, true_pos, 0.014, 3.0, 40) + fm.gl(x, true_pos + 1.5, 0.012, 3.0, 40) + rng.normal(0, 2e-4, x.size)
    problem = FitProblem(
        x=x,
        y=y,
        components=[FitComponent("gl", "A"), FitComponent("gl", "B")],
        p0=[start, 0.01, 3.0, 40, 781.2, 0.01, 3.0, 40],
        bounds_lower=[lo, 0, 0.5, 0, 779, 0, 0.5, 0],
        bounds_upper=[hi, None, 8, 100, 783, None, 8, 100],
        technique_family="xps",
        vary=[True, True, False, False, False, True, False, False],
        param_links=[
            {"source_component_id": "B", "source_key": "pos", "target_component_id": "A", "target_key": "pos", "mode": "offset", "offset": 1.5},
            {"source_component_id": "B", "source_key": "m", "target_component_id": "A", "target_key": "m", "mode": "equal"},
        ],
    )
    return float(fit_curve(problem).p_opt[0])


def test_position_starting_at_midpoint_of_its_bounds_still_moves() -> None:
    # Regression: a start exactly at the midpoint made the numerical derivative 0 and the position never moved.
    assert _fit(779.72, 779.70, 779.65, 779.75) == pytest.approx(779.72, abs=0.01)


def test_midpoint_start_goes_to_the_nearest_bound_when_the_optimum_is_outside() -> None:
    assert _fit(779.60, 779.70, 779.65, 779.75) == pytest.approx(779.65, abs=1e-3)
    assert _fit(779.85, 779.70, 779.65, 779.75) == pytest.approx(779.75, abs=1e-3)


def test_midpoint_start_matches_an_off_centre_start() -> None:
    a = _fit(779.72, 779.70, 779.65, 779.75)
    b = _fit(779.72, 779.68, 779.65, 779.75)
    assert a == pytest.approx(b, abs=5e-3)

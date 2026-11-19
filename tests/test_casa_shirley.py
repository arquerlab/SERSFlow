"""CasaXPS region Shirley rule (baseline method 'shirley', casa_rule / casa_region_from_labels; default off)."""

from __future__ import annotations

import numpy as np
import pytest

from sersflow.core.io.casa_fit import parse_casa_region
from sersflow.core.pipeline.steps import _baseline
from sersflow.core.preprocess.baseline import baseline_kwargs, correct_baseline
from sersflow.core.preprocess.xps_extra_components import casa_shirley
from sersflow.core.spectrum import XY

# Codel Co 2p OCP (CPS, CasaXPS-calibrated BE, 0.1 eV channels from 773.4636 eV): the CasaXPS region
# 773.6828-793.10244 eV (Av Width 4, Start Offset 6 %) plus 3 channels outside each end.
_OCP_Y = [
    16938.28, 16634.42, 16237.92, 16233.92, 16602.45, 16569.05, 16531.10, 16389.67, 16923.32, 16688.07,
    16841.52, 16848.80, 16577.07, 16506.62, 16790.60, 16628.72, 16743.67, 16879.25, 16722.77, 16337.82,
    16426.40, 16786.67, 16419.60, 16668.97, 17138.92, 16909.88, 17027.30, 16893.45, 16699.88, 16692.62,
    16778.28, 17056.15, 17216.55, 17062.38, 17054.55, 17100.92, 17154.62, 17516.95, 18018.85, 17866.85,
    17817.83, 18270.45, 18533.85, 18862.87, 19022.30, 19194.35, 19732.17, 20098.85, 20642.90, 20631.88,
    20514.77, 20771.92, 21281.33, 21754.50, 22323.85, 22234.65, 22359.15, 22801.30, 23248.12, 23245.05,
    23197.02, 23463.97, 23837.60, 24154.32, 23920.08, 23937.72, 24816.55, 24991.55, 24403.05, 24680.45,
    24489.57, 24696.45, 24646.27, 24206.37, 24244.05, 24040.00, 23792.30, 23714.27, 23637.50, 23765.70,
    22882.62, 22808.15, 22596.02, 22386.90, 22475.08, 22436.20, 22538.50, 22007.95, 21784.42, 21868.65,
    21505.42, 21145.02, 21110.52, 21293.50, 20940.15, 21034.77, 20627.07, 20644.97, 20232.38, 20391.92,
    20136.72, 20141.88, 19658.95, 20083.97, 20141.62, 20083.75, 19730.27, 19903.15, 20067.40, 20164.55,
    20017.45, 19862.70, 19570.80, 19756.27, 20099.88, 20066.35, 19748.00, 19460.62, 19240.65, 19579.20,
    19648.42, 19803.25, 19832.00, 19902.97, 19653.82, 19605.60, 19823.42, 19561.25, 19659.85, 19564.47,
    19692.25, 19486.80, 19700.10, 19563.07, 19589.45, 19633.42, 19725.80, 19469.90, 19214.47, 19376.72,
    19283.07, 19608.55, 19615.22, 19569.97, 19653.40, 19745.60, 19454.22, 19662.70, 19570.78, 19508.90,
    18942.60, 19240.88, 19629.97, 19587.67, 19771.80, 19518.62, 19485.33, 19299.92, 19290.17, 19470.97,
    19515.45, 19459.12, 19831.27, 19462.47, 19539.40, 19435.17, 19228.12, 19115.25, 19210.97, 19244.53,
    19359.32, 19043.47, 19205.75, 19314.50, 19437.87, 19146.92, 19244.85, 19049.15, 19509.95, 19271.35,
    19587.22, 19102.77, 18976.92, 19204.30, 19154.97, 19196.82, 19041.85, 19105.30, 18948.28, 19210.50,
    19577.57, 19439.57, 20044.95, 19552.85, 19850.17, 19785.33, 20063.75, 20432.92, 20353.30, 20119.77,]
# CasaXPS exported Background (0.1 CPS rounding) at channel indices of _OCP_Y (3 = first region channel,
# 196 = last region channel, 197 = outside the region, where CasaXPS reports the data).
_OCP_CASA_BG = {3: 16535.3, 4: 16537.1, 30: 16568.3, 60: 17069.4, 100: 18277.5, 150: 18642.2, 196: 18813.8, 197: 20432.9}


def _ocp_xy() -> tuple[np.ndarray, np.ndarray]:
    y = np.asarray(_OCP_Y, dtype=float)
    return 773.4636 + 0.1 * np.arange(y.size), y


def test_casa_shirley_reproduces_casaxps_export() -> None:
    x, y = _ocp_xy()
    bg = casa_shirley(x, y, region_min_x=773.6828, region_max_x=793.10244, avg_width=3, offset_high_pct=6.0)
    for i, ref in _OCP_CASA_BG.items():
        assert bg[i] == pytest.approx(ref, abs=0.06)
    # same result with the axis given in descending order
    bg_rev = casa_shirley(x[::-1], y[::-1], region_min_x=773.6828, region_max_x=793.10244, avg_width=3, offset_high_pct=6.0)
    assert np.allclose(bg_rev[::-1], bg)


def test_casa_shirley_rule_details() -> None:
    x, y = _ocp_xy()
    bg = casa_shirley(x, y, region_min_x=773.6828, region_max_x=793.10244, avg_width=3, offset_high_pct=6.0)
    i0, i1 = 3, 196
    lo = float(np.mean(y[i0 - 3 : i0 + 4]))  # centred, reaches outside the region
    hi = float(np.mean(y[i1 - 3 : i1 + 4])) * 0.94
    assert bg[i0] == pytest.approx(lo)
    assert np.array_equal(bg[:i0], y[:i0]) and np.array_equal(bg[i1 + 1 :], y[i1 + 1 :])
    g = np.abs(y[i0 : i1 + 1] - bg[i0 : i1 + 1])
    c = np.cumsum(g)
    assert np.allclose(bg[i0 : i1 + 1], lo + (hi - lo) * (c - g) / c[-1], atol=1e-6)  # converged fixed point
    assert bg[i1] < hi  # stops one channel's integrand short of the high level


def test_baseline_shirley_default_unchanged_and_casa_opt_in() -> None:
    x, y = _ocp_xy()
    kw = baseline_kwargs("shirley", {})
    assert kw["casa_rule"] is False and kw["casa_region_from_labels"] is False
    assert kw["region_min_x"] is None and kw["region_max_x"] is None
    legacy, _ = correct_baseline(y, method="shirley", x=x, avg_width=0, offset_high_pct=6.0)
    from sersflow.core.preprocess.xps_extra_components import shirley_static

    assert np.allclose(y - legacy, shirley_static(x, y, avg_width=0, offset_high_pct=6.0, maxit=20))
    net, info = correct_baseline(
        y, method="shirley", x=x, casa_rule=True, region_min_x=773.6828, region_max_x=793.10244, offset_high_pct=6.0
    )
    assert info["baseline"][196] == pytest.approx(_OCP_CASA_BG[196], abs=0.06)
    assert net[0] == 0.0 and net[-1] == 0.0


def test_parse_casa_region_and_step_from_labels() -> None:
    line = "CASA region (*Co 2p*) (*Shirley*) 306.89756 326.3172 1 4 6 0 0 -450 0 0 (*NoTag*) 0 0 0"
    reg = parse_casa_region([line], photon_energy_eV=1100.0)
    assert reg is not None
    assert reg["av_width"] == 4 and reg["start_offset_pct"] == 6 and reg["end_offset_pct"] == 0
    assert reg["be_min_eV"] == pytest.approx(773.6828) and reg["be_max_eV"] == pytest.approx(793.10244)
    assert reg["offset_high_pct"] == 6 and reg["offset_low_pct"] == 0  # start (low KE) = high BE end
    labels = {
        "casa_region_be_min_eV": reg["be_min_eV"],
        "casa_region_be_max_eV": reg["be_max_eV"],
        "casa_region_av_width": reg["av_width"],
        "casa_region_offset_low_pct": reg["offset_low_pct"],
        "casa_region_offset_high_pct": reg["offset_high_pct"],
    }
    x, y = _ocp_xy()
    out = _baseline(XY(x=x, y=y), {"method": "shirley", "casa_region_from_labels": True, "_spectrum_labels": labels})
    assert y[196] - out.y[196] == pytest.approx(_OCP_CASA_BG[196], abs=0.06)
    assert y[100] - out.y[100] == pytest.approx(_OCP_CASA_BG[100], abs=0.06)
    with pytest.raises(ValueError, match="casa_region_from_labels"):
        _baseline(XY(x=x, y=y), {"method": "shirley", "casa_region_from_labels": True, "_spectrum_labels": {}})

"""C3: XPS spike removal (``cosmic_ray_removal`` method ``xps_poisson``)."""

from __future__ import annotations

import numpy as np

from sersflow.core.pipeline.library import get_step, list_steps
from sersflow.core.preprocess.xps_despike import detect_spikes_poisson, remove_spikes_poisson
from sersflow.core.spectrum import XY

X = np.linspace(770.0, 800.0, 301)
TRUE = 2000.0 + 60000.0 * np.exp(-0.5 * ((X - 780.0) / 0.6) ** 2) + 20000.0 / (1.0 + np.exp((X - 780.0) / 3.0))


def _counts(seed: int) -> np.ndarray:
    return np.random.default_rng(seed).poisson(TRUE).astype(float)


def test_step_available_for_xps_and_vibrational():
    assert "cosmic_ray_removal" in {s.id for s in list_steps(technique_family="xps")}
    assert "cosmic_ray_removal" in {s.id for s in list_steps(technique_family="vibrational")}
    methods = [m.id for m in get_step("cosmic_ray_removal").ui.methods]
    assert methods == ["zscore", "derivative", "xps_poisson"]


def test_clean_poisson_data_is_untouched():
    for seed in range(40):
        y = _counts(seed)
        corrected, mask, n = remove_spikes_poisson(y)
        assert n == 0 and not mask.any()
        assert np.array_equal(corrected, y)


def test_spikes_in_background_and_on_peak_are_removed():
    hits = 0
    for seed in range(40):
        y = _counts(seed)
        inj = {40: 2500.0, 150: 40000.0, 200: 1500.0, 90: 15000.0}  # 90 sits on the rising flank
        for i, a in inj.items():
            y[i] += a
        corrected, mask, _ = remove_spikes_poisson(y)
        hits += sum(bool(mask[i]) for i in inj)
        assert set(np.flatnonzero(mask)) <= set(inj)  # no false positives
        for i in inj:
            assert abs(corrected[i] - TRUE[i]) < 6 * np.sqrt(TRUE[i]) + 1
    assert hits == 40 * 4


def test_adjacent_two_channel_spike():
    y = _counts(3)
    y[220] += 3000.0
    y[221] += 2500.0
    corrected, mask, _ = remove_spikes_poisson(y)
    assert mask[220] and mask[221]
    assert abs(corrected[220] - TRUE[220]) < 6 * np.sqrt(TRUE[220])


def test_real_peak_is_not_a_spike_even_when_sharp():
    y = TRUE.copy()  # noiseless: nothing to flag
    assert not detect_spikes_poisson(y)[0].any()
    narrow = 1000.0 + 50000.0 * np.exp(-0.5 * ((X - 785.0) / 0.25) ** 2)  # ~2.5 channels wide
    y = np.random.default_rng(5).poisson(narrow).astype(float)
    assert not remove_spikes_poisson(y)[1][np.abs(X - 785.0) < 0.3].any()


def test_direction_positive_keeps_dips_both_removes_them():
    y = _counts(7)
    y[250] = 0.0  # dead channel in the flat background (TRUE ~ 2000)
    assert not remove_spikes_poisson(y, direction="positive")[1][250]
    assert remove_spikes_poisson(y, direction="both")[1][250]


def test_step_replaces_spike_and_patches_variance():
    y = _counts(11)
    var = np.maximum(y, 1.0)
    y2 = y.copy()
    y2[40] += 5000.0
    var2 = np.maximum(y2, 1.0)  # variance as computed at load from the (spiked) raw counts
    step = get_step("cosmic_ray_removal").impl
    out = step.transform(XY(x=X, y=y2, var=var2, var_kind="absolute"), {"method": "xps_poisson"})
    assert abs(out.y[40] - TRUE[40]) < 6 * np.sqrt(TRUE[40])
    assert out.var is not None and out.var_kind == "absolute"
    assert out.var[40] < 3 * TRUE[40]  # no longer the inflated spike variance
    assert np.array_equal(np.delete(out.var, 40), np.delete(var2, 40))
    # without variance the result simply has none
    assert step.transform(XY(x=X, y=y2), {"method": "xps_poisson"}).var is None


def test_raman_methods_unchanged():
    y = np.full(200, 100.0)
    y[50] = 5000.0
    out = get_step("cosmic_ray_removal").impl.transform(XY(x=np.arange(200.0), y=y), {"method": "zscore"})
    assert out.y[50] < 200.0

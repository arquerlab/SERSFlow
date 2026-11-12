"""Preview speed-ups must not change results: lazy cohort calibration and the parsed-file cache."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from sersflow.core.pipeline import engine
from sersflow.core.preprocess.x_axis_calibration import compute_calibration_deltas_for_step

# group (current density) -> region -> spectrum id; each VB spectrum has its own Fermi edge.
_LABELS = {
    "c1s_a": {"j": 1, "xps_region": "C1s"},
    "vbc_a": {"j": 1, "xps_region": "VB_C"},
    "o1s_a": {"j": 1, "xps_region": "O1s"},
    "vbo_a": {"j": 1, "xps_region": "VB_O"},
    "c1s_b": {"j": 2, "xps_region": "C1s"},
    "vbc_b": {"j": 2, "xps_region": "VB_C"},
    "o1s_b": {"j": 2, "xps_region": "O1s"},
    "vbo_b": {"j": 2, "xps_region": "VB_O"},
}
_FERMI = {"vbc_a": 0.3, "vbo_a": 0.4, "vbc_b": -0.2, "vbo_b": 0.1}


def _run(cal_params, only_ids=None):
    calls: list[str] = []

    def measure(sid, _fp, _pos):
        calls.append(sid)
        return _FERMI.get(sid, 284.0 + 0.1 * len(sid))

    res = compute_calibration_deltas_for_step(
        spectrum_ids=list(_LABELS),
        labels_by_id=_LABELS,
        cal_params=cal_params,
        fit_params={"xps_region": cal_params.get("reference_region")},
        measure=measure,
        only_ids=only_ids,
    )
    return res.deltas, calls


@pytest.mark.parametrize(
    "cal_params",
    [
        {"method": "grouped_reference_band", "group_by": "j", "reference_mode": "valence_band", "pos_key": "fit_x_center"},
        {
            "method": "grouped_reference_band",
            "group_by": "j",
            "reference_mode": "core_level",
            "reference_region": "C1s",
            "target_x": 284.8,
            "pos_key": "fit_x_pos",
        },
    ],
)
def test_only_ids_gives_the_same_deltas_with_fewer_measurements(cal_params) -> None:
    full, full_calls = _run(cal_params)
    subset = {"c1s_a", "o1s_a"}
    part, part_calls = _run(cal_params, only_ids=subset)
    assert subset <= set(part)
    for sid in part:  # every delta that is returned equals the full computation
        assert part[sid] == pytest.approx(full[sid])
    assert set(part_calls) < set(full_calls)
    assert not any(sid.endswith("_b") for sid in part_calls)  # the other group is never measured


def test_valence_band_measures_only_the_needed_partner() -> None:
    cal = {"method": "grouped_reference_band", "group_by": "j", "reference_mode": "valence_band", "pos_key": "k"}
    deltas, calls = _run(cal, only_ids={"c1s_b"})
    assert calls == ["vbc_b"]
    assert deltas == {"c1s_b": pytest.approx(0.2)}


def test_single_reference_band_still_averages_every_reference() -> None:
    cal = {
        "method": "single_reference_band",
        "reference_filters": [{"key": "xps_region", "op": "eq", "value": "C1s"}],
        "target_x": 284.8,
        "pos_key": "k",
    }
    full, full_calls = _run(cal)
    part, part_calls = _run(cal, only_ids={"o1s_a"})
    assert sorted(part_calls) == sorted(full_calls)
    assert part["o1s_a"] == pytest.approx(full["o1s_a"])


def test_parsed_file_cache_is_reused_and_cannot_be_mutated(tmp_path: Path, monkeypatch) -> None:
    f = tmp_path / "s.txt"
    f.write_text("x\ty\n1\t10\n2\t20\n3\t30\n", encoding="utf-8")
    loads: list[Path] = []
    real = engine.load_dataset

    def counting(p):
        loads.append(Path(p))
        return real(p)

    monkeypatch.setattr(engine, "load_dataset", counting)
    engine._DATASET_CACHE.clear()
    ds1 = engine._load_dataset_cached(f)
    ds2 = engine._load_dataset_cached(f)
    assert ds1 is ds2 and len(loads) == 1

    xy = engine._extract_xy_copy(ds1, None)
    xy.y[:] = -1.0  # a step mutating its input in place must not reach the cache
    again = engine._extract_xy_copy(engine._load_dataset_cached(f), None)
    assert np.allclose(again.y, [10.0, 20.0, 30.0])

    # an edited file (new size / mtime) is re-read
    f.write_text("x\ty\n1\t11\n2\t21\n3\t31\n4\t41\n", encoding="utf-8")
    ds3 = engine._load_dataset_cached(f)
    assert ds3 is not ds1 and len(loads) == 2
    engine._DATASET_CACHE.clear()

from __future__ import annotations

import numpy as np
import pytest

from sersflow.core.preprocess.group_average import (
    SPECTRUM_ROLE_GROUP_MEAN,
    GroupAverageParams,
    GroupMember,
    group_average,
    make_group_spectrum_id,
)
from sersflow.core.spectrum import XY


def _m(sid: str, level: float, **labels) -> GroupMember:
    x = np.linspace(280.0, 290.0, 11)
    return GroupMember(spectrum_id=sid, xy=XY(x=x, y=np.full_like(x, level)), labels=labels)


def test_all_mode_splits_by_region_by_default() -> None:
    members = [
        _m("a", 1.0, xps_region="C1s"),
        _m("b", 3.0, xps_region="C1s"),
        _m("c", 10.0, xps_region="O1s"),
    ]
    out = group_average(members, GroupAverageParams.from_dict({"mode": "all", "reducer": "mean"}), dataset_id="ds")
    by_region = {g.key["xps_region"]: g for g in out}
    assert set(by_region) == {"C1s", "O1s"}
    assert np.allclose(by_region["C1s"].xy.y, 2.0)
    assert by_region["C1s"].member_ids == ["a", "b"]
    assert np.allclose(by_region["O1s"].xy.y, 10.0)


def test_all_mode_without_region_split_averages_everything() -> None:
    members = [_m("a", 1.0, xps_region="C1s"), _m("b", 3.0, xps_region="O1s")]
    out = group_average(members, GroupAverageParams.from_dict({"mode": "all", "split_by_region": False, "reducer": "mean"}), dataset_id="ds")
    assert len(out) == 1
    assert np.allclose(out[0].xy.y, 2.0)
    assert out[0].labels["xps_region"] == "mixed"


def test_by_label_groups_on_current_density() -> None:
    members = [
        _m("a", 1.0, xps_region="C1s", current_density=10.0),
        _m("b", 3.0, xps_region="C1s", current_density=10.0),
        _m("c", 5.0, xps_region="C1s", current_density=20.0),
    ]
    params = GroupAverageParams.from_dict({"mode": "by_label", "group_by": ["current_density"], "reducer": "mean"})
    out = group_average(members, params, dataset_id="ds")
    assert [g.member_ids for g in out] == [["a", "b"], ["c"]]
    assert out[0].labels["current_density"] == 10.0
    assert out[0].labels["spectrum_role"] == SPECTRUM_ROLE_GROUP_MEAN
    assert out[0].labels["n_averaged"] == 2


def test_by_range_bins_time_every_5_minutes() -> None:
    members = [_m(f"s{i}", float(i), time_s=i * 60.0) for i in range(10)]  # 0..9 min
    params = GroupAverageParams.from_dict(
        {"mode": "by_range", "range_label": "time_s", "range_width": 300.0, "split_by_region": False, "reducer": "mean"}
    )
    out = group_average(members, params, dataset_id="ds")
    assert [len(g.member_ids) for g in out] == [5, 5]
    assert out[0].key["range_start"] == 0.0 and out[0].key["range_end"] == 300.0
    assert out[0].labels["time_s"] == pytest.approx(120.0)
    assert out[0].labels["time_s_min"] == 0.0 and out[0].labels["time_s_max"] == 240.0


def test_by_range_accepts_iso_timestamps() -> None:
    members = [
        _m("a", 1.0, acquired_at="2025-01-01T10:00:00"),
        _m("b", 3.0, acquired_at="2025-01-01T10:00:10"),
        _m("c", 5.0, acquired_at="2025-01-01T10:00:30"),
    ]
    params = GroupAverageParams.from_dict(
        {"mode": "by_range", "range_label": "acquired_at", "range_width": 20, "split_by_region": False}
    )
    out = group_average(members, params, dataset_id="ds")
    assert [g.member_ids for g in out] == [["a", "b"], ["c"]]


def test_by_range_needs_numeric_label() -> None:
    members = [_m("a", 1.0, sample="x")]
    params = GroupAverageParams.from_dict(
        {"mode": "by_range", "range_label": "sample", "range_width": 5, "split_by_region": False}
    )
    with pytest.raises(ValueError, match="not numeric"):
        group_average(members, params, dataset_id="ds")


def test_group_id_independent_of_data_and_reducer() -> None:
    members_1 = [_m("a", 1.0, xps_region="C1s"), _m("b", 3.0, xps_region="C1s")]
    members_2 = [_m("a", 100.0, xps_region="C1s"), _m("b", 300.0, xps_region="C1s")]
    p_mean = GroupAverageParams.from_dict({"mode": "all", "reducer": "mean"})
    p_median = GroupAverageParams.from_dict({"mode": "all", "reducer": "median"})
    id1 = group_average(members_1, p_mean, dataset_id="ds")[0].spectrum_id
    id2 = group_average(members_2, p_median, dataset_id="ds")[0].spectrum_id
    assert id1 == id2
    assert id1 != group_average(members_1, p_mean, dataset_id="other")[0].spectrum_id
    assert id1 == make_group_spectrum_id("ds", p_mean.rule_dict(), {"xps_region": "C1s"})


def test_different_axes_are_interpolated_with_warning() -> None:
    x1 = np.linspace(0.0, 10.0, 11)
    x2 = np.linspace(0.0, 10.0, 21)
    members = [
        GroupMember("a", XY(x1, x1 * 2.0), {}),
        GroupMember("b", XY(x2, x2 * 2.0), {}),
    ]
    out = group_average(members, GroupAverageParams.from_dict({"mode": "all", "reducer": "mean"}), dataset_id="ds")
    assert np.allclose(out[0].xy.x, x1)
    assert np.allclose(out[0].xy.y, x1 * 2.0)
    assert out[0].warnings


def test_median_reducer_and_min_group_size() -> None:
    members = [_m("a", 1.0), _m("b", 2.0), _m("c", 100.0)]
    out = group_average(members, GroupAverageParams.from_dict({"mode": "all", "reducer": "median"}), dataset_id="ds")
    assert np.allclose(out[0].xy.y, 2.0)
    assert group_average(members, GroupAverageParams.from_dict({"mode": "all", "min_group_size": 4}), dataset_id="ds") == []


def test_param_validation() -> None:
    with pytest.raises(ValueError):
        GroupAverageParams.from_dict({"mode": "by_label"})
    with pytest.raises(ValueError):
        GroupAverageParams.from_dict({"mode": "by_range", "range_label": "t"})
    with pytest.raises(ValueError):
        GroupAverageParams.from_dict({"mode": "nope"})


def test_method_key_is_accepted_like_mode() -> None:
    """The generic step editor stores the variant under ``method``."""
    p = GroupAverageParams.from_dict({"method": "by_label", "group_by": "sample, current_density"})
    assert p.mode == "by_label"
    assert p.group_by == ("sample", "current_density")


def test_default_reducer_is_cumulative_sum() -> None:
    members = [_m("a", 1.0), _m("b", 3.0)]
    p = GroupAverageParams.from_dict({"mode": "all"})
    assert p.reducer == "cumulative"
    out = group_average(members, p, dataset_id="ds")
    assert np.allclose(out[0].xy.y, 4.0)
    assert GroupAverageParams.from_dict({"mode": "all", "reducer": "sum"}).reducer == "cumulative"
    with pytest.raises(ValueError):
        GroupAverageParams.from_dict({"mode": "all", "reducer": "max"})

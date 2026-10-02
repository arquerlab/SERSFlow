"""Unit tests for review improvements to format/step registries."""

from __future__ import annotations

from pathlib import Path

from sersflow.core.io.formats import get_format_for_path
from sersflow.core.io.multi_block_labels import is_multi_spectrum_path
from sersflow.core.pipeline.library import get_step, list_steps


def test_is_multi_spectrum_path_uses_registry():
    assert is_multi_spectrum_path("a.vms") is True
    assert is_multi_spectrum_path("a.nxs") is True
    assert is_multi_spectrum_path("a.nx5") is True
    assert is_multi_spectrum_path("a.txt") is False
    assert is_multi_spectrum_path("a.wdf") is False


def test_enrich_is_single_pass_over_loaded_dataset(tmp_path: Path):
    """Enrich must not call load_dataset again when dataset is provided."""
    from sersflow.core.io.formats.enrich import enrich_multi_spectrum
    from sersflow.core.models.datasets import MultiSpectrumDataset
    import numpy as np

    p = tmp_path / "x.vms"
    p.write_bytes(b"")
    ds = MultiSpectrumDataset(
        kind="multi",
        xs=(np.array([1.0, 2.0]), np.array([1.0, 2.0])),
        ys=(np.array([1.0, 2.0]), np.array([3.0, 4.0])),
        meta=({"block_name": "C1s", "xps_region": "C1s"}, {"block_name": "O1s", "xps_region": "O1s"}),
    )
    er = enrich_multi_spectrum(p, ds, {})
    assert er.block_map is not None
    assert set(er.block_map.keys()) == {"0", "1"}
    assert er.dataset is ds


def test_step_register_unique_and_qc_has_no_impl():
    assert get_step("metadata_filter") is not None
    assert get_step("metadata_filter").impl is not None
    assert get_step("crop").impl is not None
    assert len(list_steps()) >= 14


def test_format_get_for_path_lists_supported(tmp_path: Path):
    p = tmp_path / "nope.xyz"
    p.write_text("x", encoding="utf-8")
    try:
        get_format_for_path(p)
        assert False, "expected ValueError"
    except ValueError as e:
        assert ".txt" in str(e) or "Supported" in str(e)

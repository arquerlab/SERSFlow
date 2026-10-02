"""Golden load → transform paths for vibrational + XPS via format/step libraries."""

from __future__ import annotations

from pathlib import Path

import numpy as np

from sersflow.core.io.formats import get_format_for_path, list_formats
from sersflow.core.io.load_file import load_dataset
from sersflow.core.io.technique import infer_technique_family
from sersflow.core.pipeline.library import get_step, list_steps
from sersflow.core.spectrum import extract_xy


def test_golden_vibrational_txt_load_and_crop(tmp_path: Path) -> None:
    p = tmp_path / "raman.txt"
    p.write_text("Wavenumber\tIntensity\n400\t1\n500\t2\n600\t3\n700\t4\n", encoding="utf-8")
    assert infer_technique_family(p) == "vibrational"
    fmt = get_format_for_path(p)
    assert fmt.id == "ascii_xy"
    ds = load_dataset(p)
    xy = extract_xy(ds)
    assert xy is not None
    assert len(xy.x) == 4

    crop = get_step("crop")
    assert crop is not None and crop.impl is not None
    out = crop.impl.transform(xy, {"min_x": 450, "max_x": 650})
    assert float(np.min(out.x)) >= 450
    assert float(np.max(out.x)) <= 650

    step_ids = {s.id for s in list_steps(technique_family="vibrational")}
    assert "cosmic_ray_removal" in step_ids
    assert "crop" in step_ids


def test_golden_xps_meta_catalog_snapshot() -> None:
    """Catalog snapshot: XPS palette excludes vibrational-only steps; formats expose XPS packs."""
    xps_steps = {s.id for s in list_steps(technique_family="xps")}
    assert "fitting" in xps_steps
    assert "baseline" in xps_steps
    assert "cosmic_ray_removal" not in xps_steps

    vamas = next(f for f in list_formats() if f.id == "vamas")
    pub = vamas.to_public()
    assert pub["technique_family"] == "xps"
    assert "multi_block" in pub["capabilities"]
    assert pub["ui"]["show_spectrum_mode"] is True
    assert pub["ui"]["default_x_label"]

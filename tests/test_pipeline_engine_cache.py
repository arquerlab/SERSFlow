from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

from sersflow.api.schemas.pipeline import Pipeline, PipelineStep
from sersflow.core.pipeline.cache import InProcessLRUCache
from sersflow.core.pipeline.engine import EngineConfig, run_pipeline, run_pipeline_parallel_no_cache


@pytest.fixture
def upload_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("SERSFLOW_UPLOAD_DIR", str(tmp_path))
    return tmp_path


def test_reorder_does_not_reuse_stale_step_cache(upload_dir):
    """
    Regression: cache keys must include upstream lineage so swapping step order
    cannot reuse a step output computed under a different prefix.
    """
    (upload_dir / "b").mkdir()
    (upload_dir / "b" / "s.txt").write_text(
        "wn\tint\n100\t10\n200\t20\n300\t30\n",
        encoding="utf-8",
    )
    ref = SimpleNamespace(spectrum_id="s1", relative_path="b/s.txt", record_index=None)

    crop = PipelineStep(name="crop", params={"min_x": 150.0, "max_x": 250.0}, enabled=True)
    norm = PipelineStep(name="normalize", params={"method": "max"}, enabled=True)
    p_crop_then_norm = Pipeline(steps=[crop, norm])
    p_norm_then_crop = Pipeline(steps=[norm, crop])

    cache = InProcessLRUCache(max_items=64)
    cfg = EngineConfig(cache_namespace="test-ns")

    out_a = run_pipeline(inputs=[ref], pipeline=p_crop_then_norm, cache=cache, config=cfg)
    out_b = run_pipeline(inputs=[ref], pipeline=p_norm_then_crop, cache=cache, config=cfg)

    y_a = out_a["s1"].y
    y_b = out_b["s1"].y
    assert y_a.shape == y_b.shape == (1,)
    assert not np.allclose(y_a, y_b), "normalize-after-crop must not match crop-after-normalize"


def test_missing_upload_returns_empty_xy_not_raise(upload_dir):
    """Batch runs must not abort when a dataset references a file that is not on disk."""
    (upload_dir / "ok").mkdir()
    (upload_dir / "ok" / "s.txt").write_text(
        "wn\tint\n100\t10\n200\t20\n300\t30\n",
        encoding="utf-8",
    )
    ok_ref = SimpleNamespace(spectrum_id="ok", relative_path="ok/s.txt", record_index=None)
    missing_ref = SimpleNamespace(spectrum_id="gone", relative_path="missing/nope.txt", record_index=None)

    crop = PipelineStep(name="crop", params={"min_x": 150.0, "max_x": 250.0}, enabled=True)
    p = Pipeline(steps=[crop])

    out = run_pipeline(inputs=[ok_ref, missing_ref], pipeline=p, cache=None)
    assert out["ok"].x.size > 0
    assert out["gone"].x.size == 0 and out["gone"].y.size == 0


def test_parallel_no_cache_missing_upload_returns_empty_xy(upload_dir):
    (upload_dir / "a").mkdir()
    (upload_dir / "a" / "t.txt").write_text(
        "wn\tint\n100\t10\n200\t20\n300\t30\n",
        encoding="utf-8",
    )
    steps = [{"name": "crop", "params": {"min_x": 150.0, "max_x": 250.0}, "enabled": True}]
    inputs = [
        {"spectrum_id": "s1", "relative_path": "a/t.txt", "record_index": None},
        {"spectrum_id": "s2", "relative_path": "ghost/missing.txt", "record_index": None},
    ]
    out = run_pipeline_parallel_no_cache(inputs=inputs, pipeline_steps=steps, config=EngineConfig(), max_workers=2)
    assert out["s1"].x.size > 0
    assert out["s2"].x.size == 0 and out["s2"].y.size == 0

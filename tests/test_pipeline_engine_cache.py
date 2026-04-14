from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

from sersflow.api.schemas.pipeline import Pipeline, PipelineStep
from sersflow.core.pipeline.cache import InProcessLRUCache
from sersflow.core.pipeline.engine import EngineConfig, run_pipeline


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

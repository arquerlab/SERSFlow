from __future__ import annotations

from pathlib import Path

import pytest

from sersflow.infra import analysis_store


def test_analysis_prune_keeps_latest_unpinned(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SERSFLOW_DB_PATH", str(tmp_path / "a.db"))
    monkeypatch.setenv("SERSFLOW_ANALYSIS_MAX_RUNS_PER_DATASET", "2")

    analysis_store.ensure_schema()
    ids = []
    for _ in range(4):
        rid = analysis_store.create_run_pending(
            dataset_id="ds_x",
            session_id=None,
            pipeline_hash="h",
            subset_hash="s",
            pipeline_json='{"steps":[]}',
            label=None,
            pinned=False,
            client_job_key=None,
            params={"subset": {"kind": "all"}},
        )
        ids.append(rid)
        analysis_store.prune_unpinned_runs(dataset_id="ds_x", max_keep=2)

    rows = analysis_store.list_runs(dataset_id="ds_x", limit=10)
    assert len(rows) == 2
    # Newest two survive
    assert {rows[0].run_id, rows[1].run_id} == {ids[-1], ids[-2]}

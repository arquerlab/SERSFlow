from __future__ import annotations

from pathlib import Path

import pytest

from sersflow.api.schemas.pipeline import Pipeline
from sersflow.api.schemas.sessions import SubsetStrategy
from sersflow.infra.sessions_store import create_session, list_sessions_for_dataset


def test_list_sessions_for_dataset_orders_by_updated_desc(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SERSFLOW_DB_PATH", str(tmp_path / "db.sqlite"))

    ds_id = "ds_test_list"
    s1 = create_session(
        dataset_id=ds_id,
        pipeline=Pipeline(steps=[]),
        subset=SubsetStrategy(kind="all"),
    )
    s2 = create_session(
        dataset_id=ds_id,
        pipeline=Pipeline(steps=[]),
        subset=SubsetStrategy(kind="all"),
    )
    rows = list_sessions_for_dataset(dataset_id=ds_id, limit=10)
    ids = [r.session_id for r in rows]
    assert s2.session_id in ids and s1.session_id in ids
    # Most recently created/updated first (s2 after s1)
    assert ids[0] == s2.session_id

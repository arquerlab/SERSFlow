from __future__ import annotations

from sersflow.api.schemas.analysis import AnalysisExportManifest
from sersflow.api.services.observation_export import build_analysis_manifest


def test_manifest_roundtrip_pydantic() -> None:
    raw = build_analysis_manifest(
        run_id="r1",
        dataset_id="d1",
        pipeline_hash="ph",
        subset_hash="sh",
        created_at="t0",
        finished_at="t1",
        feature_columns=["I_a"],
    )
    m = AnalysisExportManifest.model_validate(raw)
    assert m.run_id == "r1"
    assert m.csv_contract.encoding == "utf-8"

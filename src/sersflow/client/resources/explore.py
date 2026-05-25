from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

from sersflow.api.schemas.explore import (
    ClusterRequest,
    CorrelationRequest,
    ExploreJobResponse,
    FPCADiscreteRequest,
    FPCAFDARequest,
    MatrixExportRequest,
    MatrixExportResponse,
    PCARequest,
    SpectrumClusterRequest,
    VIFRequest,
)
from sersflow.client.http import request_json, stream_response_to_file
from sersflow.client.polling import (
    ensure_matrix_job_ok,
    matrix_job_terminal_statuses,
    poll_until,
)
from sersflow.client.resources._common import _Base, dump_json

if TYPE_CHECKING:
    from sersflow.client.client import SersflowClient


class ExploreResource(_Base):
    def __init__(self, root: SersflowClient):
        super().__init__(root)

    def create_matrix_job(self, payload: MatrixExportRequest) -> MatrixExportResponse:
        data = request_json(self._root.http, "POST", "/explore/matrix-jobs", json_body=dump_json(payload))
        return MatrixExportResponse.model_validate(data)

    def get_matrix_job(self, matrix_job_id: str) -> dict[str, Any]:
        data = request_json(self._root.http, "GET", f"/explore/matrix-jobs/{matrix_job_id}")
        return dict(data) if isinstance(data, dict) else {}

    def wait_for_matrix_job(
        self,
        matrix_job_id: str,
        *,
        timeout_s: float = 3600.0,
        poll_interval_s: float = 0.25,
    ) -> dict[str, Any]:
        terminals = matrix_job_terminal_statuses()

        def fetch() -> dict[str, Any]:
            return self.get_matrix_job(matrix_job_id)

        def terminal(d: dict[str, Any]) -> bool:
            return str(d.get("status") or "") in terminals

        last = poll_until(
            fetch,
            job_id=matrix_job_id,
            is_terminal=terminal,
            timeout_s=timeout_s,
            initial_interval_s=poll_interval_s,
        )
        st = str(last.get("status") or "")
        ensure_matrix_job_ok(st, job_id=matrix_job_id, error=str(last.get("error") or "") or None)
        return last

    def export_matrix_to_file(self, matrix_job_id: str, dest: Any) -> None:
        stream_response_to_file(
            self._root.http,
            "GET",
            f"/explore/matrix-jobs/{matrix_job_id}/export.csv",
            dest,
        )

    def export_pca_csv_to_file(
        self,
        explore_id: str,
        kind: Literal["scores", "loadings", "variance", "mean"],
        dest: Any,
    ) -> None:
        stream_response_to_file(
            self._root.http,
            "GET",
            f"/explore/runs/{explore_id}/export/{kind}.csv",
            dest,
        )

    def correlation(self, payload: CorrelationRequest) -> ExploreJobResponse:
        data = request_json(self._root.http, "POST", "/explore/correlation", json_body=dump_json(payload))
        return ExploreJobResponse.model_validate(data)

    def vif(self, payload: VIFRequest) -> ExploreJobResponse:
        data = request_json(self._root.http, "POST", "/explore/vif", json_body=dump_json(payload))
        return ExploreJobResponse.model_validate(data)

    def pca(self, payload: PCARequest) -> ExploreJobResponse:
        data = request_json(self._root.http, "POST", "/explore/pca", json_body=dump_json(payload))
        return ExploreJobResponse.model_validate(data)

    def fpca_discrete(self, payload: FPCADiscreteRequest) -> ExploreJobResponse:
        data = request_json(self._root.http, "POST", "/explore/fpca-discrete", json_body=dump_json(payload))
        return ExploreJobResponse.model_validate(data)

    def spectrum_cluster(self, payload: SpectrumClusterRequest) -> ExploreJobResponse:
        data = request_json(self._root.http, "POST", "/explore/spectrum-cluster", json_body=dump_json(payload))
        return ExploreJobResponse.model_validate(data)

    def fpca_fda(self, payload: FPCAFDARequest) -> ExploreJobResponse:
        data = request_json(self._root.http, "POST", "/explore/fpca-fda", json_body=dump_json(payload))
        return ExploreJobResponse.model_validate(data)

    def cluster(self, payload: ClusterRequest) -> ExploreJobResponse:
        data = request_json(self._root.http, "POST", "/explore/cluster", json_body=dump_json(payload))
        return ExploreJobResponse.model_validate(data)

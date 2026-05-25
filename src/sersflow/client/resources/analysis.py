from __future__ import annotations

from collections.abc import Iterator
from typing import TYPE_CHECKING, Any, Literal

from sersflow.api.schemas.analysis import (
    AnalysisExportManifest,
    AnalysisJobStatusResponse,
    AnalysisRunCreateRequest,
    AnalysisRunCreateResponse,
    AnalysisRunDetailResponse,
    AnalysisRunSummary,
    ObservationSchemaResponse,
)
from sersflow.client.http import raise_for_response, request_bytes, request_json, stream_response_to_file
from sersflow.client.polling import (
    analysis_job_terminal_statuses,
    ensure_analysis_job_ok,
    poll_until,
)
from sersflow.client.resources._common import _Base, dump_json

if TYPE_CHECKING:
    from sersflow.client.client import SersflowClient


class AnalysisResource(_Base):
    def __init__(self, root: SersflowClient):
        super().__init__(root)

    def create_run(self, payload: AnalysisRunCreateRequest) -> AnalysisRunCreateResponse:
        data = request_json(self._root.http, "POST", "/analysis/runs", json_body=dump_json(payload))
        return AnalysisRunCreateResponse.model_validate(data)

    def list_runs(self, dataset_id: str, *, limit: int = 50) -> list[AnalysisRunSummary]:
        data = request_json(
            self._root.http,
            "GET",
            "/analysis/runs",
            params={"dataset_id": dataset_id, "limit": limit},
        )
        if not isinstance(data, list):
            return []
        return [AnalysisRunSummary.model_validate(x) for x in data]

    def get_run(self, run_id: str) -> AnalysisRunDetailResponse:
        data = request_json(self._root.http, "GET", f"/analysis/runs/{run_id}")
        return AnalysisRunDetailResponse.model_validate(data)

    def delete_run(self, run_id: str) -> dict[str, Any]:
        data = request_json(self._root.http, "DELETE", f"/analysis/runs/{run_id}")
        return dict(data) if isinstance(data, dict) else {}

    def delete_all_runs(self, dataset_id: str) -> dict[str, Any]:
        data = request_json(self._root.http, "DELETE", "/analysis/runs", params={"dataset_id": dataset_id})
        return dict(data) if isinstance(data, dict) else {}

    def get_job(self, job_id: str) -> AnalysisJobStatusResponse:
        data = request_json(self._root.http, "GET", f"/analysis/jobs/{job_id}")
        return AnalysisJobStatusResponse.model_validate(data)

    def wait_for_job(
        self,
        job_id: str,
        *,
        timeout_s: float = 3600.0,
        poll_interval_s: float = 0.25,
    ) -> AnalysisJobStatusResponse:
        terminals = analysis_job_terminal_statuses()

        def fetch() -> AnalysisJobStatusResponse:
            return self.get_job(job_id)

        def terminal(j: AnalysisJobStatusResponse) -> bool:
            return j.status in terminals

        last = poll_until(
            fetch,
            job_id=job_id,
            is_terminal=terminal,
            timeout_s=timeout_s,
            initial_interval_s=poll_interval_s,
        )
        ensure_analysis_job_ok(last.status, job_id=job_id, error=last.error)
        return last

    def wait_for_analysis_job(
        self,
        job_id: str,
        *,
        timeout_s: float = 3600.0,
        poll_interval_s: float = 0.25,
    ) -> AnalysisJobStatusResponse:
        """Alias for :meth:`wait_for_job` (same behavior; name matches API docs)."""
        return self.wait_for_job(job_id, timeout_s=timeout_s, poll_interval_s=poll_interval_s)

    def observation_schema(self, run_id: str) -> ObservationSchemaResponse:
        data = request_json(self._root.http, "GET", f"/analysis/runs/{run_id}/observation-schema")
        return ObservationSchemaResponse.model_validate(data)

    def observation_columns(
        self,
        run_id: str,
        cols: str,
        *,
        max_rows: int | None = 50_000,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"cols": cols}
        if max_rows is not None:
            params["max_rows"] = max_rows
        data = request_json(self._root.http, "GET", f"/analysis/runs/{run_id}/observation-columns", params=params)
        return dict(data) if isinstance(data, dict) else {}

    def export_manifest(self, run_id: str) -> AnalysisExportManifest:
        data = request_json(self._root.http, "GET", f"/analysis/runs/{run_id}/export/manifest")
        return AnalysisExportManifest.model_validate(data)

    def export_bundle_bytes(self, run_id: str) -> bytes:
        return request_bytes(self._root.http, "GET", f"/analysis/runs/{run_id}/export/bundle")

    def export_observation_to_file(
        self,
        run_id: str,
        dest: Any,
        *,
        layout: Literal["wide", "long"] = "wide",
        format: Literal["csv", "parquet"] = "csv",
        join: str = "labels,axes",
        max_rows: int | None = None,
    ) -> None:
        params: dict[str, Any] = {"layout": layout, "format": format, "join": join}
        if max_rows is not None:
            params["max_rows"] = max_rows
        stream_response_to_file(
            self._root.http,
            "GET",
            f"/analysis/runs/{run_id}/observation",
            dest,
            params=params,
        )

    def export_features_to_file(
        self,
        run_id: str,
        dest: Any,
        *,
        layout: Literal["wide", "long"] = "wide",
        max_rows: int | None = None,
    ) -> None:
        params: dict[str, Any] = {"layout": layout}
        if max_rows is not None:
            params["max_rows"] = max_rows
        stream_response_to_file(
            self._root.http,
            "GET",
            f"/analysis/runs/{run_id}/export",
            dest,
            params=params,
        )

    def iter_export_features(
        self,
        run_id: str,
        *,
        layout: Literal["wide", "long"] = "wide",
        max_rows: int | None = None,
    ) -> Iterator[bytes]:
        """Yield response body chunks for ``GET /analysis/runs/{run_id}/export`` (streaming CSV)."""
        params: dict[str, Any] = {"layout": layout}
        if max_rows is not None:
            params["max_rows"] = max_rows
        with self._root.http.stream("GET", f"/analysis/runs/{run_id}/export", params=params) as r:
            raise_for_response(r)
            yield from r.iter_bytes()

    def iter_export_observation(
        self,
        run_id: str,
        *,
        layout: Literal["wide", "long"] = "wide",
        format: Literal["csv", "parquet"] = "csv",
        join: str = "labels,axes",
        max_rows: int | None = None,
    ) -> Iterator[bytes]:
        """Yield response chunks for ``GET /analysis/runs/{run_id}/observation``."""
        params: dict[str, Any] = {"layout": layout, "format": format, "join": join}
        if max_rows is not None:
            params["max_rows"] = max_rows
        with self._root.http.stream("GET", f"/analysis/runs/{run_id}/observation", params=params) as r:
            raise_for_response(r)
            yield from r.iter_bytes()

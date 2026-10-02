from __future__ import annotations

import warnings
from typing import TYPE_CHECKING, Any

from sersflow.client.http import request_json
from sersflow.client.resources._common import _Base

if TYPE_CHECKING:
    from sersflow.client.client import SersflowClient

OPENAPI_VERSION_EXPECTED = "0.2.0"


class MetaResource(_Base):
    def __init__(self, root: SersflowClient):
        super().__init__(root)

    def health(self) -> dict[str, str]:
        data = request_json(self._root.http, "GET", "/health")
        return dict(data) if isinstance(data, dict) else {"status": str(data)}

    def check_server(self, *, expected_openapi_version: str | None = None) -> dict[str, Any]:
        """
        Fetch ``GET /openapi.json`` and compare ``info.version`` to the expected API version (warn-only).
        """
        exp = expected_openapi_version or OPENAPI_VERSION_EXPECTED
        spec = request_json(self._root.http, "GET", "/openapi.json")
        if not isinstance(spec, dict):
            return {}
        info = spec.get("info") if isinstance(spec.get("info"), dict) else {}
        ver = info.get("version")
        if isinstance(ver, str) and ver != exp:
            warnings.warn(
                f"SpecFlow OpenAPI version is {ver!r}; Python client was built against {exp!r}.",
                UserWarning,
                stacklevel=2,
            )
        return spec

    def formats(self) -> dict[str, Any]:
        data = request_json(self._root.http, "GET", "/meta/formats")
        return dict(data) if isinstance(data, dict) else {}

    def format_by_id(self, format_id: str) -> dict[str, Any]:
        data = request_json(self._root.http, "GET", f"/meta/formats/{format_id}")
        return dict(data) if isinstance(data, dict) else {}

    def pipeline_steps(
        self,
        *,
        technique_family: str | None = None,
        capabilities: list[str] | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {}
        if technique_family is not None:
            params["technique_family"] = technique_family
        if capabilities:
            params["capability"] = list(capabilities)
        data = request_json(self._root.http, "GET", "/meta/pipeline-steps", params=params or None)
        return dict(data) if isinstance(data, dict) else {}

    def pipeline_step_by_id(self, step_id: str) -> dict[str, Any]:
        data = request_json(self._root.http, "GET", f"/meta/pipeline-steps/{step_id}")
        return dict(data) if isinstance(data, dict) else {}

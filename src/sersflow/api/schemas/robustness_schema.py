"""Schema handshake for the robustness endpoints.

The MCP server (a separate, long-lived process) builds the request models from its own copy of the code. A stale MCP
process silently dropped an argument its tool signature lacked (``constraints``) and the study ran unconstrained.
Both sides now hash the request schemas; the client sends its hash in ``SCHEMA_HEADER`` and the API answers 409 on a
mismatch, so a stale process is detected instead of being trusted.
"""

from __future__ import annotations

import hashlib
import json

from sersflow.api.schemas.analysis import RobustnessJobCreateRequest, RobustnessReanalyseRequest

SCHEMA_HEADER = "X-SpecFlow-Robustness-Schema"


def robustness_schema_hash() -> str:
    schema = {
        "create": RobustnessJobCreateRequest.model_json_schema(),
        "reanalyse": RobustnessReanalyseRequest.model_json_schema(),
    }
    return hashlib.sha256(json.dumps(schema, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()

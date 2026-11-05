"""
K1 line-shape migration: ``gl`` changed meaning from the Gaussian–Lorentzian SUM to the CasaXPS
PRODUCT form (pipeline package schema v2).

Before v2, SpecFlow's ``gl`` component was the sum form (CasaXPS SGL) and ``a_gl`` used the sum as
its base. To keep stored work reproducible, every stored pipeline is rewritten once:

    gl   -> sgl    (sum form, identical numbers)
    a_gl -> a_sgl  (asymmetric GL on the sum base, identical numbers)

After the migration a bare ``gl`` anywhere (new pipelines, MCP agents, v2 packages) means the
CasaXPS product GL(m). Pipeline packages exported as ``sersflow.pipeline.v1`` are migrated on import.

The rewrite only touches ``fitting`` steps (``params.components[*].component_type``) and recurses
through any JSON wrapper (sessions, run snapshots ``{"pipeline": ...}``, matrix jobs), so it can be
applied to whatever pipeline-bearing JSON a store keeps.
"""

from __future__ import annotations

from typing import Any

PIPELINE_SCHEMA_V1 = "sersflow.pipeline.v1"
PIPELINE_SCHEMA_V2 = "sersflow.pipeline.v2"
SUPPORTED_PIPELINE_SCHEMAS = frozenset({PIPELINE_SCHEMA_V1, PIPELINE_SCHEMA_V2})

LEGACY_GL_RENAMES: dict[str, str] = {"gl": "sgl", "a_gl": "a_sgl"}


def _migrate_fitting_params(params: Any) -> int:
    if not isinstance(params, dict):
        return 0
    comps = params.get("components")
    if not isinstance(comps, list):
        return 0
    n = 0
    for comp in comps:
        if not isinstance(comp, dict):
            continue
        ct = str(comp.get("component_type") or "").strip().lower()
        new = LEGACY_GL_RENAMES.get(ct)
        if new is not None:
            comp["component_type"] = new
            n += 1
    return n


def migrate_legacy_gl(obj: Any) -> int:
    """
    Rewrite legacy ``gl``/``a_gl`` component types in place, anywhere inside ``obj``.

    Returns the number of components renamed. Idempotent: ``sgl``/``a_sgl`` are left alone.
    """
    n = 0
    if isinstance(obj, dict):
        if obj.get("name") == "fitting" and isinstance(obj.get("params"), dict):
            n += _migrate_fitting_params(obj["params"])
        for v in obj.values():
            n += migrate_legacy_gl(v)
    elif isinstance(obj, list):
        for v in obj:
            n += migrate_legacy_gl(v)
    return n

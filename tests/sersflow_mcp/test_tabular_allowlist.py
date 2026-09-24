"""Tabular path allowlist tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from sersflow.mcp.config import McpConfig
from sersflow.mcp.runtime import RuntimeContext
from sersflow.mcp.tools.tabular import _is_allowed


def test_allowlist_export_dir(tmp_path: Path) -> None:
    export = tmp_path / "exports"
    export.mkdir()
    f = export / "a.csv"
    f.write_text("a,b\n1,2\n", encoding="utf-8")
    cfg = McpConfig(export_dir=str(export))
    ctx = RuntimeContext(cfg)
    assert _is_allowed(f, ctx) is True
    outside = tmp_path / "secret.csv"
    outside.write_text("x\n", encoding="utf-8")
    assert _is_allowed(outside, ctx) is False


def test_allowlist_recorded_export(tmp_path: Path) -> None:
    export = tmp_path / "exports"
    export.mkdir()
    other = tmp_path / "elsewhere"
    other.mkdir()
    f = other / "out.csv"
    f.write_text("a\n1\n", encoding="utf-8")
    cfg = McpConfig(export_dir=str(export))
    ctx = RuntimeContext(cfg)
    assert _is_allowed(f, ctx) is False
    ctx.record_export("analysis:r1", f)
    assert _is_allowed(f, ctx) is True

"""Export path resolution tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from sersflow.mcp.config import McpConfig
from sersflow.mcp.runtime import RuntimeContext


def test_relative_output_stays_under_export_dir(tmp_path: Path) -> None:
    export = tmp_path / "exports"
    cfg = McpConfig(export_dir=str(export), api_start_enabled=False)
    ctx = RuntimeContext(cfg)
    dest = ctx.resolve_export_path("sub/out.csv", "default.csv")
    assert dest.parent == (export / "sub").resolve()
    assert dest.name == "out.csv"


def test_relative_escape_rejected(tmp_path: Path) -> None:
    export = tmp_path / "exports"
    cfg = McpConfig(export_dir=str(export), api_start_enabled=False)
    ctx = RuntimeContext(cfg)
    with pytest.raises(ValueError, match="export_dir"):
        ctx.resolve_export_path("../secret.csv", "default.csv")


def test_absolute_output_requires_confirm(tmp_path: Path) -> None:
    export = tmp_path / "exports"
    other = tmp_path / "elsewhere" / "x.csv"
    cfg = McpConfig(export_dir=str(export), api_start_enabled=False)
    ctx = RuntimeContext(cfg)
    with pytest.raises(Exception) as ei:
        ctx.resolve_export_path(str(other), "default.csv", confirm=False)
    from sersflow.mcp.confirm import NeedsConfirmError

    assert isinstance(ei.value, NeedsConfirmError)
    dest = ctx.resolve_export_path(str(other), "default.csv", confirm=True)
    assert dest == other.resolve()


def test_absolute_output_allowed_with_confirm(tmp_path: Path) -> None:
    export = tmp_path / "exports"
    other = tmp_path / "elsewhere" / "x.csv"
    cfg = McpConfig(export_dir=str(export), api_start_enabled=False)
    ctx = RuntimeContext(cfg)
    dest = ctx.resolve_export_path(str(other), "default.csv", confirm=True)
    assert dest == other.resolve()

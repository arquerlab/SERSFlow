"""Tests for MCP config loading."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from sersflow.mcp.config import DEFAULT_URL, load_config


def test_load_defaults(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("SERSFLOW_URL", raising=False)
    monkeypatch.delenv("SERSFLOW_USERNAME", raising=False)
    monkeypatch.delenv("SERSFLOW_PASSWORD", raising=False)
    monkeypatch.delenv("SERSFLOW_MCP_CONFIG", raising=False)
    monkeypatch.chdir(tmp_path)
    cfg = load_config()
    assert cfg.base_url == DEFAULT_URL
    assert cfg.upload_confirm_bytes == 104_857_600
    assert cfg.analysis_async_default is True
    assert cfg.username is None


def test_toml_override(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("SERSFLOW_USERNAME", raising=False)
    monkeypatch.delenv("SERSFLOW_PASSWORD", raising=False)
    toml = tmp_path / "mcp.toml"
    toml.write_text(
        'export_dir = "./out"\njob_wait_timeout_s = 12.5\nanalysis_async_default = false\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("SERSFLOW_URL", "http://127.0.0.1:9000")
    cfg = load_config(toml_path=toml)
    assert cfg.base_url == "http://127.0.0.1:9000"
    assert cfg.export_dir == "./out"
    assert cfg.job_wait_timeout_s == 12.5
    assert cfg.analysis_async_default is False
    assert "password" not in cfg.public_snapshot()
    assert "base_url" not in cfg.public_snapshot()


def test_env_credentials(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("SERSFLOW_USERNAME", "alice")
    monkeypatch.setenv("SERSFLOW_PASSWORD", "secret")
    cfg = load_config()
    assert cfg.username == "alice"
    assert cfg.password == "secret"


def test_toml_type_coercion(tmp_path: Path) -> None:
    toml = tmp_path / "mcp.toml"
    toml.write_text(
        'job_wait_timeout_s = "42"\nanalysis_async_default = "yes"\nupload_confirm_bytes = "1000"\n',
        encoding="utf-8",
    )
    cfg = load_config(toml_path=toml)
    assert cfg.job_wait_timeout_s == 42.0
    assert cfg.analysis_async_default is True
    assert cfg.upload_confirm_bytes == 1000


def test_invalid_config_rejected(tmp_path: Path) -> None:
    toml = tmp_path / "mcp.toml"
    toml.write_text("tabular_max_rows = 0\n", encoding="utf-8")
    with pytest.raises(ValueError, match="tabular_max_rows"):
        load_config(toml_path=toml)

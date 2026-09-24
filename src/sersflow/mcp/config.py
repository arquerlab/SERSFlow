"""Load MCP configuration from environment (secrets) and TOML (non-secrets)."""

from __future__ import annotations

import os
import sys
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Any, get_args, get_origin, get_type_hints
from urllib.parse import urlparse

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib  # type: ignore[no-redef, import-not-found]


DEFAULT_URL = "http://127.0.0.1:8000"


@dataclass
class McpConfig:
    """Non-secret MCP settings plus connection fields from the environment."""

    base_url: str = DEFAULT_URL
    username: str | None = None
    password: str | None = None
    export_dir: str = "./.sersflow_mcp_exports"
    http_timeout_s: float = 30.0
    job_wait_timeout_s: float = 3600.0
    job_poll_interval_s: float = 0.25
    api_start_enabled: bool = True
    api_health_timeout_s: float = 60.0
    api_health_poll_s: float = 0.5
    upload_confirm_bytes: int = 104_857_600
    fitting_confirm_max_components: int = 6
    tabular_max_rows: int = 50
    tabular_max_cols: int = 30
    analysis_async_default: bool = True
    config_path: str | None = None

    def export_dir_path(self) -> Path:
        return Path(self.export_dir).expanduser().resolve()

    def host_port(self) -> tuple[str, int]:
        """Host/port for spawning uvicorn, honoring SERSFLOW_HOST/PORT when URL is default."""
        parsed = urlparse(self.base_url)
        host = parsed.hostname or "127.0.0.1"
        port = parsed.port or 8000
        env_host = os.environ.get("SERSFLOW_HOST")
        env_port = os.environ.get("SERSFLOW_PORT")
        if self.base_url.rstrip("/") == DEFAULT_URL.rstrip("/"):
            if env_host:
                host = env_host
            if env_port:
                port = int(env_port)
        return host, int(port)

    def public_snapshot(self) -> dict[str, Any]:
        """Non-secret settings for meta tools (no URL credentials)."""
        data = asdict(self)
        data.pop("username", None)
        data.pop("password", None)
        data.pop("base_url", None)
        return data

    def validate(self) -> None:
        if self.http_timeout_s <= 0:
            raise ValueError("http_timeout_s must be > 0")
        if self.job_wait_timeout_s <= 0:
            raise ValueError("job_wait_timeout_s must be > 0")
        if self.job_poll_interval_s <= 0:
            raise ValueError("job_poll_interval_s must be > 0")
        if self.api_health_timeout_s <= 0:
            raise ValueError("api_health_timeout_s must be > 0")
        if self.api_health_poll_s <= 0:
            raise ValueError("api_health_poll_s must be > 0")
        if self.upload_confirm_bytes < 0:
            raise ValueError("upload_confirm_bytes must be >= 0")
        if self.fitting_confirm_max_components < 0:
            raise ValueError("fitting_confirm_max_components must be >= 0")
        if self.tabular_max_rows < 1:
            raise ValueError("tabular_max_rows must be >= 1")
        if self.tabular_max_cols < 1:
            raise ValueError("tabular_max_cols must be >= 1")


_TOML_KEYS = {f.name for f in fields(McpConfig)} - {"base_url", "username", "password", "config_path"}
_FIELD_TYPES: dict[str, Any] = get_type_hints(McpConfig)


def _unwrap_optional(typ: Any) -> Any:
    origin = get_origin(typ)
    args = get_args(typ)
    if origin is None and isinstance(typ, str):
        return typ
    # typing.Union / types.UnionType for X | None
    if args and type(None) in args:
        non_none = [a for a in args if a is not type(None)]
        return non_none[0] if len(non_none) == 1 else typ
    return typ


def _coerce(key: str, value: Any) -> Any:
    """Coerce TOML values to the dataclass field types."""
    typ = _unwrap_optional(_FIELD_TYPES.get(key))
    if typ is bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "y"}
        return bool(value)
    if typ is int:
        return int(value)
    if typ is float:
        return float(value)
    if typ is str:
        return str(value)
    return value


def _find_toml_path() -> Path | None:
    env = os.environ.get("SERSFLOW_MCP_CONFIG", "").strip()
    if env:
        return Path(env).expanduser()
    cwd = Path.cwd() / "sersflow_mcp.toml"
    if cwd.is_file():
        return cwd
    return None


def _load_toml(path: Path) -> dict[str, Any]:
    with path.open("rb") as f:
        data = tomllib.load(f)
    if not isinstance(data, dict):
        raise ValueError(f"MCP TOML root must be a table: {path}")
    return data


def load_config(*, toml_path: Path | str | None = None) -> McpConfig:
    """
    Load config: defaults <- TOML <- env secrets.

    TOML discovery: explicit path, else ``SERSFLOW_MCP_CONFIG``, else ``./sersflow_mcp.toml``.
    """
    cfg = McpConfig()
    path: Path | None
    if toml_path is not None:
        path = Path(toml_path).expanduser()
    else:
        path = _find_toml_path()

    if path is not None:
        if not path.is_file():
            raise FileNotFoundError(f"MCP config not found: {path}")
        raw = _load_toml(path)
        cfg.config_path = str(path.resolve())
        for key, value in raw.items():
            if key in _TOML_KEYS:
                try:
                    setattr(cfg, key, _coerce(key, value))
                except (TypeError, ValueError) as e:
                    raise ValueError(f"Invalid MCP TOML value for {key!r}: {value!r} ({e})") from e

    cfg.base_url = os.environ.get("SERSFLOW_URL", cfg.base_url).strip() or DEFAULT_URL
    user = os.environ.get("SERSFLOW_USERNAME", "").strip()
    password = os.environ.get("SERSFLOW_PASSWORD", "").strip()
    cfg.username = user or None
    cfg.password = password or None
    cfg.validate()
    return cfg

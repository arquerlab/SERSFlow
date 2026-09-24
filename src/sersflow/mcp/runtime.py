"""Shared client lifecycle: health probe, optional API spawn, auth, version probe."""

from __future__ import annotations

import atexit
import logging
import os
import subprocess
import sys
import threading
import time
import warnings
from pathlib import Path
from typing import Any, TextIO
from urllib.parse import urlparse

import httpx

from sersflow.client import SersflowClient
from sersflow.client.exceptions import SersflowApiError
from sersflow.client.resources.meta import OPENAPI_VERSION_EXPECTED
from sersflow.mcp import EXPECTED_OPENAPI_VERSION, MCP_VERSION
from sersflow.mcp import confirm as confirm_gates
from sersflow.mcp.config import McpConfig, load_config

logger = logging.getLogger(__name__)


def configure_stderr_logging(level: int = logging.INFO) -> None:
    """MCP stdio uses stdout; all logs must go to stderr."""
    root = logging.getLogger()
    # Avoid wiping unrelated handlers repeatedly; only add our stderr handler once.
    marker = "sersflow_mcp_stderr"
    if any(getattr(h, "sersflow_mcp_marker", None) == marker for h in root.handlers):
        root.setLevel(level)
        return
    handler = logging.StreamHandler(sys.stderr)
    handler.sersflow_mcp_marker = marker  # type: ignore[attr-defined]
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root.addHandler(handler)
    root.setLevel(level)


def _major(version: str | None) -> int | None:
    if not version or not isinstance(version, str):
        return None
    try:
        return int(version.strip().split(".", 1)[0])
    except ValueError:
        return None


class RuntimeContext:
    """Lazy SersflowClient + optional local API process."""

    def __init__(self, config: McpConfig | None = None):
        self.config = config or load_config()
        self.client: SersflowClient | None = None
        self.auth_mode: str | None = None
        self.warnings: list[str] = []
        self.server_openapi_version: str | None = None
        self.version_incompatible: bool = False
        self.spawned_by_mcp: bool = False
        self._proc: subprocess.Popen[Any] | None = None
        self._api_log_file: TextIO | None = None
        self.export_paths: dict[str, list[str]] = {}
        self._ready = False
        self._atexit_registered = False
        self._lock = threading.RLock()

    @classmethod
    def from_env(cls) -> RuntimeContext:
        return cls(load_config())

    def _register_cleanup(self) -> None:
        if not self._atexit_registered:
            atexit.register(self.shutdown)
            self._atexit_registered = True

    def record_export(self, key: str, path: Path | str) -> None:
        p = str(Path(path).resolve())
        with self._lock:
            self.export_paths.setdefault(key, [])
            if p not in self.export_paths[key]:
                self.export_paths[key].append(p)

    def allowed_export_paths(self) -> set[Path]:
        with self._lock:
            paths = {self.config.export_dir_path()}
            for lst in self.export_paths.values():
                for p in lst:
                    paths.add(Path(p).resolve())
            return paths

    def _close_client(self) -> None:
        if self.client is not None:
            try:
                self.client.close()
            except Exception:
                pass
            self.client = None

    def _kill_spawned_api(self, *, reason: str) -> None:
        if not self.spawned_by_mcp or self._proc is None:
            return
        if self._proc.poll() is None:
            # Avoid logging during atexit (stderr may already be closed in pytest).
            try:
                self._proc.terminate()
                self._proc.wait(timeout=10)
            except Exception:
                try:
                    self._proc.kill()
                except Exception:
                    pass
        self._proc = None
        self.spawned_by_mcp = False

    def ensure_ready(self) -> SersflowClient:
        with self._lock:
            if self._ready and self.client is not None:
                return self.client
            self.ensure_api()
            # Replace any prior client from a failed attempt
            self._close_client()
            try:
                self.client = SersflowClient(self.config.base_url, timeout=self.config.http_timeout_s)
                self.authenticate()
                self.version_probe()
                self._ready = True
                self._register_cleanup()
                return self.client
            except Exception:
                self._close_client()
                self._ready = False
                # Keep spawned API alive if we own it so retries can reuse it; atexit still cleans up.
                self._register_cleanup()
                raise

    def get_client(self) -> SersflowClient:
        return self.ensure_ready()

    def health_ok(self) -> bool:
        try:
            with httpx.Client(base_url=self.config.base_url.rstrip("/"), timeout=2.0) as h:
                r = h.get("/health")
                return r.status_code == 200
        except Exception:
            return False

    def ensure_api(self) -> None:
        if self.health_ok():
            # Do not clear ownership if we already spawned this process.
            if not self.spawned_by_mcp:
                self.spawned_by_mcp = False
            return
        if not self.config.api_start_enabled:
            raise RuntimeError(
                f"SERSFlow API not reachable at {self.config.base_url}. "
                "Start sersflow-api or set api_start_enabled=true in MCP TOML."
            )
        # Re-check before spawn (race with another process).
        if self.health_ok():
            return
        # Already spawning / spawned but not yet healthy
        if self.spawned_by_mcp and self._proc is not None and self._proc.poll() is None:
            self._wait_for_health(log_path=self.config.export_dir_path() / "api_spawn.log")
            return

        host, port = self.config.host_port()
        log_dir = self.config.export_dir_path()
        log_dir.mkdir(parents=True, exist_ok=True)
        log_path = log_dir / "api_spawn.log"
        if self._api_log_file is None:
            self._api_log_file = open(log_path, "a", encoding="utf-8")  # noqa: SIM115
        cmd = [
            sys.executable,
            "-m",
            "uvicorn",
            "sersflow.api.main:app",
            "--host",
            host,
            "--port",
            str(port),
        ]
        kwargs: dict[str, Any] = {
            "stdout": self._api_log_file,
            "stderr": subprocess.STDOUT,
            "env": os.environ.copy(),
        }
        if sys.platform == "win32":
            kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]
        logger.info("Starting SERSFlow API: %s", " ".join(cmd))
        self._proc = subprocess.Popen(cmd, **kwargs)
        self.spawned_by_mcp = True
        self._register_cleanup()
        try:
            self._wait_for_health(log_path=log_path)
        except Exception:
            self._kill_spawned_api(reason="health wait failed")
            raise

    def _wait_for_health(self, *, log_path: Path) -> None:
        assert self._proc is not None
        deadline = time.time() + self.config.api_health_timeout_s
        while time.time() < deadline:
            if self._proc.poll() is not None:
                if self.health_ok():
                    logger.info("API became healthy after spawn exit; assuming external server")
                    self.spawned_by_mcp = False
                    self._proc = None
                    return
                raise RuntimeError(
                    f"sersflow-api exited early (code={self._proc.returncode}). See {log_path}"
                )
            if self.health_ok():
                logger.info("SERSFlow API is healthy at %s", self.config.base_url)
                return
            time.sleep(self.config.api_health_poll_s)
        raise RuntimeError(
            f"Timed out waiting for API health at {self.config.base_url} after "
            f"{self.config.api_health_timeout_s}s. See {log_path}"
        )

    def authenticate(self) -> None:
        assert self.client is not None
        user, password = self.config.username, self.config.password
        if (user and not password) or (password and not user):
            raise RuntimeError(
                "Both SERSFLOW_USERNAME and SERSFLOW_PASSWORD are required when either is set."
            )
        if user and password:
            self.client.login(user, password)
            self.auth_mode = "cookie"
            return
        try:
            self.client.datasets.list(limit=1)
            self.auth_mode = "open_or_disabled"
        except SersflowApiError as e:
            if e.status_code == 401:
                raise RuntimeError(
                    "API requires authentication. Set SERSFLOW_USERNAME and SERSFLOW_PASSWORD, "
                    "or run the API with SERSFLOW_AUTH_DISABLED=1 for local testing."
                ) from e
            raise

    def version_probe(self) -> None:
        assert self.client is not None
        self.warnings = []
        self.version_incompatible = False
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", UserWarning)
                spec = self.client.meta.check_server(expected_openapi_version=EXPECTED_OPENAPI_VERSION)
        except Exception as e:
            self.warnings.append(f"Could not fetch OpenAPI version: {e}")
            return
        info = spec.get("info") if isinstance(spec, dict) else None
        ver = info.get("version") if isinstance(info, dict) else None
        self.server_openapi_version = ver if isinstance(ver, str) else None
        expected = EXPECTED_OPENAPI_VERSION
        if not self.server_openapi_version:
            self.version_incompatible = True
            self.warnings.append("Server OpenAPI version missing; treating as incompatible.")
            return
        if self.server_openapi_version == expected:
            return
        maj = _major(self.server_openapi_version)
        exp_maj = _major(expected)
        if maj is None or exp_maj is None or maj != exp_maj:
            self.version_incompatible = True
            self.warnings.append(
                f"Incompatible OpenAPI version {self.server_openapi_version!r} "
                f"(MCP expects {expected!r})."
            )
        else:
            self.warnings.append(
                f"OpenAPI version drift: server={self.server_openapi_version!r}, expected={expected!r}."
            )

    def require_compatible(self) -> dict[str, Any] | None:
        if self.version_incompatible:
            return {
                "ok": False,
                "error": "incompatible",
                "message": (
                    f"API OpenAPI {self.server_openapi_version!r} incompatible with MCP "
                    f"{MCP_VERSION} (expected {EXPECTED_OPENAPI_VERSION}). Upgrade MCP or API."
                ),
                "mcp_version": MCP_VERSION,
                "expected_openapi": EXPECTED_OPENAPI_VERSION,
                "server_openapi": self.server_openapi_version,
            }
        return None

    def meta_payload(self) -> dict[str, Any]:
        self.ensure_ready()
        return {
            "ok": True,
            "mcp_version": MCP_VERSION,
            "expected_openapi": EXPECTED_OPENAPI_VERSION,
            "client_expected_openapi": OPENAPI_VERSION_EXPECTED,
            "server_openapi": self.server_openapi_version,
            "auth_mode": self.auth_mode,
            "base_url_host": urlparse(self.config.base_url).hostname,
            "spawned_by_mcp": self.spawned_by_mcp,
            "warnings": list(self.warnings),
            "version_incompatible": self.version_incompatible,
            "config": self.config.public_snapshot(),
        }

    def resolve_export_path(
        self,
        output_path: str | None,
        default_name: str,
        *,
        confirm: bool = False,
    ) -> Path:
        """
        Resolve export destination.

        Relative paths are always under ``export_dir`` (``..`` segments cannot escape).
        Absolute paths outside ``export_dir`` require ``confirm=true``.
        """
        export_root = self.config.export_dir_path()
        export_root.mkdir(parents=True, exist_ok=True)
        if output_path:
            dest = Path(output_path).expanduser()
            if dest.is_absolute():
                dest = dest.resolve()
                try:
                    dest.relative_to(export_root)
                except ValueError:
                    blocked = confirm_gates.require_confirm(
                        confirm,
                        reason="absolute_export_outside_export_dir",
                        message=(
                            f"Absolute output_path {dest} is outside export_dir {export_root}. "
                            "Retry with confirm=true after user approval."
                        ),
                        details={"path": str(dest), "export_dir": str(export_root)},
                    )
                    if blocked is not None:
                        raise confirm_gates.NeedsConfirmError(blocked) from None
            else:
                dest = (export_root / dest).resolve()
                try:
                    dest.relative_to(export_root)
                except ValueError as e:
                    raise ValueError(
                        f"Relative output_path must stay under export_dir ({export_root}): {output_path}"
                    ) from e
        else:
            safe_name = Path(default_name).name
            dest = (export_root / safe_name).resolve()
        dest.parent.mkdir(parents=True, exist_ok=True)
        return dest

    def shutdown(self) -> None:
        with self._lock:
            self._close_client()
            self._kill_spawned_api(reason="shutdown")
            if self._api_log_file is not None:
                try:
                    self._api_log_file.close()
                except Exception:
                    pass
                self._api_log_file = None
            self._ready = False

"""Local tabular read tool (explicit preview / value lookup)."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

import pandas as pd

from sersflow.mcp.tools._util import tool_call

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

    from sersflow.mcp.runtime import RuntimeContext


def _is_allowed(path: Path, ctx: RuntimeContext) -> bool:
    resolved = path.resolve()
    export_root = ctx.config.export_dir_path()
    try:
        resolved.relative_to(export_root)
        return True
    except ValueError:
        pass
    allowed = ctx.allowed_export_paths()
    if resolved in allowed:
        return True
    for a in allowed:
        if a.is_file() and resolved == a:
            return True
        if a.is_dir():
            try:
                resolved.relative_to(a)
                return True
            except ValueError:
                continue
    return False


def register(mcp: FastMCP, ctx: RuntimeContext) -> None:
    @mcp.tool(name="read_tabular_file")
    async def read_tabular_file(
        path: str,
        columns: list[str] | None = None,
        max_rows: int | None = None,
        preview: bool = False,
    ) -> str:
        """
        Read a slice of a CSV/Parquet previously exported (or under export_dir).
        Use only when a value/preview is required; no automatic previews elsewhere.
        """

        def _run() -> dict[str, Any]:
            p = Path(path).expanduser().resolve()
            if not _is_allowed(p, ctx):
                return {
                    "ok": False,
                    "error": "validation",
                    "message": (
                        f"Path not allowed: {p}. Only files under export_dir or "
                        "paths returned by export tools may be read."
                    ),
                }
            if not p.is_file():
                raise FileNotFoundError(f"File not found: {p}")
            if p.suffix.lower() in {".parquet", ".pq"}:
                df = pd.read_parquet(p)
            else:
                df = pd.read_csv(p)
            row_cap = max_rows if max_rows is not None else ctx.config.tabular_max_rows
            if not preview and max_rows is None:
                # Still cap; agent should pass max_rows or preview when user asks
                row_cap = min(row_cap, ctx.config.tabular_max_rows)
            col_cap = ctx.config.tabular_max_cols
            total_rows = int(df.shape[0])
            truncated_cols = False
            if columns:
                missing = [c for c in columns if c not in df.columns]
                if missing:
                    raise ValueError(f"Unknown columns: {missing}. Available: {list(df.columns)[:50]}")
                df = df.loc[:, columns]
            elif df.shape[1] > col_cap:
                df = df.iloc[:, :col_cap]
                truncated_cols = True
            df = df.head(row_cap)
            records = df.where(pd.notnull(df), None).to_dict(orient="records")
            return {
                "ok": True,
                "path": str(p),
                "preview": preview,
                "rows_returned": len(records),
                "rows_total": total_rows,
                "columns": list(df.columns),
                "truncated_cols": truncated_cols,
                "records": records,
            }

        return await tool_call(ctx, _run)

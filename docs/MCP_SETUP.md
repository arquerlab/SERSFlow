# SERSFlow MCP setup (Cursor)

Optional stdio MCP server wrapping `SersflowClient` for LLM agents. Product decisions: [MCP_AGENT_BRIEF.md](MCP_AGENT_BRIEF.md).

## Install

```bash
pip install -e ".[mcp]"
```

This installs the `sersflow-mcp` console script (requires `mcp>=1.18,<2` and `httpx`).

## Local API

Either start the API yourself:

```bash
set SERSFLOW_AUTH_DISABLED=1
sersflow-api
```

Or let the MCP spawn uvicorn when `api_start_enabled = true` (default) and `/health` is down.

## Environment (secrets only)

| Variable | Role |
|----------|------|
| `SERSFLOW_URL` | API base URL (default `http://127.0.0.1:8000`) |
| `SERSFLOW_USERNAME` / `SERSFLOW_PASSWORD` | Cookie login when auth is enabled |
| `SERSFLOW_MCP_CONFIG` | Path to non-secret TOML |

If credentials are omitted and the API accepts unauthenticated calls (`SERSFLOW_AUTH_DISABLED=1`), the MCP proceeds in open mode.

## Non-secret TOML

Copy [config/sersflow_mcp.example.toml](../config/sersflow_mcp.example.toml) to `./sersflow_mcp.toml` or point `SERSFLOW_MCP_CONFIG` at it.

Do **not** put URL or passwords in TOML.

## Cursor `mcp.json` example

```json
{
  "mcpServers": {
    "sersflow": {
      "command": "sersflow-mcp",
      "env": {
        "SERSFLOW_URL": "http://127.0.0.1:8000",
        "SERSFLOW_AUTH_DISABLED": "1",
        "SERSFLOW_MCP_CONFIG": "C:/Users/you/Documents/SERSFlow/config/sersflow_mcp.example.toml"
      }
    }
  }
}
```

If `sersflow-mcp` is not on `PATH`, use the full path to the script or:

```json
"command": "python",
"args": ["-m", "sersflow.mcp"]
```

(with the same `env`).

## Agent behavior (checkpointing)

- If the user does not specify a method, **ask** before choosing fit vs integrate vs PCA, etc.
- Propose the plan / pipeline; wait for approval before heavy writes.
- Large uploads (>100 MB) and fittings with **>6 components** require retrying the tool with `confirm=true` after the user approves.
- Library pipelines: create new names only — never overwrite.
- Session working pipelines may be updated.

## Timeouts

If `post_analysis_jobs_wait` / `post_explore_matrix_jobs_wait` times out, the tool returns JSON with a `resume` object:

- Analysis: call `get_analysis_jobs` with `job_id`, or wait again with `post_analysis_jobs_wait`
- Matrix: call `get_explore_matrix_jobs` with `matrix_job_id`, or wait again with `post_explore_matrix_jobs_wait`

## Exports and previews

Export tools write under `export_dir` (default `./.sersflow_mcp_exports`) and return a **path**. Relative `output_path` values cannot escape `export_dir`. Absolute paths **outside** `export_dir` require `confirm=true`.

There is no automatic table preview. Use `read_tabular_file` only when a value or explicit preview is needed (paths must be under `export_dir` or previously returned by an export tool).

Explore tools (`post_explore_correlation`, PCA, etc.) return **compact summaries** (ids, scalars, shape hints) — not full matrices. Export CSVs and `read_tabular_file` for full tables.

## Resources

| URI | Content |
|-----|---------|
| `sersflow://pipelines` | Saved pipeline catalog |
| `sersflow://openapi/summary` | Capability sheet |
| `sersflow://analysis/runs/{run_id}/export/manifest` | Manifest + local export paths |

# SpecFlow MCP setup (Cursor)

Optional stdio MCP server wrapping `SersflowClient` for LLM agents. Product decisions: [MCP_AGENT_BRIEF.md](MCP_AGENT_BRIEF.md).

Expected OpenAPI / MCP version: **0.2.0**.

## Install

```bash
pip install -e ".[mcp]"
```

This installs the `sersflow-mcp` console script (requires `mcp>=1.18,<2` and `httpx`). Package path remains `sersflow`; the MCP display name is SpecFlow.

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

Defaults include `fitting_confirm_max_components = 20` (XPS recipes often exceed 6 peaks). Purge and oversized exports still require `confirm=true`.

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
- Large uploads (>100 MB), fittings above `fitting_confirm_max_components`, and **purge** require retrying with `confirm=true` after the user approves.
- Library pipelines: create new names only — never overwrite.
- Session working pipelines may be updated.
- Dataset and pipeline `technique_family` must match (`vibrational` or `xps`).

## XPS library workflow

1. Upload (folder pattern default `*`) → `get_io_uploads`
2. `post_datasets` with `technique_family=xps`, optional `vms_spectrum_mode` / `xps_regions`
3. Optional: `get_xps_chemical_states` (always filtered / limited)
4. `get_xps_fitting_recipes_index` → `apply_xps_fitting_recipe` or `post_xps_apply_recipe_to_session`
5. Analysis / fit-curve export / explore as needed

## Timeouts

If wait tools time out, the tool returns JSON with a `resume` object — call the matching status tool or wait again (`get_analysis_jobs`, `get_analysis_fit_curve_jobs`, `get_explore_matrix_jobs`, …).

## Exports and previews

Export and plot tools write under `export_dir` (default `./.sersflow_mcp_exports`) and return a **path**. Relative `output_path` values cannot escape `export_dir`. Absolute paths **outside** `export_dir` require `confirm=true`.

There is no automatic table preview. Use `read_tabular_file` only when a value or explicit preview is needed.

Explore tools return **compact summaries**. Plot tools return **figure file paths** (never dump full Plotly into chat).

## Resources

| URI | Content |
|-----|---------|
| `sersflow://pipelines` | Saved pipeline catalog |
| `sersflow://openapi/summary` | Capability sheet |
| `sersflow://analysis/runs/{run_id}/export/manifest` | Manifest + local export paths |
| `sersflow://meta/formats` | Format id + technique_family |
| `sersflow://xps/fitting-recipes/index` | Capped recipe index |
| `sersflow://xps/chemical-states/summary` | Catalog source hint (no full entries) |

# SERSFlow MCP — agent brief

Living notes for designing an MCP over the SERSFlow programmatic API / Python client.
Update this file as product decisions are made; it is the source of truth for MCP scope.

## Goals

- Enable an LLM agent to drive SERSFlow without the UI for spectral analysis workflows.
- Agent inputs: spectral data, metadata, and context (experiment type + analysis objective).
- Agent can upload data, create or reuse datasets and pipelines, run analysis/explore, and export CSV for humans or other agents (including the same agent in a later step).

## Target agent loop

1. Ingest data + metadata + objective
2. Upload / resolve dataset (create new or use existing)
3. Resolve or author a preprocessing (+ feature) pipeline
4. Run analysis and/or explore workflows matching the objective
5. Export CSV (+ optional short interpretation payload)
6. If the objective asks for a numeric answer (e.g. correlation), read export/API results and return or compute that value for the user

## Example objectives → intended strategies

- Correlate two specific peaks → preprocess + fit/integrate those peaks → analysis features → correlation
- Correlate many peaks/regions → many fittings OR simpler preprocess + correlation matrix / PCA
- Peak A vs time → use series axis + peak feature → export / explore time evolution

## Decisions (goals)

### Method selection

- User may specify the analysis/preprocessing method.
- If not specified, the agent must **ask** which method to choose (do not silently pick for the user).

### Autonomy

- **Current (testing):** checkpointed — propose plan / pipeline / next step and wait for approval before mutating or running heavy jobs.
- **Long-term goal:** fully autonomous end-to-end execution once testing confidence is high.

### Pipeline and dataset reuse

- Prefer **reuse** of existing datasets and pipelines when they already fit the objective.
- If any change is needed, **create a new named pipeline** (or dataset as appropriate); **do not modify** existing pipelines.
- Never edit or delete other users’ pipelines or datasets.

### Export and consumption

- Exported CSV must be usable by:
  - humans (spreadsheets / external tools),
  - other LLM agents,
  - the **same** agent that drove the MCP (e.g. to report a correlation coefficient).
- If the objective is to determine a correlation (or similar scalar/result), the agent should obtain the value from API/explore outputs or from the CSV and return it; compute it itself when the platform output is tabular but the final number is not already summarized.

### Safety / v1 non-goals (writes)

- No delete of datasets or pipelines via MCP tools (for now).
- No edit of other users’ pipelines or datasets.
- No in-place mutation of existing shared pipelines when a change is required — always fork to a new name.

## Decisions (tool surface)

### Scope: curated (not full API wrap)

- Expose only tools needed for the agent loop and agreed post-run analyses.
- Do not mirror every HTTP endpoint or UI helper in v1.

### Implementation: wrap `SersflowClient`

- MCP tools call the existing Python client (`sersflow[client]`), not raw OpenAPI codegen.
- Benefits: shared polling, parsing, and error handling with `examples/` and scripts.

### Domains in v1 vs later

**In v1 (natural agent path + post-run explore):**

- `io` — upload / resolve files
- `datasets` — create, list, get (no delete via MCP)
- `sessions` — create/bind working context as needed
- `pipelines` / pipeline run — list, reuse, create new named pipelines (no in-place edit/delete of existing)
- `fitting` — read-only catalog / enough to choose fit models when building pipelines
- `analysis` — start runs, wait/status, export CSV / observation tables
- `explore` — post-run procedures including at least:
  - correlation (pairwise and/or correlation matrix)
  - VIF
  - PCA / sparse PCA (feature-table)
  - matrix PCA / sPCA (spectrum-matrix path)
  - related matrix / explore jobs needed for those workflows

**Later / out of v1 unless needed:**

- `plot` and binary blobs (images, heavy `.npz`/plotly payloads) — prefer CSV/JSON summaries and file paths
- niche metrics helpers, refined FPCA, UI-only endpoints
- delete / mutate-other-user operations (blocked by product policy)

### Tool style: hybrid

- **Thin tools** for checkpointed control: list/create/reuse assets, start job, poll status, export CSV, call individual explore ops.
- **Optional recipe tools** for common end-to-end outcomes once autonomy increases (e.g. “correlation from named peaks after analysis”), without replacing thin tools.

## Decisions (auth, tenancy, deployment)

### Authentication

- **v1:** cookie login via existing `/auth/login` (MCP/client holds session cookie after login).
- **Future:** API keys will be added to the platform and supported by the MCP when available.
- **Not for MCP v1:** superuser act-as tools (do not let the agent switch into other users’ data scopes).

### Deployment

- **v1 / testing:** local-first — MCP talks to a local `sersflow-api` (typically `http://127.0.0.1:8000`).
- **Later:** remote multi-user deployments once auth and isolation are proven.

### Configuration

- **Secrets (env vars only):** API base URL and credentials (username/password; later API keys). Never put these in chat, git, or the TOML file.
- **Non-secrets (TOML):** timeouts, export defaults, poll intervals, feature flags, and other non-sensitive MCP settings.

### Never expose to the model / tool results

- Auth secrets, passwords, session cookies, `SERSFLOW_AUTH_SECRET`
- Raw DB paths / SQLite internals
- Other users’ sessions, datasets, pipelines, or runs
- Superuser act-as controls
- Prefer IDs + controlled export paths over dumping absolute upload/blob/artifact tree layouts

## Decisions (data and I/O)

### How spectra enter (all three)

- **Local paths** → MCP uploads via client when the user points at files/folders.
- **Upload flow** → explicit upload tools when staging files first.
- **Existing IDs** → accept `dataset_id` and/or `session_id` to skip re-ingest.
- Experiment type, analysis objective, and other context are tool/chat arguments, not spectrum payloads.

### Tool return shapes

- Default: **IDs + short JSON summaries** (counts, names, status, column lists, key scalars when already computed).
- Do **not** dump full matrices or entire CSVs into the model context.
- Read file contents only when **strictly required** (e.g. look up a specific value in an exported CSV to answer the objective).

### Large outputs

- Prefer returning a **filesystem path** to CSV/Parquet (or similar) plus IDs/metadata.
- **No automatic previews** of large tables; show a truncated preview only when the user **explicitly asks**.

### Export location

- Default export directory from non-secret **TOML** (workspace-relative recommended, e.g. under the project).
- Allow override via tool argument `output_path` when the user specifies a destination.

## Decisions (async / long-running jobs)

### Sync vs background

- **Sync (typical):** login, list/get metadata, create dataset/session, create/list pipelines, small metadata calls, export download once a run is complete, many feature-table explore calls that return quickly.
- **Async / jobs:** full-dataset analysis runs; matrix export / spectrum-matrix jobs; other heavy materialization (PCA on full matrices when job-backed).

### Agent pattern (Cursor-style)

- Match how Cursor agents usually work: **sequential tool calls** with a blocking **wait-with-timeout** as the default (`wait_for_job`), plus a thin **`get_job_status`** (poll) tool to resume after timeout or when checking progress.
- Do not rely on fire-and-forget without a clear next status step.

### Timeouts and errors

- Default timeouts / poll intervals live in **TOML** (non-secret).
- Failures return short structured info: `job_id`, `status`, `error` message — no stack traces.
- On **timeout**, the tool result must tell the user/agent how to continue, including a concrete next action, e.g. call `get_job_status` / `wait_for_job` again with the same `job_id` (and document that command clearly in the error payload/message).

## Decisions (safety and write permissions)

### Write model: create and reuse

- Allow **create** and **reuse** of datasets, sessions, and pipelines (and runs/exports as needed).
- **No delete** tools in MCP for now.
- **No in-place edit** of existing pipelines when a change is required — create a new named pipeline instead.
- Never edit or delete other users’ assets.

### Confirmation required

- **Destructive ops** (if ever exposed): require explicit user confirmation before executing.
- **Large uploads:** require confirmation when total upload size is **over 100 MB**.
- **Heavy fitting pipelines:** require confirmation when a pipeline includes fittings with **more than 6 components**.
- General checkpointing (propose → approve) still applies during testing; the above are hard gates even when autonomy increases.

### Rate limits / caps

- **No MCP-enforced rate limits or max concurrent jobs for now.**
- Large/expensive work is gated by the confirmation rules above (6b), not by separate quota machinery.

## Decisions (packaging and host)

### Language

- **Python** MCP wrapping `SersflowClient` (same repo/runtime as the API and client).

### Transport

- **v1:** **stdio** (local Cursor).
- **Later:** HTTP/SSE for remote multi-user deployments.

### Ship form

- **Bundled with the SERSFlow API** in this repository (not a separate repo): install/run alongside `sersflow-api` (package entrypoint / extra next to the API distribution).

### Target clients

- **Optimize for Cursor first** (docs, config examples, stdio).
- Keep stdio compatible with other hosts (e.g. Claude Desktop) where practical; custom/remote agents later with HTTP/SSE.

## Decisions (resources and prompts)

### Resources (v1)

- Ship **tools + a few read-only MCP resources**:
  - list / catalog of **saved pipelines** (names + short descriptions as available)
  - **OpenAPI summary / capability sheet** (what the bound API version exposes)
  - **link/path to export manifest** for completed analysis exports when available

### Prompts

- **MCP prompt templates deferred to v2** (workflow prompts can live in Cursor rules / this brief until then).

## Decisions (versioning and stability)

### Version pin

- Pin and document against **OpenAPI / client 0.1.x**.
- Expose versions in a **meta** tool (MCP version, expected OpenAPI/client version, server-reported version when available).

### Tool naming

- **Mirror HTTP:** MCP tool names follow the HTTP/API surface (routes/operations), accepting that renames on the API may rename tools.

### Breaking vs drift

- **Breaking API change:** fail with a **clear incompatible** error (versions + upgrade guidance).
- **Minor drift:** **warn** in tool/meta output when versions differ but calls may still work.

## Decisions (implementation clarifications)

### Confirmation gate

- Tools that hit a confirmation rule **refuse** unless the caller passes **`confirm=true`**.
- Typical flow: agent explains the risk → user approves in chat → agent retries the same tool with `confirm=true`.
- Applies to: destructive ops (if exposed), uploads **>100 MB**, fittings with **>6 components**.

### Auth at MCP connect

- Prefer cookie **login** when username/password (or future API key) are present in env.
- If credentials are absent and the server is running with **auth disabled**, proceed without login (local/dev).
- Do not use superuser act-as.

### API process lifecycle

- MCP may **start `sersflow-api` if it is not already reachable** (local testing convenience).
- If already running at the configured base URL, connect only — do not spawn a duplicate unnecessarily.

### Session vs library pipelines

- **Library pipelines:** create new / reuse; never in-place edit or delete via MCP.
- **Session working pipeline:** **allowed** to update (`sessions.update_pipeline`) while building or iterating in a session.

### v1 tool style

- **Thin tools only** for first ship (no multi-step recipe tools yet). Recipes remain a later/autonomy enhancement.

## Status

**Implemented (v1):** package `sersflow.mcp`, entrypoint `sersflow-mcp`, setup docs in [MCP_SETUP.md](MCP_SETUP.md).

## v1 MCP tools (HTTP-mirrored)

| Tool | Purpose |
|------|---------|
| `get_health` | API health |
| `get_mcp_meta` | Versions, auth mode, warnings, non-secret config |
| `post_io_upload` | Upload files/folder (`confirm` if >100MB) |
| `get_io_uploads` | List uploads |
| `post_datasets` / `get_datasets` / `get_datasets_by_id` / `get_datasets_spectrum_axes` | Datasets |
| `post_sessions` / `get_sessions` / `get_sessions_by_id` | Sessions |
| `put_sessions_pipeline` / `put_sessions_subset` | Session working pipeline/subset |
| `get_pipelines` / `get_pipelines_by_id` / `post_pipelines` | Library pipelines (no overwrite) |
| `get_fitting_models` | Fitting catalog |
| `post_analysis_runs` / `get_analysis_runs` / `get_analysis_runs_by_id` | Analysis runs |
| `get_analysis_jobs` / `post_analysis_jobs_wait` | Job poll / wait |
| `get_analysis_runs_export_manifest` / `get_analysis_runs_export` / `get_analysis_runs_observation` | Exports → file paths |
| `post_explore_correlation` / `post_explore_vif` / `post_explore_pca` | Feature-table explore (**compact summaries**, not full matrices) |
| `get_explore_runs_export` | PCA CSV export path |
| `post_explore_matrix_jobs` / `get_explore_matrix_jobs` / `post_explore_matrix_jobs_wait` / `get_explore_matrix_jobs_export` | Matrix jobs (validate args; fitting confirm when pipeline/session used) |
| `post_explore_fpca_discrete` | Spectrum-matrix PCA/sPCA (compact summary) |
| `read_tabular_file` | Explicit CSV/Parquet slice (allowlisted paths) |

## v1 MCP resources

| URI | Content |
|-----|---------|
| `sersflow://pipelines` | Saved pipeline catalog |
| `sersflow://openapi/summary` | Capability sheet |
| `sersflow://analysis/runs/{run_id}/export/manifest` | Manifest + local export paths |

## Open decisions (later)

- Exact checkpoint UX text (chat wording before `confirm=true`)
- v2 prompt templates and recipe tools

## Later sections (TBD)

- HTTP/SSE transport for remote agents
- API key auth when the platform adds it

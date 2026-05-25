# SERSFlow architecture (publication-oriented)

## Overview: what SERSFlow is

SERSFlow is a local-first software stack for **Surface-Enhanced Raman Spectroscopy (SERS)** workflows that combines:

- **Dataset ingest** from uploaded vendor/measurement files (single spectra, time series, or spatial maps).
- A **deterministic preprocessing pipeline** applied to spectra (noise removal, cosmic ray removal, baseline correction, crop, normalization, peak fitting, feature probes).
- **Batch feature extraction** over a full dataset to create a table suitable for multivariate statistics.
- An **exploration/modeling layer** that runs common statistical analyses (correlation, VIF, PCA / sparse PCA, clustering, FPCA) and writes results to reproducible artifacts.
- A **web UI** (legacy shell + embedded modern React workspaces) that drives the above via a FastAPI backend.

The project prioritizes:

- **Reproducibility** through explicit pipeline definitions, stable hashes, persisted run records, and exportable tables.
- **Separation of concerns** between (i) interactive preview and (ii) batch/full-dataset computation.
- **Interoperability** through CSV/Parquet export and explicit observation-table contracts.

---

## High-level system architecture

SERSFlow is organized as a **single Python service** (FastAPI) that:

1. Serves HTTP endpoints for data management, pipeline execution, analysis, and exploration.
2. Persists metadata and results to a local **SQLite database** (`sersflow.db` by default).
3. Stores uploaded raw files on disk (under `.sersflow_uploads/` by default).
4. Stores “large” computed outputs (matrices, PCA plots, JSON bundles) as **filesystem artifacts** under `.sersflow_artifacts/` (configurable).
5. Serves a web UI from `src/sersflow/api/web/` and static React bundles under `/static/...`.

### Layering (conceptual)

- **UI layer (browser)**: React workspaces for “Prepare” (pipeline & preview) and “Analyze” (exports & statistics).
- **API layer (FastAPI)**: routers that validate requests (Pydantic) and orchestrate backend services.
- **Service layer (Python)**: analysis runners, export builders, exploration/statistical routines.
- **Core layer (Python)**: pipeline engine and preprocessing step implementations (the computational contract).
- **Infrastructure layer (Python + filesystem + SQLite)**: persistence of datasets, sessions, pipeline library, analysis runs, explore runs, and artifact directories.

This separation is enforced explicitly in the codebase: **Python is the execution contract**, while TypeScript “step specs” are presentation-only (see `docs/PIPELINE_UI_AUTHORITY.md`).

---

## Repository organization

### Python package (`src/sersflow/`)

- `src/sersflow/api/`
  - `main.py`: FastAPI app assembly and `sersflow-api` entrypoint.
  - `routers/`: HTTP endpoints grouped by concern (datasets, pipeline, sessions, analysis, explore, IO, plotting).
  - `schemas/`: Pydantic request/response models for the API.
  - `services/`: higher-level operations invoked by routers (analysis runners, exports, exploration stats/plots, matrix exports).
  - `web/`: legacy HTML shell + built React assets (e.g., `preprocess-dist/`).
- `src/sersflow/core/`
  - `pipeline/`: pipeline engine, step registry, caching, hashing.
  - `preprocess/`: step implementations (baseline, noise, cosmic ray removal, crop, normalization, fitting).
  - `io/`: dataset file loaders and upload registry utilities.
  - `metrics/`: metric computation on spectra (used for quick checks and optimization sweeps).
  - `models/`: typed representations for loaded datasets (single spectrum, series, map).
- `src/sersflow/infra/`
  - `sqlite_db.py`: SQLite connection factory and DB location (`SERSFLOW_DB_PATH`).
  - `datasets_store.py`, `sessions_store.py`, `pipelines_store.py`: persistence for key objects.
  - `analysis_store.py`: analysis run + job tracking; storage of per-spectrum features JSON.
  - `explore_store.py`: exploration run tracking + matrix job tracking; artifacts root (`SERSFLOW_ARTIFACTS_DIR`).
  - `upload_labels_store.py`: label persistence for uploaded files.

### Frontend app (`frontend/`)

The React code is a Vite app whose build artifacts are served by the Python backend.

- `frontend/src/main.tsx`: mounts the React UI into `#preprocess-root`.
- `frontend/src/AppShell.tsx`: routes between two workspaces.
  - `PreprocessingWorkspace.tsx`: “Pipeline & preview” (interactive).
  - `AnalyzeWorkspace.tsx`: “Features & statistics” (batch + explore).
- `frontend/src/preprocess/`: UI components and helpers specific to pipeline editing, fitting editor, preview runner.
- `frontend/src/analyze/`: plotting utilities and API bindings for analysis/explore.
- `frontend/src/lib/`: HTTP helpers, UI persistence (localStorage), Plotly theme utilities.
- `frontend/src/legacy-wrappers/`: adapters that integrate existing legacy Plotly widgets / list widgets.

The React bundle is built into `src/sersflow/api/web/preprocess-dist/` and served from `/static/preprocess-dist/...` (see `README.md`).

---

## Backend entrypoints and HTTP surface

### FastAPI assembly

The server app is defined in `src/sersflow/api/main.py` and includes routers (see also `docs/API_ROUTERS.md`):

- **Meta** (`/health`, `/`, `/preprocess`, `/static/...`): health checks + web UI serving.
- **IO** (`/io/...`): upload/unload files and manage upload labels.
- **Datasets** (`/datasets/...`): dataset CRUD and spectrum metadata.
- **Sessions** (`/sessions/...`): sessions store the working pipeline and subset strategy used for interactive preview.
- **Pipeline** (`/pipeline/...`): stateless pipeline execution endpoints (run / sweep).
- **Pipelines** (`/pipelines/...`): persisted “pipeline library” entries (named reusable pipelines).
- **Fitting** (`/fitting/...`): fitting model catalog and fitting-related endpoints (used by the fitting UI).
- **Analysis** (`/analysis/...`): full-dataset feature extraction runs, run/job tracking, exports.
- **Explore** (`/explore/...`): multivariate statistics and modeling (correlation, VIF, PCA/SPCA, clustering, FPCA, spectrum-matrix jobs).

### Persistent state and storage locations

SERSFlow has three “persistence planes”:

1. **Raw uploads on disk**: uploaded files are stored under an uploads root (default `.sersflow_uploads/`, managed by `sersflow.core.io.upload_registry`).
2. **SQLite (`sersflow.db`)**: metadata and compact results:
   - datasets and spectrum references
   - sessions (subset strategy + pipeline JSON)
   - pipeline library entries
   - analysis runs + per-spectrum features (stored as JSON per spectrum per run)
   - explore runs and matrix job metadata
3. **Artifacts directory** (default `.sersflow_artifacts/`):
   - exploration bundles (e.g., `correlation.json`, `vif.json`, `pca.json`, clustering outputs, rendered plots)
   - spectrum matrices (`matrix.npz`) for spectrum-level PCA/FPCA workflows

The local storage paths are configurable:

- `SERSFLOW_DB_PATH`: overrides the SQLite file location (default `./sersflow.db`).
- `SERSFLOW_UPLOAD_DIR`: overrides the upload storage directory (default `./.sersflow_uploads`).
- `SERSFLOW_ARTIFACTS_DIR`: overrides the artifacts directory (default `./.sersflow_artifacts`).

---

## Core computational contract: the pipeline engine

### Pipeline model

A pipeline is an ordered list of steps, where each step has:

- **name**: selects a registered implementation (e.g., `baseline`, `crop`, `normalize`, `fitting`, `spectral_intensities`).
- **params**: step-specific parameter dictionary.
- **enabled** flag.
- optional **impl_version** (used for provenance and cache-safety).
- optional input routing (`input_from` = previous/initial/after_step and `after_step_id`) to support branching-like behaviors.

The engine executes a pipeline for each input spectrum and produces:

- a final \(x, y\) spectrum (`XY`)
- optionally a subset of **intermediate step outputs** (for interactive visualization)

### Determinism, hashing, and caching

The pipeline engine (`src/sersflow/core/pipeline/engine.py`) is designed so that step outputs are cacheable and reproducible:

- Each step execution uses a cache key that includes:
  - a **namespace** (session/job scoped)
  - spectrum_id
  - step index + name (so reordering is safe)
  - a hash of normalized parameters (including declared input routing)
  - a **rolling lineage hash** of upstream steps and raw input
- This prevents stale cache reuse when steps/params are changed.

Two execution modes are used:

- **Interactive (in-process)**: for subset previews and intermediate outputs, uses an in-process LRU cache.
- **Batch parallel (process pool)**: for full-dataset runs, uses `ProcessPoolExecutor` without shared cache (safe and scalable; avoids cross-process cache complexity).

### Step implementations

Step implementations live under `src/sersflow/core/preprocess/` and cover typical SERS preprocessing operations:

- noise smoothing (e.g., Savitzky–Golay)
- cosmic ray detection/removal
- baseline correction
- crop to wavenumber range
- normalization
- peak fitting / model-based decomposition
- feature probe extraction (e.g., spectral intensities; produces the feature table used downstream)

The authoritative definition of supported steps and their legal parameterization is in Python; the frontend mirrors it for UI forms only.

---

## Data model: datasets, sessions, and runs

### Datasets

A **dataset** is a named collection of spectrum references (`spectrum_id`, `relative_path`, `record_index`) stored in SQLite:

- A single uploaded file can expand into multiple spectra:
  - **single spectrum** file → one spectrum
  - **series** file → spectra with a time axis
  - **map** file → spectra with spatial \(x, y\) axes

During dataset creation the backend also populates per-spectrum axes and per-file grid metadata (see `src/sersflow/infra/datasets_store.py`):

- per spectrum (nullable): `axis_time_s`, `axis_map_x`, `axis_map_y`
- per file: `grid_nx`, `grid_ny`, and `kind ∈ {single, series, map}`

This metadata is crucial for downstream heatmaps and time series plots and is exportable as part of the observation table (below).

### Sessions (interactive workspace state)

A **session** binds:

- a dataset
- a current pipeline definition
- a subset strategy (often “random \(n\) with seed”) used for preview plots

Key design choice:

- **Session subsets are preview-only.** Batch runs (analysis and matrix jobs) intentionally operate on the **full dataset** to ensure reproducible cohort definitions for statistics.

### Analysis runs (batch feature extraction)

An **analysis run** (`/analysis/runs`) performs full-dataset feature extraction and persists results:

- input: dataset + pipeline (from a session or provided inline)
- cohort: always `SubsetStrategy(kind="all")` (full dataset)
- output:
  - run record (status, error, timestamps, hashes)
  - per-spectrum `features_json` stored in SQLite (`analysis_spectrum_rows`)
  - a remembered feature column list (`feature_columns_json`) for stable exports and UI defaults

Runs can execute synchronously or as an async background job (tracked in `analysis_jobs`).

### Explore runs (statistics/modeling)

Explore endpoints (`/explore/...`) are “L2” analyses that consume:

- an **analysis run** (feature table) for correlation/VIF/PCA/k-means, or
- a **matrix job** (spectrum matrix) for spectrum PCA/FPCA workflows

Explore results are stored primarily as artifact files (JSON + plots), with a lightweight DB record pointing to the artifact directory.

---

## Export contracts: “feature table” vs “observation table”

SERSFlow supports exporting tabular data for external analysis tools (R, Python, Excel, Origin, etc.).

### Feature export

The simplest export is the **feature table**:

- wide layout: one row per `spectrum_id`, columns = selected feature keys
- long layout: tidy rows `(run_id, spectrum_id, feature_key, value, kind)`

### Observation export (features + joins)

The more general export is the **observation table**, which can join:

- **features** from an analysis run
- **axes** (`axis_time_s`, `axis_map_x`, `axis_map_y`, `grid_nx`, `grid_ny`, `file_kind`)
- **metadata labels** derived from upload paths and/or user-edited labels (`meta_*` columns)

Exports are streamed (chunked) to support large datasets, and Parquet is available as an optional dependency (`pyarrow`) for wide tables.

These exports are built in `src/sersflow/api/services/observation_export.py` and exposed via `/analysis/runs/{run_id}/...`.

---

## Frontend architecture and user-facing functionality

### UI composition and embedding strategy

The backend serves a legacy HTML shell (`GET /`) and a dedicated preprocess page (`GET /preprocess`). The React app is mounted into `#preprocess-root` and can run:

- embedded inside the legacy tabbed shell, or
- standalone (its own minimal navigation rendered by `AppShell.tsx`)

React uses:

- `@tanstack/react-query` for API state management and caching.
- `react-router-dom` (hash router) for local navigation between workspaces.
- Plotly for interactive plotting (via wrappers that preserve compatibility with legacy code).

### Workspace 1: Pipeline & preview (interactive “Prepare”)

Implemented in `frontend/src/PreprocessingWorkspace.tsx`, this workspace provides:

- **Upload management** (via the legacy upload list component).
- **Dataset creation** from selected uploads (single file or multiple).
- **Session creation** and **subset sampling** for preview plots (random subsets, outlier-derived subsets).
- **Pipeline editing** using step templates and a parameter editor.
- **Preview plotting**:
  - raw or final spectra
  - intermediate “After: step” views (subset-only; guarded to avoid heavy runs)
  - optional ghost overlays and stacking for visual comparison
- **Pipeline library** interactions:
  - save pipeline to current session (“Save pipeline”)
  - save named pipelines to a shared library and reload/update them

This workspace is explicitly optimized for **fast iteration** and **interactive validation** of preprocessing choices on a subset.

### Workspace 2: Features & statistics (batch “Analyze”)

Implemented in `frontend/src/AnalyzeWorkspace.tsx`, this workspace provides:

- **Analysis run management**: create/delete feature extraction runs and monitor job status.
- **Exports**:
  - feature table export
  - observation table export with joins (labels/axes)
  - export bundle/manifest for reproducible bookkeeping
- **Multivariate statistics and modeling** (backed by `/explore/...`):
  - correlation (and associated artifact JSON)
  - variance inflation factors (VIF)
  - PCA / sparse PCA with diagnostic plots
  - k-means clustering on PCA scores
  - FPCA (discrete and FDA-backed variants, depending on server support)
  - spectrum-matrix export jobs + spectrum-level PCA/cluster
- **Plotting**:
  - scree plots, cumulative explained variance
  - scores scatter/pairplots, loadings visualizations, cluster diagnostics
  - parameter scatter plots based on selected observation columns

Key design choice (surfaced in the UI):

- **All statistical analyses assume full-dataset runs** produced by the analysis runner. This avoids the ambiguity of statistics computed on a preview subset.

---

## Typical end-to-end workflow (as implemented)

1. **Upload raw files** (`POST /io/upload`).
2. **Create a dataset** from one or more uploads (UI-driven via `/datasets/...`).
3. **Create a session** for that dataset (`POST /sessions`) and sample a preview subset (`POST /sessions/{id}/subset`).
4. **Design the preprocessing pipeline** in “Pipeline & preview”:
   - validate preprocessing by plotting raw/final and intermediate outputs on the subset
   - save the pipeline into the session (`PUT /sessions/{id}/pipeline`)
5. **Run full-dataset feature extraction** in “Features & statistics”:
   - create an analysis run (`POST /analysis/runs`, often async)
   - wait for `status=completed`
6. **Export** for external analysis or archiving:
   - wide/long feature export
   - wide/long observation export with axes/labels joins (optionally Parquet)
7. **Explore and model**:
   - correlation/VIF/PCA/clustering on scalar features
   - optionally export a spectrum matrix job and run spectrum PCA/FPCA workflows

This workflow maps cleanly to a publication narrative: preprocessing choices are validated interactively, then batch-executed for reproducible statistics and exports.

---

## Extension points (where new science/engineering fits)

### Add a new preprocessing step

Implement the step in Python (core contract) and then surface it in the UI:

- Add/register implementation under `src/sersflow/core/preprocess/` and step registry.
- Extend Pydantic models in `src/sersflow/api/schemas/pipeline.py` as needed.
- Add frontend presentation metadata in `frontend/src/preprocess/pipelineStepSpecs.ts` (labels/defaults/fields only).

The expected authority direction is documented in `docs/PIPELINE_UI_AUTHORITY.md`.

### Add a new exploration/statistics routine

Patterns established by `/explore`:

- validate preconditions (analysis run completed, numeric columns, shape checks)
- compute results (NumPy / SciPy / sklearn-style)
- write JSON outputs (and optional plots) to an artifact subdirectory
- create and finish an `explore_runs` record that references the artifact path

### Improve reproducibility

Reproducibility hooks already present:

- pipeline and subset hashes recorded on runs/jobs
- explicit manifests for exports and matrix artifacts
- stable IDs (`ds_*`, `arun_*`, `ajob_*`, `mjob_*`, `exp_*`) for provenance trails

Common publication-grade additions (easy to layer on) include: software version capture, parameter manifests for explore runs, and DOI-ready “evidence bundles” per figure/table.

---

## Summary of current functionalities (at a glance)

- **Data ingestion**
  - upload files + label extraction + label editing
  - dataset creation from uploads; supports single/series/map-derived spectra
- **Preprocessing**
  - pipeline definition (step list + params + input routing)
  - interactive preview plots with subset sampling and intermediates
  - stateless pipeline runs and bounded parameter sweeps
- **Batch analysis**
  - full-dataset feature extraction runs with async job tracking
  - persistent per-spectrum feature JSON storage
- **Exports**
  - wide/long feature table
  - wide/long observation table with metadata + axes joins
  - optional Parquet export for wide tables
- **Exploration / modeling**
  - correlation bundles, VIF
  - PCA / sparse PCA + rendered diagnostics
  - k-means clustering on feature PCA or spectrum PCA
  - spectrum matrix export jobs (`matrix.npz`) with provenance
  - FPCA (discrete; and FDA-based where enabled)


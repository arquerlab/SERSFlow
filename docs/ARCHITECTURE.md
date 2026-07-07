# SERSFlow architecture (publication-oriented)

## Overview: what SERSFlow is

SERSFlow is a local-first software stack for Surface-Enhanced Raman Spectroscopy (SERS) workflows. It combines:

- Dataset ingest from uploaded vendor/measurement files, including single spectra, time series, and spatial maps.
- Durable dataset storage through upload registries, content-addressed blobs, SQLite metadata, and reproducible dataset exports.
- A deterministic preprocessing pipeline for spectra: crop, grid alignment, smoothing, cosmic-ray removal, baseline handling, normalization, reference transforms, derivatives, fitting, spectral probes, integrations, and derived feature operations.
- Batch feature extraction over the full dataset to create stable feature and observation tables.
- An exploration/modeling layer for correlation, VIF, PCA, sparse PCA, clustering, spectrum matrices, and FPCA.
- A web UI, Python HTTP client, and publication-oriented examples that drive the same FastAPI backend.

The project prioritizes:

- Reproducibility through explicit pipeline definitions, stable hashes, persisted run/job records, durable blobs, and export manifests.
- A clear split between interactive preview and full-dataset computation.
- Interoperability through CSV/Parquet exports, observation-table contracts, and a programmatic Python client.
- Python-owned scientific behavior: TypeScript step specs are UI metadata only. See `docs/PIPELINE_UI_AUTHORITY.md`.

---

## High-level system architecture

SERSFlow is organized around one local FastAPI service that:

1. Serves HTTP endpoints for data management, plotting, pipeline execution, analysis, and exploration.
2. Persists metadata and compact results to SQLite (`sersflow.db` by default).
3. Stores uploaded raw files under `.sersflow_uploads/`.
4. Stores durable dataset blobs under `.sersflow_data/blobs/`.
5. Stores large computed outputs under `.sersflow_artifacts/`.
6. Serves the browser UI from `src/sersflow/api/web/`, including the built React bundle under `/static/preprocess-dist/...`.

### Conceptual layers

- Browser UI: React workspaces for "Pipeline & preview" and "Features & statistics", embedded in the legacy shell or run standalone.
- Python client: optional `httpx` wrapper around the same HTTP API for scripts and publication workflows.
- API layer: FastAPI routers and Pydantic schemas grouped by concern.
- Service layer: analysis runners, export builders, reference hydration, plotting, matrix jobs, and exploration routines.
- Core layer: loaders, spectrum models, labels, metrics, plotting helpers, the pipeline engine, and step implementations.
- Infrastructure layer: SQLite stores plus filesystem roots for uploads, durable blobs, and generated artifacts.

---

## Repository organization

### Python package (`src/sersflow/`)

- `src/sersflow/api/`
  - `main.py`: FastAPI app assembly and `sersflow-api` entrypoint.
  - `routers/`: HTTP surface for meta, IO, plotting, datasets, pipeline runs, pipeline library, metrics, sessions, fitting, analysis, and explore.
  - `schemas/`: Pydantic request/response models.
  - `services/`: higher-level operations used by routers, including analysis execution, dataset/observation exports, reference runtime, plotting, matrix export jobs, and explore stats/plots.
  - `web/`: legacy HTML shell and built frontend assets.
- `src/sersflow/core/`
  - `io/`: TXT/WDF loading, upload registry, file-to-dataset expansion, and wavenumber-range helpers.
  - `models/`: typed dataset representations for single spectra, series, and maps.
  - `pipeline/`: pipeline engine, step registry, hashing, cache keys, and step numbering.
  - `preprocess/`: baseline, crop, cosmic-ray removal, fitting, fitting specs/models, normalization, noise, and related step helpers.
  - `metrics/`: feature extraction utilities for fitting features, intensities, integrations, peaks, operations, and metric computation.
  - `labels/`: automatic label extraction and normalization from upload paths/filenames.
  - `plot/`: backend plot serialization and raw-spectrum plotting service.
- `src/sersflow/infra/`
  - `sqlite_db.py`: SQLite connection factory and `SERSFLOW_DB_PATH`.
  - `blob_store.py`: content-addressed raw-file blob storage under `SERSFLOW_DATA_DIR`.
  - `datasets_store.py`: dataset, spectrum, blob-reference, axis, and grid metadata persistence.
  - `sessions_store.py`, `pipelines_store.py`: interactive session and named pipeline library persistence.
  - `analysis_store.py`: analysis run/job records and per-spectrum feature JSON.
  - `explore_store.py`: explore run records, matrix job records, and artifact roots.
  - `upload_labels_store.py`: user-edited upload label overrides.
- `src/sersflow/client/`
  - `client.py`: synchronous `SersflowClient`.
  - `resources/`: API-specific resource wrappers for meta, IO, datasets, sessions, pipeline, pipelines, metrics, plot, fitting, analysis, explore, and raw streaming.
  - `polling.py`: shared polling helpers for asynchronous jobs.

### Frontend app (`frontend/`)

The frontend is a Vite/React app whose production build is served by the Python backend.

- `frontend/src/main.tsx`: mounts React into `#preprocess-root`.
- `frontend/src/AppShell.tsx`: routes between "Pipeline & preview" and "Features & statistics".
- `frontend/src/PreprocessingWorkspace.tsx`: upload/dataset/session setup, subset previews, pipeline editing, pipeline library, reference transforms, fitting, spectral probes, integrations, and feature operations.
- `frontend/src/AnalyzeWorkspace.tsx`: analysis jobs, exports, observation columns, heatmaps, parameter scatter, correlation/VIF, PCA/SPCA, clustering, spectrum matrices, FPCA, and spectrum overlays.
- `frontend/src/preprocess/`: pipeline editors, API bindings, plotting controller, reference-transform helpers, feature-operation helpers, labels, and upload/range utilities.
- `frontend/src/analyze/`: analysis/explore API bindings and plotting helpers.
- `frontend/src/lib/`: HTTP helpers, Plotly theming, and UI persistence.
- `frontend/src/legacy-wrappers/`: adapters for legacy Plotly and spectrum-list widgets.

The built bundle lands in `src/sersflow/api/web/preprocess-dist/` and is served from `/static/preprocess-dist/...`.

### Examples and publication scripts

`examples/` contains programmatic workflows that exercise the public API/client and local outputs for figures, heatmaps, PCA/SPCA analyses, multipanel plots, complementarity analyses, and SI grids. These examples are not part of the service runtime, but they document the publication-facing workflow.

---

## Backend entrypoints and HTTP surface

The app in `src/sersflow/api/main.py` includes routers for:

- Meta (`/health`, `/`, `/preprocess`, `/static/...`): health checks and UI serving.
- IO (`/io/...`): upload/unload files and upload label operations.
- Plot (`/plot/...`): backend-generated plot data for raw/uploaded spectra.
- Datasets (`/datasets/...`): dataset creation, listing, deletion, export/import, and spectrum metadata.
- Pipeline (`/pipeline/...`): stateless pipeline execution and sweep-style endpoints.
- Pipelines (`/pipelines/...`): reusable named pipeline library.
- Metrics (`/metrics/...`): quick metric computation and related helpers.
- Sessions (`/sessions/...`): working pipeline and subset strategy for interactive preview.
- Fitting (`/fitting/...`): fitting catalog and fitting-related UI support.
- Analysis (`/analysis/...`): full-dataset feature extraction runs, async job tracking, exports, and manifests.
- Explore (`/explore/...`): feature-level and spectrum-level statistical workflows.

See `docs/API_ROUTERS.md` for the endpoint-oriented view.

---

## Persistent state and storage

SERSFlow uses four local persistence planes:

1. Upload registry (`.sersflow_uploads/` by default): files as uploaded by the user, including active/unloaded registry state.
2. Durable data blobs (`.sersflow_data/blobs/` by default): content-addressed copies used by datasets so later analysis is not only path-bound to the original upload location.
3. SQLite (`sersflow.db` by default): metadata, labels, sessions, pipelines, run/job records, spectrum refs, axes, grid metadata, and compact feature JSON.
4. Artifacts (`.sersflow_artifacts/` by default): large generated outputs such as `matrix.npz`, explore JSON bundles, rendered PCA/cluster/FPCA plots, and other model diagnostics.

Configurable roots:

- `SERSFLOW_DB_PATH`: SQLite file location, default `./sersflow.db`.
- `SERSFLOW_UPLOAD_DIR`: upload directory, default `./.sersflow_uploads`.
- `SERSFLOW_DATA_DIR`: durable blob/data directory, default `./.sersflow_data`.
- `SERSFLOW_ARTIFACTS_DIR`: generated artifacts directory, default `./.sersflow_artifacts`.

Dataset records store both user-facing paths and durable blob references (`blob_id`, `blob_relative_path`, `original_relative_path`) when available. Dataset export/import can package manifests, blob payloads, file metadata, labels, and spectrum refs for reproducible transfer.

---

## Core computational contract: pipeline engine

### Pipeline model

A pipeline is an ordered list of steps. Each step has:

- `name`: selects a registered Python implementation.
- `params`: step-specific parameters.
- `enabled`: controls execution.
- optional `impl_version`: provenance and cache-safety.
- optional input routing (`input_from`, `after_step_id`) for using the initial input, previous output, or a named prior step.

The engine executes a pipeline per input spectrum and returns:

- a final `XY` spectrum;
- optional intermediate outputs for selected steps, used by interactive preview plots.

### Determinism, hashing, and caching

`src/sersflow/core/pipeline/engine.py` uses cache keys that include:

- a namespace scoped to the session/job;
- `spectrum_id`;
- step index and name;
- normalized parameters, including input routing;
- a rolling lineage hash of upstream steps and raw input.

This prevents stale cache reuse when steps are reordered, parameters change, or an upstream transform changes.

Execution modes:

- Interactive in-process execution uses an LRU cache for subset previews and intermediate outputs.
- Batch execution uses `ProcessPoolExecutor` for full-dataset runs and avoids shared process cache complexity.

### Registered steps

The Python step registry currently covers:

- `crop`: limit spectra to a wavenumber range.
- `align_resample`: interpolate spectra onto a shared grid for matrix workflows.
- `normalize`: max/min/mean/median/vector and point-based normalization modes.
- `noise_savgol`: Savitzky-Golay smoothing/derivatives.
- `cosmic_ray_removal`: cosmic-ray detection and replacement.
- `baseline`: baseline-corrected output.
- `baseline_curve`: baseline-only output for routing/visualization.
- `fitting`: model-based peak/background fitting.
- `spectral_intensities`: no-op transform that declares intensity probes for feature extraction.
- `spectral_integrations`: no-op transform that declares integration windows for feature extraction.
- `feature_operations`: no-op transform that declares formulas over previously extracted features.
- `spectrum_derivative`: derivative spectra over the current x-grid.
- `reference_transform`: subtract or divide by a selected reference spectrum.

The authoritative behavior and validation live in Python. Frontend step specs only provide labels, defaults, field controls, and presentation metadata.

---

## Data model: datasets, sessions, and runs

### Datasets

A dataset is a named collection of `SpectrumRef` rows stored in SQLite. A single source file can expand into:

- one spectrum for a single-spectrum file;
- many spectra with `axis_time_s` for a series file;
- many spectra with `axis_map_x` and `axis_map_y` for a spatial map.

Per-file metadata records `grid_nx`, `grid_ny`, and `kind` (`single`, `series`, `map`). This metadata drives heatmaps, time-series plots, observation-table joins, and publication scripts.

Automatic labels are extracted from upload paths/filenames by `src/sersflow/core/labels/` (for example sample, compound, gas, pH, current density, potential, and laser). User edits are persisted by `upload_labels_store.py` and exported as `meta_*` observation columns.

### Sessions

A session binds:

- one dataset;
- the current pipeline definition;
- a subset strategy used for interactive preview plots.

Session subsets are preview-only. Batch analysis runs and matrix jobs intentionally operate on the full dataset, with reference spectra excluded when the pipeline marks them as references.

### Analysis runs

An analysis run (`/analysis/runs`) performs full-dataset feature extraction and persists:

- a run record with status, timestamps, errors, pipeline hashes, and feature columns;
- optional async job records in `analysis_jobs`;
- per-spectrum `features_json` in `analysis_spectrum_rows`.

The analysis runner applies the saved/provided pipeline, hydrates `reference_transform` parameters, excludes selected reference spectra from the analysis cohort, and extracts features from fitting components, spectral intensities, spectral integrations, and feature operations.

### Matrix jobs and explore runs

Matrix jobs produce spectrum matrices for spectrum-level workflows:

- input: dataset plus pipeline;
- output: `matrix.npz` and provenance metadata under `.sersflow_artifacts/matrix/<mjob_id>/`;
- requirement: spectra must end on a consistent x-grid, typically through `align_resample`.

Explore runs consume either:

- an analysis run feature table for correlation, VIF, PCA/SPCA, and clustering; or
- a matrix job for spectrum PCA, spectrum clustering, and FPCA.

Explore results are stored primarily as artifact files (JSON plus plots), with lightweight SQLite records pointing to the artifact directory.

---

## Export contracts

SERSFlow exports data for external analysis tools such as Python, R, Excel, Origin, and publication scripts.

### Feature table

Feature exports are built from one analysis run:

- wide layout: one row per `spectrum_id`, columns are selected feature keys;
- long layout: tidy rows `(run_id, spectrum_id, feature_key, value, kind)`.

### Observation table

Observation exports join:

- features from an analysis run;
- axes and grid metadata (`axis_time_s`, `axis_map_x`, `axis_map_y`, `grid_nx`, `grid_ny`, `file_kind`);
- automatic and user-edited labels as `meta_*` columns.

Exports are streamed to support large datasets. Wide Parquet output is available when `pyarrow` is installed. Export manifests capture enough context to reproduce table generation.

---

## Frontend architecture and user-facing workflow

### UI composition

The backend serves both a legacy HTML shell (`GET /`) and a dedicated preprocess page (`GET /preprocess`). The React app mounts into `#preprocess-root` and can run embedded in the legacy shell or standalone with navigation from `AppShell.tsx`.

React uses:

- `react-router-dom` for local workspace routing;
- `@tanstack/react-query` for API state and caching;
- Plotly wrappers for interactive visualization while preserving legacy integrations.

### Pipeline & preview

Implemented in `frontend/src/PreprocessingWorkspace.tsx`, this workspace is optimized for fast iteration on a subset:

- upload management and label editing;
- dataset and session creation;
- subset sampling, including random and outlier-derived previews;
- pipeline editing with Python-backed step semantics and UI-only step specs;
- fitting, reference transforms, spectral intensity probes, spectral integrations, and feature operations;
- raw/final/intermediate preview plots with optional overlays/stacking;
- saving the working pipeline to the session and to the reusable pipeline library.

### Features & statistics

Implemented in `frontend/src/AnalyzeWorkspace.tsx`, this workspace is optimized for full-dataset outputs:

- analysis run creation, deletion, and async job monitoring;
- feature-table and observation-table exports;
- export bundles/manifests for reproducible bookkeeping;
- observation-column inspection and metadata-driven plotting;
- heatmaps, parameter scatter plots, and spectrum overlays;
- correlation, VIF, PCA, sparse PCA, k-means clustering, spectrum matrices, spectrum PCA/cluster, and FPCA.

The UI surfaces the central workflow rule: preview subsets are for selecting preprocessing choices; statistics and exports are based on full-dataset runs.

---

## Python HTTP client

`src/sersflow/client/` provides a synchronous `SersflowClient` for notebooks, scripts, and examples:

```python
from sersflow.client import SersflowClient

with SersflowClient("http://127.0.0.1:8000") as client:
    client.meta.health()
```

The client mirrors backend concerns through resource objects (`client.io`, `client.datasets`, `client.sessions`, `client.pipeline`, `client.pipelines`, `client.metrics`, `client.plot`, `client.fitting`, `client.analysis`, `client.explore`, and `client.raw`) and centralizes polling for async jobs.

---

## Typical end-to-end workflow

1. Upload raw files through `/io/upload` or the UI.
2. Review/edit extracted upload labels.
3. Create a dataset from selected uploads; the backend records spectrum refs, axes, grid metadata, labels, and durable blob refs.
4. Create a session and choose a preview subset.
5. Design the preprocessing pipeline in "Pipeline & preview".
6. Save the pipeline to the session and optionally to the pipeline library.
7. Run full-dataset feature extraction in "Features & statistics".
8. Export feature/observation tables or an export bundle.
9. Run exploration/modeling: correlation, VIF, PCA/SPCA, clustering, matrix jobs, spectrum PCA, and FPCA.
10. Use examples/client scripts to generate publication figures from the exported tables and artifacts.

This maps to the publication narrative: validate preprocessing interactively, execute full-dataset analysis reproducibly, then generate explicit tables/artifacts for figures and external review.

---

## Extension points

### Add a preprocessing or feature step

- Implement/register the Python step in `src/sersflow/core/pipeline/steps.py` and supporting modules under `core/preprocess/` or `core/metrics/`.
- Extend Pydantic schemas in `src/sersflow/api/schemas/` when the API contract changes.
- Add UI presentation metadata in `frontend/src/preprocess/pipelineStepSpecs.ts`.
- Keep Python as the source of truth for validation and execution.

### Add an exploration/statistics routine

Follow the `/explore` pattern:

- validate completed input runs/jobs and numeric shape requirements;
- compute the result with NumPy/SciPy/sklearn-style code;
- write JSON outputs and optional plots to an artifact subdirectory;
- create and finish an `explore_runs` record pointing to the artifact path;
- expose a thin router endpoint and optional client resource method.

### Improve reproducibility

Existing hooks include:

- pipeline, subset, and input hashes;
- stable IDs (`ds_*`, `arun_*`, `ajob_*`, `mjob_*`, `exp_*`);
- durable blob refs for dataset source files;
- export and matrix manifests;
- artifact directories for model outputs and diagnostic plots.

Future publication-grade additions can layer on software version capture, richer explore manifests, and figure/table evidence bundles.

---

## Current functionality at a glance

- Data ingestion: uploads, durable blobs, automatic labels, label overrides, dataset creation, dataset export/import.
- Preprocessing: explicit pipelines, input routing, subset previews, intermediate plots, fitting, reference transforms, alignment/resampling, feature declarations, and sweeps.
- Batch analysis: full-dataset feature extraction, async jobs, per-spectrum feature JSON, feature operations, and stable feature columns.
- Exports: wide/long feature tables, wide/long observation tables, metadata/axis joins, optional Parquet, and manifests.
- Plotting: backend raw plots, frontend Plotly workspaces, heatmaps, scatter plots, PCA/cluster diagnostics, spectrum overlays, and publication scripts.
- Exploration/modeling: correlation, VIF, PCA, sparse PCA, k-means, spectrum matrices, spectrum PCA/cluster, and FPCA.
- Automation: Python HTTP client resources and job polling for notebooks, scripts, and figure-generation workflows.


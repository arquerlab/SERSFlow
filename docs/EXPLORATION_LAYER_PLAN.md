# Exploration & modeling layer (L2) — plan

This document extends the **L1** foundation (datasets, sessions, pipelines, `spectral_intensities` analysis runs, SQLite + export) with a clear **L2** layer for exploration, multivariate analysis, and plotting. It incorporates **CSV export for external tools**, **functional PCA (FPCA)**, and a **reevaluation** of structure with concrete improvements.

---

## 1. Layering (Option A — recap)

| Layer | Responsibility |
|--------|------------------|
| **L1 — Acquisition & features** | Datasets, sessions, pipelines, analysis runs, tabular features per spectrum, provenance hashes, retention. |
| **L2 — Exploration & modeling** | Merged observation tables, statistics (correlation + FDR, VIF, regression, clustering), **PCA / sparse PCA / functional PCA**, declarative plots, **evidence bundles** (reproducible inputs + outputs). |

L2 **consumes** L1 exports; it does not replace the pipeline or analysis-run store.

---

## 2. CSV export for external analysis (first-class)

**Goal:** Users must be able to take data **out** of SERSFlow and analyze or replot in R, Python, Origin, Excel, etc., without friction.

### 2.1 Requirements

- **Wide CSV** remains the default interchange: one row per `spectrum_id`, columns = features + metadata + axes + optional uncertainty columns.
- **Explicit contract** in API docs: UTF-8, comma-separated, header row, `NaN`/empty for missing numeric values, stable column order from `feature_columns_json` (and extended manifest when metadata is joined).
- **Join options** on export (or companion endpoints):
  - `export_features` — current behavior (analysis run only).
  - `export_observation_table` — features **plus** merged columns: experimental metadata (labels), **spatial/temporal axes** (`time_s`, `map_x`, `map_y`, grid shape), and uncertainty columns when present.
- **Long-format CSV** optional for tools that prefer tidy data: `(spectrum_id, key, value, kind)` with `kind ∈ {feature, meta, axis, uncertainty}`.
- **Filenames & versioning:** suggest `dataset_{id}_run_{run_id}_wide.csv` and include a one-line **comment header** or sidecar `manifest.json` with `pipeline_hash`, `subset_hash`, `created_at`, and **column glossary** (recommended for reproducibility in external scripts).

### 2.2 Improvements to existing code (L1)

- Extend `GET /analysis/runs/{run_id}/export` (or add `GET /datasets/{dataset_id}/observation-export`) with query params:
  - `join=metadata,axes` (when spectrum-level metadata exists in DB).
  - `format=csv` (default) | future `parquet` for large tables.
- Persist or compute **per-spectrum axes** (time, map coordinates, grid dimensions) during dataset ingest or lazy enrichment — see §5.

---

## 3. Functional PCA (FPCA)

**Motivation:** Scalar peaks (`I_*`) capture selected bands; **FPCA** uses **entire curves** (after crop/normalize/etc.) as functional data, to find dominant modes of **shape** variation across spectra.

### 3.1 Inputs

- **Aligned abscissa:** All spectra must share the same **Raman shift grid** `x` (cm⁻¹) after the chosen pipeline step (e.g. after crop + normalization). If grids differ slightly, define a **target grid** (linear interpolation or warping — document choice).
- **Observation matrix:** `n_spectra × n_wavenumbers` of **y** values (or residuals), optionally **one matrix per analysis job** referencing `pipeline_hash` + `up_to_step` or step id.

### 3.2 Method (pragmatic v1)

- **Discretized FPCA:** Treat each spectrum as a high-dimensional vector on a fixed grid; perform PCA on centered data → **harmonics** resemble functional PCs when the grid is dense and smoothness is implicit.
- **Refinement (optional v2):** Use a proper **functional data** library (e.g. basis splines + FPCA, or `scikit-fda`) for smoothing and **mean curve + principal components** in function space; exposes **FPC scores** per spectrum for downstream regression/clustering.

### 3.3 Outputs (evidence bundle)

- **Mean spectrum** and **PC loading curves** (or discrete loadings plotted as curves).
- **Score table:** `spectrum_id`, `FPC1`, `FPC2`, …
- **Scree plot** data (eigenvalues / variance explained).
- **Provenance:** `x` grid vector hash, pipeline step snapshot, alignment method.

### 3.4 Scope boundary

- FPCA is an **L2** (or **special analysis run kind**) job that **reads** pipeline outputs or a **materialized spectrum matrix** export — not a replacement for `spectral_intensities` batch runs.

---

## 4. L2 evidence bundles (structure)

Each exploratory or modeling run produces:

```
exploration_id/
  manifest.json          # inputs, filters, software versions
  inputs/                # resolved table refs + column lists
  results/
    stats/               # correlation+q, VIF, tests
    projections/       # PCA/sPCA/FPCA scores & loadings
    clustering/          # labels, diagnostics
  plots/                 # specs + rendered assets (optional)
```

Storage: SQLite metadata table + filesystem under configurable `SERSFLOW_ARTIFACTS_DIR` (mirrors analysis-run pattern).

---

## 5. Spatial & temporal metadata (must-have for heatmaps / time series)

**Gap:** `SpectrumRef` today is minimal; maps/time series need **per-row** `time_s`, `map_x`, `map_y`, and **grid shape** for heatmaps.

### 5.1 Efficient storage (revised)

Avoid repeating **grid dimensions** on every spectrum row: they are **constant per source file** for a given map.

- **`dataset_file_meta`** (or equivalent): one row per `(dataset_id, relative_path)` with `grid_nx`, `grid_ny`, `kind` (`single` | `series` | `map`).
- **`dataset_spectra`**: nullable REAL columns **`axis_time_s`**, **`axis_map_x`**, **`axis_map_y`** — only the values that **vary per spectrum**. Join to `dataset_file_meta` at export/API time to expose full context.

Populate from loaders at **dataset creation** (one file read per distinct `relative_path`); optional **lazy backfill** for existing databases.

### 5.2 Export

CSV export **JOIN**s file meta so external scripts receive `grid_nx`/`grid_ny` without redundant storage per row.

---

## 6. Uncertainty, grouping plots, and advanced stats (recap)

- **Uncertainty:** Feature columns `estimate` + `_se` / CI; boxplots & error bars consume these or grouped aggregates.
- **Multiple testing:** Store **p** and **FDR q** matrices + parameters.
- **Collinearity:** VIF (or condition index) table before regression.
- **Clustering:** Store labels + method/distance in manifest.
- **Plots:** Pairplots, residual plots, scree, loadings/scores — as **declarative specs** + optional PNG/SVG export.

---

## 7. Reevaluation: structure and improvements

### 7.1 What works well

- Clear **L1** boundary (pipelines + analysis runs + SQLite).
- **Wide/long CSV** already suits sklearn/R **samples × features**.
- **Option A** avoids a single overloaded UI: **session/feature** vs **explore/model**.

### 7.2 Risks and mitigations

| Risk | Mitigation |
|------|------------|
| Column explosion (many peaks + metadata) | Column manifest with `role` tags; UI column picker; optional Parquet. |
| Duplicate computation (PCA on full spectra vs features) | Single **materialize matrix** job with hashed inputs; FPCA references that artifact. |
| External CSV misuse (wrong join) | Sidecar manifest + documented stable column names. |
| FPCA cost on huge maps | Subsample, ROI crop step, or max spectra per job. |

### 7.3 Proposed structural improvements

1. **Single “observation table” contract** — documented schema: `spectrum_id`, features, `meta_*`, `axis_*`, `u_*` (uncertainty). All L2 tools read this shape.
2. **Export service** — one module that builds wide/long CSV from `(analysis_run_id | pipeline matrix job) + dataset_id + join flags`.
3. **Analysis job kinds** — extend or mirror: `batch_features` | `matrix_export` | `fpca` | `explore_bundle` (keeps SQLite rows interpretable).
4. **Frontend (future):** two areas under one app — **Data & pipeline** vs **Explore & model**, sharing the same exported table picker.
5. **Dependencies:** add only when needed: `statsmodels` / `scikit-learn` already common; **FPCA refinement** may add `scikit-fda` or similar — gate behind optional extra `[explore]` in `pyproject.toml`.

### 7.5 L2 and matrix artifacts (efficiency)

- **`explore_runs` SQLite rows stay slim:** ids, kind, status, small `input_ref_json`, path to **artifact folder** — not full correlation matrices or PCA loadings in the DB.
- **Spectrum matrix job:** persist **`matrix.npz`** with `Y` in **float32**, `x` (wavenumbers), `spectrum_ids`; sidecar JSON for hashes and pipeline provenance. Use **memmap** only if files exceed available RAM.
- **L1 `features_json`:** keep; do not add a redundant materialized wide table unless profiling requires it — **stream** wide CSV from JSON + manifest keys.

### 7.4 Phasing

| Phase | Deliverables |
|-------|----------------|
| **P0** | Documented CSV export + manifest; join metadata when available; observation table endpoint spec. |
| **P1** | Spectrum axes in DB + export; L2 bundle skeleton + correlation + PCA on numeric wide table. |
| **P2** | FPCA (discretized first), scree/loadings plots, clustering, FDR/VIF. |
| **P3** | Refined FPCA (basis/smoothing), interactive plot specs, optional Parquet. |

---

## 8. Summary

- **CSV for external tools** is a **first-class** deliverable: wide/long, joins, manifests, and stable headers — extend current analysis export rather than bolting on an ad hoc download.
- **Functional PCA** belongs in **L2** (or a dedicated matrix+FPCA job), with aligned wavenumber grids, discrete PCA first, optional functional refinement, and bundle outputs (mean curve, loadings, scores, scree).
- **Reevaluation:** strengthen the **observation-table contract**, **spectrum axes** in storage, a unified **export service**, explicit **job kinds**, and phased delivery to avoid scope creep.

This plan is intended to live beside implementation; update it when P0–P3 milestones ship.

### Milestone (aligned with current app)

- **Full-dataset cohort:** Batch feature extraction and matrix `Y` jobs use the full dataset; the session subset applies only to **Prepare** preview plots.
- **Observation table:** Wide export joins upload labels (`meta_*`) and per-spectrum axes; `GET /analysis/runs/{run_id}/observation-schema` lists selectable columns; `GET .../observation-columns` returns JSON slices for plotting.
- **Explore:** Correlation / PCA / sparse PCA / VIF / k-means on scalar features use merged observation rows when columns include metadata. Discrete spectrum PCA and sparse PCA share the matrix-job `Y` path; **`POST /explore/spectrum-cluster`** runs k-means on PCA scores of centered `Y`.
- **UI:** Secondary navigation (Pipeline & preview vs Features & statistics), observation-wide download highlighted as the primary export, and parameter-vs-parameter scatter plots for numeric merged columns.

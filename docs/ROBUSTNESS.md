# Robustness study (multi-factor analyst-choice analysis)

A single-parameter scan ("Test peak model") shows how one choice moves a fit. A **robustness study** varies several
analyst choices together (background, fit window, line-shape mix, FWHM constraint, satellites, an upstream baseline
method, ...), refits every combination on every selected spectrum and answers:

* which choice (or interaction of choices) moves the result most - ANOVA variance shares per factor / interaction;
* does a trend (e.g. a fraction against current density, time, pH, any label) survive reasonable choices;
* how large is the spread caused by choices compared with counting noise (noise Monte Carlo on a reference cell);
* where do fits land in different minima (multi-start flags a cell as `degenerate`).

It is technique-agnostic: factors patch any pipeline step, responses are read from the fit, and the x variable is any
spectrum label. Code: `core/robustness/` (design, patches, responses, cell_fit, anova, study, presets) and
`api/services/robustness_runner.py` (job).

## Workflow

1. `post_analysis_robustness_plan` (REST `POST /analysis/runs/{id}/robustness-plan`): dry run. With `preset` it
   proposes factors / responses from the run's fitting step; it always returns the cost estimate. Edit the spec.
2. `post_analysis_robustness_jobs` (`POST /analysis/runs/{id}/robustness-jobs`): run it. Poll with the fit-curve job
   tools (`content: "robustness"`).
3. `get_analysis_robustness_summary` (`GET /analysis/robustness-jobs/{job}/summary`) or download the zip.
4. `post_analysis_robustness_reanalyse` (`POST .../reanalyse`): other responses / filter / interaction order /
   x label from the **stored fits**, no refitting.
5. `post_analysis_robustness_resume` (`POST .../resume`): continue a failed or interrupted job.

## Study spec

```json
{
  "fitting_step_index": 0,
  "preset": "fit_model_choices",
  "factors": [{"name": "background", "levels": [{"name": "shirley", "patches": []},
                {"name": "linear", "patches": [{"op": "swap_component_type",
                  "select": {"role": "background"}, "new_type": "linear_bg"}]}]}],
  "responses": [{"name": "Co3_frac", "kind": "group_fraction", "numerator": ["peak_1"],
                 "denominator": ["peak_1", "peak_2", "peak_3"]}],
  "x_label": "current_density_A_cm2",
  "n_starts": 5, "seed": 0,
  "filter": {"mode": "delta_bic_common", "threshold": 10, "exclude_degenerate": false},
  "noise": {"n_replicates": 50},
  "max_cells": null, "interaction_order": "all", "workers": 8
}
```

Explicit `factors` / `responses` win over the preset's. **The first level of every factor is the nominal setting.**
Level names must be unique within a factor; factor names unique in the study.

### Patches (a level is a list of patches)

`target` selects the pipeline step: absent / `"fit"` = the fitting step under study; `{"step_id": ..}`,
`{"step_index": N}` or `{"step_name": "baseline", "occurrence": 1}` = an UPSTREAM step.

| op | applies to | fields |
|---|---|---|
| `set_step_param` | any step | `key` (dotted for nested), `value` |
| `set_step_enabled` | upstream steps | `enabled` |
| `replace_step_params` | any step | `params` (e.g. a full recipe-generated set) |
| `set_component_param` | fit | `select`, `key`, `value?`, `vary?`, `lower?`, `upper?`, `lower_rel?`, `upper_rel?` |
| `swap_component_type` | fit | `select`, `new_type`, `degree?`, `p0?` (defaults from the component specs) |
| `drop_components` | fit | `select` (links touching them are removed) |
| `tie_param` | fit | `select`, `key`, `mode?`, `driver?` (links the dependent ones to the first / `driver`) |
| `untie_param` | fit | `key`, `select?` (removes links, frees the parameter) |

`select`: `{"component_ids": [..]}`, `{"component_type": "gl" | [..]}`, `{"role": "peaks" | "background" | "all"}`
(keys are ANDed). A selector that matches nothing is an error, not a silent no-op.

### Responses

`area_pct`, `area` (`component_id`), `param` (`component_id`, `key`: `pos`, `fwhm`, `amp`, `m`, ...),
`group_fraction` (`numerator` ids, optional `denominator` ids, default = all peaks), `ratio` / `difference`
(operands are response names or inline specs). They are evaluated from the stored fit, so any response can be added
later with `reanalyse`. A response whose component does not exist in a cell (e.g. a dropped satellite) is empty there.

### Presets (proposals, always review the levels)

* `fit_model_choices`: background type (XPS: Shirley / Tougaard U4 / linear; vibrational: polynomial degrees), fit
  window (+/- `window_delta`, default 5 % of the window), line-shape mix (`m` / `eta` fixed at nominal +/- `mix_delta`),
  FWHM constraint (tied vs free; for recipe fits with fixed widths: fixed vs free within +/- `fwhm_free_rel`, default
  30 %), satellite treatment (area-ratio locked / unlocked / absent). Factors that do not apply are skipped, with a note.
* `baseline_method`: the `method` of an upstream `baseline` step (`preset_options.methods`, `occurrence`).

Default responses: the area share of every peak.

## Design, caps and cost

The design is the **full factorial**. `max_cells` (number or `null` = no cap) refuses oversized designs instead of
thinning them; `subsample: {"n": N, "seed": S}` is an explicit opt-in that draws N cells (ANOVA then approximate).
### Exclusion rules (`constraints`)

A full factorial spends fits on combinations nobody would choose (e.g. a 3.0 eV Co3+ width with a 1.2 width ratio gives
a 3.6 eV Co2+ width). `constraints` removes such cells BEFORE anything is fitted; the cap, the cost estimate and the
subsample all count the cells that remain. Two rule kinds, each with an optional `name`:

* `{"exclude_when": {"<factor>": ["<level>", ...], ...}}` drops a cell when, for EVERY listed factor, its level is one
  of the listed ones.
* `{"require": "<expression>"}` keeps a cell only when the expression holds. Names come from `values` on the levels
  (`{"name": "1.8", "values": {"w3": 1.8}, "patches": [...]}`, numbers only, ignored by the fit). A value name must be
  given on every level of its factor and belongs to one factor. Allowed: numbers, value names, `+ - * /`, comparisons,
  `and` / `or` / `not`, `abs` / `min` / `max`. Comparisons tolerate 1e-9, so `3.0 * 1.0 <= 3.0` holds.

```json
"factors": [
  {"name": "fwhm_co3", "levels": [{"name": "2.6", "values": {"w3": 2.6}, "patches": [...]}, ...]},
  {"name": "relation", "levels": [{"name": "current", "values": {"rel": 1.0, "extra": 0.4}, "patches": [...]}, ...]}
],
"constraints": [{"name": "co2 width", "require": "w3 * rel + extra <= 3.2 and w3 >= 1.8"}]
```

Rules must keep the nominal cell (first level of every factor), which is the reference for the noise study; otherwise the
design is refused. Once a rule removes a cell the design is **unbalanced**: `exact` is false and the ANOVA uses the
sequential least-squares decomposition, so shares depend on the order of the factors and are approximate (the same as for
a subsample or missing fits). The plan's `design` block reports `n_excluded` and `excluded_by_rule`. The rules and level
values enter the design hash. Rules cannot be changed in `reanalyse` (the stored cells are fixed).

`interaction_order`: 1 = main effects, 2 = pairwise, ..., `null` / `"all"`. Higher orders are pooled into
`higher-order`. Cost = cells x spectra x `n_starts` (+ `noise.n_replicates` x spectra). The server refuses studies above
`SERSFLOW_ROBUSTNESS_MAX_FITS` (default 20000) unless `allow_large: true`; the MCP tool asks for `confirm` above
`robustness_confirm_max_fits` (default 400). Fits per second depend strongly on the model: recipe fits take about 0.1 s,
but Tougaard U4 with locked satellites can take 10-25 s per fit, so check the plan first.

## Fit quality, BIC and comparability

Native BIC / chi2 are only comparable between fits of the **same data points and weighting**. Different fit windows
change N, so a native-BIC filter across windows is invalid. Each cell therefore also gets a **common-window score**
(`rmse_common`, `chi2_common`, `bic_common`): its residuals restricted to the window shared by all cells. It is
comparable across windows, backgrounds and constraints, but only between cells with the **same upstream settings**
(an upstream baseline or normalisation change rescales y; such cells are compared within their upstream group).

Filter `mode`: `none`, `delta_bic_common` (default threshold 10), `delta_bic_native` (only within groups with identical
points and weighting), `rmse_ratio`; plus `exclude_degenerate` and `max_at_bound`. The summary reports what each filter
removed **per factor level** (a filter that removes mostly one level biases that factor) and the unfiltered ANOVA.
A zero or very tight threshold leaves one cell per spectrum, so there is nothing to decompose.

## Multi-start and degeneracy

`n_starts` K: start 0 is the nominal p0, starts 1..K-1 jitter the free parameters inside their bounds (`jitter_frac`,
seeded per spectrum and cell, so results do not depend on worker scheduling). The lowest chi2 is kept. A cell is
`degenerate` when another start within `cost_tol` (relative chi2) gives a response differing by more than
`max(resp_tol_abs, resp_tol_rel*|value|)`: the data cannot decide between those solutions.

## ANOVA

One observation per cell, no replicates: shares are SS(term) / SS(total). On a complete full factorial the
decomposition is exact (equal to first-order and interaction Sobol indices of the discrete design). With missing
cells (failed fits, a filter, subsampling) a sequential least-squares decomposition is used and flagged
`exact: false`. Shares are computed per spectrum and reported as mean / median / min / max over spectra and
`share_pooled` (sum of SS / sum of total SS).

## Trend and noise comparison

With `x_label`, every cell gets Spearman rho and slope of the response against x over the spectra. The summary gives the
fraction of cells keeping the sign of the reference (majority sign, or `reference_cell`), the ordering agreement with the
median profile, and per-spectrum percentile bands across cells (the analyst-choice band for plots). With
`noise.n_replicates`, the existing noise Monte Carlo (same engine as the Monte Carlo job) runs on the reference cell
(default: the first cell = all nominal levels), and `noise_comparison` gives variance across cells / variance across
noise replicates per spectrum and their median.

## Execution

* Parallel process pool (`workers`, default `SERSFLOW_ROBUSTNESS_WORKERS` or min(CPUs, 8)); `workers: 1` runs inline
  with identical numbers (tested).
* Cells with equal upstream patches share their pre-fit spectra: the pipeline up to the fit runs once per distinct
  upstream setting (not once per cell). Upstream factors recompute from the start of the pipeline for their group.
* Every finished record is appended to `robustness_records.jsonl`; `resume` skips the (spectrum, cell) pairs already
  there and tolerates a torn last line.

## Output (`export.zip`)

`summary.json`, `design.csv`, `variant_points.csv` (spectrum x cell: levels, responses, fit health, native and common
scores, multi-start flags, `kept`), `anova.csv`, `trend.csv`, `bands.csv`, `noise_comparison.csv`, `filter_report.csv`,
`study_spec.json`, `provenance.json` (software version, git commit, design hash, seed), `robustness_records.jsonl`.

## Limits

* Responses come from the fitting step under study (not from other steps' features).
* Noise Monte Carlo is run on one reference cell, not on every cell.
* Levels are the analyst's responsibility: levels nobody would choose inflate the spread.
* After a server code change the MCP server must be restarted to expose the tools.

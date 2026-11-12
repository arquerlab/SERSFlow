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

## Patch-effect check (is every level real?)

A factor level can silently do nothing: a typo in a component id, a step key the step never reads, a value set on a
parameter that is tied by an expression, two levels that are the same configuration, or a change that only moves the
initial value of a free parameter. The ANOVA then reports a ~0 share for a choice that was never tested, and the
robustness claim covers less than it says. Before a study is planned or run, `core/robustness/patch_check.py`
compares **what the optimizer receives**, never the response:

* *inert*: the optimizer input equals the nominal one: a bug, reported as an error;
* *insensitive*: the input differs but the response hardly moves: a real finding, never flagged.

The fit is split into `prepare_fit` (patches -> `FitProblem`: fit-window crop, weighting, components, bounds) and
`solve_fit` (multi-start); `fit_cell` is their composition. `core/robustness/fit_hash.py` hashes the problem:
`data_hash` (window x / y / sigma and weighting), `config_hash` (model, parameters, settings; the initial value of a
free parameter excluded; a linked parameter records only its link, a fixed one only its value) and `start_hash`
(config plus initial values and `initial_guess_mode` / `initial_area_ratios`). SHA-256 over canonical JSON, floats
rounded to 12 significant digits, arrays as float64 text plus shape: stable across processes and machines.

Layers, all at plan time (only `prepare_fit` runs, no optimisation):

1. **spec**: every patch resolves (`PatchResult`: op, target, resolved, old / new value, reason; a `set_step_param`
   key must be one the step declares or already carries), the patched pipeline differs from the nominal one, and the
   levels of a factor differ pairwise;
2. **upstream**: for levels that patch steps before the fit, the pre-fit spectra (n points, x range, data hash) differ
   from nominal on at least one spectrum;
3. **fit**: the one-factor-at-a-time cell versus the nominal one: config or data hash differs on at least one
   spectrum. If the plain OFAT cell was excluded (`constraints`) or not drawn (`subsample`), the nearest allowed pair is
   compared; if none exists the level is `untestable`.

Statuses: `ok`, `inert`, `upstream_inert`, `unresolved_target`, `duplicate_of:<level>` (errors); `start_only`,
`untestable` (warnings). `start_only` means only initial values differ: with multi-start jitter that is not a model
choice (for a free parameter give the level bounds, or fix it, to make it a real choice).

Strict by default. `post_analysis_robustness_plan` returns the table in `patch_check` (with `n_errors`,
`n_warnings`); with errors the call is **HTTP 422** and the table is the body. The run endpoint refuses (422) unless
`allow_inert: true`; the job re-checks at start and writes `patch_check.json` into the export. The plan also echoes the
spec as the server parsed it (`received_spec`, `spec_hash`): the MCP tools raise when it differs from what they sent.
The request schema rejects unknown keys (`extra="forbid"`), and the client sends `X-SpecFlow-Robustness-Schema` (a hash
of the request schemas): a stale MCP or API process gets **HTTP 409** ("restart it") instead of silently dropping an
argument, which is how a study once ran without its exclusion rules.

Retro-audit of a stored study (nothing is refitted, records untouched):
`post_analysis_robustness_check_patches(job_id)` (`POST /analysis/robustness-jobs/{job}/check-patches`) or
`sersflow-admin robustness-check-patches <job_id>` re-runs the check on the stored spec and cohort, writes
`patch_check.json` (`patch_check_audit.json` if the job already has one) and adds `records_audit`: cells whose stored
hashes show identical optimizer inputs (only for records written after this feature).

New record fields (additive; old records still load): `prefit_data_hash`, `fit_config_hash`, `fit_start_hash`,
`fit_data_hash`, `n_points_fit`, `fit_x_min`, `fit_x_max`, `patch_check_version`. `provenance.json` also carries
`spec_hash`.

Limitations: layer 3 is one-factor-at-a-time, so a level that only acts together with another factor's level (an
interaction-only effect) can look inert; the check sees optimizer *inputs*, so an input the engine later re-derives
internally is only caught when it changes the fit data or the problem the engine is handed; a window wider than the
spectrum is inert by construction (the data do not extend there).

## Limits

* Responses come from the fitting step under study (not from other steps' features).
* Noise Monte Carlo is run on one reference cell, not on every cell.
* Levels are the analyst's responsibility: levels nobody would choose inflate the spread.
* After a server code change the MCP server must be restarted to expose the tools.

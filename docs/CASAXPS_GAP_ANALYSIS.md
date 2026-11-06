# CasaXPS → SpecFlow feature gap analysis

Status: written 2026-11-05 against `main` @ `b845749`. **Implemented since:** K1, K2, K3, IO1, F1, F2, F3, F4, R1, B1, L1, M1, S1 (see "Implementation notes" under each).

## 0. How to use this document (for a planning / implementing agent)

This is the input for building an implementation plan. Each gap has a stable ID (e.g. `Q1`, `F2`). When you plan:

1. Pick items by priority (P0 first) and check their **Depends on** line.
2. Re-verify the **Current state** pointers before designing. They were accurate at `b845749`, but the code moves.
3. Treat the **Done when** criteria as the acceptance tests.
4. Every item must meet the **surface rule** in §2.

Source abbreviations used in the "CasaXPS ref" lines:
- **CB** = *CasaXPS Cookbook 2026* (Casa Software, 189 pp.), printed page numbers.
- **BB** = *CasaXPS Manual 2.3.15* ("Blue Book", 2009), printed page numbers.
- **REV** = *CasaXPS 2.3.25 Review* (2022), https://casaxps.com/pdfs/CasaXPS2325-Review.pdf
- **RBD** = CasaXPS feature list, https://www.rbdinstruments.com/phi/files/casa-xps/casaxps-feature-list.pdf
- **ISO19830** = ISO 19830:2015, minimum reporting requirements for peak fitting in XPS.
- **MAJOR** = Major et al., *JVST A* 38, 061203 (2020), "Practical guide for curve fitting in XPS", including its Table I of common errors.

Local copies of the two books: `C:\Users\apinilla\OneDrive - ICFO\Documents\OPERIS\CasaXPSCookbook2026.pdf` and `...\BlueBookA4forA5ebook.pdf`.

## 1. Goals and scope (decided with the user)

- **Target:** results that are good enough to publish. Users are the whole research group, working through the web UI and through MCP/agents.
- **In scope:**
  - XPS: fitting, backgrounds, quantification, calibration, reporting
  - multivariate analysis
  - imaging/mapping
  - depth profiles and series
  - file formats: the most common ones, and the formats that most instruments can export
- **Low priority:** angle-resolved XPS (ARXPS).
- **Out of scope for now:**
  - AES quantification (derivative/peak-to-peak, AES libraries)
  - ToF-SIMS, dynamic SIMS, SNMS
  - CasaXPS-specific UI conventions (MDI windows, tile pages) unless they map to a real workflow need
- **Also in scope:** the deferred items listed in `CLAUDE.md` (they appear here as K3, K4, K5).

## 2. Cross-cutting rules for every item

- **Surface rule.** A feature counts as done only when all four of these exist:
  - core Python under `src/sersflow/core/`;
  - a REST route under `src/sersflow/api/routers/`;
  - UI in the React app under `frontend/src/`, or the legacy shell when it is a viewer;
  - an MCP tool under `src/sersflow/mcp/tools/`, or exposure through pipeline JSON when the feature is a pipeline step.

  An item that is deliberately API/MCP-only must say so.
- **Pipeline steps.** A new pipeline step needs:
  - a StepSpec in `core/pipeline/library/builtins.py`;
  - an implementation registered in `core/pipeline/steps.py` (`DEFAULT_STEPS`);
  - a UI schema in `core/pipeline/library/ui_schemas.py`;
  - a section in `api/web/help/pages/r-steps.html`. `tests/test_help_pages.py` enforces this section.
- **Reproducibility.** Every new numeric option must be stored in pipeline JSON, so it is covered by the pipeline hash, and must appear in the fit/quant report (R1).
- **Conventions** (repo `CLAUDE.md`):
  - Files use CRLF.
  - Never round-trip `core/xps/data/fitting_recipes.json` through a JSON loader; use targeted text insertion.
  - The MCP server on PCES01 must be restarted to pick up new code.

## 3. Priority and effort scale

| Priority | Meaning |
|---|---|
| **P0** | Without it, results are wrong, missing (no quantification), or not reportable to ISO 19830 / MAJOR standard. Blocks publication-grade use. |
| **P1** | Needed for routine group work at CasaXPS-level quality, or an area the user explicitly asked for (depth profiles, multivariate). |
| **P2** | Valuable extension: imaging, more formats, advanced multivariate, global fitting. |
| **P3** | Nice to have, or marked low priority by the user (ARXPS). |

Effort: **S** = one module, small change. **M** = several modules across the four surfaces. **L** = a new subsystem or data model.

## 4. Summary table

| ID | Title | Pri | Effort | Depends on |
|---|---|---|---|---|
| K1 | `gl` line shape is the sum form (CasaXPS SGL) but is labelled GL; add the true product GL | P0 | S–M | – |
| K2 | Failed fits pass through silently as unchanged spectra | P0 | S | – |
| K3 | Warn when a recipe lacks the requested pass-energy column (deferred) | P0 | S | – |
| IO1 | VAMAS reader: corresponding variables (transmission), counts vs CPS, robustness | P0 | M | – |
| F1 | Poisson-weighted fitting, normalised residual, residual STD | P0 | M | IO1 |
| F2 | Parameter uncertainties: covariance errors exported, Monte Carlo | P0 | M–L | F1 |
| F3 | Doublet constraints: lock spin-orbit area ratio; `area_ratio` for all line shapes | P0 | M | – |
| Q1 | Quantification engine: regions, RSF library, atomic % | P0 | L | IO1 |
| Q2 | Intensity correction chain: transmission, escape depth, angular correction, instrument profiles | P0 | L | Q1, IO1 |
| R1 | Publication fit and quant report (ISO 19830 / MAJOR), with software version | P0 | M–L | F1, F2, Q1 |
| F4 | General relational constraint expressions | P1 | M | F3 |
| B1 | Background options: endpoint averaging, offsets, linear, Tougaard presets, erfc step/edge | P1 | M | – |
| L1 | Line shapes: finite-area DS, tail modifiers, trapezium/Shirley-profile components | P1 | M | K1 |
| M1 | Linear least squares (NNLS) with reference spectra, mixed with peak models | P1 | M | F1 |
| S1 | Fit robustness ("Test Peak Model"): parameter scans, noise replicates | P1 | M | F1 |
| R3 | Automatic fit-quality warnings (MAJOR Table I checklist) | P1 | M | R1 |
| R4 | Tags and formula reports: chemical-state sums, ratios, Auger parameter | P1 | S–M | Q1 |
| D1 | Depth profiles and series: experimental variable, at.% profiles, etch time → depth | P1 | M | Q1 |
| D2 | Propagation with per-spectrum overrides; sequential seeding along a series | P1 | M | – |
| X1 | Interactive fitting UX: drag peaks, brush windows, add peak at residual, fit history | P1 | L | – |
| X2 | Element and chemical-state identification UI (survey labels, reference markers) | P1 | M | Q1 (for auto regions) |
| X3 | UI/MCP parity fixes for existing backend features | P1 | S | – |
| IO2 | Generic ASCII and SPECS `.xy` import | P1 | S–M | – |
| IO3 | CasaXPS interoperability: turn imported CasaXPS fits into SpecFlow steps | P1 | M | K1, F4 |
| K4 | Recipe `satellite_of` field (deferred) | P1 | S | – |
| K5 | Fit-window check against the spin-orbit partner (deferred) | P1 | S | – |
| M2 | NMF / MCR-ALS for spectra series and maps | P2 | M | – |
| M3 | Spectral PCA: reconstruction/noise reduction, factor-count criterion, target factor analysis | P2 | M | F1 |
| IM1 | XPS imaging: image stacks, per-pixel fit/quant maps, ROI spectra, image multivariate | P2 | L | IO1, Q1, M2 |
| IO4 | Vendor native formats: PHI `.spe`/`.pro`, Thermo `.avg` directories, Kratos `.kal`, Scienta | P2 | M–L | IO1, Q2 |
| C1 | Transmission-function builder from reference spectra | P2 | M | Q2 |
| C2 | X-ray satellite subtraction (non-monochromatic Mg/Al) | P2 | S–M | – |
| C3 | Spike removal for XPS | P2 | S | – |
| F5 | Global fitting across spectra/regions with shared parameters | P2 | L | F4 |
| D3 | Overlayer thickness (Hill equation, EAL) | P2 | S–M | Q2, R4 |
| V1 | Valence band and Fermi edge tools (VBM extrapolation, resolution) | P2 | S–M | B1 |
| X4 | Publication figure composer: overlays, waterfall, on-plot tables and labels | P2 | M | R1 |
| A1 | ARXPS: angle as variable, thickness from angle series | P3 | M | D3 |
| S2 | Limit of detection and S/N metrics | P3 | S | F1 |
| T1 | Synthetic test-data generator with known truth | P3 | S | – |
| K6 | DS/GDS parameter units labelled `cm^-1` | P3 | S | – |

Suggested order of work, in phases (each phase can ship on its own):

1. **Correctness:** K1, K2, K3, IO1, F1, F3
2. **Quantification:** Q1, Q2, F2
3. **Reporting:** R1, R3, R4, S1
4. **Daily workflow:** X1, X2, X3, B1, L1, M1, D1, D2, IO2, IO3, F4, K4, K5
5. **Extensions:** the P2 items, then P3

---

## 5. Gap details

### P0: correctness and minimum publishable output

#### K1. `gl` line shape is the sum form, not CasaXPS GL (product)
- **CasaXPS ref:** In CasaXPS, GL(m) is the **product** Gaussian×Lorentzian and SGL(m) is the **sum** (BB p.38–39; CB p.67; REV).
- **Current state:**
  - `core/preprocess/fitting_models.py` `gl()`: its docstring says "CasaXPS-style Gaussian–Lorentzian sum GL(m)", and it is implemented as `pseudo_voigt`.
  - Recipes in `core/xps/data/fitting_recipes.json` carry the CasaXPS strings (e.g. `GL(30)`) from Biesinger, whose fits were done in CasaXPS with the product form.
  - So recipe FWHMs and m values are applied to the wrong function.
- **Build:**
  - Add a true product GL(m) (and GL(m,n) with extra Gaussian convolution, per CB p.67).
  - Expose the sum form as `sgl`.
  - Decide how to keep old runs reproducible. Recommended: keep the `gl` id as a deprecated alias of `sgl` for stored pipelines, add `gl_product` (or a schema-version bump), and switch the recipe mapping in `core/xps/lineshape_kinds.py` / `recipe_apply.py` to the product form.
  - The analytic area per height for the product form needs a numeric integral, which feeds F3.
- **Implementation notes (done 2026-11-05):** `gl` = product with `fwhm` = TRUE FWHM (Biesinger/CasaXPS table values; F derived);
  closed-form area via erfcx; `sgl` = sum; `gl_gauss` = GL(m,n) (`fwhm_g` in eV); `a_gl` product base, `a_sgl` legacy.
  Versioned migration (pipeline schema v2): stored pipelines/sessions/run snapshots/matrix jobs rewritten `gl`→`sgl`,
  `a_gl`→`a_sgl` once at startup; v1 packages migrated on import. Pipeline hashes of migrated pipelines change (accepted);
  fitting `impl_version` 3→4. Tests: `tests/test_gl_product.py`.
- **Done when:**
  - The product GL(30) matches the CasaXPS shape on a reference grid. Tests compare against tabulated values or a numeric integral.
  - Recipes produce the product shape.
  - Old pipelines still reproduce their stored hashes and results.
  - `r-fitting.html` documents both forms.

#### K2. Failed fits pass through silently
- **Current state:** `core/pipeline/steps.py` (fitting step, ~line 228–238) catches `ValueError`/`RuntimeError`, logs at INFO, and returns the input spectrum unchanged. A failed fit then looks like data in the exports.
- **Build:**
  - Keep the pass-through for the legitimate "region does not match" case. For that case, prefer filtering with `xps_region` before fitting is attempted.
  - Any other failure must be recorded: `fit_health.success=false`, a run-level warning, NaN feature columns. The UI shows a badge and MCP returns the warnings.
- **Implementation notes (done 2026-11-05):** statuses ok / not_applicable (window outside spectrum, region mismatch) /
  failed (exception, invalid set-up, empty spectrum: NaN features, success=0) / not_converged (features kept, success=0).
  Run summary `warnings` + `fit_failures` (`analysis_runs.warnings_json`); `fit_health.csv` gains `fit_status`,
  `fit_failure_reason` and rows for failed spectra; Analyze badge + panel; MCP run summary and `post_analysis_jobs_wait`.
  The step output stays the raw spectrum (user decision). Tests: `tests/test_fit_failures.py`.
- **Done when:**
  - A deliberately failing fit appears as failed in the run summary, in `fit_health.csv`, and in the MCP response.
  - No fit features are emitted for it.

#### K3. Recipe pass-energy column fallback (deferred item)
- **Current state:** `core/xps/recipe_apply.py` ~78–92 falls back silently to another `fwhm_<PE>` column, or to 1.0, when the requested pass energy has no column.
- **Build:** Return a structured warning naming the requested PE and the column used. Show it in `FittingRecipePicker.tsx` and in the MCP recipe tool responses.
- **Implementation notes (done 2026-11-05):** `pass_energy_resolution` {requested, acquisition, used, source, available,
  fallback, fwhm_fallbacks} in core, REST schema and MCP recipe tools; one summary warning instead of one per peak;
  amber notice in `FittingRecipePicker.tsx` (the picker now lets the server resolve the dataset PE). 34 packaged recipes
  fall back at PE 20. Tests: `tests/test_recipe_pass_energy.py`.
- **Done when:** A test applies a recipe at an unsupported PE and gets the warning on all surfaces.

#### IO1. VAMAS reader hardening
- **CasaXPS ref:**
  - VAMAS ISO 14976 is the native format (CB p.6; BB p.212).
  - Blocks carry corresponding variables: the transmission function, CPS, calibrated data (BB p.117–119, 283–286).
  - Vendor exports (SpecsLab 2, Kratos Vision 2) embed the transmission function as a second corresponding variable (BB p.283, 287).
- **Current state:**
  - `core/io/read_vms.py:520` rejects blocks with `n_corresponding_variables > 1`.
  - `dwell_time`, `n_scans` and `signal_mode` sit in `extra_fields` but are unused, so it is unknown whether y is counts or CPS.
  - Images and maps in VAMAS (spatial blocks) are not handled.
- **Build:**
  1. Read all corresponding variables. Keep the first as the spectrum and store the others as named auxiliary arrays: `transmission`, or a generic name.
  2. Record whether y is counts or counts/s, from the signal mode and corresponding-variable unit, together with dwell and scans. Provide `counts_per_channel(y)`, needed by F1, and `cps(y)`, needed by Q1.
  3. Handle irregular abscissa and KE/BE correctly. Add tests on Kratos, SPECS, Thermo-via-CasaXPS and PHI-via-CasaXPS VAMAS samples, using real files from the group.
  4. Preserve CasaXPS comment blocks; `casa_fit.py` already parses them.
- **Implementation notes (done 2026-11-05):** ISO 14976 header/block layout per experiment mode (NORM, SDP/SDPSV/MAPDP
  sputter fields, MAP positions + field of view, linescans, AES diff width), several experiment variables, manual items,
  future-upgrade entries, n corresponding variables (interleaved; first = spectrum, others → `VamasBlock.aux`, e.g.
  `transmission`), per-variable min/max, IRREGULAR scan mode (abscissa = first corresponding variable; ASSUMED convention,
  verify on a real file). Clear errors for MAPPING scan mode and parameter inclusion/exclusion lists. `y_unit`
  (counts | cps | unknown), `dwell_time_s`, `n_scans`, `aux_arrays` in block labels; helpers `counts_per_channel` (F1)
  and `cps` (Q1) in `core/io/read_vms.py`. REST `GET /datasets/{id}/spectra/{sid}/acquisition`, MCP
  `get_datasets_spectrum_acquisition`, Prepare acquisition summary. Still open: real Kratos/SPECS/Thermo/PHI fixtures.
  Tests: `tests/test_vamas_iso.py`.
- **Done when:**
  - Multi-variable VAMAS files load.
  - A transmission array is available to Q2.
  - Count statistics are available to F1.
  - Existing VAMAS tests pass.

#### F1. Poisson-weighted fitting and residual STD
- **CasaXPS ref:**
  - Chi-square with Poisson weighting vs a plain-RMS option ("Use RMS", CB p.119).
  - Normalised residual (residual / √counts) and Residual STD, which should be about 1 for pulse-counted data. A Regression background on a featureless interval gives the instrument's noise target (CB p.72–74).
  - K-Alpha data are converted back to counts per bin so the statistics stay valid (BB p.312).
- **Current state:**
  - `core/preprocess/fitting_lmfit.py` fits unweighted.
  - `fit_diagnostics.py` reports χ²/AIC/BIC under unit variance; `r-fitting.html:62` acknowledges this.
- **Build:**
  - Add a `weighting` option (`none` | `poisson`) to the fitting step, with σ = √max(counts, 1) taken from IO1.
  - Export `residual_std_normalised` and `chi2_reduced_weighted`.
  - Add a normalised-residual view in the UI (`fitResidualPlot.ts`).
  - Static background subtraction before fitting changes the statistics. Document that weighting uses the raw counts, before any static background is removed.
  - Default to `poisson` for XPS when counts are known.
- **Implementation notes (done 2026-11-05):** `XY.var` / `var_kind` carry the RAW counting variance from load
  (multi-block XPS files: integer counts or cps×dwell×scans → absolute; scaled/normalised "counts" or unknown units →
  relative, σ² = g·y) through crop, x-calibration, static baseline (raw counts kept), normalize (exact rescale) and
  cosmic-ray removal; every other step drops it. Fitting-step `weighting` = auto (default, Poisson for XPS) | poisson |
  poisson_relative | none, applied as lmfit `weights=1/σ`; default applies to stored steps too (user decision), fitting
  `impl_version` 4→5. Diagnostics: `weighting`, `weighting_note`, `residual_std_normalised`, `chi2_reduced_weighted`,
  `poisson_gain`; chi2/redchi/AIC/BIC use weighted residuals when weighted. REST: `/pipeline/run` final items return
  `var`, `/fitting/fit` takes `y_variance`/`variance_kind`/`weighting` and returns `residual_normalised` (also the Analyze
  fitting preview). UI: weighting selector + description at the top of the Peak Fitting step, applied weighting in every
  fit plot title and preview status, normalised-residual toggle (Prepare and Analyze). Single-spectrum text formats have
  no counting statistics (fitted unweighted). Tests: `tests/test_poisson_weighting.py`.
- **Done when:**
  - On simulated Poisson data with a known model, the reduced χ² is about 1 and the normalised residual STD is about 1.
  - The UI can show the normalised residual.

#### F2. Parameter uncertainties and Monte Carlo
- **CasaXPS ref:**
  - Monte Carlo button: Poisson-noise replicates refitted, giving uncertainty in %area and in atomic % (CB p.124; RBD).
  - Std Dev Area on regions and "Calculate Error Bars" (CB p.167).
  - ISO19830 clause 10 requires uncertainties on BE and area.
- **Current state:**
  - lmfit covariance is computed, but only `median_rel_stderr` is exported.
  - `help/pages/r-exports.html:50` says explicitly that there are no per-parameter error columns.
  - No Monte Carlo or bootstrap.
- **Build:**
  1. Export `stderr` for every fitted parameter (position, FWHM, amplitude, area, %area) as observation columns. Cover them in the export contracts and the observation schema.
  2. Add an optional Monte Carlo (`n_replicates`, seed): simulate Poisson noise on the fitted envelope plus background, refit, and report SD / percentiles for each parameter and %area.
  3. Run it as an async job, like sweep jobs. Expose it through REST, the UI (Analyze → fit diagnostics) and MCP.
  4. Pass the uncertainty through to Q1 (atomic % ± σ).
- **Implementation notes (done 2026-11-05):** `FitResult.p_cov` is now the covariance of the FULL flat parameter
  vector (J C J^T: varied → identity, linked → finite differences through `Parameters.update_constraints`, fixed → 0),
  scaled by χ²ν (lmfit default, user decision); `FitResult.p_stderr` = 1σ (NaN fixed). `core/metrics/fit_uncertainty.py`:
  area / %area (share of the step's summed peak areas, backgrounds and DS/GDS excluded) and their errors by numerical
  Jacobian; `run_monte_carlo` (noise follows the fit weighting — Poisson σ, relative Poisson √(g·y), or RMSE; Gaussian
  draws; user decision). Observation columns per component: `_area_pct`, `_<param>_stderr`, `_area_stderr`,
  `_area_pct_stderr` (after the values, so the parameter/area layout is unchanged); fitting `impl_version` 5→6.
  Monte Carlo is an on-demand job (user decision, not a pipeline option): `POST /analysis/runs/{id}/monte-carlo-jobs`,
  `GET /analysis/monte-carlo-jobs/{id}/summary`, zip via the fit-curve job download; MCP `post_analysis_monte_carlo_jobs`,
  `get_analysis_monte_carlo_summary`; UI Analyze → Fit diagnostics (± table + Monte Carlo panel). `/fitting/fit` and the
  fitting preview return `stderr`, `area`, `area_pct` and their errors per component. Step 4 (Q1) waits for Q1; the R1
  report should read the `_stderr` columns. Tests: `tests/test_parameter_uncertainty.py`.
- **Done when:**
  - On synthetic data with known truth, Monte Carlo SDs agree with the empirical scatter.
  - Error columns appear in CSV/Parquet and in the R1 report.

#### F3. Doublet constraints and `area_ratio` for every line shape
- **CasaXPS ref:**
  - "Create x 2" builds a spin-orbit pair with library constraints (CB p.109).
  - Area constraints such as `A*0.5` lock the ratio (CB p.107, 137).
- **Current state:**
  - `recipe_apply.py` ~524–538 seeds spin-orbit areas at 2:1 but does **not** lock them.
  - `fitting_lmfit.py:404–431` supports `area_ratio` only for gl, gaussian, lorentzian and pseudo_voigt. Satellites on other shapes fall back to a fixed height scale (`recipe_apply.py:658–662`).
- **Build:**
  - Give every line shape an area-per-height expression, numeric where no closed form exists (LA, voigt, apv, asymmetric_voigt, lf, product GL), so `area_ratio` works for all of them.
  - Add a "doublet" helper: create a pair with an offset link, equal-FWHM link and area-ratio link from (2j+1). Make it available in the UI component editor and as a recipe option that locks by default.
  - Recipes lock the spin-orbit ratio unless the recipe says otherwise.
- **Implementation notes (done 2026-11-05):** literature checked first (Biesinger thesis 1.2.4 / Table 1.1 / 2.3.1-2.3.3,
  CasaXPS Cookbook p.107-111/137, Blue Book p.37-38). `fitting_lmfit._area_per_height_expr` covers every finite-area
  peak through a registered `sf_area_per_height(ctype, ...)` (same factors as the area export); DS/GDS rejected.
  `peak_area.area_per_height` no longer turns 0 into the default (GL(0) was read as GL(30)). `core/xps/spin_orbit.py`:
  nlj label parsing, pairs (prefix/suffix aware, e.g. `4f7/2_sat`), theoretical ratios p 1/2, d 2/3, f 3/4 (user
  decision: theoretical always), `doublet_links`, `add_spin_orbit_partner(_for_all_peaks)`. Recipes: labelled pairs get
  offset + FWHM equal or the table ratio when both widths are printed (Ti/V Coster-Kronig: user decision) + shape
  equal when the recipe shape is identical (user decision) + area lock (`lock_spin_orbit`, recipe
  `spin_orbit_area_lock: false` opt-out); the old equal-FWHM link for Ti/V and the duplicate pos link are gone; satellites
  use area_ratio for every shape (Ir LF parents no longer fall back to a height scale); a 4f5/2 satellite follows the
  4f7/2 satellite 3:4. One-member recipes (Co/Ni/Fe/Mn/Cr 2p3/2) stay single (user decision) unless
  `spin_orbit_partner_splitting_eV` is given (user-entered; the project literature has no Co 2p splitting). REST:
  apply-recipe query params, `POST /xps/spin-orbit-partner`; MCP `post_xps_add_spin_orbit_partner` + recipe tool params;
  UI: recipe picker options, "Spin-orbit partner…" per peak. Tests: `tests/test_spin_orbit_doublets.py`.
- **Done when:**
  - A Co 2p recipe fit holds area(2p1/2)/area(2p3/2) = 0.5 exactly.
  - `area_ratio` works for LA components (test).

#### Q1. Quantification engine
- **CasaXPS ref:**
  - Regions: Name, RSF, Start, End, BG type, Av Width, St/End Offset, Tag; outputs Area, Std Dev, FWHM, Position, %Conc, heights (CB p.167–171; BB p.20–25).
  - Concentration X_i = 100·(I_i/S_i)/Σ(I_j/S_j), from regions and/or components (BB p.106, 284).
  - Element library with source-matched RSFs (Scofield Al/Mg by default) and vendor library import (BB p.100–106, 298–321).
  - `#Name` lookup of RSF (CB p.169).
  - Survey quantification workflow (CB p.156–178).
  - Regions with RSF = 0 are excluded from quantification (BB p.33, 309).
- **Current state:**
  - No RSF, atomic % or region concept. A grep finds RSF only in `core/io/casa_fit.py`, parsed and unused.
  - `spectral_integrations` integrates windows without background.
  - Fitted areas exist as features (`core/metrics/fitting_features.py`).
- **Build:**
  1. **Element library** (`core/xps/element_library.py` + `data/`):
     - per-line fields: element, transition, BE, typical FWHM, RSF, source string;
     - a Scofield Al Kα / Mg Kα default set, with licence and provenance noted;
     - user libraries that can be loaded and merged; import of CasaXPS `.lib` format.
     - Libraries are versioned and their hash is recorded in runs.
  2. **Quantification regions:** window, background type (reuses B1), endpoint averaging, offsets, RSF, tag. Implement as a pipeline step `xps_quant_regions`, or as part of a new `xps_quantify` step.
  3. **Quantification step:**
     - groups spectra into a "measurement set", meaning the same sample and the same experimental-variable value (CasaXPS: one browser row). Use labels (`xps_region`, sample, experiment, replicate) to define the set;
     - computes corrected intensities in CPS·eV (needs IO1), divides by RSF × corrections (Q2), and outputs at.% per element and per component/tag;
     - supports mixing region areas with component areas from fitting steps.
  4. **Outputs:** observation columns `quant_<name>_atpct`, `_rsf`, `_raw_area`, `_corrected_area`, `_atpct_sd` (from F2).
  5. **UI:** a Quantify panel listing the set, regions, RSF source and the at.% table. Export it.
  6. **MCP:** tools to list libraries, create regions from the library, and run and fetch quantification.
- **Status (2026-11-05): DEFERRED by the user.** No RSF / cross-section source is available yet (no CasaXPS
  library or Scofield table in the project; values must not be typed from memory) and the group's main data are
  synchrotron (hv differs per region: Co 2p/W 4f 1100 eV, O 1s 980 eV, C 1s 740 eV), which needs hv-dependent
  cross-sections and photon-flux normalisation rather than lab RSFs. Revisit when the user has (a) an RSF/cross-section
  source, (b) the flux/I0 information, (c) a CasaXPS-quantified reference file. Findings kept for then: CasaXPS
  corrected area A = I*E^n/(T(E)*RSF) with n negative (e.g. -0.7; BB p.284-287), angular factor
  1 - (beta/4)(3cos^2(theta) - 1) for Scofield RSFs (CB p.25), VAMAS source/analyser polar+azimuth are already kept
  in the block extra fields (the source-analyser angle is now exposed by the acquisition payload / R1 report).
- **Done when:**
  - A survey of a known stoichiometric reference (e.g. NaCl, PTFE, or a group standard) gives at.% within tolerance of the CasaXPS result on the same file with the same RSFs and corrections.
  - The test fixture stores the CasaXPS numbers.

#### Q2. Intensity correction chain and instrument profiles
- **CasaXPS ref:**
  - Total sensitivity = transmission × escape depth × cross-section × angular-distribution correction, with each factor reported separately (CB p.21–33, 173–176; BB p.282–293).
  - Escape depth: E^n with n set per instrument (e.g. −0.6 to −0.7), or TPP-2M IMFP / EAL.
  - Angular correction: 1 − (β/4)(3cos²θ − 1), using the source–analyser angle from file metadata or a configured default (BB p.292–298).
  - Transmission models:
    - PHI: a, b
    - Thermo VG: C0–C3
    - SPECS: a·E^−b
    - NPL: rational polynomial
    - Files can be loaded (simple ASCII, NPL `Q.vms`).
    - Relative transmission functions can be set per lens mode and pass energy (CB p.145–155, 177–184; BB p.287–291).
- **Current state:** none of this exists.
- **Build:**
  1. **Instrument profile entity** (stored, versioned, owned per group): instrument name, source energy, source–analyser angle, E^n exponent or IMFP model, RSF library id, and transmission functions keyed by (lens mode, pass energy). Profiles are selected per dataset, or matched automatically from metadata.
  2. **Transmission:** use the per-block transmission array from IO1 when present, otherwise the profile's model. Supported model types: PHI a/b, VG C0–C3, SPECS power law, NPL polynomial, tabulated.
  3. **Escape depth:** E^n, or TPP-2M with material parameters (density, Eg, Nv, M). The simple E^n is enough for P0; TPP-2M can follow.
  4. **Angular-distribution correction:** β values per line, applied when the RSFs are taken from the library.
  5. **Reports:** itemise the raw area, T(E), escape-depth term, angular-correction factor, library RSF, total sensitivity and at.%. This matches CasaXPS's report keywords: RAW_AREA, TRANSMISSION, MEAN_FREE_PATH, TOTAL_SENSITIVITY_FACTOR (BB p.77–78; CB p.40).
- **Status (2026-11-05): DEFERRED together with Q1** (see Q1 status).
- **Done when:**
  - The same file quantified in CasaXPS and in SpecFlow, with identical RSFs, transmission and exponent, agrees within 1 % relative per element.
  - Each correction factor is visible in the exports.

#### R1. Publication fit and quantification report
- **Refs:**
  - ISO19830, clauses 4–10, Annex C template.
  - MAJOR §J.
  - ISO 19318 (charge-correction reporting), ISO 16243.
  - CasaXPS standard/custom reports with keyword-configured columns (BB p.77–81, 197–202; CB p.40, 131–141).
- **Current state:**
  - Run exports: CSV, Parquet, ZIP bundle with a manifest (`api/routers/analysis.py`; schema in `api/schemas/analysis.py:109–119`).
  - Fit-curve ZIPs with PNG/SVG (`api/services/fit_curve_plot.py`).
  - The software version is **not** captured (`__version__` in `src/sersflow/__init__.py` is unused; `docs/ARCHITECTURE.md:378`).
  - No per-fit parameter or constraint table, and no report document.
- **Build:** a report job that produces Markdown/HTML (PDF optional) plus machine-readable JSON for each run. Contents:
  1. Raw file name, block and SHA-256 hash. Software name, version and git commit. Pipeline hash.
  2. Acquisition metadata: instrument, source energy, mono or non-mono, pass energy, step, dwell, scans, counts and count rate at the maximum channel, as available from the readers.
  3. Charge-correction method, reference and applied shift (from `x_axis_calibration`).
  4. Processing history (the ordered pipeline steps with their parameters).
  5. Per region:
     - background type, parameters, window and averaging;
     - for each component: line-shape string in CasaXPS notation, position, FWHM, area, %area, height, each with ± (F2), and its status (fixed / bounded [min,max] / linked + expression).
  6. Fit statistics: optimiser, N points, M free parameters, χ², reduced χ², normalised residual STD (F1).
  7. Quantification table with the itemised corrections (Q2).
  8. An annotated figure of data, envelope, components, background and residual, with a component table on the plot.
- **Implementation notes (done 2026-11-05):** `api/services/fit_report.py` builds the report from the run's stored fit
  columns (via the fitting preview), the pipeline snapshot and the VAMAS blocks; `core/report/fit_report_model.py`
  (CasaXPS line-shape strings, parameter status fixed/bounded/free/linked + relation text incl. F4 expressions,
  optimiser text, checklist), `core/report/render.py` (self-contained HTML with embedded PNGs, Markdown, user decision:
  HTML + Markdown + JSON, no native PDF). `core/provenance.py`: software name/version, git commit (env
  `SERSFLOW_GIT_COMMIT` or `git rev-parse`, `-dirty` suffix), file SHA-256 (cached). Acquisition payload now exposes
  source label, hv, analyser mode, step, source/analyser angles + their angle, counts and cps at the max channel.
  Charge-correction shifts are recomputed for the run cohort with the engine's calibration precompute. Figure: the
  fit-curve plot gained an on-plot component table and an inverted BE axis. Quantification section = "not performed"
  (Q1/Q2 deferred). Async job (`report-jobs`, fit-curve job polling/download, zip `fit_report_<id>.zip`), `GET
  /analysis/report-jobs/{id}/json`, MCP `post_analysis_report_jobs` / `get_analysis_report_json`, Analyze "Download
  report". ISO 19830 itself is not in the project: the checklist follows the item list of this section.
  Tests: `tests/test_fit_report.py`.
- **Done when:**
  - A report generated for a Co 2p run contains every ISO 19830 clause-5/10 item.
  - The REST, UI ("Download report") and MCP surfaces all produce the same report.

### P1: daily workflow at CasaXPS level

#### F4. General relational constraint expressions
- **CasaXPS ref:**
  - Constraints are either intervals or relations to another component, e.g. area `A*0.5`, FWHM `A*1`, position `A+1.2` (CB p.107).
  - Keywords `lock`, `link`, `factor=`, `Offset=`, `regions` (REV p.17–21).
- **Current state:** `param_links` supports the modes equal, scale, offset and area_ratio (`fitting_lmfit.py:434–474`). Each link is one-to-one, so there are no free expressions and no many-to-one links.
- **Build:**
  - Add an `expr` link mode that takes a safe expression over other components' parameters (reuse the safe evaluator in `core/metrics/feature_operations.py`, or lmfit `expr` with a whitelist).
  - Validate expressions for cycles.
  - In the UI link editor, show linked fields colour-coded by their target, as CasaXPS does.
- **Implementation notes (done 2026-11-05):** `core/preprocess/param_expressions.py`: link `mode: "expr"` with
  `{peak.param}` references (user decision: brace syntax; id = text before the last dot), `{A.area}` = amp x
  area-per-height and `defines: "area"` on amp links (user decision: area on both sides), ast whitelist (numbers,
  + - * / **, unary +/-, abs sqrt exp log min max), `validate_param_links` (unknown ids/keys, duplicate definitions,
  self references, cycles over ALL link modes incl. area_ratio shape dependencies, loop named in the error). lmfit:
  rendered into the parameter `expr`; validation runs before every fit (failures recorded per K2). Every linked
  parameter now ignores its own bounds (user decision; lmfit used to clip silently, e.g. +12 eV offset -> +10.5 eV).
  Recipe merge remaps ids inside expressions. REST `POST /fitting/validate-links` ({ok, errors, drivers}); MCP
  `post_fitting_validate_links`; UI: "Expression…" link mode with a `defines` selector on amp, live validation notice,
  link fields bordered in the driver peak's plot colour (grey for several drivers), bounds greyed while linked; peak
  rename / recipe add-remove rewrite expressions. Tests: `tests/test_param_expressions.py`.
- **Done when:**
  - An expression such as `pos(C) = pos(A) + 0.5*(pos(B)-pos(A))` fits correctly.
  - Cyclic expressions are rejected with a clear error.

#### B1. Background options
- **CasaXPS ref:**
  - **Region options:** Av Width endpoint averaging; St/End Offset (CB p.69, 171–173).
  - **Background types:** about 50, including Linear, Shirley variants (Iterated, Reduced, Offset, Flex Shirley with noise-split segments), Tougaard U2/U3/U4 with editable B, C, D, T0, material universal cross-sections, Min Limits, Regression, Poly Regression, Extrapolated linear/quadratic, and erfc Step/Edge Up/Down with fitted parameters (CB p.68–71, 98–100, 117–118, 171–173; BB p.23–24).
  - **Other:** a Shirley computed from a subset of components (MAJOR Fig. 17).
- **Current state:**
  - Static: pybaselines catalogue plus Shirley and Tougaard via lmfitxps (`core/preprocess/baseline.py:211–284`).
  - Active (fitted together with the peaks): `shirley_bg`, `tougaard_bg`, `slope_bg`.
  - No endpoint averaging, offsets, linear endpoint background, Tougaard presets, or erfc step.
- **Build:**
  1. Endpoint averaging (±N channels) and percentage offsets for static and active Shirley/linear backgrounds.
  2. Linear endpoint background.
  3. Tougaard presets: U2 universal (B≈2866, C=1643), U3 polymer / material classes, U4 with T0 for band-gap onset. Expose them as named presets in the UI.
  4. erfc Step/Edge background with fitted a0..a3, used for Fermi-edge calibration (connects to V1).
  5. Optional: a Shirley that integrates only selected components.
- **Implementation notes (done 2026-11-05):** `core/preprocess/xps_extra_components.py`. Av Width (+-N channels; 'auto' =
  legacy; no averaging when the window does not fit, CasaXPS) and percent offsets (low/high x end) for the static
  `shirley` (own iterative Shirley when non-default; lmfitxps otherwise, so old pipelines are unchanged) and new static
  `linear` baseline methods, and as component options on active `shirley_bg` and new `linear_bg`. Active `erfc_step_bg`
  (pos/height/fwhm/const; Edge position = pos - a sqrt(pi)/2; its `pos` is a calibration key, user decision: active +
  Fermi-edge calibration). `tougaard_u4_bg` (B, C, C', D, T0; own kernel) with the U2 preset; U3/U4 values entered by
  the user (user decision: not in project literature). Item 5 via SB (`shirley_of_bg`, see L1). Reported in R1 (all
  backgrounds with options). Tests: `tests/test_b1_l1_m1_s1.py`.
- **Done when:** Each new background has unit tests on synthetic data, is selectable in the UI and pipeline JSON, and is reported in R1.

#### L1. Line-shape extensions
- **CasaXPS ref:**
  - LA, LF, LS families; DS(α,n,l) Shirley-truncated Doniach–Šunjić and DSS (finite area).
  - Modifier prefixes: ST(μ,γ) asymmetry, T(k)/PHI(j,k) exponential tails, SB(0) Shirley-profile component, TP(α,β,n) trapezium/slope component (CB p.65–68; REV; RBD).
  - Line shapes built from measured spectra (REV p.18–19).
- **Current state:**
  - Present: gaussian, lorentzian, pseudo_voigt, gl (sum), voigt, ds, gds, la, lf, a_gl (approximate), apv, asymmetric_voigt, polynomial_background, fermi_edge (`core/preprocess/fitting_specs.py`).
  - DS/GDS produce no area (`INFINITE_AREA_COMPONENT_TYPES`), so metals cannot be quantified from DS fits.
- **Build:**
  - In priority order: a finite-area DS (truncated or DSS), so metallic components get an area; TP slope/constant components; SB(0) Shirley-profile components; T(k) tails.
  - A parser from CasaXPS line-shape strings to SpecFlow specs, shared with IO3 and the recipes.
  - Measured-reference components are covered under M1.
- **Implementation notes (done 2026-11-05):** DS/GDS areas integrated over the fit window (user decision; mapping rows carry
  `x_window`; area_ratio / expressions use the same window). `shirley_of_bg` = SB(0)X (hidden `ref_*` parameters tied
  to the source peak). `core/xps/casaxps_lineshape.py` parses/formats GL, SGL, GL(m,n), LA, LF, A(a,n,m)GL/SGL, DS and
  the SB prefix; all recipe strings round-trip and match the recipe kinds/params. T(k), ST, PHI and TP deferred (user
  decision: not defined in the project literature). Metallic Co/Ir recipes use LA/LF, which have areas since F3.
- **Done when:** Metallic Co/Ir recipes with asymmetric shapes yield areas, and the string parser round-trips the shapes used in the recipes.

#### M1. Linear least squares with reference spectra
- **CasaXPS ref:**
  - Linear least squares (LLS) via SVD with positivity, using basis spectra from references or difference spectra. It needs calibrated, re-binned data and a residual STD of about 1 (CB p.101–106).
  - "Generate Spectra" writes the scaled components out (BB p.92–99).
  - Recommended for multiplet-rich oxides (Fe, Cr, and also Co).
- **Current state:**
  - `reference_transform` does subtract or divide only.
  - `align_resample` re-bins.
  - No NNLS or LLS (a grep for nnls or lstsq finds nothing).
- **Build:**
  - A fitting component type `reference_spectrum`: amplitude-only, optional shift, taken from a chosen dataset spectrum or a stored reference library.
  - NNLS for linear-only models; joint non-linear fitting when it is mixed with synthetic peaks.
  - A reference-spectrum library store with provenance. Output scaled components and fractions.
- **Implementation notes (done 2026-11-05):** `infra/reference_spectra_store.py` (per user, user decision; unit-area
  normalisation so amp = area; SHA-256; provenance), `/references` REST (inline processed spectrum, raw dataset
  spectrum, two-column text import, rename, delete), component `reference_spectrum` (`core/preprocess/reference_component.py`;
  options reference_id + reference_sha256 checked at fit time; shift fixed 0 by default, user decision), exact NNLS
  (`fit_references_nnls`) for pure-reference models with fixed shifts, joint lmfit fit otherwise. Fitting-component only
  (no standalone LLS tool, user decision). UI: "Reference spectra library" panel + reference picker; MCP get/post/delete.
- **Done when:** A mixture of two measured references is recovered with correct fractions, and the result can be mixed with GL peaks in one fit.

#### S1. Fit robustness: "Test Peak Model"
- **CasaXPS ref:** Test Peak Model scans a line-shape parameter or a constrained parameter across an interval, writing χ² and %area profiles, or fits noise replicates; the result is overlaid to show unstable components (CB p.119–125).
- **Current state:** `api/services/sweep_runner.py` sweeps fixed parameters and refits (API/MCP, **no UI**).
- **Build:**
  - Expose sweeps in the UI as "Test peak model", with χ²-vs-parameter and %area-vs-parameter plots.
  - Add a noise-replicate mode that shares the Monte Carlo engine from F2.
  - Add line-shape parameter scans across all components with the same index.
- **Implementation notes (done 2026-11-05):** `core/metrics/peak_model_test.py` (scan one parameter or the same parameter
  of every component of a type; noise replicates on the F2 Monte Carlo engine with overlay curves and %area
  distributions), `POST /fitting/test-peak-model`, Prepare "Test peak model" panel (chi2 and %area profiles; overlay +
  histograms), Analyze sweep panel on the existing sweep job (now with `pct:<id>` columns and a JSON summary at
  `GET /analysis/sweep-jobs/{id}/summary`), MCP `post_fitting_test_peak_model` / `get_analysis_sweep_summary`.
- **Done when:** From the fitting editor, a user can scan the position of one component and see the χ² and %area profile plots.

#### R3. Fit-quality warnings (MAJOR Table I)
- **Current state:** fit health exists: n_at_bound, bg_gt_data_frac, residual autocorrelation (`core/preprocess/fit_diagnostics.py`, `frontend/src/preprocess/fitHealth.ts`).
- **Build:** add rule-based warnings, reported in the UI, MCP and R1:
  - FWHM spread among components of one chemical-state family above about ±10 % or 0.1 eV;
  - FWHM below the instrument resolution (from the instrument profile, Q2);
  - only one spin-orbit partner inside the fit window (this is K5);
  - background crossing the data;
  - normalised residual STD far from 1;
  - more components than the information criteria support (ΔAIC/BIC against a model with one fewer component);
  - components at bounds;
  - a fit shown on smoothed data only.
- **Done when:** Each rule has a test that triggers it, and the warnings appear in the report.

#### R4. Tags and formula reports
- **CasaXPS ref:**
  - Components and regions can carry Tags. Items with the same name are summed.
  - The Custom Report offers formulae, ratios and tag sums (CB p.131, 138–141; BB p.81–91).
  - The Auger parameter and Wagner plots are built from the Custom Report (casa-software.com video 16).
- **Current state:** `feature_operations` evaluates formulas over features (`core/metrics/feature_operations.py`). Components have no tag concept.
- **Build:**
  - Add a `tag` field to fitting components and recipes (e.g. `Co3+`, `Co2+`, `satellite`).
  - Automatically sum area and at.% by tag.
  - Make quantification items (Q1) available as variables in `feature_operations`.
  - Provide a modified Auger parameter helper.
- **Done when:** A Co 2p fit outputs `tag_Co2+_pct` and `tag_Co3+_pct` summed over the main lines and satellites.

#### D1. Depth profiles and series
- **CasaXPS ref:**
  - The experimental variable (etch time, depth, temperature, angle) organises blocks into rows. Quantification is propagated across the rows and profiles are created from report tables (CB p.127–144; BB p.43–49, 339–342).
  - The Adjust Experimental Variable dialog converts etch time to depth using a sputter rate (CB p.142–144).
  - Normalise to total intensity per layer.
  - Per-layer energy calibration (REV).
- **Current state:**
  - Label-based series exist (current density, potential, time) with parameter plots (`frontend/src/analyze/ParamPlotEditor.tsx`).
  - `x_axis_calibration` supports grouped charge correction.
  - No etch-time/depth handling and no at.%-vs-variable profile, because there is no quantification yet.
- **Build:**
  - Read the experimental variable from VAMAS/SLE metadata (etch time, cycle) into labels.
  - Add a "profile" view of at.% (Q1) or tag % (R4) against any numeric label.
  - Convert etch time to depth with a sputter rate, either piecewise per layer or extrapolated.
  - Export profiles as CSV and as a figure.
- **Done when:** A sputter depth-profile VAMAS file produces at.% vs etch time and at.% vs depth, matching CasaXPS on the same data.

#### D2. Propagation with per-spectrum overrides and sequential seeding
- **CasaXPS ref:**
  - Copy and Fit, Browser Operations "Propagate", and Copy Names/TAGs/RSFs only (CB p.112–116, 130–131).
  - Each block keeps its own adjustments after a propagation (BB p.130–133).
- **Current state:** a pipeline step applies the same parameters to all spectra (region-filtered). There are no per-spectrum overrides and no option to seed each fit from the previous spectrum in a series.
- **Build:**
  - Store per-spectrum parameter overrides in a session or run, keyed by spectrum id. Overrides are part of the hash.
  - Add a "seed from neighbour" mode along a sorted numeric label (useful for in-situ series).
  - In the UI, "Apply to all" and "Override for this spectrum".
- **Done when:** In a 20-spectrum series, two spectra carry overrides; re-running reproduces exactly, and the report lists the overrides.

#### X1. Interactive fitting UX
- **CasaXPS ref:**
  - Drag a peak maximum to move it; new peaks are placed at the largest residual (BB p.34–35).
  - Region limits are draggable on the plot (BB p.30–31).
  - STORE/RECALL/RESET of model states, with every fit saved to a history (CB p.119).
- **Current state:** all editing is through forms. The only `plotly_click` handler is on the Analyze heatmap (`AnalyzeWorkspace.tsx:1552`). There is no brush selection and no fit history.
- **Build:**
  - Plotly editable shapes or a drag layer in the fitting preview: drag a component for position and height, drag its width.
  - Brush to set the fit window or region.
  - An "Add peak at max residual" button.
  - A fit history (stack of parameter snapshots per session step) with recall and compare.
- **Done when:** A full Co 2p model can be set up and adjusted without typing positions, and the previous fit states can be recalled.

#### X2. Element and chemical-state identification UI
- **CasaXPS ref:**
  - The element library dialog marks lines on the spectrum, with Find Peaks, Create Regions, and Zoom/Create When Line Selected (CB p.161–166; BB p.25–35).
  - Periodic-table selection.
  - Annotation peak labels.
- **Current state:** the chemical-state library (`core/xps/chemical_states.py`, 141 sections) is available through API and MCP only; it has no UI. There are no survey markers.
- **Build:**
  - Survey view with element-line markers from the Q1 library; a periodic-table picker; auto-detect peaks; create quantification regions from the markers.
  - Narrow-scan view: chemical-state reference markers from the chemical-state library, with BE ± spread, shown on the fit plot.
- **Done when:** A survey can be labelled and quantified from the UI, and the Co 2p view shows Co⁰/Co²⁺/Co³⁺ reference markers.

#### X3. UI and MCP parity fixes (existing backend features)
| Feature | What is missing |
|---|---|
| `GET /xps/chemical-states` | UI (part of X2) |
| `GET /datasets/{id}/casa-fits` | UI viewer (part of IO3) |
| `POST /analysis/runs/{id}/sweep-jobs` | UI (part of S1) |
| `POST /analysis/runs/{id}/step-outputs-jobs` | MCP tool |
| `GET /analysis/runs/{id}/spectra/{sid}`, `GET /analysis/runs/{id}/pipeline-steps` | MCP tools |
| `PUT /pipelines/{id}`, the delete endpoints | MCP tools, behind the confirmation gate in `sf/mcp/confirm.py` |
| Recipe MCP tools | Should read the dataset pass energy (deferred item from `CLAUDE.md`) |

**Done when:** each row is reachable from both the UI and MCP; tests are added to the MCP tool tests.

#### IO2. Generic ASCII and SPECS `.xy`
- **Current state:** `ascii_xy` registers only `.txt` (`core/io/formats/ascii_xy.py`).
- **Build:**
  - Accept `.xy`, `.dat`, `.csv` and `.tsv`, sniffing the delimiter.
  - Parse the SPECS Prodigy `.xy` export header (region name, pass energy, excitation energy, dwell, scans, and the multiple regions and cycles in one file).
  - BE/KE detection.
- **Done when:** A Prodigy `.xy` export with several regions loads with region labels and pass energy.

#### IO3. CasaXPS interoperability
- **Current state:** `core/io/casa_fit.py` parses CasaXPS region and component comments from VAMAS. The data is shown only as reference (REST/MCP `casa-fits`). Nothing turns it into a fitting step.
- **Build:**
  - Convert parsed CasaXPS regions and components into a SpecFlow `fitting` step plus a quantification-region definition. This uses the L1 string parser and maps constraints onto F4 expressions.
  - Show differences side by side: CasaXPS result vs SpecFlow refit.
  - Optional (P2): export SpecFlow fits back to VAMAS with CASA comment lines, so colleagues on CasaXPS can open them.
- **Done when:** A CasaXPS-fitted VAMAS file is refitted in SpecFlow from its own model, and the parameters agree within tolerance.

#### K4. Recipe `satellite_of` field (deferred)
- **Build:**
  - Add an explicit `satellite_of: <peak index>` to the recipe peak schema. Insert it with targeted text edits, per `CLAUDE.md`.
  - Use it in `recipe_apply.py` instead of inferring the parent from order.
  - Validate it in `core/xps/catalog_validate.py`.

#### K5. Fit-window check against the spin-orbit partner (deferred)
- **Build:** when a recipe or doublet has a partner line that falls outside `fit_min_x`/`fit_max_x`, emit a warning or extend the window. This rule is also part of R3.

### P2: extensions

#### M2. NMF / MCR-ALS
- **Why:** physically interpretable (non-negative) components for in-situ series and maps. In the literature, MCR-ALS beats PCA on XPS maps.
- **Current state:** the multivariate tools are PCA, sparse PCA, FPCA and k-means (`api/routers/explore.py`); there is no NMF or MCR.
- **Build:**
  - Add NMF (scikit-learn) and MCR-ALS (pyMCR, or a small own implementation) as matrix-job methods. Support non-negativity and closure constraints and initialisation from references (M1).
  - Plots: component spectra and concentration vs label.

#### M3. Spectral PCA in the CasaXPS sense
- **CasaXPS ref:**
  - PCA page: covariance/correlation about origin, iterative SVD and NIPALS, factor count by a noise criterion, "Predict using Factors" for noise reduction, Target FA, linear regression with positivity (CB p.53–58; BB p.95–96).
- **Current state:** FPCA-discrete exists for exploration. There is no reconstruction, target factor analysis, or factor-count rule based on the residual STD.
- **Build:**
  - A pipeline step "PCA reconstruct" that keeps N factors, for noise reduction.
  - A factor-count suggestion from the residual STD (needs F1).
  - Target factor analysis against reference spectra.

#### IM1. XPS imaging and mapping
- **CasaXPS ref:**
  - Image stacks become per-pixel spectra (BB p.108–122).
  - Images can be built from regions or components: area, peak-to-peak, FWHM, position, centroid (BB p.120–121, 182–185).
  - Quantified %-maps.
  - Spectra can be extracted from false-colour zones as ROI spectra (BB p.185–187, 194–197).
  - Image tools (BB p.187): arithmetic, histogram equalisation, line scans, PCA/NIPALS/target factor analysis on images.
  - Kratos and Thermo image acquisitions are treated as equivalent data sets (Imaging XPS, SIA 2024).
- **Current state:** maps exist only for Raman (WDF/TXT), with map info, preview and points plots (`api/routers/plot.py`, legacy `ui/plot.js`). XPS has no spatial data model.
- **Build:**
  - Generalise the map data model so XPS spectra can carry (x, y).
  - Importers for image stacks (VAMAS spatial blocks via IO1; PHI `.map` via IO4).
  - Run the pipeline per pixel (the existing parallel engine).
  - Map any fit or quant feature.
  - Select an ROI by threshold or brush, then sum the spectra.
  - Line scans.
  - Matrix jobs run on map spectra (PCA from M3, NMF from M2).

#### IO4. Vendor native formats
- **Refs:**
  - CasaXPS converters (REV; RBD; BB p.294–324): PHI MultiPak `.spe`/`.pro`/`.map` (with the transmission parameters and angle in the header), Thermo Avantage `.avg` directories (one `.vms` per folder; the `.dth` recursive filter), Kratos `.kal`, Scienta `.pxt`/`.txt`/`.ibw`, SpecsLab 1 `.exp`.
  - The open-source pynxtools-xps parsers cover Scienta, SPECS, PHI and VAMAS (https://fairmat-nfdi.github.io/pynxtools-xps). Check the licence before vendoring.
- **Suggested order, by how common each instrument is in the group or at partner facilities:**
  1. Thermo `.avg` directory
  2. PHI `.spe`/`.pro`
  3. Kratos `.kal`
  4. Scienta `.txt`/`.ibw`
- **Rule:** each importer must fill the IO1 metadata (counts, dwell, pass energy, lens mode, angle, transmission) so that Q2 works.

#### C1. Transmission-function builder
- **CasaXPS ref:** relative transmission functions from Au/Ag reference surveys. Per pass energy and lens mode: background-only regions, ratio to a reference spectrum, polynomial fit. Applied automatically on import by an instrument and lens-mode naming convention (CB p.145–155, 177–184).
- **Build:**
  - A wizard (UI + MCP) that takes reference surveys and produces a transmission entry in the instrument profile (Q2).
  - A consistency check that compares two lines of the same element at different kinetic energies (e.g. Na 1s vs Na 2s, CB p.97–98).

#### C2. X-ray satellite subtraction
For non-monochromatic Mg/Al sources: subtract Kα3/4 (and Kβ) satellites using standard offsets and intensities (RBD; ISO19830 clause 7). Implement it as a pipeline step.

#### C3. Spike removal for XPS
`cosmic_ray_removal` is restricted to vibrational data (`requires_technique={"vibrational"}`). Validate it on XPS data and enable it there, or add an XPS-specific despike step.

#### F5. Global fitting across spectra and regions
- **Why:**
  - Shared FWHM or line shape across a depth profile or in-situ series.
  - Constraints that span regions, such as a C–O component linked between C 1s and O 1s (MAJOR Table I).
  - CasaXPS lets constraints span acquisition regions (REV).
- **Build:**
  - A multi-spectrum fitting problem with shared parameters. lmfit supports this through a concatenated residual.
  - A UI to choose which parameters are shared.

#### D3. Overlayer thickness
- **CasaXPS ref:** Hill equation in the Custom Report, using an EAL from Seah's formula (CB p.33–35, 133–141).
- **Build:** a helper in `feature_operations` or R4 for d = λ·cosθ·ln(1 + (I_o/I_o∞)/(I_s/I_s∞)), with an EAL/IMFP calculator (TPP-2M) shared with Q2.

#### V1. Valence band and Fermi edge tools
- **CasaXPS ref:** erfc Step/Edge fits give the Fermi edge position and the instrument resolution (CB p.98–100); Fermi-edge fitting with three options (casa-software.com video 7).
- **Current state:** `fermi_edge` component exists; valence-band-referenced calibration exists in `x_axis_calibration`.
- **Build:**
  - Valence-band-maximum determination by linear extrapolation of the leading edge (with uncertainty).
  - Resolution from the Fermi-edge width, stored into the instrument profile for R3.

#### X4. Publication figure composer
- **CasaXPS ref:** overlays and offset stacks, on-plot component and quantification tables, peak labels, an annotation history, about 600-dpi export (BB p.13–14, 29–53; RBD).
- **Current state:** publication Plotly theme, PNG/SVG download, overlay and stack modes. No on-plot tables or labels.
- **Build:**
  - Multi-panel figures (regions side by side, series as a waterfall).
  - Component colours stay consistent across panels.
  - Optional on-plot tables and labels.
  - Vector export, plus a Python script that reproduces the figure.

### P3: low priority

- **A1. ARXPS:** tilt angle as an experimental variable (PHI `.ang`, BB p.294–297), relative-depth plots, thickness from an angle series or thickogram. Depends on D3.
- **S2. Limit of detection and S/N:** CasaXPS's "Limit of Detection" background shows one Poisson SD above a linear background (CB p.19–20). Report S/N per region.
- **T1. Synthetic test-data generator:** spectra with known components, background and Poisson noise. Useful for validating F1, F2, M1 and S1, and for the help tutorials. CasaXPS has a Test Data page for this (BB p.93–94).
- **K6. Cosmetic:** DS/GDS parameter units are labelled `cm^-1` (`core/preprocess/fitting_specs.py:207`, vibrational heritage). Should be eV for XPS.

---

## 6. Where SpecFlow already matches or exceeds CasaXPS (keep and build on)

- **Agent automation:** an MCP tool surface covering datasets, pipelines, sessions, runs, recipes and exports, with confirmation gates. CasaXPS only offers socket remote control.
- **Reproducibility:**
  - declarative pipelines with pipeline, subset and input hashes;
  - per-step `impl_version`;
  - content-addressed blobs;
  - import/export of pipeline packages.
- **Fitting recipes:** 133 Biesinger compound fits plus method defaults (`core/xps/data/fitting_recipes.json`). CasaXPS has no equivalent curated recipe library.
- **Chemical-state library:** 141 element/line sections with provenance (UI still missing, see X2).
- **Active backgrounds:** Shirley, Tougaard and slope backgrounds fitted together with the peaks (lmfitxps).
- **Fit statistics:** information criteria (AIC, BIC, AICc) and fit-health metrics (bounds, residual autocorrelation).
- **Cohort tools:** QC and outlier detection, low-signal filter, group averaging, filename label extraction (pH, potential, current density, …).
- **Exploratory statistics on extracted features:** PCA, sparse PCA, FPCA, k-means, correlation, VIF.
- **Platform:** multi-user web access with ownership scoping, and a help system with tutorials.

## 7. Not planned (explicitly out of scope)

- AES: SG-derivative peak-to-peak quantification, AES libraries keyed by gun energy, JEOL AES library import (BB p.56–99, 105–106, 123–135).
- ToF-SIMS mass calibration and peak identification; dynamic SIMS and SNMS quantification (BB p.136–281).
- CasaXPS window and tile management (experiment frames, MDI, page tile formats), except where a requirement already appears in X1 or X4.

## 8. Open questions for the user before implementation

1. Which instruments and file formats does the group actually use? This sets the order of IO4 and which instrument profiles Q2 starts with.
2. Which RSF set is the group standard: Scofield with an E^n exponent, vendor libraries, or Wagner? Are there licensing limits on vendor libraries? CasaXPS notes that converted Avantage libraries must not be redistributed (BB p.319–321).
3. For K1: is it acceptable to change existing `gl` results in stored runs, or must old runs stay bit-identical through an alias?
4. Should the report (R1) also produce a PDF, or is HTML/Markdown plus JSON enough?

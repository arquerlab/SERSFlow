/** F2: formatting and shaping of parameter uncertainties (covariance ± and Monte Carlo spread). */

export type ComponentUncertainty = {
  component_id: string;
  component_type: string;
  param_keys?: string[];
  params?: Record<string, number>;
  stderr?: Record<string, number | null> | null;
  area?: number | null;
  area_stderr?: number | null;
  area_pct?: number | null;
  area_pct_stderr?: number | null;
};

export type MonteCarloRow = {
  spectrum_id: string;
  component_id: string;
  component_type: string;
  quantity: string;
  best_fit: number | null;
  stderr_cov: number | null;
  mc_mean: number | null;
  mc_sd: number | null;
  mc_p2_5: number | null;
  mc_p50: number | null;
  mc_p97_5: number | null;
  n_ok: number;
  n_requested: number;
  noise_model: string;
};

export type MonteCarloSummary = {
  run_id: string;
  fitting_step_num: number;
  n_replicates: number;
  seed: number;
  spectra: Array<{ spectrum_id: string; error: string | null; n_ok?: number; noise_model?: string; weighting?: string }>;
  rows: MonteCarloRow[];
};

function finite(v: unknown): v is number {
  return typeof v === "number" && Number.isFinite(v);
}

/** Decimal places that show `se` with two significant digits (0 … 8). */
export function decimalsForError(se: number): number {
  if (!finite(se) || se <= 0) return 3;
  const d = 1 - Math.floor(Math.log10(Math.abs(se)));
  return Math.max(0, Math.min(8, d));
}

/** "779.40 ± 0.012" style: the error with 2 significant digits, the value rounded to the same decimal. */
export function formatValueError(value: number | null | undefined, se: number | null | undefined): string {
  if (!finite(value)) return "—";
  if (!finite(se) || se <= 0) {
    const d = Math.abs(value) >= 100 ? 2 : Math.abs(value) >= 1 ? 3 : 4;
    return value.toFixed(d);
  }
  const d = decimalsForError(se);
  return `${value.toFixed(d)} ± ${se.toFixed(d)}`;
}

/** Interval [lo, hi] rounded like `formatValueError` with the given scale. */
export function formatInterval(lo: number | null | undefined, hi: number | null | undefined, scale?: number | null): string {
  if (!finite(lo) || !finite(hi)) return "—";
  const d = decimalsForError(finite(scale) && scale > 0 ? scale : Math.abs(hi - lo) / 4);
  return `[${lo.toFixed(d)}, ${hi.toFixed(d)}]`;
}

/** Display rows for one component: free/linked parameters with errors, fixed ones marked, then area and %area. */
export function componentUncertaintyCells(c: ComponentUncertainty): Array<{ key: string; text: string; fixed: boolean }> {
  const keys = c.param_keys ?? Object.keys(c.params ?? {});
  const out: Array<{ key: string; text: string; fixed: boolean }> = [];
  for (const k of keys) {
    const v = c.params?.[k];
    const se = c.stderr?.[k];
    const fixed = !finite(se);
    out.push({ key: k, text: fixed ? `${formatValueError(v, null)} (fixed)` : formatValueError(v, se), fixed });
  }
  if (finite(c.area)) out.push({ key: "area", text: formatValueError(c.area, c.area_stderr), fixed: false });
  if (finite(c.area_pct)) out.push({ key: "%area", text: formatValueError(c.area_pct, c.area_pct_stderr), fixed: false });
  return out;
}

/** Whether any component carries a covariance error (runs made before F2 have none). */
export function hasAnyStderr(components: ComponentUncertainty[] | null | undefined): boolean {
  return (components ?? []).some(
    (c) => Object.values(c.stderr ?? {}).some((v) => finite(v)) || finite(c.area_stderr) || finite(c.area_pct_stderr)
  );
}

/** Ratio MC SD / covariance error; > ~1.5 flags uncertainty the linearised covariance misses. */
export function mcToCovRatio(r: MonteCarloRow): number | null {
  if (!finite(r.mc_sd) || !finite(r.stderr_cov) || r.stderr_cov <= 0) return null;
  return r.mc_sd / r.stderr_cov;
}

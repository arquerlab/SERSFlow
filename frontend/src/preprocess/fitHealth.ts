import type { FitDiagnostics } from "./api";

export type FitHealthSummary = {
  /** One-line badge text (RMSE / R² / BIC plus the fit-health metrics when present). */
  text: string;
  /** True when something deserves a second look (pinned parameter, background above data, structured residual). */
  warn: boolean;
  /** Human-readable reasons behind ``warn``. */
  reasons: string[];
};

const fmt = (v: number | null | undefined, digits = 3): string =>
  v == null || !Number.isFinite(Number(v)) ? "—" : Number(Number(v).toPrecision(digits)).toString();

/**
 * Fit-health summary of a fit's diagnostics.
 *
 * Thresholds: any parameter on a bound, background above the data in more than 10% of the points,
 * or residual lag-1 autocorrelation above 0.7 (clearly structured residual).
 */
export function fitHealthSummary(d: FitDiagnostics | null | undefined): FitHealthSummary {
  const diag = d ?? {};
  const reasons: string[] = [];
  const atBound = diag.n_at_bound;
  if (atBound != null && atBound > 0) {
    reasons.push(`${atBound} parameter${atBound === 1 ? "" : "s"} at a bound`);
  }
  const bgFrac = diag.bg_gt_data_frac;
  if (bgFrac != null && bgFrac > 0.1) {
    reasons.push(`background above data in ${Math.round(bgFrac * 100)}% of points`);
  }
  const lag1 = diag.resid_lag1_autocorr;
  if (lag1 != null && lag1 > 0.7) {
    reasons.push(`structured residual (lag-1 ${fmt(lag1, 2)})`);
  }
  let text = `RMSE=${fmt(diag.rmse)}  R²=${fmt(diag.r2)}  BIC=${fmt(diag.bic)}`;
  if (lag1 != null || atBound != null) {
    text += `  lag1=${fmt(lag1, 2)}  at-bound=${atBound == null ? "—" : atBound}`;
  }
  if (diag.resid_mean_edge_lo != null || diag.resid_mean_edge_hi != null) {
    text += `  edge resid lo/hi=${fmt(diag.resid_mean_edge_lo, 3)}/${fmt(diag.resid_mean_edge_hi, 3)}`;
  }
  if (reasons.length) text += `  ⚠ ${reasons.join("; ")}`;
  return { text, warn: reasons.length > 0, reasons };
}

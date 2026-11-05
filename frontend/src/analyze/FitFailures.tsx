import type { AnalysisRunSummary } from "./api";

/** Number of fits that failed or did not converge in a run (K2). */
export function fitProblemCount(run: Pick<AnalysisRunSummary, "fit_failures"> | undefined): number {
  const ff = run?.fit_failures;
  if (!ff) return 0;
  return (ff.n_failed ?? 0) + (ff.n_not_converged ?? 0);
}

/** Compact badge for run lists; renders nothing when every fit succeeded. */
export function FitFailureBadge({ run }: { run: AnalysisRunSummary }) {
  const n = fitProblemCount(run);
  if (!n) return null;
  const ff = run.fit_failures!;
  const title =
    `${ff.n_failed} failed, ${ff.n_not_converged} not converged of ${ff.n_fits} fits.\n` +
    "Failed fits keep the raw spectrum; their fit features are empty.";
  return (
    <span className="badge-warn" title={title} data-testid="fit-failure-badge" style={{ marginLeft: 6, whiteSpace: "nowrap" }}>
      ⚠ {n} fit{n === 1 ? "" : "s"}
    </span>
  );
}

/** Detail panel for the selected run (Overview). */
export function FitFailurePanel({ run }: { run: AnalysisRunSummary }) {
  const warnings = run.warnings ?? [];
  const ff = run.fit_failures;
  if (!warnings.length && !fitProblemCount(run)) return null;
  return (
    <div className="warn-note" role="status" data-testid="fit-failure-panel" style={{ marginTop: 8 }}>
      {warnings.map((w) => (
        <div key={w}>{w}</div>
      ))}
      {ff && ff.items.length ? (
        <details style={{ marginTop: 4 }}>
          <summary>
            Show {ff.items.length}
            {ff.truncated ? "+" : ""} affected spectra
          </summary>
          <ul style={{ margin: "4px 0 0", paddingLeft: 16, overflowWrap: "anywhere" }}>
            {ff.items.map((it) => {
              const reason = it.reason ?? "";
              const short = reason.length > 140 ? `${reason.slice(0, 140)}…` : reason;
              return (
                <li key={`${it.spectrum_id}-${it.step_id ?? it.step_index}`} title={reason} style={{ marginBottom: 2 }}>
                  <span style={{ fontFamily: "var(--mono)" }}>{it.spectrum_id}</span>
                  {it.xps_region ? ` · ${it.xps_region}` : ""}
                  {it.step_id ? ` · ${it.step_id}` : ""} · <b>{it.status === "failed" ? "failed" : "not converged"}</b>
                  {short ? ` — ${short}` : ""}
                </li>
              );
            })}
          </ul>
        </details>
      ) : null}
    </div>
  );
}

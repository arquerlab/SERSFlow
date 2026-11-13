import { useState } from "react";
import { getFitCurveJobDownloadUrl, isAbortError, postReportJob, waitForFitCurveJob } from "./api";
import { useUnmountSignal } from "../lib/useUnmountSignal";

type Props = {
  runId: string;
  stepNum: number | null;
  selectedIds: string[];
  download: (url: string, filename: string, onErr: (msg: string) => void) => Promise<void>;
};

/** R1: publication fit report (zip with report.html, report.md, report.json and figures). */
export function ReportDownload({ runId, stepNum, selectedIds, download }: Props) {
  const [scope, setScope] = useState<"selected" | "all">("selected");
  const [allSteps, setAllSteps] = useState(false);
  const [figures, setFigures] = useState(true);
  const [busy, setBusy] = useState(false);
  const getUnmountSignal = useUnmountSignal();
  const [note, setNote] = useState<string | null>(null);

  async function run() {
    setBusy(true);
    setNote(null);
    try {
      const created = await postReportJob(runId, {
        spectrum_ids: scope === "selected" ? selectedIds : null,
        fitting_step_nums: allSteps || stepNum == null ? null : [stepNum],
        include_figures: figures,
      });
      await waitForFitCurveJob(created.job_id, {
        label: "Report job",
        timeoutS: 3600,
        signal: getUnmountSignal(),
        onProgress: (st) => setNote(`Report ${st.status}: ${st.progress_done}/${st.progress_total} fits`),
      });
      await download(getFitCurveJobDownloadUrl(created.job_id), `fit_report_${runId}.zip`, setNote);
      setNote((n) => n ?? "Report downloaded (open report.html; report.json is machine-readable).");
    } catch (e) {
      if (isAbortError(e)) return;
      setNote(String((e as Error)?.message ?? e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div data-testid="report-download" style={{ marginTop: 12 }}>
      <div className="section-title">Publication report</div>
      <p className="hint" style={{ marginTop: 0 }}>
        HTML + Markdown + JSON: file hashes, software version, acquisition, charge correction, processing history, every
        component with line shape, values ± 1σ and constraint status, fit statistics and an annotated figure.
      </p>
      <div className="row" style={{ flexWrap: "wrap", gap: 8, alignItems: "flex-end" }}>
        <label className="inline">
          Spectra
          <select value={scope} onChange={(e) => setScope(e.target.value as "selected" | "all")}>
            <option value="selected">Selected ({selectedIds.length})</option>
            <option value="all">All spectra of the run</option>
          </select>
        </label>
        <label className="inline">
          <input type="checkbox" checked={allSteps} onChange={(e) => setAllSteps(e.target.checked)} />
          All fitting steps
        </label>
        <label className="inline">
          <input type="checkbox" checked={figures} onChange={(e) => setFigures(e.target.checked)} />
          Figures
        </label>
        <button
          type="button"
          className="mini"
          data-testid="report-run"
          disabled={busy || (scope === "selected" && selectedIds.length === 0)}
          onClick={() => void run()}
        >
          {busy ? "Building…" : "Download report"}
        </button>
      </div>
      {note ? (
        <div className="hint" data-testid="report-note" style={{ marginTop: 6 }}>
          {note}
        </div>
      ) : null}
    </div>
  );
}

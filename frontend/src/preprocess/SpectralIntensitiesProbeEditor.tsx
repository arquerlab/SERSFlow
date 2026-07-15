import type { EditorStep } from "./editorTypes";
import type { SpectralProbeEditorRow } from "./spectralIntensitiesUtils";
import { defaultProbeRow } from "./spectralIntensitiesUtils";
import { DraftNumberInput } from "../lib/draftInputs";

type Props = {
  probes: SpectralProbeEditorRow[];
  steps: EditorStep[];
  selectedStepId: string;
  onChange: (next: SpectralProbeEditorRow[]) => void;
};

export function SpectralIntensitiesProbeEditor({ probes, steps, selectedStepId, onChange }: Props) {
  const rows = probes.length ? probes : [defaultProbeRow(0)];
  const selectedStepIndex = steps.findIndex((s) => s.id === selectedStepId);
  const baselineStepOptions =
    selectedStepIndex >= 0
      ? steps
          .slice(0, selectedStepIndex)
          .map((step, index) => ({ step, index }))
          .filter(({ step }) => step.enabled !== false && step.name === "baseline")
      : [];

  function patchRow(i: number, patch: Partial<SpectralProbeEditorRow>) {
    const next = rows.map((r, j) => (j === i ? { ...r, ...patch } : r));
    onChange(next);
  }

  return (
    <div style={{ display: "grid", gap: "10px" }}>
      <div className="hint" style={{ margin: 0 }}>
        Defines analysis feature columns <code>I_*</code> (intensity at a wavenumber or nearest peak). Use{" "}
        <strong>signal</strong> for the processed spectrum wired into this step (<code>input_from</code>), or{" "}
        <strong>baseline</strong> to sample the estimated baseline from an earlier baseline step — useful for comparing
        peak vs baseline distributions.
      </div>
      {rows.map((row, i) => {
        const baselineStepIsInvalid =
          row.source === "baseline" &&
          row.baseline_step_id !== "" &&
          !baselineStepOptions.some(({ step }) => step.id === row.baseline_step_id);

        return (
          <div
            key={i}
            className="card-inner"
            style={{
              display: "grid",
              gap: "8px",
              gridTemplateColumns: "repeat(auto-fill, minmax(160px, 1fr))",
              alignItems: "end",
            }}
          >
            <label className="inline" style={{ flexDirection: "column", alignItems: "stretch", gap: "4px" }}>
              <span className="hint">id (optional)</span>
              <input
                type="text"
                placeholder="auto if empty"
                value={row.id}
                onChange={(e) => patchRow(i, { id: e.target.value })}
              />
            </label>
            <label className="inline" style={{ flexDirection: "column", alignItems: "stretch", gap: "4px" }}>
              <span className="hint">source</span>
              <select
                value={row.source}
                onChange={(e) => {
                  const source = e.target.value === "baseline" ? "baseline" : "signal";
                  const baseline_step_id =
                    source === "baseline"
                      ? row.baseline_step_id || baselineStepOptions[0]?.step.id || ""
                      : "";
                  patchRow(i, { source, baseline_step_id });
                }}
              >
                <option value="signal">signal (processed spectrum)</option>
                <option value="baseline">baseline</option>
              </select>
            </label>
            {row.source === "baseline" ? (
              <label className="inline" style={{ flexDirection: "column", alignItems: "stretch", gap: "4px" }}>
                <span className="hint">baseline step</span>
                <select
                  value={row.baseline_step_id}
                  onChange={(e) => patchRow(i, { baseline_step_id: e.target.value })}
                >
                  <option value="">Select baseline step…</option>
                  {baselineStepOptions.map(({ step, index }) => {
                    const baselineMethod = String((step.params as Record<string, unknown>)?.method || "derpsalsa");
                    return (
                      <option key={step.id} value={step.id}>
                        Step {index + 1}: baseline ({baselineMethod})
                      </option>
                    );
                  })}
                </select>
              </label>
            ) : null}
            <label className="inline" style={{ flexDirection: "column", alignItems: "stretch", gap: "4px" }}>
              <span className="hint">target_cm⁻¹</span>
              <DraftNumberInput
                value={row.target_cm1}
                onChange={(n) => {
                  if (n != null) patchRow(i, { target_cm1: n });
                }}
              />
            </label>
            <label className="inline" style={{ flexDirection: "column", alignItems: "stretch", gap: "4px" }}>
              <span className="hint">acquisition</span>
              <select
                value={row.acquisition}
                onChange={(e) => {
                  const acquisition = e.target.value === "nearest_peak" ? "nearest_peak" : "fixed";
                  patchRow(i, { acquisition, window_cm1: acquisition === "fixed" ? "" : row.window_cm1 || 50 });
                }}
              >
                <option value="fixed">fixed (interpolate at target)</option>
                <option value="nearest_peak">nearest_peak</option>
              </select>
            </label>
            {row.acquisition === "nearest_peak" ? (
              <label className="inline" style={{ flexDirection: "column", alignItems: "stretch", gap: "4px" }}>
                <span className="hint">window_cm⁻¹</span>
                <DraftNumberInput
                  nullable
                  placeholder="optional"
                  value={row.window_cm1 === "" ? null : row.window_cm1}
                  onChange={(n) => patchRow(i, { window_cm1: n === null ? "" : n })}
                />
              </label>
            ) : null}
            <label className="inline" style={{ flexDirection: "column", alignItems: "stretch", gap: "4px" }}>
              <span className="hint">method</span>
              <select
                value={row.method}
                onChange={(e) => patchRow(i, { method: e.target.value === "nearest" ? "nearest" : "linear_interp" })}
              >
                <option value="linear_interp">linear_interp</option>
                <option value="nearest">nearest</option>
              </select>
            </label>
            <label className="inline" style={{ flexDirection: "column", alignItems: "stretch", gap: "4px" }}>
              <span className="hint">extrapolation</span>
              <select
                value={row.extrapolation}
                onChange={(e) => patchRow(i, { extrapolation: e.target.value === "clip" ? "clip" : "nan" })}
              >
                <option value="nan">nan (outside range)</option>
                <option value="clip">clip</option>
              </select>
            </label>
            <label className="inline" style={{ flexDirection: "column", alignItems: "stretch", gap: "4px" }}>
              <span className="hint">no_peak_fallback</span>
              <select
                value={row.no_peak_fallback}
                onChange={(e) =>
                  patchRow(i, { no_peak_fallback: e.target.value === "fixed_nearest" ? "fixed_nearest" : "none" })
                }
              >
                <option value="none">none</option>
                <option value="fixed_nearest">fixed_nearest</option>
              </select>
            </label>
            {row.source === "baseline" && !baselineStepOptions.length ? (
              <div className="hint" style={{ gridColumn: "1 / -1" }}>
                Add or move an enabled baseline step before this intensities step.
              </div>
            ) : null}
            {baselineStepIsInvalid ? (
              <div className="err" style={{ gridColumn: "1 / -1" }}>
                Selected baseline step is no longer an earlier enabled baseline step.
              </div>
            ) : null}
            <div className="row" style={{ alignItems: "flex-end" }}>
              <button
                type="button"
                className="mini danger"
                disabled={rows.length <= 1}
                onClick={() => onChange(rows.filter((_, j) => j !== i))}
              >
                Remove
              </button>
            </div>
          </div>
        );
      })}
      <button
        type="button"
        className="mini"
        onClick={() => onChange([...rows, defaultProbeRow(rows.length)])}
      >
        + Add probe
      </button>
    </div>
  );
}

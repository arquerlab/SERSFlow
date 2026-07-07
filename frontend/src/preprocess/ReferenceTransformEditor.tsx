import type { SpectrumRef } from "./api";
import type { EditorStep } from "./editorTypes";
import type { ReferenceTransformParams } from "./referenceTransformUtils";

type Props = {
  params: ReferenceTransformParams;
  spectra: SpectrumRef[];
  previousSteps: EditorStep[];
  onChange: (next: ReferenceTransformParams) => void;
};

function spectrumLabel(ref: SpectrumRef): string {
  const path = ref.original_relative_path || ref.relative_path || ref.spectrum_id;
  const rec = ref.record_index === null || ref.record_index === undefined ? "" : ` #${ref.record_index}`;
  return `${path}${rec} (${ref.spectrum_id})`;
}

export function ReferenceTransformEditor({ params, spectra, previousSteps, onChange }: Props) {
  const selectedStepStillAvailable =
    params.reference_stage !== "after_step" || previousSteps.some((step) => step.id === params.reference_step_id);

  return (
    <div style={{ display: "grid", gap: "10px" }}>
      <div className="hint" style={{ margin: 0 }}>
        Subtract or divide each spectrum by a selected reference spectrum. The reference spectrum is excluded from
        downstream analysis exports.
      </div>
      <label className="inline" style={{ justifyContent: "space-between", gap: "12px" }}>
        reference file
        <select
          value={params.reference_spectrum_id}
          onChange={(e) => onChange({ ...params, reference_spectrum_id: String(e.target.value || "") })}
          style={{ minWidth: "320px" }}
        >
          <option value="">Select reference spectrum…</option>
          {spectra.map((ref) => (
            <option key={ref.spectrum_id} value={ref.spectrum_id}>
              {spectrumLabel(ref)}
            </option>
          ))}
        </select>
      </label>
      <label className="inline" style={{ justifyContent: "space-between" }}>
        operation
        <select
          value={params.operation}
          onChange={(e) => onChange({ ...params, operation: e.target.value === "divide" ? "divide" : "subtract" })}
        >
          <option value="subtract">subtract reference</option>
          <option value="divide">divide by reference</option>
        </select>
      </label>
      <label className="inline" style={{ justifyContent: "space-between" }}>
        reference stage
        <select
          value={params.reference_stage === "after_step" ? `after:${params.reference_step_id}` : "raw"}
          onChange={(e) => {
            const raw = String(e.target.value || "raw");
            if (raw === "raw") {
              onChange({ ...params, reference_stage: "raw", reference_step_id: "" });
            } else {
              onChange({ ...params, reference_stage: "after_step", reference_step_id: raw.slice("after:".length) });
            }
          }}
        >
          <option value="raw">Raw data</option>
          {previousSteps.map((step, i) => (
            <option key={step.id} value={`after:${step.id}`}>
              After step {i + 1}: {step.name}
            </option>
          ))}
        </select>
      </label>
      {params.reference_stage === "after_step" && !selectedStepStillAvailable ? (
        <div className="err">Selected reference stage is no longer before this step. Choose another stage.</div>
      ) : null}
      {!spectra.length ? <div className="hint">Select a dataset before choosing a reference spectrum.</div> : null}
    </div>
  );
}

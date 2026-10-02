import type { EditorStep } from "../editorTypes";
import { inputSelectValue, parseInputSelectValue, sanitizeStepInputs } from "../editorTypes";

type PipelineStepListProps = {
  steps: EditorStep[];
  selectedStepId: string | null;
  /** Human labels keyed by step name (catalog id). Falls back to technical name. */
  stepLabels?: Record<string, string>;
  onSelectStep: (id: string) => void;
  onStepsChange: (updater: (prev: EditorStep[]) => EditorStep[]) => void;
  onPipelineVersionBump: () => void;
  onSelectedStepCleared: () => void;
};

export function PipelineStepList({
  steps,
  selectedStepId,
  stepLabels,
  onSelectStep,
  onStepsChange,
  onPipelineVersionBump,
  onSelectedStepCleared,
}: PipelineStepListProps) {
  return (
    <div style={{ display: "grid", gap: "8px" }}>
      {steps.map((st, idx) => {
        const label = stepLabels?.[st.name] ?? st.name;
        return (
          <div
            key={st.id}
            className={`card-inner${st.id === selectedStepId ? " is-selected" : ""}`}
            style={{ display: "grid", gap: "4px" }}
          >
            <div className="row" style={{ justifyContent: "space-between", alignItems: "center", gap: "8px" }}>
              <div className="row" style={{ gap: "6px", alignItems: "center", minWidth: 0 }}>
                <button
                  type="button"
                  className={`pipeline-step-title-btn${st.id === selectedStepId ? " is-selected" : ""}`}
                  onClick={() => onSelectStep(st.id)}
                  title={st.name}
                >
                  <span className="pipeline-step-title-text">
                    {idx + 1}. {label}
                  </span>
                </button>

                <div className="row" style={{ gap: "4px", flexWrap: "nowrap" }}>
                  <button
                    type="button"
                    className="mini"
                    onClick={() => {
                      onStepsChange((prev) => {
                        const i = prev.findIndex((p) => p.id === st.id);
                        if (i <= 0) return prev;
                        const next = prev.slice();
                        const [it] = next.splice(i, 1);
                        next.splice(i - 1, 0, it);
                        return sanitizeStepInputs(next);
                      });
                      onPipelineVersionBump();
                    }}
                    disabled={idx === 0}
                    title="Move up"
                  >
                    ↑
                  </button>
                  <button
                    type="button"
                    className="mini"
                    onClick={() => {
                      onStepsChange((prev) => {
                        const i = prev.findIndex((p) => p.id === st.id);
                        if (i < 0 || i === prev.length - 1) return prev;
                        const next = prev.slice();
                        const [it] = next.splice(i, 1);
                        next.splice(i + 1, 0, it);
                        return sanitizeStepInputs(next);
                      });
                      onPipelineVersionBump();
                    }}
                    disabled={idx === steps.length - 1}
                    title="Move down"
                  >
                    ↓
                  </button>
                  <button
                    type="button"
                    className="mini"
                    onClick={() => {
                      onStepsChange((prev) => prev.map((p) => (p.id === st.id ? { ...p, enabled: !p.enabled } : p)));
                      onPipelineVersionBump();
                    }}
                    title={st.enabled ? "Disable step" : "Enable step"}
                  >
                    {st.enabled ? "OFF" : "ON"}
                  </button>
                  <button
                    type="button"
                    className="mini danger"
                    onClick={() => {
                      onStepsChange((prev) => sanitizeStepInputs(prev.filter((p) => p.id !== st.id)));
                      if (selectedStepId === st.id) onSelectedStepCleared();
                      onPipelineVersionBump();
                    }}
                    title="Delete step"
                  >
                    Del
                  </button>
                </div>
              </div>

              <select
                className="mini"
                title="Input XY for this step"
                value={inputSelectValue(st)}
                onChange={(e) => {
                  const v = String(e.target.value || "");
                  const parsed = parseInputSelectValue(v);
                  onStepsChange((prev) => sanitizeStepInputs(prev.map((p) => (p.id === st.id ? { ...p, ...parsed } : p))));
                  onPipelineVersionBump();
                }}
              >
                <option value="previous">Previous</option>
                <option value="initial">Initial</option>
                {steps.slice(0, idx).map((prev, i) => (
                  <option key={prev.id} value={`after:${prev.id}`}>
                    After step {i + 1}: {stepLabels?.[prev.name] ?? prev.name}
                  </option>
                ))}
              </select>
            </div>
          </div>
        );
      })}
    </div>
  );
}

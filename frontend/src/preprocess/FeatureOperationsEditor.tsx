import type { FeatureOperationEditorRow, FeatureVariable } from "./featureOperationsUtils";
import { defaultFeatureOperationRow } from "./featureOperationsUtils";

type Props = {
  operations: FeatureOperationEditorRow[];
  variables: FeatureVariable[];
  onChange: (next: FeatureOperationEditorRow[]) => void;
};

const helpText =
  "Use feature columns inside curly braces, for example {fit_p1_area}/{area_band1}**0.25. " +
  "Allowed operators: +, -, *, /, **, %, parentheses, and functions abs, sqrt, log, log10, exp, min, max. " +
  "Formulas are evaluated per spectrum; missing or invalid values export as empty cells.";

export function FeatureOperationsEditor({ operations, variables, onChange }: Props) {
  const rows = operations.length ? operations : [defaultFeatureOperationRow(0)];

  function patchRow(i: number, patch: Partial<FeatureOperationEditorRow>) {
    onChange(rows.map((row, j) => (j === i ? { ...row, ...patch } : row)));
  }

  function insertVariable(i: number, key: string) {
    const row = rows[i] ?? defaultFeatureOperationRow(i);
    patchRow(i, { formula: `${row.formula}{${key}}` });
  }

  return (
    <div style={{ display: "grid", gap: "10px" }}>
      <div className="hint" style={{ margin: 0 }}>
        Derived feature columns from previous extracted features.{" "}
        <button type="button" className="param-help" title={helpText} aria-label={helpText}>
          ?
        </button>
      </div>
      {rows.map((row, i) => (
        <div key={i} className="card-inner" style={{ display: "grid", gap: "8px" }}>
          <div
            style={{
              display: "grid",
              gap: "8px",
              gridTemplateColumns: "minmax(120px, 180px) 1fr auto",
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
              <span className="hint">formula</span>
              <input
                type="text"
                placeholder="{fit_p1_area}/{area_band1}**0.25"
                value={row.formula}
                onChange={(e) => patchRow(i, { formula: e.target.value })}
              />
            </label>
            <button
              type="button"
              className="mini danger"
              disabled={rows.length <= 1}
              onClick={() => onChange(rows.filter((_, j) => j !== i))}
            >
              Remove
            </button>
          </div>
          {variables.length ? (
            <div className="row" style={{ gap: "6px", alignItems: "center" }}>
              <span className="hint">Insert variable</span>
              <select value="" onChange={(e) => e.target.value && insertVariable(i, e.target.value)}>
                <option value="">Select feature…</option>
                {variables.map((v) => (
                  <option key={`${v.source}:${v.key}`} value={v.key}>
                    {v.key}
                  </option>
                ))}
              </select>
            </div>
          ) : null}
        </div>
      ))}
      <button type="button" className="mini" onClick={() => onChange([...rows, defaultFeatureOperationRow(rows.length)])}>
        + Add operation
      </button>
      <div className="card-inner" style={{ display: "grid", gap: "6px" }}>
        <div className="hint" style={{ fontWeight: 800 }}>
          Variables available from previous feature steps
        </div>
        {variables.length ? (
          <div style={{ display: "grid", gap: "4px", maxHeight: "180px", overflow: "auto" }}>
            {variables.map((v) => (
              <button
                key={`${v.source}:${v.key}`}
                type="button"
                className="mini"
                style={{ justifyContent: "space-between", display: "flex" }}
                title={`Click to copy ${v.key}`}
                onClick={() => navigator.clipboard?.writeText(`{${v.key}}`).catch(() => undefined)}
              >
                <code>{`{${v.key}}`}</code>
                <span className="hint">{v.source}</span>
              </button>
            ))}
          </div>
        ) : (
          <div className="hint">Add fitting, intensities, or integration steps before this operation step.</div>
        )}
      </div>
    </div>
  );
}

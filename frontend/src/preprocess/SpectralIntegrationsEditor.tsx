import type { IntegrationMode, IntegrationWindowEditorRow } from "./spectralIntegrationsUtils";
import { defaultIntegrationRow } from "./spectralIntegrationsUtils";

type Props = {
  windows: IntegrationWindowEditorRow[];
  onChange: (next: IntegrationWindowEditorRow[]) => void;
};

const modes: { value: IntegrationMode; label: string }[] = [
  { value: "signed", label: "signed" },
  { value: "positive", label: "positive only" },
  { value: "absolute", label: "absolute" },
];

export function SpectralIntegrationsEditor({ windows, onChange }: Props) {
  const rows = windows.length ? windows : [defaultIntegrationRow(0)];

  function patchRow(i: number, patch: Partial<IntegrationWindowEditorRow>) {
    onChange(rows.map((row, j) => (j === i ? { ...row, ...patch } : row)));
  }

  return (
    <div style={{ display: "grid", gap: "10px" }}>
      <div className="hint" style={{ margin: 0 }}>
        Defines analysis feature columns <code>area_*</code> by trapezoid integration over each wavenumber window.
      </div>
      {rows.map((row, i) => (
        <div
          key={i}
          className="card-inner"
          style={{
            display: "grid",
            gap: "8px",
            gridTemplateColumns: "repeat(auto-fill, minmax(150px, 1fr))",
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
            <span className="hint">min_cm⁻¹</span>
            <input
              type="number"
              value={row.min_cm1}
              onChange={(e) => {
                const n = Number(e.target.value);
                patchRow(i, { min_cm1: Number.isFinite(n) ? n : row.min_cm1 });
              }}
            />
          </label>
          <label className="inline" style={{ flexDirection: "column", alignItems: "stretch", gap: "4px" }}>
            <span className="hint">max_cm⁻¹</span>
            <input
              type="number"
              value={row.max_cm1}
              onChange={(e) => {
                const n = Number(e.target.value);
                patchRow(i, { max_cm1: Number.isFinite(n) ? n : row.max_cm1 });
              }}
            />
          </label>
          <label className="inline" style={{ flexDirection: "column", alignItems: "stretch", gap: "4px" }}>
            <span className="hint">mode</span>
            <select value={row.mode} onChange={(e) => patchRow(i, { mode: e.target.value as IntegrationMode })}>
              {modes.map((mode) => (
                <option key={mode.value} value={mode.value}>
                  {mode.label}
                </option>
              ))}
            </select>
          </label>
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
      ))}
      <button type="button" className="mini" onClick={() => onChange([...rows, defaultIntegrationRow(rows.length)])}>
        + Add window
      </button>
    </div>
  );
}

import type { SpectralProbeEditorRow } from "./spectralIntensitiesUtils";
import { defaultProbeRow } from "./spectralIntensitiesUtils";

type Props = {
  probes: SpectralProbeEditorRow[];
  onChange: (next: SpectralProbeEditorRow[]) => void;
};

export function SpectralIntensitiesProbeEditor({ probes, onChange }: Props) {
  const rows = probes.length ? probes : [defaultProbeRow(0)];

  function patchRow(i: number, patch: Partial<SpectralProbeEditorRow>) {
    const next = rows.map((r, j) => (j === i ? { ...r, ...patch } : r));
    onChange(next);
  }

  return (
    <div style={{ display: "grid", gap: "10px" }}>
      <div className="hint" style={{ margin: 0 }}>
        Defines analysis feature columns <code>I_*</code> (intensity at a wavenumber or nearest peak). Add one row per band.
      </div>
      {rows.map((row, i) => (
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
            <span className="hint">target_cm⁻¹</span>
            <input
              type="number"
              value={row.target_cm1}
              onChange={(e) => {
                const n = Number(e.target.value);
                patchRow(i, { target_cm1: Number.isFinite(n) ? n : row.target_cm1 });
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
              <input
                type="number"
                placeholder="optional"
                value={row.window_cm1 === "" ? "" : row.window_cm1}
                onChange={(e) => {
                  const raw = e.target.value.trim();
                  if (raw === "") patchRow(i, { window_cm1: "" });
                  else {
                    const n = Number(raw);
                    patchRow(i, { window_cm1: Number.isFinite(n) ? n : "" });
                  }
                }}
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

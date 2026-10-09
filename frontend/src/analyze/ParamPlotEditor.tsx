import { PARAM_PLOT_STYLES, selectedYs, type ParamPlotConfig, type ParamPlotStyle } from "./paramPlots";

type Props = {
  index: number;
  config: ParamPlotConfig;
  columns: string[];
  busy: boolean;
  hasResult: boolean;
  canRemove: boolean;
  onChange: (next: ParamPlotConfig) => void;
  onRemove: () => void;
  onPlot: () => void;
  onExportImage: (format: "png" | "svg") => void;
  onExportCsv: () => void;
};

function ColumnSelect({ value, columns, onChange }: { value: string; columns: string[]; onChange: (v: string) => void }) {
  return (
    <select value={value} onChange={(e) => onChange(e.target.value)}>
      <option value="">—</option>
      {columns.map((c) => (
        <option key={c} value={c}>
          {c}
        </option>
      ))}
    </select>
  );
}

export function ParamPlotEditor({
  index,
  config,
  columns,
  busy,
  hasResult,
  canRemove,
  onChange,
  onRemove,
  onPlot,
  onExportImage,
  onExportCsv,
}: Props) {
  const set = (patch: Partial<ParamPlotConfig>) => onChange({ ...config, ...patch });
  const ys = selectedYs(config);
  const withErrors = config.style === "errorbars" || config.style === "errorbars_line";

  return (
    <div style={{ border: "1px solid #ddd", borderRadius: 4, padding: 8, marginTop: 8 }}>
      <div className="row" style={{ justifyContent: "space-between", alignItems: "center" }}>
        <strong>Plot {index + 1}</strong>
        {canRemove ? (
          <button type="button" className="mini" onClick={onRemove} title="Remove this plot">
            Remove
          </button>
        ) : null}
      </div>
      <div className="row" style={{ flexWrap: "wrap", gap: "8px", alignItems: "flex-end" }}>
        <label className="inline">
          Style
          <select value={config.style} onChange={(e) => set({ style: e.target.value as ParamPlotStyle })}>
            {PARAM_PLOT_STYLES.map((s) => (
              <option key={s.value} value={s.value}>
                {s.label}
              </option>
            ))}
          </select>
        </label>
        <label className="inline">
          X
          <ColumnSelect value={config.x} columns={columns} onChange={(v) => set({ x: v })} />
        </label>
        <label className="inline">
          Color (optional)
          <ColumnSelect value={config.color} columns={columns} onChange={(v) => set({ color: v })} />
        </label>
        {withErrors ? (
          <label className="inline">
            X error (optional)
            <ColumnSelect value={config.xErr} columns={columns} onChange={(v) => set({ xErr: v })} />
          </label>
        ) : null}
        {withErrors && ys.length <= 1 ? (
          <label className="inline">
            Y error (optional)
            <ColumnSelect value={config.yErr} columns={columns} onChange={(v) => set({ yErr: v })} />
          </label>
        ) : null}
      </div>
      <div className="row" style={{ flexWrap: "wrap", gap: "8px", alignItems: "flex-end", marginTop: 4 }}>
        {config.ys.map((y, i) => (
          <label key={i} className="inline">
            {config.ys.length > 1 ? `Y${i + 1}` : "Y"}
            <span className="row" style={{ gap: 2 }}>
              <ColumnSelect
                value={y}
                columns={columns}
                onChange={(v) => set({ ys: config.ys.map((old, j) => (j === i ? v : old)) })}
              />
              {config.ys.length > 1 ? (
                <button
                  type="button"
                  className="mini"
                  title="Remove this Y column"
                  onClick={() => set({ ys: config.ys.filter((_, j) => j !== i) })}
                >
                  ×
                </button>
              ) : null}
            </span>
          </label>
        ))}
        <button type="button" className="mini" onClick={() => set({ ys: [...config.ys, ""] })}>
          + Y column
        </button>
      </div>
      {withErrors && ys.length > 1 ? (
        <div className="hint">With several Y columns, error bars are the standard deviation within each X group.</div>
      ) : null}
      {config.color && ys.length > 1 && config.style !== "scatter" && config.style !== "line" ? (
        <div className="hint">Color grouping is ignored when several Y columns are selected.</div>
      ) : null}
      <div className="row" style={{ flexWrap: "wrap", gap: "8px", marginTop: 6 }}>
        <button type="button" disabled={busy || !config.x || !ys.length} onClick={onPlot}>
          {busy ? "Loading…" : "Plot"}
        </button>
        <button type="button" disabled={!hasResult} onClick={() => onExportImage("png")}>
          Export plot (PNG)
        </button>
        <button type="button" disabled={!hasResult} onClick={() => onExportImage("svg")}>
          Export plot (SVG)
        </button>
        <button type="button" disabled={!hasResult} onClick={onExportCsv}>
          Export CSV
        </button>
      </div>
    </div>
  );
}

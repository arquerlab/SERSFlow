import { useMemo, useState } from "react";
import { PlotlyWrapper } from "./legacy-wrappers/PlotlyWrapper";
import { SpectrumCheckboxListWrapper } from "./legacy-wrappers/SpectrumCheckboxListWrapper";

export default function PreprocessingWorkspace() {
  const [selected, setSelected] = useState<string[]>([]);
  const [ghost, setGhost] = useState(true);
  const [mode, setMode] = useState<"overlay" | "stack">("overlay");
  const [sep, setSep] = useState(1000);

  const fig = useMemo(() => {
    // Placeholder figure so PlotlyWrapper proves it works (no backend wiring yet).
    const x = Array.from({ length: 200 }, (_, i) => i);
    const mk = (phase: number, name: string) => ({
      type: "scatter",
      mode: "lines",
      x,
      y: x.map((v) => Math.sin(v / 10 + phase) * 100 + 1000),
      name,
    });
    return {
      data: [mk(0, "trace_a"), mk(1, "trace_b")],
      layout: { margin: { l: 50, r: 20, t: 10, b: 40 } },
    };
  }, []);

  return (
    <div style={{ padding: 6 }}>
      <div style={{ display: "flex", gap: 12, alignItems: "center", flexWrap: "wrap" }}>
        <label style={{ display: "inline-flex", gap: 8, alignItems: "center" }}>
          Plot mode
          <select value={mode} onChange={(e) => setMode(e.target.value as any)}>
            <option value="overlay">Overlay</option>
            <option value="stack">Stack</option>
          </select>
        </label>
        <label style={{ display: "inline-flex", gap: 8, alignItems: "center" }}>
          Stack sep
          <input type="number" value={sep} onChange={(e) => setSep(Number(e.target.value || 0))} />
        </label>
        <label style={{ display: "inline-flex", gap: 8, alignItems: "center" }}>
          <input type="checkbox" checked={ghost} onChange={(e) => setGhost(e.target.checked)} />
          Ghost overlay
        </label>
      </div>

      <div style={{ marginTop: 14, display: "grid", gridTemplateColumns: "360px 1fr", gap: 14, alignItems: "start" }}>
        <div>
          <h2 style={{ margin: "8px 0" }}>Uploads</h2>
          <SpectrumCheckboxListWrapper onSelectionChange={setSelected} />
          <div style={{ marginTop: 10, opacity: 0.8, fontSize: 13 }}>
            Selected: {selected.length}
          </div>
        </div>
        <div>
          <h2 style={{ margin: "8px 0" }}>Plot</h2>
          <PlotlyWrapper
            figure={fig}
            previousFigure={fig}
            plotStyle={{ mode, stackSep: sep }}
            ghostOverlayEnabled={ghost}
          />
        </div>
      </div>
    </div>
  );
}


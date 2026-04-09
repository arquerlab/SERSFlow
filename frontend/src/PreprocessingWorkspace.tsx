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
    <div className="preprocess-grid">
      <div className="preprocess-top card">
        <div className="section-title">Plot controls</div>
        <div className="row">
          <label className="inline">
            Plot mode
            <select value={mode} onChange={(e) => setMode(e.target.value as any)}>
              <option value="overlay">Overlay</option>
              <option value="stack">Stack</option>
            </select>
          </label>
          <label className="inline">
            Stack separation
            <input type="number" value={sep} onChange={(e) => setSep(Number(e.target.value || 0))} />
          </label>
          <label className="inline">
            <input type="checkbox" checked={ghost} onChange={(e) => setGhost(e.target.checked)} />
            Ghost overlay
          </label>
        </div>
      </div>

      <div className="preprocess-left card">
        <div className="section-title">Uploads</div>
        <SpectrumCheckboxListWrapper onSelectionChange={setSelected} />
        <div className="hint">Selected: {selected.length}</div>
      </div>

      <div className="preprocess-center card">
        <div className="section-title">Plot</div>
        <PlotlyWrapper
          figure={fig}
          previousFigure={fig}
          plotStyle={{ mode, stackSep: sep }}
          ghostOverlayEnabled={ghost}
          className="plot"
        />
      </div>
    </div>
  );
}


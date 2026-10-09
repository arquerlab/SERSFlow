import { describe, expect, it } from "vitest";
import { buildParamPlot, newParamPlotConfig, paramPlotColumns, paramPlotCsv, type ParamPlotConfig } from "./paramPlots";

const rows = [
  { spectrum_id: "a", t: 2, f1: 20, f2: 200, g: 1 },
  { spectrum_id: "b", t: 1, f1: 10, f2: null, g: 1 },
  { spectrum_id: "c", t: 3, f1: 30, f2: 300, g: 2 },
  { spectrum_id: "d", t: 4, f1: null, f2: null, g: 2 },
];

function cfg(patch: Partial<ParamPlotConfig>): ParamPlotConfig {
  return { ...newParamPlotConfig(), x: "t", ...patch };
}

describe("buildParamPlot", () => {
  it("line style sorts by X and draws lines without error bars", () => {
    const res = buildParamPlot(cfg({ style: "line", ys: ["f1"] }), rows);
    expect(res.figure.data).toHaveLength(1);
    const tr = res.figure.data[0];
    expect(tr.mode).toBe("lines+markers");
    expect(tr.x).toEqual([1, 2, 3]);
    expect(tr.y).toEqual([10, 20, 30]);
    expect(tr.error_y).toBeUndefined();
  });

  it("multiple Y columns give one trace each and a shared CSV", () => {
    const res = buildParamPlot(cfg({ style: "scatter", ys: ["f1", "f2", ""] }), rows);
    expect(res.figure.data.map((t) => t.name)).toEqual(["f1", "f2"]);
    expect(res.figure.data[1].y).toEqual([200, 300]);
    expect(res.figure.layout.yaxis.title).toBe("value");
    expect(res.csvHeader).toEqual(["spectrum_id", "t", "f1", "f2"]);
    // Row d has no Y values at all and is dropped.
    expect(res.csvRows.map((r) => r[0])).toEqual(["a", "b", "c"]);
    expect(paramPlotCsv(res).split("\n")[2]).toBe("b,1,10,");
  });

  it("line with a discrete color splits into one line per color value", () => {
    const res = buildParamPlot(cfg({ style: "line", ys: ["f1"], color: "g" }), rows);
    expect(res.figure.data.map((t) => t.name)).toEqual(["g=1", "g=2"]);
  });

  it("error bars with several Y columns aggregate each Y separately", () => {
    const res = buildParamPlot(cfg({ style: "errorbars", ys: ["f1", "f2"], yErr: "g" }), rows);
    expect(res.figure.data.map((t) => t.name)).toEqual(["f1", "f2"]);
    // Y error column is ignored for multiple Y (std within group is used instead).
    expect(paramPlotColumns(cfg({ ys: ["f1", "f2"], yErr: "g" }))).toEqual(["t", "f1", "f2"]);
  });
});

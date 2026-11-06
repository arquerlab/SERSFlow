import { describe, expect, it } from "vitest";
import { areaPctFigure, chi2Figure, scanGrid } from "./peakModelTestFigures";
import { componentOptionsFromRaw, defaultFittingEditorParams, flattenFittingForPipeline, migrateFittingParamsToEditor } from "./fittingUtils";

describe("S1 test peak model figures", () => {
  it("builds an even grid and profile figures", () => {
    expect(scanGrid(0, 1, 5)).toEqual([0, 0.25, 0.5, 0.75, 1]);
    expect(scanGrid(0, 1, 1)).toHaveLength(2);
    const pts = [
      { value: 1, error: null, chi2: 5, area_pct: { a: 60, b: 40 } },
      { value: 2, error: null, chi2: 3, area_pct: { a: 50, b: 50 } },
      { value: 3, error: "boom" },
    ];
    expect(chi2Figure(pts, "b.pos", 2).data).toHaveLength(2);
    const f = areaPctFigure(pts, "b.pos");
    expect(f.data.map((t) => t.name)).toEqual(["a", "b"]);
    expect(f.data[0]!.x).toEqual([1, 2]);
  });
});

describe("B1/L1/M1 component options", () => {
  it("survive flatten / migrate", () => {
    expect(componentOptionsFromRaw({ component_id: "x", component_type: "gl", degree: 2, avg_width: 3, of: "" })).toEqual({ avg_width: 3 });
    const base = defaultFittingEditorParams(undefined);
    const comp = { ...base.components[0]!, component_id: "p1", options: { avg_width: 5, offset_low_pct: 10 } };
    const flat = flattenFittingForPipeline({ ...base, components: [comp] }) as { components: Record<string, unknown>[] };
    expect(flat.components[0]).toMatchObject({ component_id: "p1", avg_width: 5, offset_low_pct: 10 });
    const back = migrateFittingParamsToEditor(flat as unknown as Record<string, unknown>, undefined);
    expect(back.components[0]!.options).toEqual({ avg_width: 5, offset_low_pct: 10 });
  });
});

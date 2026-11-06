import { describe, expect, it } from "vitest";
import type { ReferenceMarkerGroup } from "./api";
import {
  applyMarkers,
  figureFirstSpectrum,
  figureXRange,
  lineMarker,
  parseRegionLine,
  pickLibraryLine,
  referenceMarker,
  windowsFromPeaks,
  type PlotMarker,
} from "./identification";

const m = (x: number, extra: Partial<PlotMarker> = {}): PlotMarker => ({ kind: "ref", label: `m${x}`, x, color: "#000", ...extra });

describe("applyMarkers", () => {
  it("adds a line, a label and an optional band per marker on the main panel", () => {
    const fig: any = { data: [], layout: { shapes: [{ type: "line", keep: true }] } };
    const out = applyMarkers(fig, [m(780, { x0: 779, x1: 781 }), m(785)]);
    expect(out.layout!.shapes).toHaveLength(1 + 3); // existing + (band + line) + line
    expect(out.layout!.annotations).toHaveLength(2);
    const lines = (out.layout!.shapes as any[]).filter((s) => s.type === "line" && !s.keep);
    expect(lines.every((s) => s.yref === "y domain")).toBe(true);
    expect(fig.layout.shapes).toHaveLength(1); // input is not mutated
  });

  it("is a no-op without markers and walks every figure of a fit stack", () => {
    const fig: any = { data: [], layout: {} };
    expect(applyMarkers(fig, [])).toBe(fig);
    const stack: any = { kind: "fit_stack", figures: [{ data: [], layout: {} }, { data: [], layout: {} }] };
    const out = applyMarkers(stack, [m(1)]);
    expect(out.figures!.every((f: any) => (f.layout!.shapes as unknown[]).length === 1)).toBe(true);
  });
});

describe("region parsing", () => {
  it("reads element and line from XPS region names", () => {
    expect(parseRegionLine("Co2pspectrum1")).toEqual({ element: "Co", line: "2p" });
    expect(parseRegionLine("W 4f")).toEqual({ element: "W", line: "4f" });
    expect(parseRegionLine("O1s_2")).toEqual({ element: "O", line: "1s" });
    expect(parseRegionLine("Survey")).toBeNull();
    expect(parseRegionLine(undefined)).toBeNull();
  });

  it("maps a region line onto the library lines", () => {
    expect(pickLibraryLine(["2p3/2", "3d"], "2p")).toBe("2p3/2");
    expect(pickLibraryLine(["2p", "3d"], "2P")).toBe("2p");
    expect(pickLibraryLine(["3d"], "2p")).toBe("3d");
    expect(pickLibraryLine([], "2p")).toBeNull();
  });
});

describe("marker builders", () => {
  it("shows the min-max band only when the library entries differ", () => {
    const g: ReferenceMarkerGroup = { compound: "CoO", line: "2p", energy_kind: "binding", median_eV: 780.4, min_eV: 779.9, max_eV: 780.9, n_entries: 5, distinct_values_eV: [], phases: [], provenance: ["phi_handbook"], elemental: false };
    expect(referenceMarker({ ...g }, "#111")).toMatchObject({ x: 780.4, x0: 779.9, x1: 780.9, label: "CoO" });
    expect(referenceMarker({ ...g, min_eV: 780.4, max_eV: 780.4 }, "#111").x0).toBeUndefined();
    const lm = lineMarker({ element: "C", line: "1s", label: "C 1s", section_id: "C_1s", kind: "core", be_eV: 287.4, be_min_eV: 280, be_max_eV: 296, ke_eV: null, basis: "compounds_median", n_entries: 9 });
    expect(lm.kind).toBe("line");
    expect(lm.detail).toContain("median of compounds");
  });
});

describe("survey region windows", () => {
  it("centres windows on the measured peaks of included, matched rows only", () => {
    const peak = (be: number) => ({ be_eV: be, height: 1, prominence: 1, prominence_pct: 1, match: null, alternatives: [] });
    const match = (label: string, el: string, line: string) => ({ label, element: el, line, kind: "core", be_eV: 0, delta_eV: 0, range_distance_eV: 0, in_library_range: true, basis: "elemental" });
    const rows = [
      { peak: peak(285.1), match: match("C 1s", "C", "1s"), include: true },
      { peak: peak(531.2), match: match("O 1s", "O", "1s"), include: false },
      { peak: peak(400), match: null, include: true },
    ];
    const w = windowsFromPeaks(rows, 10);
    expect(w).toHaveLength(1);
    expect(w[0]).toMatchObject({ label: "C 1s", be_eV: 285.1, be_min_eV: 275.1, be_max_eV: 295.1 });
  });
});

describe("figure helpers", () => {
  it("find the x range and the first plain spectrum", () => {
    const x = Array.from({ length: 20 }, (_, i) => 1000 - i * 10);
    const fig = { data: [{ x, y: x.map((v) => v / 2) }], layout: {} };
    expect(figureXRange(fig)).toEqual([810, 1000]);
    expect(figureFirstSpectrum(fig)!.x).toHaveLength(20);
    expect(figureFirstSpectrum({ data: [{ x: [1, 2], y: [1, 2] }] })).toBeNull();
    const stack = { kind: "fit_stack", figures: [fig] };
    expect(figureXRange(stack)).toEqual([810, 1000]);
  });
});

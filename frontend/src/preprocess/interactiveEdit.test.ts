import { describe, expect, it } from "vitest";
import {
  addBackground,
  addSatellite,
  backgroundHandles,
  deleteComponent,
  dragBackground,
  groupAnchor,
  recipeGroups,
  setRowField,
  shiftGroup,
  tieCandidates,
  tieOf,
  tieParam,
  windowEndLevels,
} from "./interactiveEdit";
import type { FitMeta } from "./interactiveFit";
import type { FittingEditorParams } from "./fittingUtils";


const spec = (component_type: string, keys: string[]) => ({
  component_type,
  display_name: component_type,
  kind: "parametric" as const,
  params: keys.map((key) => ({ key, label: key, default: 0, bounds_default: { lower: null, upper: null }, unit: null, ui: {} })),
});
const CATALOG = [
  spec("linear_bg", ["low", "high"]),
  spec("erfc_step_bg", ["pos", "height", "fwhm", "const"]),
  spec("shirley_bg", ["k", "const"]),
  spec("shirley_of_bg", ["k", "shift"]),
];

const X = Array.from({ length: 201 }, (_, i) => 775 + i * 0.1);
const g = (pos: number, amp: number, w: number) => X.map((x) => amp * Math.exp(-4 * Math.LN2 * ((x - pos) / w) ** 2));
const row = (key: string, p0: number, extra: Record<string, unknown> = {}) => ({ key, label: key, p0, lower: null, upper: null, ...extra });

function fixture() {
  const a = g(780, 1000, 1.6);
  const b = g(785, 400, 2.4);
  const fp: FittingEditorParams = {
    output_mode: "fit",
    fill_opacity: 0.15,
    initial_guess_mode: "default",
    fit_min_x: 776,
    fit_max_x: 790,
    components: [
      { component_id: "a", component_type: "gaussian" as never, degree: 0, rows: [row("pos", 780), row("amp", 1000), row("fwhm", 1.6)] },
      { component_id: "b", component_type: "gaussian" as never, degree: 0, rows: [row("pos", 785), row("amp", 400), row("fwhm", 2.4)] },
    ],
    param_links: [],
    recipe_components: { Co_multiplet: ["a", "b"] },
  };
  const y = X.map((x, i) => 100 + 2 * (x - 775) + a[i]! + b[i]!);
  const meta: FitMeta = {
    x: X,
    y,
    yHat: y,
    residual: y.map(() => 0),
    fitted: true,
    fitMin: 776,
    fitMax: 790,
    xAxisTitle: "BE",
    components: [
      { component_id: "a", component_type: "gaussian", params: { pos: 780, amp: 1000, fwhm: 1.6 }, area: 1700, y_hat: a },
      { component_id: "b", component_type: "gaussian", params: { pos: 785, amp: 400, fwhm: 2.4 }, area: 1020, y_hat: b },
    ],
  };
  return { fp, meta };
}

describe("window end levels", () => {
  it("averages the data near both window ends", () => {
    const { meta } = fixture();
    const lv = windowEndLevels(meta);
    expect(lv.xlo).toBeCloseTo(776, 1);
    expect(lv.xhi).toBeCloseTo(790, 1);
    expect(lv.lo).toBeCloseTo(102, 0); // 100 + 2*(776.1-775)
    expect(lv.hi).toBeCloseTo(130, 0);
  });
});

describe("add background", () => {
  it("seeds a linear background from the data ends, fixed, and puts it first", () => {
    const { fp, meta } = fixture();
    const r = addBackground(fp, meta, CATALOG, "linear_bg");
    const c = r.fp.components[0]!;
    expect(c.component_type).toBe("linear_bg");
    expect(r.fp.components).toHaveLength(3);
    const lo = c.rows.find((q) => q.key === "low")!;
    expect(lo.p0).toBeCloseTo(102, 0);
    expect(lo.vary).toBe(false);
    expect(r.needsRefit).toBe(false);
    expect(r.replaced).toBeNull();
  });

  it("replaces an existing baseline but keeps additive erfc steps", () => {
    const { fp, meta } = fixture();
    const withLinear = addBackground(fp, meta, CATALOG, "linear_bg").fp;
    const sh = addBackground(withLinear, meta, CATALOG, "shirley_bg");
    expect(sh.replaced).toBe("linear");
    expect(sh.fp.components.filter((c) => /_bg$/.test(String(c.component_type)))).toHaveLength(1);
    expect(sh.needsRefit).toBe(true);
    const erfc = addBackground(sh.fp, meta, CATALOG, "erfc_step_bg");
    expect(erfc.replaced).toBeNull();
    expect(erfc.fp.components.some((c) => c.component_type === "shirley_bg")).toBe(true);
    const e = erfc.fp.components[erfc.fp.components.length - 1]!;
    expect(e.rows.find((q) => q.key === "height")!.p0).toBeCloseTo(28, 0);
    expect(e.rows.find((q) => q.key === "pos")!.p0).toBeCloseTo(783, 0);
  });

  it("drops links of the replaced baseline and records the SB source option", () => {
    const { fp, meta } = fixture();
    const lk = { ...fp, param_links: [{ source_component_id: "a", source_key: "fwhm", target_component_id: "b", target_key: "fwhm", mode: "equal" as const }] };
    const sb = addBackground(lk, meta, CATALOG, "shirley_of_bg", { sbSource: "a" });
    expect(sb.fp.param_links).toHaveLength(1);
    expect(sb.fp.components[sb.fp.components.length - 1]!.options).toEqual({ of: "a" });
  });
});

describe("background handles", () => {
  function withLinear() {
    const { fp, meta } = fixture();
    const r = addBackground(fp, meta, CATALOG, "linear_bg");
    const m: FitMeta = { ...meta, fitted: false, components: [...meta.components, { component_id: "linear", component_type: "linear_bg", params: { low: 102, high: 130 }, y_hat: X.map(() => 0) }] };
    return { fp: r.fp, meta: m };
  }

  it("puts a handle on each linear end and drags the level", () => {
    const { fp, meta } = withLinear();
    const hs = backgroundHandles(meta, fp);
    expect(hs.map((h) => h.kind)).toEqual(["lo", "hi"]);
    const next = dragBackground(fp, meta, hs[1]!, { x: 790, y: 150 });
    expect(next.components[0]!.rows.find((r) => r.key === "high")!.p0).toBe(150);
  });

  it("drags an erfc step: position and height from the handle, width from the second", () => {
    const { fp, meta } = fixture();
    const e = addBackground(fp, meta, CATALOG, "erfc_step_bg").fp;
    const m: FitMeta = { ...meta, fitted: false, components: [...meta.components, { component_id: "erfc", component_type: "erfc_step_bg", params: { pos: 783, height: 28, fwhm: 0.5, const: 102 }, y_hat: X.map(() => 0) }] };
    const hs = backgroundHandles(m, e);
    expect(hs.map((h) => h.kind)).toEqual(["edge", "edge-width"]);
    const moved = dragBackground(e, m, hs[0]!, { x: 784, y: 102 + 25 });
    const rows = moved.components.find((c) => c.component_id === "erfc")!.rows;
    expect(rows.find((r) => r.key === "pos")!.p0).toBe(784);
    expect(rows.find((r) => r.key === "height")!.p0).toBeCloseTo(50, 6);
    const wide = dragBackground(e, m, hs[1]!, { x: 783 + 1.2, y: 0 });
    expect(wide.components.find((c) => c.component_id === "erfc")!.rows.find((r) => r.key === "fwhm")!.p0).toBeCloseTo(1.2, 6);
  });

  it("a follower level has no editable handle", () => {
    const { fp, meta } = withLinear();
    const linked = { ...fp, param_links: [{ source_component_id: "linear", source_key: "high", target_component_id: "linear", target_key: "low", mode: "equal" as const }] };
    const hs = backgroundHandles(meta, linked);
    expect(hs.find((h) => h.kind === "hi")!.canEdit).toBe(false);
    expect(dragBackground(linked, meta, hs.find((h) => h.kind === "hi")!, { x: 790, y: 999 })).toBe(linked);
  });
});

describe("satellites and groups", () => {
  it("adds a satellite tied by offset and area ratio, copying the parent's shape", () => {
    const { fp, meta } = fixture();
    const r = addSatellite(fp, meta, 0, { offset: 6, ratio: 0.3 });
    const s = r.fp.components[r.fp.components.length - 1]!;
    expect(s.component_id).toBe("a_sat");
    expect(s.rows.find((q) => q.key === "pos")!.p0).toBe(786);
    expect(s.rows.find((q) => q.key === "fwhm")!.p0).toBe(1.6);
    expect(tieOf(r.fp, "a_sat", "pos")).toEqual({ mode: "offset", driver: "a", value: 6 });
    expect(tieOf(r.fp, "a_sat", "amp")).toEqual({ mode: "area_ratio", driver: "a", value: 0.3 });
    expect(() => addSatellite(fp, meta, 0, { offset: 6, ratio: 0 })).toThrow();
  });

  it("shifts a recipe group together, bounds included", () => {
    const { fp, meta } = fixture();
    const bounded = setRowField(fp, undefined, 0, "pos", { lower: 778, upper: 782 });
    expect(recipeGroups(bounded)).toEqual([{ id: "Co_multiplet", members: ["a", "b"] }]);
    const sh = shiftGroup(bounded, meta, ["a", "b"], 0.5);
    const a = sh.components[0]!.rows.find((r) => r.key === "pos")!;
    expect([a.p0, a.lower, a.upper]).toEqual([780.5, 778.5, 782.5]);
    expect(sh.components[1]!.rows.find((r) => r.key === "pos")!.p0).toBe(785.5);
    expect(groupAnchor(meta, ["a", "b"])!.x).toBeCloseTo(780, 1);
  });

  it("a single-peak recipe is not a group", () => {
    const { fp } = fixture();
    expect(recipeGroups({ ...fp, recipe_components: { one: ["a"], gone: ["a", "zzz"] } })).toEqual([]);
  });
});

describe("inspector edits", () => {
  it("ties a width to another peak and reads the tie back; cycles are not offered", () => {
    const { fp, meta } = fixture();
    expect(tieCandidates(fp, "b", "fwhm")).toEqual(["a"]);
    const tied = tieParam(fp, meta, "b", "fwhm", "equal", "a");
    expect(tieOf(tied, "b", "fwhm")).toEqual({ mode: "equal", driver: "a", value: null });
    expect(tieCandidates(tied, "a", "fwhm")).toEqual([]); // a -> b would close a loop
    const off = tieParam(fp, meta, "b", "pos", "offset", "a");
    expect(tieOf(off, "b", "pos").value).toBeCloseTo(5, 6); // default = current separation
    const ratio = tieParam(fp, meta, "b", "amp", "area_ratio", "a");
    expect(tieOf(ratio, "b", "amp").value).toBeCloseTo(1020 / 1700, 6); // default = drawn area ratio
    expect(tieOf(tieParam(tied, meta, "b", "fwhm", "none", ""), "b", "fwhm").mode).toBe("none");
  });

  it("fixes a value and sets bounds, adopting the drawn fit first", () => {
    const { fp, meta } = fixture();
    const moved = { ...meta, components: meta.components.map((c) => (c.component_id === "a" ? { ...c, params: { ...c.params, fwhm: 2.0 } } : c)) };
    const n = setRowField(fp, moved, 0, "pos", { vary: false, lower: 779, upper: 781 });
    const r = n.components[0]!.rows;
    expect(r.find((q) => q.key === "pos")).toMatchObject({ vary: false, lower: 779, upper: 781 });
    expect(r.find((q) => q.key === "fwhm")!.p0).toBe(2.0);
  });

  it("deleting a component removes its links and its recipe membership", () => {
    const { fp, meta } = fixture();
    const tied = tieParam(fp, meta, "b", "fwhm", "equal", "a");
    const d = deleteComponent(tied, 0);
    expect(d.components.map((c) => c.component_id)).toEqual(["b"]);
    expect(d.param_links).toEqual([]);
    expect(d.recipe_components!.Co_multiplet).toEqual(["b"]);
  });
});

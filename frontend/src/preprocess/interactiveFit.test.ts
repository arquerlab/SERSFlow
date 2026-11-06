import { describe, expect, it } from "vitest";
import {
  addPeak,
  adoptDisplayedParams,
  buildFitRequest,
  dragPeak,
  isFollower,
  maxResidualPoint,
  peakHandles,
  setWindow,
  setWindowEdge,
  type FitMeta,
} from "./interactiveFit";
import type { FittingEditorParams } from "./fittingUtils";

const X = Array.from({ length: 401 }, (_, i) => 775 + i * 0.05);
const gauss = (pos: number, amp: number, fwhm: number) => X.map((x) => amp * Math.exp(-4 * Math.LN2 * ((x - pos) / fwhm) ** 2));

function fixture(opts: { varyPos?: boolean; link?: boolean } = {}) {
  const a = gauss(780, 1000, 1.6);
  const b = gauss(785, 400, 2.4);
  const bg = X.map(() => 50);
  const fp: FittingEditorParams = {
    output_mode: "fit",
    fill_opacity: 0.15,
    initial_guess_mode: "default",
    fit_min_x: 776,
    fit_max_x: 790,
    components: [
      {
        component_id: "a",
        component_type: "gaussian" as never,
        degree: 0,
        rows: [
          { key: "pos", label: "pos", p0: 779.5, lower: 770, upper: 800, vary: opts.varyPos },
          { key: "amp", label: "amp", p0: 0, lower: 0, upper: null, auto: true },
          { key: "fwhm", label: "fwhm", p0: 1.0, lower: 0.2, upper: 5 },
        ],
      },
      {
        component_id: "b",
        component_type: "gaussian" as never,
        degree: 0,
        rows: [
          { key: "pos", label: "pos", p0: 785, lower: null, upper: null },
          { key: "amp", label: "amp", p0: 400, lower: 0, upper: null },
          { key: "fwhm", label: "fwhm", p0: 2.4, lower: 0.2, upper: 5 },
        ],
      },
      { component_id: "bg", component_type: "linear_bg" as never, degree: 0, rows: [{ key: "low", label: "low", p0: 1, lower: null, upper: null }] },
    ],
    param_links: opts.link
      ? [{ source_component_id: "b", source_key: "pos", target_component_id: "a", target_key: "pos", mode: "offset", offset: 5 }]
      : [],
  };
  const total = X.map((_, i) => a[i]! + b[i]! + 50);
  const data = X.map((_, i) => total[i]! + (X[i]! > 782 && X[i]! < 783 ? 200 : 0));
  const meta: FitMeta = {
    x: X,
    y: data,
    yHat: total,
    residual: data.map((v, i) => v - total[i]!),
    fitted: true,
    fitMin: 776,
    fitMax: 790,
    xAxisTitle: "BE",
    components: [
      { component_id: "a", component_type: "gaussian", params: { pos: 780, amp: 1000, fwhm: 1.6 }, y_hat: a },
      { component_id: "b", component_type: "gaussian", params: { pos: 785, amp: 400, fwhm: 2.4 }, y_hat: b },
      { component_id: "bg", component_type: "linear_bg", params: { low: 50 }, y_hat: bg },
    ],
  };
  return { fp, meta };
}

describe("peak handles", () => {
  it("sit at the curve maximum on top of the background, with a half-maximum width handle", () => {
    const { fp, meta } = fixture();
    const hs = peakHandles(meta, fp);
    expect(hs.map((h) => h.component_id)).toEqual(["a", "b"]);
    const a = hs[0]!;
    expect(a.xMax).toBeCloseTo(780, 1);
    expect(a.height).toBeCloseTo(1000, 0);
    expect(a.top).toBeCloseTo(1050, 0);
    expect(a.halfX! - a.xMax).toBeCloseTo(0.8, 1); // FWHM/2
    expect(a.halfY).toBeCloseTo(550, 0);
    expect(a.canMove && a.canHeight && a.canWidth).toBe(true);
  });

  it("have no handle for a fixed parameter or a follower of a link", () => {
    const fixed = fixture({ varyPos: false });
    expect(peakHandles(fixed.meta, fixed.fp)[0]!.canMove).toBe(false);
    const linked = fixture({ link: true });
    expect(isFollower(linked.fp, "b", "pos")).toBe(true);
    const hb = peakHandles(linked.meta, linked.fp)[1]!;
    expect(hb.canMove).toBe(false);
    expect(hb.canHeight).toBe(true);
  });
});

describe("dragging", () => {
  it("moves position by the drag distance and scales the amplitude with the height above the baseline", () => {
    const { fp, meta } = fixture();
    const h = peakHandles(meta, fp)[0]!;
    const next = dragPeak(fp, meta, h, "move", { x: h.xMax + 0.4, y: 50 + 500 });
    const rows = next.components[0]!.rows;
    expect(rows[0]!.p0).toBeCloseTo(780.4, 3); // fitted 780 + 0.4, not the old seed 779.5
    expect(rows[1]!.p0).toBeCloseTo(500, 3); // half the height -> half the amplitude
    expect(rows[1]!.auto).toBe(false);
    // other components adopt their DRAWN values so the evaluation does not jump back to the seeds
    expect(next.components[1]!.rows[1]!.p0).toBe(400);
  });

  it("clips to the parameter bounds and respects locks", () => {
    const { fp, meta } = fixture();
    const h = peakHandles(meta, fp)[0]!;
    const far = dragPeak(fp, meta, h, "move", { x: 900, y: 1050 });
    expect(far.components[0]!.rows[0]!.p0).toBe(800); // upper bound
    const fixed = fixture({ varyPos: false });
    const hf = peakHandles(fixed.meta, fixed.fp)[0]!;
    const moved = dragPeak(fixed.fp, fixed.meta, hf, "move", { x: 781, y: 1050 });
    expect(moved.components[0]!.rows[0]!.p0).toBe(780); // adopted, not moved
  });

  it("sets the FWHM in proportion to the distance of the half-maximum handle", () => {
    const { fp, meta } = fixture();
    const h = peakHandles(meta, fp)[0]!;
    const next = dragPeak(fp, meta, h, "width", { x: h.xMax + 1.6, y: h.halfY });
    expect(next.components[0]!.rows[2]!.p0).toBeCloseTo(3.2, 1); // handle twice as far -> FWHM x2
  });

  it("adopting leaves an evaluation untouched", () => {
    const { fp, meta } = fixture();
    expect(adoptDisplayedParams(fp, { ...meta, fitted: false })).toBe(fp);
  });
});

describe("fit window", () => {
  it("drags an edge without crossing and sets a box selection", () => {
    const { fp, meta } = fixture();
    expect(setWindowEdge(fp, meta, "min", 778).fit_min_x).toBe(778);
    expect(setWindowEdge(fp, meta, "min", 800).fit_min_x).toBeLessThan(790);
    expect(setWindowEdge(fp, meta, "max", 700).fit_max_x).toBeGreaterThan(776);
    const w = setWindow(fp, meta, 788, 779);
    expect([w.fit_min_x, w.fit_max_x]).toEqual([779, 788]);
    expect(setWindow(fp, meta, 780, 780)).toBe(fp);
  });
});

describe("add peak", () => {
  it("finds the largest positive residual inside the window", () => {
    const { meta } = fixture();
    const p = maxResidualPoint(meta)!;
    expect(p.x).toBeGreaterThan(782);
    expect(p.x).toBeLessThan(783);
    expect(p.residual).toBeCloseTo(200, 3);
    expect(maxResidualPoint({ ...meta, fitMin: 786, fitMax: 790 })).toBeNull();
  });

  it("copies a peak's shape and scales its amplitude to the requested height", () => {
    const { fp, meta } = fixture();
    const { fp: next, component_id } = addPeak(fp, meta, undefined, { x: 782.5, height: 200 }, { kind: "copy", ci: 0 }, null);
    const c = next.components[next.components.length - 1]!;
    expect(c.component_id).toBe(component_id);
    expect(next.components.length).toBe(4);
    const row = (k: string) => c.rows.find((r) => r.key === k)!;
    expect(row("pos").p0).toBe(782.5);
    expect(row("fwhm").p0).toBeCloseTo(1.6, 6); // adopted fitted shape of the source
    expect(row("amp").p0).toBeCloseTo(200, 3); // source amp/height = 1
    expect(new Set(next.components.map((q) => q.component_id)).size).toBe(4);
  });
});

describe("request", () => {
  it("builds an evaluate-only request from the flat step params", () => {
    const req = buildFitRequest(
      { components: [{ component_id: "a", component_type: "gl" }], p0: [1], bounds_lower: [null], bounds_upper: [null], vary: [true], fit_min_x: 1, fit_max_x: 2 },
      { spectrum_id: "s", x: [1, 2, 3], y: [1, 2, 3] },
      { technique: "xps", fit: false }
    );
    expect(req.fit).toBe(false);
    expect(req.fit_min_x).toBe(1);
    expect(req.target).toMatchObject({ kind: "inline" });
  });
});

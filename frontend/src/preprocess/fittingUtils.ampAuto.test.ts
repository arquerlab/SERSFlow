import { describe, expect, it } from "vitest";
import {
  allBandAmplitudeAutosOn,
  applyPeakShiftEv,
  defaultFittingEditorParams,
  flattenFittingForPipeline,
  migrateFittingParamsToEditor,
  parseInitialAreaRatios,
  PEAK_SHIFT_STEP_EV,
  setBandAmplitudeAutos,
  syncAmpAutoBandsFlag,
  type FittingEditorParams,
} from "./fittingUtils";

function twoPeakEditor(): FittingEditorParams {
  const base = defaultFittingEditorParams(undefined);
  const p2 = {
    component_id: "p2",
    component_type: "gaussian" as const,
    degree: 0,
    rows: base.components[0]!.rows.map((r) => ({ ...r })),
  };
  return {
    ...base,
    components: [
      { ...base.components[0]!, component_id: "p1" },
      p2,
    ],
  };
}

describe("parseInitialAreaRatios", () => {
  it("accepts empty and colon ratios", () => {
    expect(parseInitialAreaRatios("")).toEqual({ ok: true, ratios: [] });
    expect(parseInitialAreaRatios("1:0.6:0.3")).toEqual({ ok: true, ratios: [1, 0.6, 0.3] });
  });

  it("rejects non-positive or junk", () => {
    expect(parseInitialAreaRatios("1:0").ok).toBe(false);
    expect(parseInitialAreaRatios("a:b").ok).toBe(false);
  });
});

describe("band amplitude auto master", () => {
  it("master on sets all peak amp autos", () => {
    const next = setBandAmplitudeAutos(twoPeakEditor(), true);
    expect(next.amp_auto_bands).toBe(true);
    expect(allBandAmplitudeAutosOn(next)).toBe(true);
    for (const c of next.components) {
      const amp = c.rows.find((r) => r.key === "amp");
      expect(amp?.auto).toBe(true);
      expect(amp?.p0).toBe(0);
    }
  });

  it("master off clears autos without inventing fancy amps", () => {
    const on = setBandAmplitudeAutos(twoPeakEditor(), true);
    const off = setBandAmplitudeAutos(on, false);
    expect(off.amp_auto_bands).toBe(false);
    expect(allBandAmplitudeAutosOn(off)).toBe(false);
  });

  it("flatten includes ratios only when band auto is on", () => {
    const fp = setBandAmplitudeAutos(
      { ...twoPeakEditor(), initial_area_ratios: "1:2" },
      true
    );
    const flat = flattenFittingForPipeline(fp);
    expect(flat.amp_auto_bands).toBe(true);
    expect(flat.initial_area_ratios).toBe("1:2");
    expect((flat.p0 as number[])[1]).toBe(0);

    const noAuto = flattenFittingForPipeline({
      ...twoPeakEditor(),
      amp_auto_bands: false,
      initial_area_ratios: "1:2",
    });
    expect(noAuto.initial_area_ratios).toBeUndefined();
  });

  it("invalid ratio count does not crash flatten", () => {
    const fp = setBandAmplitudeAutos(
      { ...twoPeakEditor(), initial_area_ratios: "1:2:3:4" },
      true
    );
    expect(() => flattenFittingForPipeline(fp)).not.toThrow();
    const flat = flattenFittingForPipeline(fp);
    expect(flat.initial_area_ratios).toBe("1:2:3:4");
  });

  it("migrate restores amp_auto_bands and ratios from flat params", () => {
    const flat = {
      components: [
        { component_id: "p1", component_type: "gaussian" },
        { component_id: "p2", component_type: "gaussian" },
      ],
      p0: [520, 0, 10, 530, 0, 12],
      bounds_lower: [500, 0, 1e-6, 500, 0, 1e-6],
      bounds_upper: [540, null, 50, 560, null, 50],
      amp_auto_bands: true,
      initial_area_ratios: "38.1:26.6",
    };
    const ed = migrateFittingParamsToEditor(flat, undefined);
    expect(ed.amp_auto_bands).toBe(true);
    expect(ed.initial_area_ratios).toBe("38.1:26.6");
    expect(allBandAmplitudeAutosOn(ed)).toBe(true);
  });

  it("syncAmpAutoBandsFlag follows individual autos", () => {
    let fp = setBandAmplitudeAutos(twoPeakEditor(), true);
    const rows = fp.components[0]!.rows.map((r) =>
      r.key === "amp" ? { ...r, auto: false, p0: 5 } : r
    );
    fp = syncAmpAutoBandsFlag({
      ...fp,
      components: [{ ...fp.components[0]!, rows }, fp.components[1]!],
    });
    expect(fp.amp_auto_bands).toBe(false);
  });
});

describe("peak shift", () => {
  it("shifts peak pos seeds and bounds by delta and records cumulative shift", () => {
    const base = twoPeakEditor();
    const pos0 = base.components[0]!.rows.find((r) => r.key === "pos")!;
    const withBounds: FittingEditorParams = {
      ...base,
      components: [
        {
          ...base.components[0]!,
          rows: base.components[0]!.rows.map((r) =>
            r.key === "pos" ? { ...r, p0: 780, lower: 778, upper: 782 } : r
          ),
        },
        base.components[1]!,
      ],
      peak_shift_eV: 0,
    };
    const next = applyPeakShiftEv(withBounds, PEAK_SHIFT_STEP_EV);
    expect(next.peak_shift_eV).toBe(0.2);
    const pos = next.components[0]!.rows.find((r) => r.key === "pos")!;
    expect(pos.p0).toBeCloseTo(780.2);
    expect(pos.lower).toBeCloseTo(778.2);
    expect(pos.upper).toBeCloseTo(782.2);
    expect(pos0.p0).not.toBe(pos.p0);

    const back = applyPeakShiftEv(next, 0);
    expect(back.peak_shift_eV).toBe(0);
    const posBack = back.components[0]!.rows.find((r) => r.key === "pos")!;
    expect(posBack.p0).toBeCloseTo(780);
  });

  it("flatten persists non-zero peak_shift_eV", () => {
    const flat = flattenFittingForPipeline({ ...twoPeakEditor(), peak_shift_eV: -0.4 });
    expect(flat.peak_shift_eV).toBe(-0.4);
    const ed = migrateFittingParamsToEditor(flat, undefined);
    expect(ed.peak_shift_eV).toBe(-0.4);
  });
});

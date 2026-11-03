import { describe, expect, it } from "vitest";
import { fitHealthSummary } from "./fitHealth";
import { flattenFittingForPipeline, migrateFittingParamsToEditor, defaultFittingEditorParams } from "./fittingUtils";

describe("fitHealthSummary", () => {
  it("is quiet for a healthy fit", () => {
    const h = fitHealthSummary({
      rmse: 10,
      r2: 0.99,
      bic: 100,
      n_at_bound: 0,
      bg_gt_data_frac: 0.02,
      resid_lag1_autocorr: 0.1,
      resid_mean_edge_lo: 1,
      resid_mean_edge_hi: -2,
    });
    expect(h.warn).toBe(false);
    expect(h.text).toContain("RMSE=10");
    expect(h.text).toContain("lag1=0.1");
    expect(h.text).toContain("at-bound=0");
    expect(h.text).toContain("edge resid lo/hi=1/-2");
  });

  it("warns for a pinned parameter, background above data and structured residual", () => {
    const h = fitHealthSummary({ rmse: 5, n_at_bound: 2, bg_gt_data_frac: 0.25, resid_lag1_autocorr: 0.9 });
    expect(h.warn).toBe(true);
    expect(h.reasons).toEqual([
      "2 parameters at a bound",
      "background above data in 25% of points",
      "structured residual (lag-1 0.9)",
    ]);
    expect(h.text).toContain("⚠");
  });

  it("handles old runs without health metrics", () => {
    const h = fitHealthSummary({ rmse: 3, r2: 0.5, bic: 7 });
    expect(h.warn).toBe(false);
    expect(h.text).toBe("RMSE=3  R²=0.5  BIC=7");
    expect(fitHealthSummary(undefined).warn).toBe(false);
  });
});

describe("area_ratio param links", () => {
  it("survive migrate -> flatten round trip with their ratio", () => {
    const base = defaultFittingEditorParams(undefined);
    const comp2 = { ...base.components[0]!, component_id: "sat", rows: base.components[0]!.rows.map((r) => ({ ...r })) };
    const comp1 = { ...base.components[0]!, component_id: "main" };
    const editor = {
      ...base,
      components: [comp1, comp2],
      param_links: [
        {
          source_component_id: "sat",
          source_key: "amp",
          target_component_id: "main",
          target_key: "amp",
          mode: "area_ratio" as const,
          ratio: 0.28,
        },
      ],
    };
    const flat = flattenFittingForPipeline(editor) as { param_links: Array<Record<string, unknown>> };
    expect(flat.param_links).toHaveLength(1);
    expect(flat.param_links[0]).toMatchObject({ mode: "area_ratio", ratio: 0.28 });
    const back = migrateFittingParamsToEditor(flat, undefined);
    expect(back.param_links?.[0]).toMatchObject({ mode: "area_ratio", ratio: 0.28 });
  });

  it("unknown modes still fall back to equal", () => {
    const flat = {
      components: [
        { component_id: "a", component_type: "gaussian" },
        { component_id: "b", component_type: "gaussian" },
      ],
      p0: [0, 1, 1, 0, 1, 1],
      bounds_lower: [null, 0, 0.1, null, 0, 0.1],
      bounds_upper: [null, null, 10, null, null, 10],
      vary: [true, true, true, true, true, true],
      param_links: [
        { source_component_id: "b", source_key: "amp", target_component_id: "a", target_key: "amp", mode: "bogus" },
      ],
    };
    const back = migrateFittingParamsToEditor(flat, undefined);
    expect(back.param_links?.[0]?.mode).toBe("equal");
  });
});

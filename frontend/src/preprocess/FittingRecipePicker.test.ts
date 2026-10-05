import { describe, expect, it } from "vitest";
import {
  appendRecipeApplyIntoEditor,
  mergeRecipeApplyIntoEditor,
  removeRecipeFromEditor,
} from "./FittingRecipePicker";
import {
  defaultFittingEditorParams,
  uniqueComponentIdAgainst,
  type FittingEditorParams,
} from "./fittingUtils";
import type { FittingRecipeApplyResponse } from "./api";

function fakeApply(partial: Partial<FittingRecipeApplyResponse>): FittingRecipeApplyResponse {
  return {
    recipe_id: "r1",
    recipe_pass_energy: 20,
    xps_region: "C1s",
    components: [{ component_id: "Peak_1", component_type: "gl" }],
    p0: [285.0, 1.0, 1.2, 30.0],
    bounds_lower: [280.0, 0.0, 1e-6, 0.0],
    bounds_upper: [290.0, null, 8.0, 100.0],
    vary: [true, true, true, true],
    param_links: [],
    warnings: [],
    ...partial,
  };
}

describe("uniqueComponentIdAgainst", () => {
  it("increments trailing numbers and falls back to _N", () => {
    const used = new Set<string>(["peak_1", "peak_2"]);
    expect(uniqueComponentIdAgainst("Peak_1", used)).toBe("Peak_3");
    expect(uniqueComponentIdAgainst("foo", used)).toBe("foo");
    expect(uniqueComponentIdAgainst("foo", used)).toBe("foo_2");
  });
});

describe("recipe apply merge helpers", () => {
  it("replace keeps fit window and sets recipe_ids", () => {
    const current: FittingEditorParams = {
      ...defaultFittingEditorParams(undefined),
      fit_min_x: 280,
      fit_max_x: 295,
    };
    const next = mergeRecipeApplyIntoEditor(current, fakeApply({ recipe_id: "c_1s" }), undefined);
    expect(next.fit_min_x).toBe(280);
    expect(next.fit_max_x).toBe(295);
    expect(next.recipe_ids).toEqual(["c_1s"]);
    expect(next.recipe_id).toBe("c_1s");
    expect(next.recipe_components?.["c_1s"]).toEqual(["Peak_1"]);
  });

  it("append skips backgrounds and renames colliding peak ids", () => {
    const base: FittingEditorParams = {
      ...defaultFittingEditorParams(undefined),
      components: [
        {
          component_id: "bg",
          component_type: "shirley_bg",
          degree: 0,
          rows: [{ key: "k", label: "k", p0: 1, lower: 0, upper: null, vary: true }],
        },
        {
          component_id: "Peak_1",
          component_type: "gl",
          degree: 0,
          rows: [
            { key: "pos", label: "pos", p0: 285, lower: 280, upper: 290, vary: true },
            { key: "amp", label: "amp", p0: 1, lower: 0, upper: null, vary: true },
            { key: "fwhm", label: "fwhm", p0: 1.2, lower: 1e-6, upper: 8, vary: true },
            { key: "m", label: "m", p0: 30, lower: 0, upper: 100, vary: true },
          ],
        },
      ],
      recipe_id: "r_a",
      recipe_ids: ["r_a"],
      recipe_components: { r_a: ["Peak_1"] },
    };
    const addedPeaks = fakeApply({
      recipe_id: "r_b",
      components: [{ component_id: "Peak_1", component_type: "gl" }],
      p0: [286.5, 1.0, 1.1, 30.0],
      bounds_lower: [280.0, 0.0, 1e-6, 0.0],
      bounds_upper: [290.0, null, 8.0, 100.0],
      vary: [true, true, true, true],
    });
    const next = appendRecipeApplyIntoEditor(base, addedPeaks, undefined);
    const types = next.components.map((c) => c.component_type);
    expect(types.filter((t) => t === "shirley_bg")).toHaveLength(1);
    expect(types.filter((t) => t === "gl")).toHaveLength(2);
    const ids = next.components.map((c) => c.component_id);
    expect(new Set(ids.map((x) => x.toLowerCase())).size).toBe(ids.length);
    expect(ids).toContain("Peak_1");
    expect(ids).toContain("Peak_2");
    expect(next.recipe_ids).toEqual(["r_a", "r_b"]);
    expect(next.recipe_components?.["r_b"]).toEqual(["Peak_2"]);
  });

  it("remove drops owned peaks and keeps other recipes", () => {
    const base: FittingEditorParams = {
      ...defaultFittingEditorParams(undefined),
      components: [
        {
          component_id: "bg",
          component_type: "shirley_bg",
          degree: 0,
          rows: [{ key: "k", label: "k", p0: 1, lower: 0, upper: null, vary: true }],
        },
        {
          component_id: "Peak_1",
          component_type: "gl",
          degree: 0,
          rows: [
            { key: "pos", label: "pos", p0: 285, lower: 280, upper: 290, vary: true },
            { key: "amp", label: "amp", p0: 1, lower: 0, upper: null, vary: true },
            { key: "fwhm", label: "fwhm", p0: 1.2, lower: 1e-6, upper: 8, vary: true },
            { key: "m", label: "m", p0: 30, lower: 0, upper: 100, vary: true },
          ],
        },
        {
          component_id: "Peak_2",
          component_type: "gl",
          degree: 0,
          rows: [
            { key: "pos", label: "pos", p0: 286.5, lower: 280, upper: 290, vary: true },
            { key: "amp", label: "amp", p0: 1, lower: 0, upper: null, vary: true },
            { key: "fwhm", label: "fwhm", p0: 1.1, lower: 1e-6, upper: 8, vary: true },
            { key: "m", label: "m", p0: 30, lower: 0, upper: 100, vary: true },
          ],
        },
      ],
      recipe_id: "r_a",
      recipe_ids: ["r_a", "r_b"],
      recipe_components: { r_a: ["Peak_1"], r_b: ["Peak_2"] },
      param_links: [
        {
          source_component_id: "Peak_2",
          source_key: "amp",
          target_component_id: "Peak_1",
          target_key: "amp",
          mode: "scale",
          scale: 0.5,
        },
      ],
    };
    const next = removeRecipeFromEditor(base, "r_b", undefined);
    expect(next.recipe_ids).toEqual(["r_a"]);
    expect(next.components.map((c) => c.component_id)).toEqual(["bg", "Peak_1"]);
    expect(next.param_links ?? []).toEqual([]);
    expect(next.recipe_components?.["r_b"]).toBeUndefined();
  });

  it("remove last recipe resets to default editor", () => {
    const only: FittingEditorParams = {
      ...defaultFittingEditorParams(undefined),
      components: [
        {
          component_id: "Peak_1",
          component_type: "gl",
          degree: 0,
          rows: [
            { key: "pos", label: "pos", p0: 285, lower: 280, upper: 290, vary: true },
            { key: "amp", label: "amp", p0: 1, lower: 0, upper: null, vary: true },
            { key: "fwhm", label: "fwhm", p0: 1.2, lower: 1e-6, upper: 8, vary: true },
            { key: "m", label: "m", p0: 30, lower: 0, upper: 100, vary: true },
          ],
        },
      ],
      recipe_id: "r_a",
      recipe_ids: ["r_a"],
      recipe_components: { r_a: ["Peak_1"] },
      fit_min_x: 280,
    };
    const next = removeRecipeFromEditor(only, "r_a", undefined);
    expect(next.recipe_ids ?? []).toEqual([]);
    expect(next.components).toHaveLength(1);
    expect(next.components[0]?.component_type).toBe("gaussian");
    expect(next.fit_min_x).toBe(280);
  });
});

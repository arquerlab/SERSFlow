import { describe, expect, it } from "vitest";
import {
  appendRecipeApplyIntoEditor,
  filterIndex,
  mergeRecipeApplyIntoEditor,
  removeRecipeFromEditor,
} from "./FittingRecipePicker";
import {
  defaultFittingEditorParams,
  flattenFittingForPipeline,
  renameFittingComponent,
  uniqueComponentIdAgainst,
  type FittingEditorParams,
} from "./fittingUtils";
import type { FittingRecipeApplyResponse, FittingRecipeIndexItem } from "./api";

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

function fakeIndexItem(partial: Partial<FittingRecipeIndexItem>): FittingRecipeIndexItem {
  return {
    id: "x",
    element: "O",
    region: "O_1s",
    compound: "Ni(II) NiO",
    source_table: "3.7",
    pass_energies: [10, 20],
    label: "Ni(II) NiO · O 1s · table 3.7",
    aliases: [],
    ...partial,
  };
}

describe("filterIndex element exact match", () => {
  const items = [
    fakeIndexItem({ id: "o_nio", element: "O", compound: "Ni(II) NiO", region: "O_1s" }),
    fakeIndexItem({ id: "o_feo", element: "O", compound: "Fe(II) FeO", region: "O_1s" }),
    fakeIndexItem({
      id: "ni_nio",
      element: "Ni",
      compound: "Ni(II) NiO",
      region: "Ni_2p3/2",
      label: "Ni(II) NiO · Ni 2p3/2",
    }),
    fakeIndexItem({
      id: "fe_feo",
      element: "Fe",
      compound: "Fe(II) FeO",
      region: "Fe_2p3/2",
      label: "Fe(II) FeO · Fe 2p3/2",
    }),
  ];

  it("O chip returns only element=O recipes, not every oxide formula", () => {
    const matched = filterIndex(items, "O");
    expect(matched.map((m) => m.id).sort()).toEqual(["o_feo", "o_nio"]);
  });

  it("still finds O 1s by region query", () => {
    const matched = filterIndex(items, "O 1s");
    expect(matched.every((m) => m.element === "O")).toBe(true);
    expect(matched.length).toBe(2);
  });
});

describe("uniqueComponentIdAgainst", () => {
  it("increments trailing numbers and falls back to _N", () => {
    const used = new Set<string>(["peak_1", "peak_2"]);
    expect(uniqueComponentIdAgainst("Peak_1", used)).toBe("Peak_3");
    expect(uniqueComponentIdAgainst("foo", used)).toBe("foo");
    expect(uniqueComponentIdAgainst("foo", used)).toBe("foo_2");
  });
});

describe("fitting component renames", () => {
  it("remaps parameter links and recipe ownership", () => {
    const fp: FittingEditorParams = {
      ...defaultFittingEditorParams(undefined),
      components: [
        {
          component_id: "water",
          component_type: "gl",
          degree: 0,
          rows: [{ key: "fwhm", label: "FWHM", p0: 1, lower: 0, upper: 3 }],
        },
        {
          component_id: "hydroxide",
          component_type: "gl",
          degree: 0,
          rows: [{ key: "fwhm", label: "FWHM", p0: 1, lower: 0, upper: 3 }],
        },
      ],
      param_links: [
        { source_component_id: "water", source_key: "fwhm", target_component_id: "hydroxide", target_key: "fwhm", mode: "equal" },
      ],
      recipe_components: { o_1s: ["water", "hydroxide"] },
    };
    const next = renameFittingComponent(fp, 0, "water_organic");
    expect(next.param_links).toEqual([
      { source_component_id: "water_organic", source_key: "fwhm", target_component_id: "hydroxide", target_key: "fwhm", mode: "equal" },
    ]);
    expect(next.recipe_components?.o_1s).toEqual(["water_organic", "hydroxide"]);
  });

  it("does not send dangling legacy links to the fitter", () => {
    const fp: FittingEditorParams = {
      ...defaultFittingEditorParams(undefined),
      components: [
        {
          component_id: "hydroxide",
          component_type: "gl",
          degree: 0,
          rows: [{ key: "fwhm", label: "FWHM", p0: 1, lower: 0, upper: 3 }],
        },
      ],
      param_links: [
        { source_component_id: "water", source_key: "fwhm", target_component_id: "hydroxide", target_key: "fwhm", mode: "equal" },
      ],
    };
    expect(flattenFittingForPipeline(fp).param_links).toBeUndefined();
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
    expect(next.amp_auto_bands).toBe(true);
  });

  it("replace prefills initial_area_ratios from apply payload", () => {
    const current = defaultFittingEditorParams(undefined);
    const next = mergeRecipeApplyIntoEditor(
      current,
      fakeApply({ recipe_id: "co_oh", initial_area_ratios: "38.1:26.6:33:2.4" }),
      undefined
    );
    expect(next.initial_area_ratios).toBe("38.1:26.6:33:2.4");
    expect(next.amp_auto_bands).toBe(true);
    const amp = next.components.find((c) => c.component_type !== "shirley_bg")?.rows.find((r) => r.key === "amp");
    expect(amp?.auto).toBe(true);
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

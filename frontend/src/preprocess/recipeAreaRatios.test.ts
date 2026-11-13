import { describe, expect, it } from "vitest";
import {
  fixRecipeAreaRatios,
  flattenFittingForPipeline,
  freeRecipeAreaRatios,
  migrateFittingParamsToEditor,
  recipeAreaLinks,
  recipePeakIds,
  renameFittingComponent,
  type FittingEditorParams,
} from "./fittingUtils";

function row(key: string, p0: number, vary = true) {
  return { key, label: key, p0, lower: null, upper: null, vary };
}

function base(): FittingEditorParams {
  const peak = (id: string, ampVary: boolean) => ({
    component_id: id,
    component_type: "gl" as const,
    degree: 0,
    rows: [row("pos", 1), row("amp", 1, ampVary), row("fwhm", 1, false), row("m", 30, false)],
    options: { recipe: "r1" },
  });
  return {
    output_mode: "fit",
    fill_opacity: 0.15,
    initial_guess_mode: "default",
    components: [peak("a", true), peak("b", false), peak("c", false)],
    param_links: [
      { source_component_id: "b", source_key: "amp", target_component_id: "a", target_key: "amp", mode: "area_ratio", ratio: 0.5 },
      { source_component_id: "c", source_key: "amp", target_component_id: "a", target_key: "amp", mode: "area_ratio", ratio: 0.2 },
      { source_component_id: "b", source_key: "pos", target_component_id: "a", target_key: "pos", mode: "offset", offset: 1 },
    ],
    recipe_id: "r1",
    recipe_ids: ["r1"],
  } as unknown as FittingEditorParams;
}

describe("recipe area ratios Fix / Free", () => {
  it("frees only the amp links of the recipe peaks, frees their amplitudes, and fix restores them", () => {
    const fp = base();
    expect(recipeAreaLinks(fp, "r1")).toHaveLength(2);
    const freed = freeRecipeAreaRatios(fp, "r1");
    expect(recipeAreaLinks(freed, "r1")).toHaveLength(0);
    expect(freed.param_links?.some((l) => l.source_key === "pos")).toBe(true); // positions stay linked
    expect(freed.components[1]!.rows.find((r) => r.key === "amp")!.vary).toBe(true);
    expect(freed.components[1]!.rows.find((r) => r.key === "fwhm")!.vary).toBe(false);
    const fixed = fixRecipeAreaRatios(freed, "r1");
    expect(recipeAreaLinks(fixed, "r1").map((l) => l.ratio)).toEqual([0.5, 0.2]);
    expect(fixed.components[2]!.rows.find((r) => r.key === "amp")!.vary).toBe(false);
    expect(fixed.recipe_area_links?.r1).toBeUndefined();
  });

  it("keeps working after a rename (peaks are found by their recipe tag, stored links are remapped)", () => {
    const freed = freeRecipeAreaRatios(base(), "r1");
    const renamed = renameFittingComponent(freed, 1, "Co_oct");
    expect(recipePeakIds(renamed, "r1")).toContain("Co_oct");
    const fixed = fixRecipeAreaRatios(renamed, "r1");
    expect(recipeAreaLinks(fixed, "r1").some((l) => l.source_component_id === "Co_oct")).toBe(true);
  });

  it("survives the pipeline round trip", () => {
    const freed = freeRecipeAreaRatios(base(), "r1");
    const flat = flattenFittingForPipeline(freed);
    expect((flat.components as Array<Record<string, unknown>>)[0]!.recipe).toBe("r1");
    const back = migrateFittingParamsToEditor(flat, undefined);
    expect(back.recipe_area_links?.r1).toHaveLength(2);
    expect(recipePeakIds(back, "r1")).toEqual(["a", "b", "c"]);
  });
});

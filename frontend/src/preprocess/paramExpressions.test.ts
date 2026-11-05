import { describe, expect, it } from "vitest";
import {
  defaultFittingEditorParams,
  flattenFittingForPipeline,
  migrateFittingParamsToEditor,
  renameFittingComponent,
  type FittingEditorParams,
  type FittingParamLink,
} from "./fittingUtils";
import { exprRefs, linkColor, linkDriverIds, linkUsesOnly, remapExprIds } from "./paramExpressions";

const expr: FittingParamLink = {
  source_component_id: "C",
  source_key: "pos",
  target_component_id: "",
  target_key: "",
  mode: "expr",
  expr: "{A.pos} + 0.5*({B.pos} - {A.pos})",
};

describe("F4 expression links", () => {
  it("parses references, including ids with symbols", () => {
    expect(exprRefs(expr.expr)).toEqual([
      { componentId: "A", key: "pos" },
      { componentId: "B", key: "pos" },
    ]);
    expect(exprRefs("{Co3+.area}*{2p3/2_sat.fwhm}").map((r) => r.componentId)).toEqual(["Co3+", "2p3/2_sat"]);
    expect(remapExprIds("{A.pos}+{A.fwhm}", (id) => (id === "A" ? "Z" : id))).toBe("{Z.pos}+{Z.fwhm}");
  });

  it("knows which peaks a link follows and colours it", () => {
    expect(linkDriverIds(expr)).toEqual(["A", "B"]);
    const colours = new Map([
      ["A", "#e67e22"],
      ["B", "#3498db"],
    ]);
    expect(linkColor(expr, colours)).toBe("#7f8c8d"); // several drivers: neutral
    expect(linkColor({ ...expr, expr: "{B.pos}+1" }, colours)).toBe("#3498db");
    expect(linkUsesOnly(expr, new Set(["A", "B", "C"]))).toBe(true);
    expect(linkUsesOnly(expr, new Set(["A", "C"]))).toBe(false);
  });

  it("survives flatten / migrate and a peak rename", () => {
    const base = defaultFittingEditorParams(undefined);
    const comps = ["A", "B", "C"].map((id) => ({ ...base.components[0]!, component_id: id }));
    let fp: FittingEditorParams = { ...base, components: comps, param_links: [expr] };
    const flat = flattenFittingForPipeline(fp) as { param_links: Record<string, unknown>[] };
    expect(flat.param_links).toEqual([
      { source_component_id: "C", source_key: "pos", mode: "expr", expr: expr.expr },
    ]);
    const back = migrateFittingParamsToEditor(flat as Record<string, unknown>, undefined);
    expect(back.param_links?.[0]?.mode).toBe("expr");
    fp = renameFittingComponent(fp, 0, "Co3plus");
    expect(fp.param_links?.[0]?.expr).toBe("{Co3plus.pos} + 0.5*({B.pos} - {Co3plus.pos})");
  });
});

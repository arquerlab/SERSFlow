import { describe, expect, it } from "vitest";
import { migrateMetadataFilterStepsOnLoad, type EditorStep } from "./editorTypes";

function mf(id: string, action: string, values: string[]): EditorStep {
  return {
    id,
    name: "metadata_filter",
    enabled: true,
    params: { action, filters: [{ field: "xps_region", op: "in", values }] },
    input_from: "previous",
    after_step_id: null,
  };
}

describe("migrateMetadataFilterStepsOnLoad", () => {
  it("rewrites exclude/empty action to keep and keeps sequential filters separate", () => {
    const steps: EditorStep[] = [
      mf("a", "exclude", ["C1s"]),
      mf("b", "exclude", ["O1s"]),
      {
        id: "c",
        name: "baseline",
        enabled: true,
        params: {},
        input_from: "previous",
        after_step_id: null,
      },
    ];
    const out = migrateMetadataFilterStepsOnLoad(steps);
    expect(out).toHaveLength(3);
    expect(out[0]?.name).toBe("metadata_filter");
    expect(out[0]?.params.action).toBe("keep");
    expect(out[0]?.params.filters).toEqual([{ field: "xps_region", op: "in", values: ["C1s"] }]);
    expect(out[1]?.name).toBe("metadata_filter");
    expect(out[1]?.params.action).toBe("keep");
    expect(out[1]?.params.filters).toEqual([{ field: "xps_region", op: "in", values: ["O1s"] }]);
    expect(out[2]?.name).toBe("baseline");
  });

  it("does not merge different fields", () => {
    const steps: EditorStep[] = [
      mf("a", "keep", ["C1s"]),
      {
        id: "b",
        name: "metadata_filter",
        enabled: true,
        params: {
          action: "keep",
          filters: [{ field: "other", op: "in", values: ["x"] }],
        },
        input_from: "previous",
        after_step_id: null,
      },
    ];
    const out = migrateMetadataFilterStepsOnLoad(steps);
    expect(out).toHaveLength(2);
  });
});

import { describe, expect, it } from "vitest";
import type { EditorStep } from "./editorTypes";
import {
  canonicalizeCalibrationPosKey,
  fittingPosKeysForStep,
  normalizeXAxisCalibrationParams,
} from "./xAxisCalibrationUtils";

describe("xAxisCalibrationUtils", () => {
  it("canonicalizes legacy multi-fit pos_key prefixes", () => {
    expect(canonicalizeCalibrationPosKey("s1_fit_C1s_main_pos")).toBe("fit_C1s_main_pos");
    expect(canonicalizeCalibrationPosKey("fit_g1_pos")).toBe("fit_g1_pos");
  });

  it("normalizes params by stripping sN_ from pos_key", () => {
    const n = normalizeXAxisCalibrationParams(
      {
        method: "reference_peak",
        fitting_step_id: "f1",
        pos_key: "s1_fit_C1s_main_pos",
        target_x: 284.8,
      },
      "xps"
    );
    expect(n.pos_key).toBe("fit_C1s_main_pos");
    expect(n.method).toBe("reference_peak");
    expect(n.reference_filters).toEqual([]);
  });

  it("fittingPosKeysForStep is always unprefixed", () => {
    const step: EditorStep = {
      id: "fit-1",
      name: "fitting",
      enabled: true,
      input_from: "previous",
      after_step_id: null,
      params: {
        xps_region: "C1s",
        components: [{ component_id: "main", component_type: "gaussian" }],
      },
    };
    expect(fittingPosKeysForStep(step)).toEqual(["fit_C1s_main_pos"]);
  });

  it("includes fermi center keys", () => {
    const step: EditorStep = {
      id: "fit-1",
      name: "fitting",
      enabled: true,
      input_from: "previous",
      after_step_id: null,
      params: {
        xps_region: "valence band",
        components: [{ component_id: "Fermi_edge", component_type: "fermi_edge" }],
      },
    };
    expect(fittingPosKeysForStep(step)).toEqual(["fit_valence_band_Fermi_edge_center"]);
  });
});

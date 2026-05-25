import type { FieldSpec } from "./editorTypes";

/** UI-only method/param matrix for preprocess steps; backend remains authoritative for execution. */
export const pipelineStepSpecs: Record<
  string,
  {
    methodLabel: string;
    methods: { id: string; label: string; defaults: Record<string, unknown>; fields: FieldSpec[] }[];
    commonFields?: FieldSpec[];
  }
> = {
  cosmic_ray_removal: {
    methodLabel: "method",
    methods: [
      {
        id: "zscore",
        label: "zscore",
        defaults: {
          threshold: 5.0,
          window: 5,
          interpolation: "median",
          max_width: 10,
          min_intensity_ratio: 2.0,
          n_iterations: 3,
        },
        fields: [],
      },
      {
        id: "derivative",
        label: "derivative",
        defaults: {
          threshold: 3.0,
          window: 3,
          interpolation: "median",
          max_width: 10,
          min_intensity_ratio: 2.0,
          n_iterations: 3,
        },
        fields: [],
      },
    ],
    commonFields: [
      { key: "threshold", kind: "number", label: "threshold" },
      { key: "window", kind: "int", label: "window" },
      { key: "interpolation", kind: "select", label: "interpolation", options: ["median", "linear", "cubic"] },
      { key: "max_width", kind: "int", label: "max_width" },
      { key: "min_intensity_ratio", kind: "number", label: "min_intensity_ratio" },
      { key: "n_iterations", kind: "int", label: "n_iterations" },
    ],
  },
  baseline: {
    methodLabel: "method",
    methods: [
      {
        id: "derpsalsa",
        label: "derpsalsa",
        defaults: { lam: 3e5, p: 0.001 },
        fields: [
          { key: "lam", kind: "number", label: "lam" },
          { key: "p", kind: "number", label: "p" },
        ],
      },
      {
        id: "asls",
        label: "asls",
        defaults: { lam: 1e6, p: 0.01 },
        fields: [
          { key: "lam", kind: "number", label: "lam" },
          { key: "p", kind: "number", label: "p" },
        ],
      },
      { id: "arpls", label: "arpls", defaults: { lam: 1e5 }, fields: [{ key: "lam", kind: "number", label: "lam" }] },
      { id: "mor", label: "mor", defaults: { half_window: 30 }, fields: [{ key: "half_window", kind: "int", label: "half_window" }] },
      { id: "mormol", label: "mormol", defaults: { half_window: 30 }, fields: [{ key: "half_window", kind: "int", label: "half_window" }] },
      {
        id: "ria",
        label: "ria",
        defaults: { half_window: 6, width_scale: 1, extrapolate_window: 20 },
        fields: [
          { key: "half_window", kind: "int", label: "half_window" },
          { key: "width_scale", kind: "number", label: "width_scale" },
          { key: "extrapolate_window", kind: "int", label: "extrapolate_window" },
        ],
      },
      {
        id: "snip",
        label: "snip",
        defaults: { max_half_window: 40 },
        fields: [{ key: "max_half_window", kind: "int", label: "max_half_window" }],
      },
    ],
  },
  normalize: {
    methodLabel: "method",
    methods: [
      { id: "max", label: "max", defaults: {}, fields: [] },
      { id: "min", label: "min", defaults: {}, fields: [] },
      { id: "mean", label: "mean", defaults: {}, fields: [] },
      { id: "median", label: "median", defaults: {}, fields: [] },
      { id: "vector", label: "vector (L2)", defaults: {}, fields: [] },
      {
        id: "spectrum_point",
        label: "spectrum point",
        defaults: { point_x: 1000 },
        fields: [{ key: "point_x", kind: "number", label: "point_x" }],
      },
      {
        id: "baseline_point",
        label: "baseline point",
        defaults: { baseline_step_id: "", point_x: 1000 },
        fields: [{ key: "point_x", kind: "number", label: "point_x" }],
      },
    ],
  },
  align_resample: {
    methodLabel: "mode",
    methods: [
      {
        id: "uniform",
        label: "uniform grid",
        defaults: {
          method: "uniform",
          min_x: 400,
          max_x: 2000,
          grid_mode: "step",
          step: 1.0,
          n_points: 512,
          interp: "linear",
        },
        fields: [
          { key: "min_x", kind: "number", label: "min_x" },
          { key: "max_x", kind: "number", label: "max_x" },
          { key: "grid_mode", kind: "select", label: "grid_mode", options: ["step", "points"] },
          { key: "step", kind: "number", label: "step" },
          { key: "n_points", kind: "int", label: "n_points" },
          { key: "interp", kind: "select", label: "interp", options: ["linear", "cubic"] },
        ],
      },
    ],
  },
};

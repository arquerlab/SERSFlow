import type { BaselineMethodSpecPublic, BaselineMethodsResponse, BaselineParamSpecPublic } from "./api";

const desc: Record<string, string> = {
  lam: "Smoothness penalty; larger values produce smoother baselines.",
  p: "Asymmetry or penalty balance; lower values suppress positive peaks more strongly.",
  half_window: "Local window radius used for morphological or smoothing operations.",
  max_half_window: "Maximum local window radius used by iterative smoothing methods.",
  min_half_window: "Minimum local window radius.",
  width_scale: "Ria peak-width scaling factor.",
  num_knots: "Number of spline knots; higher values allow more flexible baselines.",
  poly_order: "Polynomial degree used to model the baseline.",
  quantile: "Target quantile for quantile-based baseline fitting.",
  fraction: "Fraction of points used in each local LOESS regression.",
  freq_cutoff: "BEADS cutoff frequency separating baseline from peaks.",
};

function p(key: string, kind: BaselineParamSpecPublic["kind"], def: unknown, role: BaselineParamSpecPublic["ui_role"]): BaselineParamSpecPublic {
  return {
    key,
    kind,
    default: def,
    nullable: def === null,
    ui_role: role,
    description: desc[key] ?? `pybaselines parameter ${key}.`,
    options: [],
  };
}

function method(id: string, category: string, params: BaselineParamSpecPublic[], ui_enabled = true): BaselineMethodSpecPublic {
  return { id, label: id, category, ui_enabled, params };
}

export const fallbackBaselineCatalog: BaselineMethodsResponse = {
  categories: [
    { id: "whittaker", label: "Whittaker" },
    { id: "smoothing", label: "Smoothing" },
    { id: "splines", label: "Splines" },
    { id: "polynomial", label: "Polynomial" },
    { id: "morphological", label: "Morphological" },
    { id: "miscellaneous", label: "Miscellaneous" },
  ],
  methods: [
    method("asls", "whittaker", [p("lam", "number", 1_000_000, "primary"), p("p", "number", 0.01, "primary")]),
    method("iasls", "whittaker", [p("lam", "number", 1_000_000, "primary"), p("p", "number", 0.01, "primary")]),
    method("airpls", "whittaker", [p("lam", "number", 1_000_000, "primary")]),
    method("arpls", "whittaker", [p("lam", "number", 100_000, "primary")]),
    method("drpls", "whittaker", [p("lam", "number", 100_000, "primary")]),
    method("iarpls", "whittaker", [p("lam", "number", 100_000, "primary")]),
    method("aspls", "whittaker", [p("lam", "number", 100_000, "primary")]),
    method("psalsa", "whittaker", [p("lam", "number", 100_000, "primary"), p("p", "number", 0.5, "primary")]),
    method("derpsalsa", "whittaker", [p("lam", "number", 1_000_000, "primary"), p("p", "number", 0.01, "primary")]),
    method("brpls", "whittaker", [p("lam", "number", 100_000, "primary")]),
    method("lsrpls", "whittaker", [p("lam", "number", 100_000, "primary")]),
    method("noise_median", "smoothing", [p("half_window", "int", null, "primary")]),
    method("snip", "smoothing", [p("max_half_window", "int", null, "primary")]),
    method("swima", "smoothing", [p("min_half_window", "int", 3, "primary"), p("max_half_window", "int", null, "primary")]),
    method("ipsa", "smoothing", [p("half_window", "int", null, "primary")]),
    method("ria", "smoothing", [p("half_window", "int", null, "primary"), p("width_scale", "number", 0.1, "primary")]),
    method("peak_filling", "smoothing", [p("half_window", "int", null, "primary")]),
    method("mixture_model", "splines", [p("lam", "number", 100_000, "primary"), p("p", "number", 0.01, "primary"), p("num_knots", "int", 100, "primary")]),
    method("irsqr", "splines", [p("lam", "number", 100, "primary"), p("num_knots", "int", 100, "primary")]),
    method("corner_cutting", "splines", []),
    method("pspline_asls", "splines", [p("lam", "number", 1_000, "primary"), p("p", "number", 0.01, "primary"), p("num_knots", "int", 100, "primary")]),
    method("pspline_iasls", "splines", [p("lam", "number", 10, "primary"), p("p", "number", 0.01, "primary"), p("num_knots", "int", 100, "primary")]),
    method("pspline_airpls", "splines", [p("lam", "number", 1_000, "primary"), p("num_knots", "int", 100, "primary")]),
    method("pspline_arpls", "splines", [p("lam", "number", 1_000, "primary"), p("num_knots", "int", 100, "primary")]),
    method("pspline_drpls", "splines", [p("lam", "number", 1_000, "primary"), p("num_knots", "int", 100, "primary")]),
    method("pspline_iarpls", "splines", [p("lam", "number", 1_000, "primary"), p("num_knots", "int", 100, "primary")]),
    method("pspline_aspls", "splines", [p("lam", "number", 10_000, "primary"), p("num_knots", "int", 100, "primary")]),
    method("pspline_psalsa", "splines", [p("lam", "number", 1_000, "primary"), p("p", "number", 0.5, "primary"), p("num_knots", "int", 100, "primary")]),
    method("pspline_derpsalsa", "splines", [p("lam", "number", 100, "primary"), p("p", "number", 0.01, "primary"), p("num_knots", "int", 100, "primary")]),
    method("pspline_mpls", "splines", [p("half_window", "int", null, "primary"), p("lam", "number", 1_000, "primary"), p("p", "number", 0, "primary"), p("num_knots", "int", 100, "primary")]),
    method("pspline_brpls", "splines", [p("lam", "number", 1_000, "primary"), p("num_knots", "int", 100, "primary")]),
    method("pspline_lsrpls", "splines", [p("lam", "number", 1_000, "primary"), p("num_knots", "int", 100, "primary")]),
    method("poly", "polynomial", [p("poly_order", "int", 2, "primary")]),
    method("modpoly", "polynomial", [p("poly_order", "int", 2, "primary")]),
    method("imodpoly", "polynomial", [p("poly_order", "int", 2, "primary")]),
    method("penalized_poly", "polynomial", [p("poly_order", "int", 2, "primary")]),
    method("loess", "polynomial", [p("fraction", "number", 0.2, "primary"), p("poly_order", "int", 1, "primary")]),
    method("quant_reg", "polynomial", [p("poly_order", "int", 2, "primary"), p("quantile", "number", 0.05, "primary")]),
    method("goldindec", "polynomial", [p("poly_order", "int", 2, "primary")]),
    method("mpls", "morphological", [p("half_window", "int", null, "primary"), p("lam", "number", 1_000_000, "primary"), p("p", "number", 0, "primary")]),
    method("mor", "morphological", [p("half_window", "int", null, "primary")]),
    method("imor", "morphological", [p("half_window", "int", null, "primary")]),
    method("mormol", "morphological", [p("half_window", "int", null, "primary")]),
    method("amormol", "morphological", [p("half_window", "int", null, "primary")]),
    method("rolling_ball", "morphological", [p("half_window", "int", null, "primary")]),
    method("mwmv", "morphological", [p("half_window", "int", null, "primary")]),
    method("tophat", "morphological", [p("half_window", "int", null, "primary")]),
    method("mpspline", "morphological", [p("half_window", "int", null, "primary"), p("lam", "number", 10_000, "primary"), p("p", "number", 0, "primary")]),
    method("jbcd", "morphological", [p("half_window", "int", null, "primary")]),
    method("interp_pts", "miscellaneous", [], false),
    method("beads", "miscellaneous", [p("freq_cutoff", "number", 0.005, "primary")]),
  ],
};

export function methodSpec(catalog: BaselineMethodsResponse, methodId: string): BaselineMethodSpecPublic | undefined {
  return catalog.methods.find((m) => m.id === methodId);
}

export function methodsForCategory(catalog: BaselineMethodsResponse, categoryId: string): BaselineMethodSpecPublic[] {
  return catalog.methods.filter((m) => m.category === categoryId && m.ui_enabled !== false);
}

export function methodCategoryFor(catalog: BaselineMethodsResponse, methodId: string): string {
  return methodSpec(catalog, methodId)?.category ?? catalog.categories[0]?.id ?? "";
}

export function defaultMethodForCategory(catalog: BaselineMethodsResponse, categoryId: string): BaselineMethodSpecPublic | undefined {
  return methodsForCategory(catalog, categoryId)[0] ?? catalog.methods.find((m) => m.ui_enabled !== false);
}

export function primaryParams(method: BaselineMethodSpecPublic | undefined): BaselineParamSpecPublic[] {
  return (method?.params ?? []).filter((p) => p.ui_role === "primary");
}

export function additionalParams(method: BaselineMethodSpecPublic | undefined): BaselineParamSpecPublic[] {
  return (method?.params ?? []).filter((p) => p.ui_role === "advanced");
}

export function paramsByKey(method: BaselineMethodSpecPublic | undefined): Map<string, BaselineParamSpecPublic> {
  return new Map((method?.params ?? []).map((p) => [p.key, p]));
}

export function defaultsForPrimaryParams(method: BaselineMethodSpecPublic | undefined): Record<string, unknown> {
  return Object.fromEntries(primaryParams(method).map((p) => [p.key, p.default]));
}

export function normalizeBaselineParams(
  params: Record<string, unknown> | null | undefined,
  catalog: BaselineMethodsResponse = fallbackBaselineCatalog
): Record<string, unknown> {
  const pIn = { ...(params ?? {}) };
  const methodId = String(pIn.method || catalog.methods.find((m) => m.ui_enabled !== false)?.id || "derpsalsa");
  const method = methodSpec(catalog, methodId) ?? catalog.methods.find((m) => m.ui_enabled !== false);
  if (!method) return pIn;
  const allowed = paramsByKey(method);
  const extra = Object.fromEntries(
    Object.entries(pIn).filter(([k]) => k !== "method" && allowed.has(k))
  );
  return { method: method.id, ...defaultsForPrimaryParams(method), ...extra };
}

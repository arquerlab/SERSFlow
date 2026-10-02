"""UI schemas lifted from the frontend pipelineStepSpecs matrix."""

from __future__ import annotations

from sersflow.core.pipeline.library.types import StepMethodUi, StepUiSchema, UiFieldSpec

_F = UiFieldSpec


def _custom(editor: str) -> StepUiSchema:
    return StepUiSchema(method_param_key=None, methods=(), custom_editor=editor)


CROP = StepUiSchema(
    method_param_key=None,
    methods=(
        StepMethodUi(
            id="crop",
            label="crop",
            defaults={"min_x": None, "max_x": None},
            fields=(
                _F("min_x", "number", "min_x", "Lower axis bound (inclusive)."),
                _F("max_x", "number", "max_x", "Upper axis bound (inclusive)."),
            ),
        ),
    ),
)

COSMIC_RAY_REMOVAL = StepUiSchema(
    method_param_key="method",
    methods=(
        StepMethodUi(
            id="zscore",
            label="zscore",
            defaults={
                "threshold": 5.0,
                "window": 5,
                "interpolation": "median",
                "max_width": 10,
                "min_intensity_ratio": 2.0,
                "n_iterations": 3,
            },
        ),
        StepMethodUi(
            id="derivative",
            label="derivative",
            defaults={
                "threshold": 3.0,
                "window": 3,
                "interpolation": "median",
                "max_width": 10,
                "min_intensity_ratio": 2.0,
                "n_iterations": 3,
            },
        ),
    ),
    common_fields=(
        _F(
            "threshold",
            "number",
            "threshold",
            "Detection sensitivity. Higher values are less aggressive.",
        ),
        _F("window", "int", "window", "Neighborhood half-window (points)."),
        _F(
            "interpolation",
            "select",
            "interpolation",
            "How flagged spike regions are replaced.",
            options=("median", "linear", "cubic"),
        ),
        _F("max_width", "int", "max_width", "Maximum spike width (points) to correct."),
        _F(
            "min_intensity_ratio",
            "number",
            "min_intensity_ratio",
            "Spike must exceed local baseline by this ratio.",
        ),
        _F("n_iterations", "int", "n_iterations", "Number of detect→correct passes."),
    ),
)

BASELINE = StepUiSchema(
    method_param_key="method",
    methods=(
        StepMethodUi(
            id="derpsalsa",
            label="derpsalsa",
            defaults={"lam": 3e5, "p": 0.001},
            fields=(_F("lam", "number", "lam"), _F("p", "number", "p")),
        ),
        StepMethodUi(
            id="asls",
            label="asls",
            defaults={"lam": 1e6, "p": 0.01},
            fields=(_F("lam", "number", "lam"), _F("p", "number", "p")),
        ),
        StepMethodUi(id="arpls", label="arpls", defaults={"lam": 1e5}, fields=(_F("lam", "number", "lam"),)),
        StepMethodUi(
            id="mor",
            label="mor",
            defaults={"half_window": 30},
            fields=(_F("half_window", "int", "half_window"),),
        ),
        StepMethodUi(
            id="mormol",
            label="mormol",
            defaults={"half_window": 30},
            fields=(_F("half_window", "int", "half_window"),),
        ),
        StepMethodUi(
            id="ria",
            label="ria",
            defaults={"half_window": 6, "width_scale": 1, "extrapolate_window": 20},
            fields=(
                _F("half_window", "int", "half_window"),
                _F("width_scale", "number", "width_scale"),
                _F("extrapolate_window", "int", "extrapolate_window"),
            ),
        ),
        StepMethodUi(
            id="snip",
            label="snip",
            defaults={"max_half_window": 40},
            fields=(_F("max_half_window", "int", "max_half_window"),),
        ),
    ),
)

NORMALIZE = StepUiSchema(
    method_param_key="method",
    methods=(
        StepMethodUi(id="max", label="max"),
        StepMethodUi(id="min", label="min"),
        StepMethodUi(id="mean", label="mean"),
        StepMethodUi(id="median", label="median"),
        StepMethodUi(id="vector", label="vector (L2)"),
        StepMethodUi(
            id="spectrum_point",
            label="spectrum point",
            defaults={"point_x": 1000},
            fields=(_F("point_x", "number", "point_x"),),
        ),
        StepMethodUi(
            id="baseline_point",
            label="baseline point",
            defaults={"baseline_step_id": "", "point_x": 1000},
            fields=(_F("point_x", "number", "point_x"),),
        ),
    ),
)

ALIGN_RESAMPLE = StepUiSchema(
    method_param_key="mode",
    methods=(
        StepMethodUi(
            id="uniform",
            label="uniform grid",
            defaults={
                "method": "uniform",
                "min_x": 400,
                "max_x": 2000,
                "grid_mode": "step",
                "step": 1.0,
                "n_points": 512,
                "interp": "linear",
            },
            fields=(
                _F("min_x", "number", "min_x", "Lower Raman-shift bound for the common grid."),
                _F("max_x", "number", "max_x", "Upper Raman-shift bound for the common grid."),
                _F(
                    "grid_mode",
                    "select",
                    "grid_mode",
                    "Define the grid by step size or number of points.",
                    options=("step", "points"),
                ),
                _F("step", "number", "step", "Grid spacing when grid_mode=step."),
                _F("n_points", "int", "n_points", "Number of points when grid_mode=points."),
                _F(
                    "interp",
                    "select",
                    "interp",
                    "Interpolation method during resampling.",
                    options=("linear", "cubic"),
                ),
            ),
        ),
    ),
)

X_AXIS_CALIBRATION = StepUiSchema(
    method_param_key="method",
    methods=(
        StepMethodUi(
            id="fixed_offset",
            label="fixed offset",
            defaults={"offset": 0, "fitting_step_id": "", "pos_key": "", "target_x": 0},
            fields=(
                _F(
                    "offset",
                    "number",
                    "offset",
                    "Constant added to every x value (same units as the spectrum axis).",
                ),
            ),
        ),
        StepMethodUi(
            id="reference_peak",
            label="reference peak",
            defaults={"offset": 0, "fitting_step_id": "", "pos_key": "", "target_x": 0},
            fields=(
                _F(
                    "target_x",
                    "number",
                    "target_x",
                    "Desired position of the selected fitted peak after calibration.",
                ),
            ),
        ),
    ),
)

NOISE_SAVGOL = StepUiSchema(
    method_param_key="method",
    methods=(
        StepMethodUi(
            id="savgol",
            label="Savitzky–Golay",
            defaults={"window_length": 11, "polyorder": 3},
            fields=(
                _F(
                    "window_length",
                    "int",
                    "window_length",
                    "Filter window length (odd integer).",
                ),
                _F(
                    "polyorder",
                    "int",
                    "polyorder",
                    "Polynomial order; must be < window_length.",
                ),
            ),
        ),
    ),
)

SPECTRUM_DERIVATIVE = StepUiSchema(
    method_param_key="method",
    methods=(
        StepMethodUi(
            id="gradient",
            label="gradient",
            defaults={"method": "gradient", "order": 1},
            fields=(
                _F("order", "int", "order", "Derivative order (1 = first derivative)."),
            ),
        ),
    ),
)

BASELINE_CURVE = StepUiSchema(
    method_param_key="method",
    methods=BASELINE.methods,
)

FITTING = _custom("fitting")
SPECTRAL_INTENSITIES = _custom("spectral_intensities")
SPECTRAL_INTEGRATIONS = _custom("spectral_integrations")
FEATURE_OPERATIONS = _custom("feature_operations")
REFERENCE_TRANSFORM = _custom("reference_transform")
LOW_SIGNAL_FILTER = _custom("low_signal_filter")
OUTLIER_DETECTION = _custom("outlier_detection")
METADATA_FILTER = _custom("metadata_filter")

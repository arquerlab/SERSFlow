"""Register builtin StepSpecs wrapping DEFAULT_STEPS + QC palette entries."""

from __future__ import annotations

from sersflow.core.pipeline.library import ui_schemas as ui
from sersflow.core.pipeline.library.registry import register_step
from sersflow.core.pipeline.library.types import StepSpec
from sersflow.core.pipeline.steps import DEFAULT_STEPS


def _impl(name: str):
    return DEFAULT_STEPS.get(name)


def _register(spec: StepSpec) -> StepSpec:
    from sersflow.core.pipeline.library.registry import STEP_LIBRARY

    if spec.id in STEP_LIBRARY:
        raise ValueError(f"Step id already registered: {spec.id!r}")
    return register_step(spec)


_register(
    StepSpec(
        id="crop",
        label="Cropping",
        category="geometry",
        palette_group="Data Preparation",
        description="Restrict the spectral axis to a selected range.",
        impl=_impl("crop"),
        ui=ui.CROP,
    )
)
_register(
    StepSpec(
        id="align_resample",
        label="Alignment & Resampling",
        category="geometry",
        palette_group="Preprocessing",
        description="Align spectral features and interpolate onto a common axis.",
        impl=_impl("align_resample"),
        ui=ui.ALIGN_RESAMPLE,
    )
)
_register(
    StepSpec(
        id="x_axis_calibration",
        label="X-axis Calibration",
        category="calibrate",
        palette_group="Preprocessing",
        description="Shift the spectral axis using a fixed offset or a reference peak.",
        impl=_impl("x_axis_calibration"),
        ui=ui.X_AXIS_CALIBRATION,
    )
)
_register(
    StepSpec(
        id="noise_savgol",
        label="Smoothing",
        category="denoise",
        palette_group="Preprocessing",
        description="Reduce high-frequency noise while preserving peak shapes.",
        impl=_impl("noise_savgol"),
        ui=ui.NOISE_SAVGOL,
    )
)
_register(
    StepSpec(
        id="cosmic_ray_removal",
        label="Cosmic Ray Removal",
        category="denoise",
        palette_group="Preprocessing",
        description="Detect and replace spike-like cosmic ray artifacts.",
        impl=_impl("cosmic_ray_removal"),
        ui=ui.COSMIC_RAY_REMOVAL,
        requires_technique=frozenset({"vibrational"}),
    )
)
_register(
    StepSpec(
        id="baseline",
        label="Baseline Correction",
        category="baseline",
        palette_group="Preprocessing",
        description="Estimate and subtract a slowly varying background.",
        impl=_impl("baseline"),
        ui=ui.BASELINE,
        validation_rules=("no_dual_xps_background",),
    )
)
_register(
    StepSpec(
        id="baseline_curve",
        label="Baseline curve",
        category="baseline",
        palette_group="Preprocessing",
        description="Compute a baseline curve without subtracting it.",
        impl=_impl("baseline_curve"),
        ui=ui.BASELINE_CURVE,
        validation_rules=("no_dual_xps_background",),
    )
)
_register(
    StepSpec(
        id="normalize",
        label="Normalization",
        category="geometry",
        palette_group="Transformation",
        description="Transform spectral intensity scale.",
        impl=_impl("normalize"),
        ui=ui.NORMALIZE,
    )
)
_register(
    StepSpec(
        id="spectrum_derivative",
        label="Derivative",
        category="features",
        palette_group="Transformation",
        description="Calculate first- or higher-order spectral derivatives.",
        impl=_impl("spectrum_derivative"),
        ui=ui.SPECTRUM_DERIVATIVE,
    )
)
_register(
    StepSpec(
        id="reference_transform",
        label="Reference Transformation",
        category="reference",
        palette_group="Transformation",
        description="Transform each spectrum relative to a selected reference.",
        impl=_impl("reference_transform"),
        ui=ui.REFERENCE_TRANSFORM,
    )
)
_register(
    StepSpec(
        id="spectral_intensities",
        label="Peak Identification",
        category="features",
        palette_group="Feature Extraction",
        description="Detect spectral peaks (intensity probes).",
        impl=_impl("spectral_intensities"),
        ui=ui.SPECTRAL_INTENSITIES,
    )
)
_register(
    StepSpec(
        id="fitting",
        label="Peak Fitting",
        category="fit",
        palette_group="Feature Extraction",
        description="Fit analytical peak models and extract parameters.",
        impl=_impl("fitting"),
        ui=ui.FITTING,
    )
)
_register(
    StepSpec(
        id="spectral_integrations",
        label="Peak Integration",
        category="features",
        palette_group="Feature Extraction",
        description="Integrate intensity over regions or fitted peaks.",
        impl=_impl("spectral_integrations"),
        ui=ui.SPECTRAL_INTEGRATIONS,
    )
)
_register(
    StepSpec(
        id="feature_operations",
        label="Metric Calculation",
        category="features",
        palette_group="Feature Extraction",
        description="Derive metrics from previously extracted features.",
        impl=_impl("feature_operations"),
        ui=ui.FEATURE_OPERATIONS,
    )
)
_register(
    StepSpec(
        id="low_signal_filter",
        label="Low-Signal Filter",
        category="qc",
        palette_group="Data Preparation",
        description="Detect and exclude low-count spectra.",
        impl=None,
        ui=ui.LOW_SIGNAL_FILTER,
    )
)
_register(
    StepSpec(
        id="outlier_detection",
        label="Outlier Detection",
        category="qc",
        palette_group="Data Preparation",
        description="Detect anomalous whole spectra.",
        impl=None,
        ui=ui.OUTLIER_DETECTION,
    )
)
_register(
    StepSpec(
        id="metadata_filter",
        label="Metadata Filter",
        category="geometry",
        palette_group="Data Preparation",
        description=(
            "Mask non-matching spectra on this branch (empty XY), like crop for spectra. "
            "Respects input_from so a later filter can restart from initial."
        ),
        impl=_impl("metadata_filter"),
        ui=ui.METADATA_FILTER,
    )
)

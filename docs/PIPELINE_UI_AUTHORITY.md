# Pipeline UI authority

## Source of truth

- **Behavioral truth** for what a pipeline step does, which parameters are legal, and how the engine executes lives in **Python**: the pipeline engine (`sersflow.core.pipeline`), step library (`sersflow.core.pipeline.library`), and Pydantic models (`sersflow.api.schemas.pipeline` and related schemas).
- **UI schemas** for the Prepare palette and generic param editors are served by `GET /meta/pipeline-steps` from Python `StepUiSchema`. The frontend must not own a parallel defaults matrix.

If the UI emits JSON that the backend accepts but the Python engine cannot run, the bug is either in backend validation or in the UI emitting invalid combinations — fix by aligning with Python, not by “fixing” the engine to match the form.

## Checklist: add or change a step

1. Implement or update the transform in Python and register a `StepSpec` in `core/pipeline/library/` (impl + UI + applicability).
2. Extend Pydantic `PipelineStep` / params models if new fields are required.
3. Add or update tests under `tests/` that run a minimal pipeline containing the step.
4. Confirm `GET /meta/pipeline-steps` exposes the new step; add a React custom editor only when `ui.custom_editor` is set.
5. Run `pytest` and `npm run build` in `frontend/` before merging.

## Related

- File formats: `GET /meta/formats` and `sersflow.core.io.formats` (add a format = new module under `formats/` + `register_format()`).
- Historical multi-block label key `vms_spectra` is format-agnostic persistence; access only via helpers in `multi_block_labels.py` (no rename of persisted blobs).
- Filter/plot field labels come from capability-pack `FilterFieldDef`s (`formats/packs.py`), not parallel XPS tuple catalogs.
- Fitting XPS background shapes/keys come from `GET /fitting/models`; vibrational peak fallbacks may remain in the FE for offline defaults.
- Engine resolves transform steps only from `STEP_LIBRARY`; QC-only steps (`impl is None`) raise if executed as transforms.

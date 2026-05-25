# Pipeline UI authority

## Source of truth

- **Behavioral truth** for what a pipeline step does, which parameters are legal, and how the engine executes lives in **Python**: the pipeline engine (`sersflow.core.pipeline`), step implementations, and Pydantic models (`sersflow.api.schemas.pipeline` and related schemas).
- **TypeScript** specs in the frontend (`frontend/src/preprocess/pipelineStepSpecs.ts`, editor helpers, forms) are **presentation-only**: they describe labels, default values, and which fields to show. They must not be treated as an execution contract.

If the UI emits JSON that the backend accepts but the Python engine cannot run, the bug is either in backend validation or in the UI emitting invalid combinations — fix by aligning with Python, not by “fixing” the engine to match the form.

## Checklist: add or change a step

1. Implement or update the step in Python and register it in the step registry used by the engine.
2. Extend Pydantic `PipelineStep` / params models if new fields are required.
3. Add or update tests under `tests/` that run a minimal pipeline containing the step (see `tests/test_pipeline_step_schema.py` and integration tests).
4. Update the **TS** `pipelineStepSpecs` (and related editor code) so the Prepare UI stays usable — defaults and field lists only.
5. Run `pytest` and `npm run build` in `frontend/` before merging.

## Backlog

Optional `GET /pipeline/step-metadata` generated from Python is **not** implemented. Consider it only if duplication between UI and backend becomes painful; until then, follow this document and keep contract tests green.

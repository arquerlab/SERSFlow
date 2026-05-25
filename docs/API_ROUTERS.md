# API routers map

FastAPI app assembly: `src/sersflow/api/main.py`. Each row is the HTTP prefix exposed by `include_router`.

| URL prefix | Router module | Primary concern |
|------------|---------------|-----------------|
| _(none)_ | `routers/meta.py` | Health, static UI shell |
| `/io` | `routers/io.py` | Uploads and file IO |
| `/plot` | `routers/plot.py` | Plotting helpers |
| `/datasets` | `routers/datasets.py` | Dataset CRUD, spectrum metadata |
| `/pipeline` | `routers/pipeline.py` | Stateless pipeline runs |
| `/pipelines` | `routers/pipelines.py` | Saved pipeline library |
| `/metrics` | `routers/metrics.py` | Metric definitions |
| `/sessions` | `routers/sessions.py` | Sessions, subset, session runs |
| `/fitting` | `routers/fitting.py` | Fitting registry and fit |
| `/analysis` | `routers/analysis.py` | Analysis runs, exports |
| `/explore` | `routers/explore.py` | Explore stats, matrix jobs, FPCA |

OpenAPI tags on each router match these names for `/docs` grouping.

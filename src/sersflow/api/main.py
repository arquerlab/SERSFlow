from __future__ import annotations

import os

from fastapi import FastAPI

from sersflow.api.routers.datasets import router as datasets_router
from sersflow.api.routers.io import router as io_router
from sersflow.api.routers.meta import router as meta_router
from sersflow.api.routers.metrics import router as metrics_router
from sersflow.api.routers.pipeline import router as pipeline_router
from sersflow.api.routers.pipelines import router as pipelines_library_router
from sersflow.api.routers.plot import router as plot_router
from sersflow.api.routers.sessions import router as sessions_router
from sersflow.api.routers.fitting import router as fitting_router
from sersflow.api.routers.analysis import router as analysis_router
from sersflow.api.routers.explore import router as explore_router


app = FastAPI(title="SERSFlow API", version="0.1.0")

app.include_router(meta_router)
app.include_router(io_router)
app.include_router(plot_router)
app.include_router(datasets_router)
app.include_router(pipeline_router)
app.include_router(pipelines_library_router)
app.include_router(metrics_router)
app.include_router(sessions_router)
app.include_router(fitting_router)
app.include_router(analysis_router)
app.include_router(explore_router)


def run() -> None:
    """
    Entrypoint for the `sersflow-api` console script.
    """
    import subprocess
    import sys

    host = os.environ.get("SERSFLOW_HOST", "127.0.0.1")
    port = int(os.environ.get("SERSFLOW_PORT", "8000"))
    reload_ = os.environ.get("SERSFLOW_RELOAD", "0").strip().lower() in {"1", "true", "yes", "y"}

    # On Windows, calling `uvicorn.run()` from a console-script entrypoint can
    # sometimes exit immediately depending on how the console is hosting the
    # process. Spawning the CLI module is more robust and matches `uvicorn ...`.
    cmd = [
        sys.executable,
        "-m",
        "uvicorn",
        "sersflow.api.main:app",
        "--host",
        host,
        "--port",
        str(port),
    ]
    if reload_:
        cmd.append("--reload")
    raise SystemExit(subprocess.call(cmd))


if __name__ == "__main__":
    run()


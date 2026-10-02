from __future__ import annotations

from pathlib import Path
import json
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Response
from fastapi.responses import FileResponse, HTMLResponse

from sersflow.core.io.formats import list_formats
from sersflow.core.pipeline.library import get_step, list_steps


router = APIRouter(tags=["Meta"])


def _web_root() -> Path:
    # sersflow/api/routers/meta.py -> sersflow/api/web
    return (Path(__file__).resolve().parent.parent / "web").resolve()


@router.get("/health")
def health() -> dict[str, str]:
    """
    Simple health check endpoint.
    """
    return {"status": "ok"}


@router.get("/")
def root() -> HTMLResponse:
    """
    Serve the index.html file (the main web interface).
    """
    index_path = _web_root() / "index.html"
    html = index_path.read_text(encoding="utf-8")
    return HTMLResponse(html, headers={"Cache-Control": "no-cache, must-revalidate"})


@router.get("/preprocess")
def preprocess() -> HTMLResponse:
    """
    Serve preprocess.html (React preprocessing workspace).

    In production, this injects hashed Vite assets from preprocess-dist/manifest.json.
    In dev, you should use the Vite dev server at http://localhost:5173.
    """
    web_root = _web_root()
    # Vite writes the manifest under preprocess-dist/.vite/manifest.json
    manifest_path = web_root / "preprocess-dist" / ".vite" / "manifest.json"
    if not manifest_path.exists():
        # Fallback to the static preprocess.html (useful before first build).
        html = (web_root / "preprocess.html").read_text(encoding="utf-8")
        return HTMLResponse(html)

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    entry = manifest.get("index.html") or manifest.get("src/main.tsx") or {}
    js_file = entry.get("file")
    css_files = entry.get("css") or []
    if not js_file:
        return HTMLResponse("Invalid preprocess-dist/manifest.json (missing index.html entry).", status_code=500)

    css_links = "\n".join([f'    <link rel="stylesheet" href="/static/preprocess-dist/{c}" />' for c in css_files])
    html = f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>SpecFlow • Preprocessing</title>
    <link rel="stylesheet" href="/static/styles.css" />
{css_links}
  </head>
  <body>
    <div class="wrap">
      <header>
        <h1>SpecFlow</h1>
        <div class="links">
          <a href="/">Legacy UI</a>
          <a href="/docs">Docs</a>
          <a href="/openapi.json">OpenAPI</a>
          <a href="/health">Health</a>
        </div>
      </header>
      <div id="preprocess-root"></div>
    </div>
    <script type="module" src="/static/preprocess-dist/{js_file}"></script>
  </body>
</html>
"""
    return HTMLResponse(html)


@router.get("/static/{asset_path:path}")
def static_assets(asset_path: str) -> FileResponse:
    """
    Serve static assets from the web directory (e.g. CSS, JavaScript, images).
    """
    web_root = _web_root()
    candidate = (web_root / asset_path).resolve()
    if candidate != web_root and web_root not in candidate.parents:
        return FileResponse(web_root / "index.html", status_code=404)
    if not candidate.exists() or not candidate.is_file():
        return FileResponse(web_root / "index.html", status_code=404)
    resp = FileResponse(candidate)
    # Legacy JS modules change often; avoid sticky browser caches of outdated plot helpers.
    if candidate.suffix.lower() in {".js", ".mjs", ".css", ".html", ".map"}:
        resp.headers["Cache-Control"] = "no-cache, must-revalidate"
    return resp


@router.get("/favicon.ico")
def favicon() -> Response:
    """
    Serve the favicon.ico icon image.
    """
    return Response(status_code=204)


@router.get("/meta/formats")
def meta_formats() -> dict[str, Any]:
    """Public catalog of registered file formats (loaders + UI treatments)."""
    return {"items": [f.to_public() for f in list_formats()]}


@router.get("/meta/formats/{format_id}")
def meta_format_by_id(format_id: str) -> dict[str, Any]:
    for f in list_formats():
        if f.id == format_id:
            return f.to_public()
    raise HTTPException(status_code=404, detail=f"Unknown format: {format_id}")


@router.get("/meta/pipeline-steps")
def meta_pipeline_steps(
    technique_family: str | None = Query(None),
    capability: list[str] | None = Query(None),
) -> dict[str, Any]:
    """
    Processing step palette filtered by dataset technique + capabilities.

    Pass ``capability`` multiple times for a union of capability tokens.
    """
    caps: list[str] = []
    if capability:
        caps = [str(c) for c in capability if c is not None]
    specs = list_steps(technique_family=technique_family, capabilities=caps)
    return {"items": [s.to_public() for s in specs]}


@router.get("/meta/pipeline-steps/{step_id}")
def meta_pipeline_step_by_id(step_id: str) -> dict[str, Any]:
    spec = get_step(step_id)
    if spec is None:
        raise HTTPException(status_code=404, detail=f"Unknown step: {step_id}")
    return spec.to_public()


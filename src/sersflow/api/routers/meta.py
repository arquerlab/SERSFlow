from __future__ import annotations

from pathlib import Path
import json

from fastapi import APIRouter, Response
from fastapi.responses import FileResponse, HTMLResponse


router = APIRouter(tags=["meta"])


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
    return HTMLResponse(html)


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
    <title>SERSFlow • Preprocessing</title>
    <link rel="stylesheet" href="/static/styles.css" />
{css_links}
  </head>
  <body>
    <div class="wrap">
      <header>
        <h1>SERSFlow</h1>
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
    return FileResponse(candidate)


@router.get("/favicon.ico")
def favicon() -> Response:
    """
    Serve the favicon.ico icon image.
    """
    return Response(status_code=204)


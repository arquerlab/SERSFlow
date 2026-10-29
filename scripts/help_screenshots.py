"""Regenerate the Help tab screenshots from the synthetic sample data.

Starts a throw-away SpecFlow API (own database, auth disabled), uploads the sample files, builds
datasets/pipelines/runs through the API, then drives headless Chrome to capture the images into
``src/sersflow/api/web/help/img/``. Run again whenever the UI changes.

    python scripts/make_help_sample_data.py      # only if the sample zips are missing
    python scripts/help_screenshots.py [--port 8765] [--chrome PATH]

Needs: the sersflow package, httpx, websockets and Google Chrome (or Edge).
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
import zipfile
from pathlib import Path

import httpx
import websockets

ROOT = Path(__file__).resolve().parents[1]
HELP = ROOT / "src" / "sersflow" / "api" / "web" / "help"
OUT = HELP / "img"
SAMPLE = HELP / "sample"


def find_chrome(explicit: str | None) -> str:
    cands = [explicit] if explicit else []
    cands += [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        shutil.which("google-chrome") or "",
        shutil.which("chromium") or "",
    ]
    for c in cands:
        if c and Path(c).exists():
            return c
    sys.exit("Chrome/Edge not found: pass --chrome PATH")


# --------------------------------------------------------------------------- demo data via the API


def sers_pipeline() -> dict:
    def step(name, params, sid):
        return {"name": name, "params": params, "enabled": True, "impl_version": None,
                "step_id": sid, "input_from": "previous", "after_step_id": None}

    return {
        "technique_family": "vibrational",
        "steps": [
            step("crop", {"min_x": 450, "max_x": 1800}, "s_crop"),
            step("cosmic_ray_removal", {"method": "zscore", "threshold": 5.0, "window": 5,
                                        "interpolation": "median", "max_width": 10,
                                        "min_intensity_ratio": 2.0, "n_iterations": 3}, "s_cosmic"),
            step("noise_savgol", {"window_length": 11, "polyorder": 3}, "s_smooth"),
            step("baseline", {"method": "asls", "lam": 1000000.0, "p": 0.01}, "s_base"),
            step("spectral_integrations", {"windows": [
                {"id": "band1", "min_cm1": 1050, "max_cm1": 1110, "mode": "signed"},
                {"id": "band2", "min_cm1": 1550, "max_cm1": 1620, "mode": "signed"}]}, "s_int"),
            step("fitting", {
                "output_mode": "fit", "fill_opacity": 0.15, "initial_guess_mode": "default",
                "components": [{"component_id": "band_1080", "component_type": "lorentzian"},
                               {"component_id": "band_1580", "component_type": "lorentzian"}],
                "p0": [1080, 0, 22, 1580, 0, 26],
                "bounds_lower": [1050, 0, 5, 1550, 0, 5],
                "bounds_upper": [1110, None, 60, 1620, None, 60]}, "s_fit"),
        ],
    }


def find_key(obj, key):
    """First value stored under `key` anywhere in a nested JSON response."""
    if isinstance(obj, dict):
        if key in obj:
            return obj[key]
        for v in obj.values():
            r = find_key(v, key)
            if r is not None:
                return r
    elif isinstance(obj, list):
        for v in obj:
            r = find_key(v, key)
            if r is not None:
                return r
    return None


def map_pipeline() -> dict:
    def step(name, params, sid):
        return {"name": name, "params": params, "enabled": True, "impl_version": None,
                "step_id": sid, "input_from": "previous", "after_step_id": None}

    return {
        "technique_family": "vibrational",
        "steps": [
            step("crop", {"min_x": 850, "max_x": 1750}, "m_crop"),
            step("baseline", {"method": "asls", "lam": 1000000.0, "p": 0.01}, "m_base"),
            step("spectral_integrations", {"windows": [
                {"id": "band1", "min_cm1": 1050, "max_cm1": 1110, "mode": "signed"},
                {"id": "band2", "min_cm1": 1550, "max_cm1": 1620, "mode": "signed"}]}, "m_int"),
        ],
    }


def setup_demo(base: str, work: Path) -> dict:
    ids: dict = {}
    for z in SAMPLE.glob("*.zip"):
        with zipfile.ZipFile(z) as zf:
            zf.extractall(work / z.stem)
    c = httpx.Client(base_url=base, timeout=120)

    def upload(folder: Path, prefix: str) -> list[str]:
        files = sorted(folder.glob("*.txt"))
        multipart = [("files", (f"{prefix}/{f.name}", f.read_bytes(), "text/plain")) for f in files]
        r = c.post("/io/upload", files=multipart)
        r.raise_for_status()
        return [f"{prefix}/{f.name}" for f in files]

    upload(work / "specflow_sample_sers", "run42_sers")
    upload(work / "specflow_sample_series_and_map", "run43_time_and_map")
    upload(work / "specflow_sample_xps", "xps_NiFeOx")
    uploads = c.get("/io/uploads", params={"limit": 500}).json()["items"]

    def rel(token_a: str, token_b: str = "") -> list[str]:
        return [u["relative_path"] for u in uploads if token_a in u["relative_path"] and token_b in u["relative_path"]]

    def make_ds(name, paths):
        r = c.post("/datasets", json={"relative_paths": paths, "metadata": {"name": name}})
        if r.status_code >= 400:
            sys.exit(f"dataset '{name}' failed: {r.text[:400]}")
        return find_key(r.json(), "dataset_id")

    ids["sers"] = make_ds("sers_run42", rel("run42_sers"))
    ids["series"] = make_ds("timeseries_run43", rel("timeseries"))
    ids["map"] = make_ds("map_run43", rel("_map_"))
    ids["c1s"] = make_ds("xps_C1s", rel("C1s"))
    ids["o1s"] = make_ds("xps_O1s", rel("O1s"))

    pl = sers_pipeline()
    r = c.post("/pipelines", json={"name": "run42_v1", "pipeline": pl, "technique_family": "vibrational"})
    r.raise_for_status()
    r = c.post("/sessions", json={"dataset_id": ids["sers"], "pipeline": pl})
    r.raise_for_status()
    ids["session"] = find_key(r.json(), "session_id")
    r = c.post("/analysis/runs", json={"dataset_id": ids["sers"], "session_id": ids["session"],
                                       "subset": {"kind": "all"}, "label": "sers_run42 run42_v1 00"})
    r.raise_for_status()
    ids["run"] = find_key(r.json(), "run_id")
    mp = map_pipeline()
    c.post("/pipelines", json={"name": "maps_v1", "pipeline": mp, "technique_family": "vibrational"}).raise_for_status()
    r = c.post("/sessions", json={"dataset_id": ids["map"], "pipeline": mp}); r.raise_for_status()
    r = c.post("/analysis/runs", json={"dataset_id": ids["map"], "session_id": find_key(r.json(), "session_id"),
                                       "subset": {"kind": "all"}, "label": "map_run43 maps_v1 00"})
    r.raise_for_status()
    return ids


# --------------------------------------------------------------------------- browser driver


class Browser:
    def __init__(self, ws, width=1440, height=900):
        self.ws, self.n, self.width, self.height = ws, 0, width, height

    async def call(self, method, **params):
        self.n += 1
        await self.ws.send(json.dumps({"id": self.n, "method": method, "params": params}))
        while True:
            m = json.loads(await self.ws.recv())
            if m.get("id") == self.n:
                return m

    async def js(self, code):
        r = await self.call("Runtime.evaluate", expression=code, awaitPromise=True, returnByValue=True)
        res = r.get("result", {})
        if "exceptionDetails" in res:
            raise RuntimeError(res["exceptionDetails"].get("text", "") + str(res["exceptionDetails"].get("exception", {}).get("description", "")))
        return res.get("result", {}).get("value")

    async def wait_for(self, cond: str, timeout=60, what=""):
        t0 = time.time()
        while time.time() - t0 < timeout:
            try:
                if await self.js(f"!!({cond})"):
                    return
            except RuntimeError:
                pass
            await asyncio.sleep(0.4)
        raise TimeoutError(what or cond)

    async def shot(self, name, clip=None):
        kw = {"format": "png", "captureBeyondViewport": True}
        if clip:
            kw["clip"] = dict(clip, scale=1)
        r = await self.call("Page.captureScreenshot", **kw)
        (OUT / name).write_bytes(base64.b64decode(r["result"]["data"]))
        print("  saved", name)

    async def shot_card(self, title, name, pad=8, max_h=1100, full_header=False):
        rect = await self.js(
            "((t)=>{const el=[...document.querySelectorAll('.section-title,.subsection-title')].find(e=>e.textContent.trim()===t && e.offsetParent!==null);"
            "if(!el) return null; const c=el.closest('.card,.card-inner')||el; c.scrollIntoView({block:'start'});"
            "const r=c.getBoundingClientRect(); return {x:r.left+scrollX,y:r.top+scrollY,w:r.width,h:r.height};})"
            f"({json.dumps(title)})"
        )
        if not rect:
            print("  !! card not found:", title)
            return
        await asyncio.sleep(0.6)
        await self.shot(name, {"x": max(0, rect["x"] - pad), "y": max(0, rect["y"] - pad),
                               "width": rect["w"] + 2 * pad, "height": min(rect["h"], max_h) + 2 * pad})

    async def select(self, contains: str, nth=0, within="document"):
        """Choose the <select> option whose text contains `contains` (React-safe)."""
        code = f"""((txt)=>{{ const sels=[...{within}.querySelectorAll('select')].filter(s=>[...s.options].some(o=>o.text.includes(txt)));
          const s=sels[{nth}]; if(!s) return 'nosel'; const o=[...s.options].find(o=>o.text.includes(txt));
          Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype,'value').set.call(s,o.value);
          s.dispatchEvent(new Event('change',{{bubbles:true}})); return o.text; }})({json.dumps(contains)})"""
        r = await self.js(code)
        if r == "nosel":
            opts = await self.js("[...document.querySelectorAll('select')].map(s=>[...s.options].map(o=>o.text).slice(0,8).join(' | ')).join(' || ')")
            raise RuntimeError(f"select with option '{contains}' not found; selects: {opts}")
        return r

    async def click(self, text: str, exact=True):
        cmp = "b.innerText.trim()===t" if exact else "b.innerText.includes(t)"
        r = await self.js(f"""((t)=>{{const b=[...document.querySelectorAll('button,a.tab')].find(b=>!b.disabled && {cmp}); if(!b) return false; b.click(); return true;}})({json.dumps(text)})""")
        if not r:
            raise RuntimeError(f"button '{text}' not found")

    async def tab(self, key):
        await self.js(f"document.querySelector('[data-tab={key}]').click()")
        await asyncio.sleep(1.2)


async def capture(base: str, ids: dict, chrome: str, port_dbg: int):
    prof = tempfile.mkdtemp(prefix="sf_help_chrome_")
    proc = subprocess.Popen([chrome, "--headless=new", f"--remote-debugging-port={port_dbg}", f"--user-data-dir={prof}",
                             "--window-size=1440,900", "--hide-scrollbars", "about:blank"],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        page = None
        for _ in range(60):
            try:
                tabs = json.load(urllib.request.urlopen(f"http://127.0.0.1:{port_dbg}/json"))
                page = [t for t in tabs if t["type"] == "page"][0]
                break
            except Exception:
                await asyncio.sleep(0.3)
        async with websockets.connect(page["webSocketDebuggerUrl"], max_size=100_000_000) as ws:
            b = Browser(ws)
            await b.call("Emulation.setDeviceMetricsOverride", width=1440, height=900, deviceScaleFactor=1, mobile=False)
            await b.call("Page.navigate", url=base + "/")
            await b.wait_for("document.querySelector('[data-tab=uploads]') && document.querySelectorAll('#uploadedList *').length>5", 30, "uploads")
            await asyncio.sleep(1.5)

            print("Uploads")
            await b.js("window.scrollTo(0,0)")
            await b.shot("uploads.png", {"x": 0, "y": 0, "width": 1440, "height": 900})
            # label editor: tick the first SERS file
            await b.js("""(()=>{const cb=[...document.querySelectorAll('#uploadedList input[type=checkbox]')].find(c=>c.closest('div,li').textContent.includes('-0d3VRHE')); if(cb) cb.click();})()""")
            await asyncio.sleep(1.2)
            await b.js("document.getElementById('labelsEditor').scrollIntoView({block:'start'})")
            await asyncio.sleep(0.5)
            await b.shot_card("Edit labels", "labels.png", max_h=700)

            print("Raw")
            await b.tab("raw")
            await b.js("""(()=>{const s=document.querySelector('#plotFileSelectors select'); const o=[...s.options].find(o=>o.text.includes('timeseries')); Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype,'value').set.call(s,o.value); s.dispatchEvent(new Event('change',{bubbles:true}));})()""")
            await asyncio.sleep(3)
            await b.js("window.scrollTo(0,0)")
            await b.click("Series heatmap")
            await asyncio.sleep(3)
            await b.shot("raw_heatmap.png", {"x": 0, "y": 100, "width": 1440, "height": 760})

            print("Prepare")
            await b.tab("prepare")
            await b.wait_for("[...document.querySelectorAll('select')].some(s=>[...s.options].some(o=>o.text.includes('sers_run42')))", 30)
            await b.select("sers_run42")
            await asyncio.sleep(3)
            await b.shot_card("Create new dataset", "create_dataset.png", max_h=760)
            await b.select("run42_v1")  # library pipeline -> editor + session
            await asyncio.sleep(3)
            await b.js("""(()=>{const l=[...document.querySelectorAll('label')].find(l=>l.textContent.includes('Subset size')); const i=l&&l.querySelector('input'); if(!i) return; Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set.call(i,'3'); i.dispatchEvent(new Event('input',{bubbles:true}));})()""")
            await b.click("Create subset")
            await b.select("Raw (subset)")
            await asyncio.sleep(5)
            await b.shot_card("Plot", "plot_raw.png", max_h=760)
            await b.shot_card("Pipeline & preview", "dataset_bar.png")

            print("Pipeline")
            await b.shot_card("Pipeline", "pipeline.png", max_h=1000)
            await b.select("After: baseline")
            await asyncio.sleep(2)
            await b.click("Run preview plot (subset)", exact=False)
            await asyncio.sleep(6)
            await b.shot_card("Plot", "after_baseline.png", max_h=900)
            await b.select("After: fitting")
            await b.click("Run preview plot (subset)", exact=False)
            await asyncio.sleep(4)
            await b.wait_for("!document.body.innerText.includes('Fitting: spectrum')", 120, "fit preview")
            await asyncio.sleep(3)
            await b.shot_card("Plot", "fit_preview.png", max_h=1100)

            print("Analyze")
            await b.tab("analyze")
            await b.wait_for("[...document.querySelectorAll('select')].some(s=>[...s.options].some(o=>o.text.includes('sers_run42')))", 30)
            await b.select("sers_run42")
            await asyncio.sleep(2)
            await b.select("run42", nth=0)  # pipeline select shows library names; harmless if absent
            await asyncio.sleep(1)
            await b.js("window.scrollTo(0,0)")
            await b.shot("analyze.png", {"x": 0, "y": 100, "width": 1440, "height": 760})
            # select the run
            await b.js("""(()=>{const s=[...document.querySelectorAll('select')].find(s=>[...s.options].some(o=>o.text.includes('(completed)')||o.text.includes('completed'))); if(s){const o=[...s.options].find(o=>o.value); Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype,'value').set.call(s,o.value); s.dispatchEvent(new Event('change',{bubbles:true}));}})()""")
            await asyncio.sleep(2)
            await b.select("Exports")
            await asyncio.sleep(2)
            await b.shot("exports.png", {"x": 0, "y": 100, "width": 1440, "height": 900})
            await b.select("PCA / Cluster")
            await asyncio.sleep(2)
            await b.click("Run PCA")
            await asyncio.sleep(8)
            await b.shot("pca.png", {"x": 0, "y": 100, "width": 1440, "height": 900})
            await b.select("Plots")
            await asyncio.sleep(2)
            await b.shot("plots.png", {"x": 0, "y": 100, "width": 1440, "height": 900})

            print("Heatmap")
            await b.select("map_run43")
            await asyncio.sleep(3)
            await b.js("""(()=>{const s=[...document.querySelectorAll('select')].find(s=>[...s.options].some(o=>o.text.includes('completed'))); if(s){const o=[...s.options].find(o=>o.value); Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype,'value').set.call(s,o.value); s.dispatchEvent(new Event('change',{bubbles:true}));}})()""")
            await asyncio.sleep(2)
            await b.select("Heatmaps")
            await asyncio.sleep(3)
            await b.select("area_band2")
            await asyncio.sleep(1)
            await b.click("Plot heatmaps")
            await b.wait_for("document.querySelector('.plot-host.js-plotly-plot .nsewdrag')", 30, "heatmap")
            await asyncio.sleep(2)
            if await b.js("document.body.innerText.includes('Analyze error')"):
                raise RuntimeError("Heatmaps crashed: " + str(await b.js("document.body.innerText.slice(0,300)")))
            # click a cell: the processed spectrum of that position is overlaid underneath
            rect = await b.js("(()=>{const r=document.querySelector('.plot-host.js-plotly-plot .nsewdrag').getBoundingClientRect();return {x:r.left+r.width*0.8,y:r.top+r.height*0.4}})()")
            await b.call("Input.dispatchMouseEvent", type="mouseMoved", x=rect["x"] - 3, y=rect["y"] - 3)
            await asyncio.sleep(0.4)
            await b.call("Input.dispatchMouseEvent", type="mouseMoved", x=rect["x"], y=rect["y"])
            await asyncio.sleep(0.6)
            print("  plotly_click listeners:", await b.js("document.querySelector('.plot-host.js-plotly-plot')._ev?._events?.plotly_click ? 'bound' : 'MISSING'"))
            await b.call("Input.dispatchMouseEvent", type="mousePressed", x=rect["x"], y=rect["y"], button="left", clickCount=1)
            await b.call("Input.dispatchMouseEvent", type="mouseReleased", x=rect["x"], y=rect["y"], button="left", clickCount=1)
            try:
                await b.wait_for("!document.body.innerText.includes('No spectra selected yet')", 30, "clicked cell overlays a spectrum")
            except TimeoutError:
                print("  DIAG customdata:", await b.js("JSON.stringify(document.querySelector('.plot-host.js-plotly-plot').data[0].customdata?.slice?.(0,1))"))
                print("  DIAG plots:", await b.js("JSON.stringify([...document.querySelectorAll('.js-plotly-plot')].map(e=>({cls:e.className.slice(0,40), keys:Object.keys(e.data?.[0]||{}).join(','), on: typeof e.on, ev: !!e._ev})))"))
                print("  DIAG error box:", await b.js("document.getElementById('error')?.innerText"))
                print("  DIAG net:", await b.js("JSON.stringify(performance.getEntriesByType('resource').map(r=>r.name).filter(n=>n.includes('spectr')).slice(-3))"))
                raise
            await asyncio.sleep(2)
            await b.js("window.scrollTo(0,0)")
            await b.shot("heatmap.png", {"x": 0, "y": 100, "width": 1440, "height": 900})
    finally:
        proc.terminate()
        shutil.rmtree(prof, ignore_errors=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--chrome")
    ap.add_argument("--keep", action="store_true", help="leave the demo server running (for debugging)")
    args = ap.parse_args()
    if not list(SAMPLE.glob("*.zip")):
        subprocess.check_call([sys.executable, str(ROOT / "scripts" / "make_help_sample_data.py")])
    chrome = find_chrome(args.chrome)
    OUT.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="sf_help_demo_"))
    env = dict(os.environ,
               SERSFLOW_AUTH_DISABLED="1",
               SERSFLOW_DB_PATH=str(work / "demo.db"),
               SERSFLOW_DATA_DIR=str(work / "data"),
               SERSFLOW_UPLOAD_DIR=str(work / "uploads"),
               SERSFLOW_ARTIFACTS_DIR=str(work / "artifacts"))
    server = subprocess.Popen([sys.executable, "-m", "uvicorn", "sersflow.api.main:app", "--port", str(args.port)],
                              env=env, stdout=open(work / "server.log", "w"), stderr=subprocess.STDOUT)
    base = f"http://127.0.0.1:{args.port}"
    try:
        for _ in range(80):
            try:
                urllib.request.urlopen(base + "/health", timeout=1)
                break
            except Exception:
                time.sleep(0.5)
        else:
            sys.exit("demo server did not start; see " + str(work / "server.log"))
        ids = setup_demo(base, work)
        print("demo ids:", ids)
        asyncio.run(capture(base, ids, chrome, args.port + 1000))
    finally:
        if not args.keep:
            server.terminate()
            shutil.rmtree(work, ignore_errors=True)
        else:
            print("server left running on", base, "work dir", work)


if __name__ == "__main__":
    main()

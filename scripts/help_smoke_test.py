"""Browser smoke test for the Help tab (headless Chrome, no extra test framework).

Opens every Help page, follows deep links, checks Back, search, auto-links, live catalogs, in-app
"Help" links and console errors. Exit code 1 when a check fails.

    python scripts/help_smoke_test.py [--url http://127.0.0.1:8000] [--chrome PATH]
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

import websockets

sys.path.insert(0, str(Path(__file__).resolve().parent))
from help_screenshots import find_chrome  # noqa: E402

JS = (Path(__file__).resolve().parents[1] / "src/sersflow/api/web/help/help.js").read_text(encoding="utf-8")
PAGE_IDS = re.findall(r'\{ id: "([a-z0-9-]+)", title:', JS)

failures: list[str] = []


def check(ok: bool, what: str) -> None:
    print(("  ok   " if ok else "  FAIL ") + what)
    if not ok:
        failures.append(what)


async def run(url: str, chrome: str) -> None:
    prof = tempfile.mkdtemp(prefix="sf_help_smoke_")
    proc = subprocess.Popen([chrome, "--headless=new", "--remote-debugging-port=9444", f"--user-data-dir={prof}",
                             "--window-size=1440,900", "about:blank"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        page = None
        for _ in range(60):
            try:
                page = [t for t in json.load(urllib.request.urlopen("http://127.0.0.1:9444/json")) if t["type"] == "page"][0]
                break
            except Exception:
                await asyncio.sleep(0.3)
        async with websockets.connect(page["webSocketDebuggerUrl"], max_size=100_000_000) as ws:
            n = 0
            errors: list[str] = []

            async def call(method, **params):
                nonlocal n
                n += 1
                await ws.send(json.dumps({"id": n, "method": method, "params": params}))
                while True:
                    m = json.loads(await ws.recv())
                    if m.get("method") == "Runtime.exceptionThrown":
                        d = m["params"]["exceptionDetails"]
                        errors.append(d.get("exception", {}).get("description") or d.get("text", ""))
                    elif m.get("method") == "Log.entryAdded" and m["params"]["entry"]["level"] == "error":
                        errors.append(m["params"]["entry"]["text"] + " " + m["params"]["entry"].get("url", ""))
                    if m.get("id") == n:
                        return m

            async def js(code):
                r = await call("Runtime.evaluate", expression=code, awaitPromise=True, returnByValue=True)
                return r["result"].get("result", {}).get("value")

            async def wait(cond, timeout=15):
                t0 = time.time()
                while time.time() - t0 < timeout:
                    if await js(f"!!({cond})"):
                        return True
                    await asyncio.sleep(0.2)
                return False

            await call("Runtime.enable")
            await call("Log.enable")
            await call("Emulation.setDeviceMetricsOverride", width=1440, height=900, deviceScaleFactor=1, mobile=False)

            print("Shared link opens Help")
            await call("Page.navigate", url=f"{url}/#help/r-steps/step-xcal")
            check(await wait("document.querySelector('#tab-help.active') && document.querySelector('#step-xcal')", 20), "deep link shows r-steps at step-xcal")
            check(await js("document.querySelector('.help-nav-link.active')?.dataset.help") == "r-steps", "menu highlights the page")
            check(await js("location.hash") == "#help/r-steps/step-xcal", "URL keeps the route")

            print("Every page loads")
            for pid in PAGE_IDS:
                await js(f"window.openSpecFlowHelp('{pid}')")
                ok = await wait(f"document.querySelector('.help-nav-link.active')?.dataset.help==='{pid}' && document.querySelector('#helpContent h1')", 10)
                bad = await js("!!document.querySelector('#helpContent .help-missing')")
                check(ok and not bad, f"page {pid}")

            print("Links, Back and last page")
            await js("window.openSpecFlowHelp('t-xps-calibrate')")
            await wait("document.querySelector('#helpContent a.help-auto')")
            check(await js("document.querySelectorAll('#helpContent a.help-auto').length") > 2, "tutorial has auto-links")
            await js("[...document.querySelectorAll('#helpContent a.help-auto')].find(a=>a.textContent==='X-axis Calibration')?.click()")
            check(await wait("document.querySelector('.help-nav-link.active')?.dataset.help==='r-steps'"), "auto-link opens the step reference")
            await js("history.back()")
            check(await wait("document.querySelector('.help-nav-link.active')?.dataset.help==='t-xps-calibrate'"), "Back returns to the tutorial")
            check(await js("localStorage.getItem('specflow.help.last')") in PAGE_IDS, "last page remembered")

            print("Search")
            await js("window.openSpecFlowHelp('start')")
            await js("(()=>{const s=document.getElementById('helpSearch'); s.value='despike'; s.dispatchEvent(new Event('input'));})()")
            check(await wait("document.querySelector('#helpContent .help-hit') && document.body.innerText.includes('Cosmic Ray Removal')"), "'despike' lists the Cosmic Ray Removal step")
            await js("(()=>{const s=document.getElementById('helpSearch'); s.value='charge correction'; s.dispatchEvent(new Event('input'));})()")
            check(await wait("document.querySelector('#helpContent h2')?.textContent==='Pipeline steps'"), "steps come first")
            check(await js("!!document.querySelector('#helpContent mark')"), "matches are highlighted")
            await js("(()=>{const s=document.getElementById('helpSearch'); s.value='shirley'; s.dispatchEvent(new Event('input'));})()")
            await wait("document.querySelector('#helpContent .help-hit mark')?.textContent.toLowerCase()==='shirley'")
            await js("document.querySelector('#helpContent .help-hit a')?.click()")
            await wait("!document.querySelector('#helpContent .help-hit')")
            check(await wait("document.querySelector('#helpContent mark')"), "page opened from search highlights the term")
            await js("(()=>{const s=document.getElementById('helpSearch'); s.value='';})()")

            print("Live catalogs")
            await js("window.openSpecFlowHelp('r-steps')")
            check(await wait("document.querySelector('[data-gen=steps] table')"), "steps table generated")
            check(await js("document.querySelector('[data-gen=steps]').innerText.includes('Cosmic Ray Removal')"), "steps table includes vibrational-only steps")
            await js("window.openSpecFlowHelp('r-baseline')")
            check(await wait("document.querySelector('[data-gen=baseline] table')"), "baseline methods generated")
            await js("window.openSpecFlowHelp('r-fitting')")
            check(await wait("document.querySelector('[data-gen=fit-models] table')"), "fit models generated")

            print("Extras")
            await js("window.openSpecFlowHelp('r-mcp')")
            check(await wait("document.querySelector('#helpContent pre .help-copy')"), "copy buttons on code blocks")
            check(await wait("document.querySelector('#helpFoot')?.textContent.includes('reviewed against')"), "version footer")

            print("In-app Help links")
            await js("document.querySelector('[data-tab=prepare]').click()")
            check(await wait("document.querySelectorAll('#tab-spa a.help-ctx').length>0", 20), "Prepare shows Help links")
            await js("document.querySelector('[data-tab=analyze]').click()")
            check(await wait("document.querySelectorAll('#tab-spa a.help-ctx').length>0", 20), "Analyze shows Help links")
            await js("document.querySelector('[data-tab=uploads]').click()")
            await js("document.querySelector('#tab-uploads a.help-ctx')?.click()")
            check(await wait("document.querySelector('#tab-help.active') && document.querySelector('.help-nav-link.active')?.dataset.help==='r-uploads'"), "Uploads Help link opens r-uploads")

            print("Open a page from another tab")
            await js("document.querySelector('[data-tab=prepare]').click()")
            await asyncio.sleep(1.5)
            await js("window.openSpecFlowHelp('t-xps-fit')")
            await asyncio.sleep(1.5)
            check(await js("document.querySelector('.help-nav-link.active')?.dataset.help") == "t-xps-fit", "openSpecFlowHelp from Prepare lands on the requested page")

            print("Narrow screen")
            await call("Emulation.setDeviceMetricsOverride", width=390, height=800, deviceScaleFactor=1, mobile=True)
            await js("window.openSpecFlowHelp('r-exports')")
            await asyncio.sleep(1)
            check(await js("document.documentElement.scrollWidth <= window.innerWidth + 4"), "no horizontal page scroll at 390 px")

            real_errors = [e for e in errors if "favicon" not in e and "cdn.plot.ly" not in e]
            check(not real_errors, "no console errors" + (": " + " | ".join(real_errors[:3]) if real_errors else ""))
    finally:
        proc.terminate()
        shutil.rmtree(prof, ignore_errors=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:8000")
    ap.add_argument("--chrome")
    args = ap.parse_args()
    asyncio.run(run(args.url.rstrip("/"), find_chrome(args.chrome)))
    print(f"\n{len(failures)} failure(s)")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()

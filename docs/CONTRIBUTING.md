# Contributing

## Paths in documentation

Use **forward slashes** in markdown and code snippets for repository paths (for example `src/sersflow/api/main.py`, `frontend/src/main.tsx`). This keeps docs consistent across platforms.

## Local commands on Windows

Examples in READMEs may use Unix-style chaining (`cd foo && pytest`). In **PowerShell**, use `Set-Location foo; pytest` or run commands from the project root in separate steps. The project root is the git checkout directory (for example `C:\Users\you\Documents\SERSFlow`).

## Help tab (user guide)

The in-app guide lives in `src/sersflow/api/web/help/`: plain HTML pages in `pages/`, the menu and search vocabulary in `help.js`, styles in `help.css`, screenshots in `img/`, synthetic practice data in `sample/`. There is no build step: edit and reload the browser.

- **Add a page:** create `pages/<id>.html` and add `{ id, title }` to `HELP_SECTIONS` in `help.js`. Cross-link with `<a href="#" data-help="page-id#section-id">`. Section ids are explicit `id` attributes or the slug of the heading text.
- **Add or rename a pipeline step:** update `STEPS` in `help.js` and write its section in `r-steps.html` / `r-features.html`. Tables of steps, baseline methods and fit models are generated from the server (`data-gen` blocks), so they stay current by themselves.
- **Tests:** `pytest tests/test_help_pages.py` checks that every page is in the menu, links and anchors resolve, images exist, and the guide knows every step the server offers. `python scripts/help_smoke_test.py` drives headless Chrome through every page, search, deep links and the in-app "Help" links (needs a running server and Chrome).
- **Screenshots:** `python scripts/help_screenshots.py` starts a throw-away server with the sample data and recaptures all images. Re-run it after UI changes. `python scripts/make_help_sample_data.py` regenerates the sample zips.
- When a release changes behaviour described in the guide, review the pages and bump `GUIDE_VERSION` / `GUIDE_REVIEWED` in `help.js` (shown in each page footer).

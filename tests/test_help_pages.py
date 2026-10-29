"""Consistency checks for the Help tab (src/sersflow/api/web/help).

Catches the usual ways a hand-written guide rots: a page that is not in the menu, a link to a
missing page or section, a missing image, nesting mistakes, or a pipeline step the guide does not
know about.
"""
from __future__ import annotations

import html
import re
from html.parser import HTMLParser
from pathlib import Path

import pytest

HELP = Path(__file__).resolve().parents[1] / "src" / "sersflow" / "api" / "web" / "help"
PAGES = HELP / "pages"
JS = (HELP / "help.js").read_text(encoding="utf-8")

VOID = {"img", "br", "hr", "input", "meta", "link"}


def slug(text: str) -> str:
    return re.sub(r"^-|-$", "", re.sub(r"[^a-z0-9]+", "-", text.lower()))


class PageScan(HTMLParser):
    """Collect ids, heading slugs, links, images and nesting errors of one page."""

    def __init__(self) -> None:
        super().__init__()
        self.stack: list[str] = []
        self.nesting_errors: list[str] = []
        self.ids: set[str] = set()
        self.help_links: list[str] = []
        self.images: list[str] = []
        self.hrefs: list[str] = []
        self._heading: list | None = None
        self.headings: list[tuple[str, str]] = []  # (explicit id, text)

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if "id" in a:
            self.ids.add(a["id"])
        if a.get("data-help"):
            self.help_links.append(a["data-help"])
        if tag == "img" and a.get("src"):
            self.images.append(a["src"])
        if tag == "a" and a.get("href") and a["href"] != "#":
            self.hrefs.append(a["href"])
        if tag in ("h2", "h3"):
            self._heading = [a.get("id", ""), ""]
        if tag not in VOID:
            self.stack.append(tag)

    def handle_endtag(self, tag):
        if tag in VOID:
            return
        if self.stack and self.stack[-1] == tag:
            self.stack.pop()
        else:
            self.nesting_errors.append(f"</{tag}> at line {self.getpos()[0]}")
        if tag in ("h2", "h3") and self._heading is not None:
            self.headings.append((self._heading[0], self._heading[1]))
            self._heading = None

    def handle_data(self, data):
        if self._heading is not None:
            self._heading[1] += data

    def anchors(self) -> set[str]:
        out = set(self.ids)
        used = set(self.ids)
        for explicit, text in self.headings:
            if explicit:
                continue
            s = slug(html.unescape(text).strip()) or "section"
            while s in used:
                s += "-x"
            used.add(s)
            out.add(s)
        return out


def scan(page_id: str) -> PageScan:
    p = PageScan()
    p.feed((PAGES / f"{page_id}.html").read_text(encoding="utf-8"))
    return p


def menu_ids() -> list[str]:
    return re.findall(r'\{ id: "([a-z0-9-]+)", title:', JS)


def test_every_menu_entry_has_a_page_and_vice_versa():
    ids = menu_ids()
    assert ids, "no pages found in help.js"
    assert len(ids) == len(set(ids)), "duplicate page ids in help.js"
    files = {p.stem for p in PAGES.glob("*.html")}
    assert set(ids) - files == set(), "menu entries without a page"
    assert files - set(ids) == set(), "pages missing from the menu in help.js"


@pytest.mark.parametrize("page_id", sorted(p.stem for p in PAGES.glob("*.html")))
def test_page_is_well_formed(page_id):
    p = scan(page_id)
    assert not p.nesting_errors, p.nesting_errors
    assert not p.stack, f"unclosed tags: {p.stack}"


def link_targets() -> list[tuple[str, str]]:
    """(where, target) for every in-guide link: page hrefs, help.js tables."""
    out: list[tuple[str, str]] = []
    for f in PAGES.glob("*.html"):
        for t in scan(f.stem).help_links:
            out.append((f.name, t))
    # help.js: step table targets, auto-link terms, in-app context links
    for t in re.findall(r'"((?:r|t)-[a-z0-9-]+(?:#[a-z0-9-]+)?)"', JS):
        if t.split("#")[0] in set(menu_ids()):
            out.append(("help.js", t))
    return out


def test_all_links_resolve_to_a_page_and_section():
    anchors = {f.stem: scan(f.stem).anchors() for f in PAGES.glob("*.html")}
    bad = []
    for where, target in link_targets():
        page, _, anchor = target.partition("#")
        if page not in anchors:
            bad.append(f"{where}: unknown page {target}")
        elif anchor and anchor not in anchors[page]:
            bad.append(f"{where}: no section '{anchor}' in {page}")
    assert not bad, "\n".join(sorted(set(bad)))


def test_images_and_downloads_exist():
    missing = []
    for f in PAGES.glob("*.html"):
        s = scan(f.stem)
        for ref in s.images + s.hrefs:
            if ref.startswith("/static/help/"):
                if not (HELP / ref.removeprefix("/static/help/")).exists():
                    missing.append(f"{f.name}: {ref}")
    assert not missing, "\n".join(missing)


def server_step_labels(client) -> set[str]:
    """Palette labels offered for either technique (the catalog depends on technique_family)."""
    labels: set[str] = set()
    for fam in ("vibrational", "xps"):
        r = client.get("/meta/pipeline-steps", params={"technique_family": fam})
        assert r.status_code == 200
        labels |= {s["label"] for s in r.json()["items"] if s.get("palette_group")}
    return labels


def test_guide_knows_every_pipeline_step():
    from fastapi.testclient import TestClient

    from sersflow.api.main import app

    server = server_step_labels(TestClient(app))
    guide = {html.unescape(n) for n in re.findall(r'\{ name: "([^"]+)", target:', JS)}
    assert server - guide == set(), f"steps missing from STEPS in help.js: {server - guide}"
    assert guide - server == set(), f"STEPS in help.js not offered by the server: {guide - server}"


def test_every_server_step_has_a_section_in_the_reference():
    from fastapi.testclient import TestClient

    from sersflow.api.main import app

    labels = server_step_labels(TestClient(app))
    text = " ".join((PAGES / f).read_text(encoding="utf-8") for f in ("r-steps.html", "r-features.html", "r-fitting.html"))
    text = html.unescape(re.sub(r"<[^>]+>", " ", text))
    assert [label for label in labels if label not in text] == []

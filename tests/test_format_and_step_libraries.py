"""Format registry + processing step library smoke tests."""

from __future__ import annotations

from fastapi.testclient import TestClient

from sersflow.api.main import app
from sersflow.core.io.formats import get_format_for_suffix, list_formats, supported_suffixes
from sersflow.core.pipeline.library import get_step, list_steps


def test_formats_cover_builtin_suffixes():
    suffixes = set(supported_suffixes())
    for s in (".txt", ".wdf", ".vms", ".nxs", ".nx5"):
        assert s in suffixes
    assert get_format_for_suffix(".vms").id == "vamas"
    assert get_format_for_suffix(".nxs").id == "nexus_xps"
    assert "multi_block" in get_format_for_suffix(".vms").all_capabilities()
    public = [f.to_public() for f in list_formats()]
    assert any(p["id"] == "ascii_xy" for p in public)
    assert all("ui" in p and "filter_fields" in p for p in public)


def test_step_library_applicability():
    all_ids = {s.id for s in list_steps()}
    assert "crop" in all_ids
    assert "fitting" in all_ids
    assert "metadata_filter" in all_ids
    assert get_step("crop") is not None
    assert get_step("crop").impl is not None

    vib = {s.id for s in list_steps(technique_family="vibrational")}
    xps = {s.id for s in list_steps(technique_family="xps")}
    assert "cosmic_ray_removal" in vib
    assert "cosmic_ray_removal" not in xps

    public = get_step("baseline").to_public()
    assert public["ui"]["method_param_key"] == "method"
    assert public["palette_group"] == "Preprocessing"


def test_meta_formats_and_steps_endpoints():
    client = TestClient(app)
    r = client.get("/meta/formats")
    assert r.status_code == 200
    body = r.json()
    assert "items" in body
    assert len(body["items"]) >= 4

    r2 = client.get("/meta/pipeline-steps", params={"technique_family": "xps"})
    assert r2.status_code == 200
    ids = {it["id"] for it in r2.json()["items"]}
    assert "fitting" in ids
    assert "cosmic_ray_removal" not in ids

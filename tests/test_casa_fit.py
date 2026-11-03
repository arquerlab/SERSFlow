"""CasaXPS fit components stored in VAMAS block comments."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from sersflow.api.main import app
from sersflow.api.schemas.datasets import DatasetMetadata, SpectrumRef
from sersflow.core.io.casa_fit import parse_casa_comments
from sersflow.core.io.read_vms import read_vms_blocks
from sersflow.infra.datasets_store import create_dataset

from tests.test_vms_loader import _casa_header, _casa_ke_block

REGION = "CASA region (*Co 2p*) (*Shirley*) 306.89756 326.3172 1 4 6 0 0 -450 0 0 (*NoTag*) 0 0 0"
COMP_MAIN = (
    "CASA comp (*Co3+*) (*GL(30)*) Area 21108.783 1e-020 301742.6 -1 1 MFWHM 3.2240763 3.159771 3.559771 -1 1 "
    "Position 320.2 320.2 320.3 -1 1 RSF 1 MASS 0 INDEX -1 (*3+*) CONST (**) UNCORRECTEDRSF 0"
)
COMP_LINKED = (
    "CASA comp (*Co2+a*) (*GL(30)*) Area 7527.9738 1e-020 181282.84 -1 1 MFWHM 3.2240763 0.19955654 4.9889135 0 1 "
    "Position 318.4 0 0 0 -1.8 RSF 1 MASS 0 INDEX -1 (*2+*) CONST (**) UNCORRECTEDRSF 0"
)
COMP_SAT = (
    "CASA comp (*Co3+sat*) (*GL(30)*) Area 3084.3953 1e-020 181282.84 -1 1 MFWHM 5 2.8 3.2 3 1 "
    "Position 310.3 0 0 0 -9.9 RSF 1 MASS 0 INDEX -1 (*NoTag*) CONST (**) UNCORRECTEDRSF 0"
)


def test_parse_region_and_components() -> None:
    fit = parse_casa_comments(["Casa Info Follows", REGION, "3", COMP_MAIN, COMP_LINKED, COMP_SAT], photon_energy_eV=1100.0)
    assert fit is not None
    assert fit["region"]["name"] == "Co 2p" and fit["region"]["background"] == "Shirley"
    assert fit["region"]["be_start_eV"] == pytest.approx(1100.0 - 306.89756)
    c0, c1, c2 = fit["components"]
    assert (c0["name"], c0["lineshape"], c0["m"]) == ("Co3+", "GL(30)", 30.0)
    assert c0["ke_eV"] == pytest.approx(320.2)
    assert c0["be_eV"] == pytest.approx(779.8)  # hv - KE
    assert c0["area"] == pytest.approx(21108.783)
    assert c0["fwhm"] == pytest.approx(3.2240763)
    assert c0["position_constraint"]["linked_to"] is None
    # Co2+a: position and FWHM tied to component 0 (offset -1.8 KE, i.e. +1.8 BE)
    assert c1["position_constraint"]["linked_to"] == 0
    assert c1["position_constraint"]["link_factor"] == pytest.approx(-1.8)
    assert c1["fwhm_constraint"]["linked_to"] == 0
    assert c1["area_constraint"]["linked_to"] is None
    # satellite FWHM tied to component 3 (Co2+sat in the real file)
    assert c2["fwhm_constraint"]["linked_to"] == 3
    assert c2["fwhm"] == pytest.approx(5.0)
    assert "tag" not in c2 and c1["tag"] == "2+"


def test_parse_tolerates_garbage_and_missing() -> None:
    assert parse_casa_comments(None) is None
    assert parse_casa_comments(["Casa Info Follows", "Calib M = 3.1 A = 0 BE ADD"]) is None
    fit = parse_casa_comments(["CASA comp (*x*) (*GL(30)*) Area oops", COMP_MAIN], photon_energy_eV=None)
    assert fit is not None and len(fit["components"]) == 1
    assert fit["components"][0]["be_eV"] is None  # no photon energy -> no BE


def _vms_with_casa(path: Path) -> Path:
    block = _casa_ke_block(n_comment_lines=6)
    repl = {"comment-2": REGION, "comment-3": "2", "comment-4": COMP_MAIN, "comment-5": COMP_LINKED}
    block = [repl.get(line, line) for line in block]
    plain = _casa_ke_block(block_name="O 1s", species="O 1s", n_comment_lines=2)
    path.write_text("\n".join(_casa_header(n_blocks=2) + block + plain) + "\n", encoding="utf-8")
    return path


def test_read_blocks_keep_casa_comments(tmp_path: Path) -> None:
    p = _vms_with_casa(tmp_path / "x.vms")
    _hdr, blocks = read_vms_blocks(p)
    assert len(blocks) == 2
    fit = parse_casa_comments(blocks[0].extra_fields["block_comments"], photon_energy_eV=blocks[0].excitation_energy_eV)
    assert fit is not None and [c["name"] for c in fit["components"]] == ["Co3+", "Co2+a"]
    assert parse_casa_comments(blocks[1].extra_fields["block_comments"]) is None


def test_casa_fits_endpoint(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SERSFLOW_DB_PATH", str(tmp_path / "db.sqlite"))
    monkeypatch.setenv("SERSFLOW_UPLOAD_DIR", str(tmp_path))
    monkeypatch.setenv("SERSFLOW_DATA_DIR", str(tmp_path / "data"))
    (tmp_path / "b1").mkdir()
    _vms_with_casa(tmp_path / "b1" / "x.vms")
    ds = create_dataset(
        owner_user_id="dev",
        metadata=DatasetMetadata(name="casa", technique_family="xps"),
        spectra=[
            SpectrumRef(spectrum_id="sp_0", relative_path="b1/x.vms", record_index=0),
            SpectrumRef(spectrum_id="sp_1", relative_path="b1/x.vms", record_index=1),
        ],
    )
    client = TestClient(app)
    r = client.get(f"/datasets/{ds.dataset_id}/casa-fits")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["n_spectra"] == 1  # the O 1s block has no CasaXPS fit
    it = body["items"][0]
    assert it["spectrum_id"] == "sp_0" and it["xps_region"]
    assert [c["name"] for c in it["components"]] == ["Co3+", "Co2+a"]
    assert it["components"][0]["be_eV"] == pytest.approx(779.8)
    assert "hv" in body["be_convention"] or "photon" in body["be_convention"]
    assert client.get(f"/datasets/{ds.dataset_id}/casa-fits", params={"region": "nope"}).json()["n_spectra"] == 0
    assert client.get("/datasets/ds_missing/casa-fits").status_code == 404

"""IO1: ISO 14976 VAMAS reader hardening (synthetic fixtures; real instrument files to be added)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from sersflow.core.io.read_vms import (
    VmsParseError,
    block_meta_dict,
    classify_y_unit,
    count_statistics,
    counts_per_channel,
    cps,
    read_file_vms,
    read_vms_blocks,
)


def _header(
    *,
    n_blocks: int,
    mode: str = "NORM",
    scan: str = "REGULAR",
    exp_vars: list[tuple[str, str]] | None = None,
    n_incl: int = 0,
    manual: list[str] | None = None,
    future_exp: list[str] | None = None,
    n_future_block: int = 0,
    comments: list[str] | None = None,
) -> list[str]:
    exp_vars = exp_vars or []
    lines = [
        "VAMAS Surface Chemical Analysis Standard Data Transfer Format 1988 May 4",
        "Org",
        "Instr",
        "Op",
        "exp-iso",
        str(len(comments or [])),
        *(comments or []),
        mode,
        scan,
    ]
    if mode in ("MAP", "MAPDP", "NORM", "SDP"):
        lines.append("1")  # number of spectral regions
    if mode in ("MAP", "MAPDP"):
        lines += ["4", "2", "2"]  # analysis positions, discrete x, discrete y
    lines.append(str(len(exp_vars)))
    for lab, unit in exp_vars:
        lines += [lab, unit]
    lines.append(str(n_incl))
    lines.append(str(len(manual or [])))
    lines += list(manual or [])
    lines.append(str(len(future_exp or [])))
    lines.append(str(n_future_block))
    lines += list(future_exp or [])
    lines.append(str(n_blocks))
    return lines


def _block(
    *,
    name: str = "Co 2p",
    mode: str = "NORM",
    scan: str = "REGULAR",
    technique: str = "XPS",
    exp_values: list[str] | None = None,
    x_label: str = "Binding Energy",
    x_start: float = 790.0,
    x_step: float = -0.5,
    corr_vars: list[tuple[str, str]] | None = None,
    columns: list[list[float]] | None = None,
    signal_mode: str = "pulse counting",
    dwell: str = "0.1",
    scans: str = "5",
    future_block_values: list[str] | None = None,
    photon: float = 1486.6,
    work_function: float = 4.5,
) -> list[str]:
    corr_vars = corr_vars or [("counts", "d")]
    columns = columns or [[10.0, 20.0, 30.0, 20.0]]
    assert len(columns) == len(corr_vars)
    n = len(columns[0])
    lines = [name, "sample-A", "2026", "11", "5", "10", "0", "0", "0", "1", "a block comment", technique]
    if mode in ("MAP", "MAPDP"):
        lines += ["1", "2"]  # x, y coordinate
    lines += list(exp_values or [])
    lines.append("Al mono")
    if mode in ("MAPDP", "MAPSVDP", "SDP", "SDPSV"):
        lines += ["18", "1", "1"]  # sputtering ion Z, n atoms, charge
    lines += [str(photon), "0", "0", "0"]  # energy, strength, beam width x, y
    if mode in ("MAP", "MAPDP", "MAPSV", "MAPSVDP", "SEM"):
        lines += ["100", "100"]  # field of view
    lines += ["54.7", "0"]  # polar angle, azimuth
    lines += ["FAT", "20", "1", str(work_function), "0", "0", "0", "0", "0"]
    lines += [name.split()[0], name.split()[-1], "-1"]
    if scan != "IRREGULAR":
        lines += [x_label, "eV", str(x_start), str(x_step)]
    lines.append(str(len(corr_vars)))
    for lab, unit in corr_vars:
        lines += [lab, unit]
    lines += [signal_mode, dwell, scans, "0"]
    if technique in ("XPS", "AES dir", "UPS") and mode in ("MAPDP", "MAPSVDP", "SDP", "SDPSV"):
        lines += ["3000", "1e-6", "1", "1", "45", "0", "continuous"]  # sputtering source
    lines += ["0", "0", "0", "0"]  # tilt, tilt azimuth, rotation, n additional params
    lines += list(future_block_values or [])
    lines.append(str(n * len(corr_vars)))
    for col in columns:
        lines += [str(min(col)), str(max(col))]
    for i in range(n):
        for col in columns:
            lines.append(str(col[i]))
    return lines


def _write(tmp_path: Path, lines: list[str], name: str = "f.vms") -> Path:
    p = tmp_path / name
    p.write_text("\n".join(lines + ["end of experiment"]) + "\n", encoding="utf-8")
    return p


def test_two_corresponding_variables_give_spectrum_and_transmission(tmp_path: Path) -> None:
    counts = [100.0, 220.0, 400.0, 210.0]
    trans = [0.9, 0.95, 1.0, 1.05]
    p = _write(
        tmp_path,
        _header(n_blocks=1)
        + _block(corr_vars=[("counts", "d"), ("Transmission", "d")], columns=[counts, trans]),
    )
    _h, (b,) = read_vms_blocks(p)
    np.testing.assert_allclose(b.y, counts)
    np.testing.assert_allclose(b.aux["transmission"], trans)
    np.testing.assert_allclose(b.x, [790.0, 789.5, 789.0, 788.5])
    assert b.y_min_declared == 100.0 and b.y_max_declared == 400.0
    meta = block_meta_dict(b)
    assert meta["aux_arrays"] == ["transmission"]
    assert meta["y_unit"] == "counts" and meta["dwell_time_s"] == 0.1 and meta["n_scans"] == 5
    assert b.extra_fields["block_comments"] == ["a block comment"]  # comments preserved

    ds = read_file_vms(p)
    np.testing.assert_allclose(ds.ys[0], counts)  # dataset loader still sees only the spectrum


def test_counts_and_cps_helpers(tmp_path: Path) -> None:
    p = _write(
        tmp_path,
        _header(n_blocks=2)
        + _block(name="C 1s")
        + _block(name="O 1s", corr_vars=[("counts per second", "c/s")], columns=[[50.0, 100.0, 60.0, 40.0]]),
    )
    _h, (b_counts, b_cps) = read_vms_blocks(p)
    m_counts, m_cps = block_meta_dict(b_counts), block_meta_dict(b_cps)
    assert m_counts["y_unit"] == "counts" and m_cps["y_unit"] == "cps"
    np.testing.assert_allclose(counts_per_channel(b_counts.y, m_counts), b_counts.y)
    np.testing.assert_allclose(cps(b_counts.y, m_counts), b_counts.y / (0.1 * 5))
    np.testing.assert_allclose(counts_per_channel(b_cps.y, m_cps), b_cps.y * 0.1 * 5)
    np.testing.assert_allclose(cps(b_cps.y, m_cps), b_cps.y)
    assert count_statistics(m_cps)["counts_scale"] == pytest.approx(0.5)


@pytest.mark.parametrize(
    ("label", "unit", "mode", "expected"),
    [
        ("counts", "d", "pulse counting", "counts"),
        ("Intensity", "d", "pulse counting", "counts"),
        ("counts per second", "c/s", "pulse counting", "cps"),
        ("CPS", "", "", "cps"),
        ("counts", "d", "analogue", "unknown"),
        ("normalised intensity", "arb. units", "pulse counting", "unknown"),
    ],
)
def test_classify_y_unit(label: str, unit: str, mode: str, expected: str) -> None:
    assert classify_y_unit(label, unit, mode) == expected


def test_unknown_unit_has_no_count_statistics() -> None:
    meta = {"y_unit": "unknown", "dwell_time_s": 0.1, "n_scans": 3}
    assert counts_per_channel(np.ones(3), meta) is None
    assert cps(np.ones(3), meta) is None


def test_multiple_experiment_variables(tmp_path: Path) -> None:
    p = _write(
        tmp_path,
        _header(n_blocks=1, exp_vars=[("Etch Time", "s"), ("Cycle", "d")])
        + _block(exp_values=["120", "3"]),
    )
    h, (b,) = read_vms_blocks(p)
    assert h.experiment_variable_labels == ["Etch Time", "Cycle"]
    assert b.extra_fields["experiment_variable_values"] == ["120", "3"]
    np.testing.assert_allclose(b.y, [10.0, 20.0, 30.0, 20.0])


def test_manual_items_future_entries_and_header_comments(tmp_path: Path) -> None:
    p = _write(
        tmp_path,
        _header(n_blocks=1, manual=["8", "9"], future_exp=["x1"], n_future_block=2, comments=["c1", "c2"])
        + _block(future_block_values=["fb1", "fb2"]),
    )
    _h, (b,) = read_vms_blocks(p)
    assert b.extra_fields["future_block_values"] == ["fb1", "fb2"]
    np.testing.assert_allclose(b.y, [10.0, 20.0, 30.0, 20.0])


def test_sputter_depth_profile_block(tmp_path: Path) -> None:
    p = _write(
        tmp_path,
        _header(n_blocks=2, mode="SDP", exp_vars=[("Etch Time", "s")])
        + _block(mode="SDP", exp_values=["0"])
        + _block(mode="SDP", exp_values=["60"], columns=[[1.0, 2.0, 3.0, 4.0]]),
    )
    _h, blocks = read_vms_blocks(p)
    assert [b.extra_fields["experiment_variable_value"] for b in blocks] == ["0", "60"]
    assert blocks[1].extra_fields["sputter_source"][0] == "3000"
    assert blocks[0].extra_fields["sputter_ion"] == ["18", "1", "1"]
    np.testing.assert_allclose(blocks[1].y, [1.0, 2.0, 3.0, 4.0])


def test_map_mode_block_positions(tmp_path: Path) -> None:
    p = _write(tmp_path, _header(n_blocks=1, mode="MAP") + _block(mode="MAP"))
    h, (b,) = read_vms_blocks(p)
    assert h.map_info == {"n_analysis_positions": 4, "n_x_coordinates": 2, "n_y_coordinates": 2}
    assert b.extra_fields["map_xy"] == ["1", "2"]
    assert b.extra_fields["field_of_view"] == ["100", "100"]


def test_irregular_scan_takes_abscissa_from_first_variable(tmp_path: Path) -> None:
    ke = [1190.0, 1191.0, 1193.0, 1196.0]  # irregular steps, kinetic energy
    counts = [5.0, 8.0, 13.0, 7.0]
    p = _write(
        tmp_path,
        _header(n_blocks=1, scan="IRREGULAR")
        + _block(
            scan="IRREGULAR",
            corr_vars=[("Kinetic Energy", "eV"), ("counts", "d"), ("Transmission", "d")],
            columns=[ke, counts, [1.0, 1.0, 1.1, 1.2]],
        ),
    )
    _h, (b,) = read_vms_blocks(p)
    np.testing.assert_allclose(b.y, counts)
    np.testing.assert_allclose(b.x, [1486.6 - k - 4.5 for k in ke])  # KE -> BE
    assert sorted(b.aux) == ["transmission"]
    assert block_meta_dict(b)["x_irregular"] is True


def test_inclusion_list_is_rejected_clearly(tmp_path: Path) -> None:
    p = _write(tmp_path, _header(n_blocks=1, n_incl=-2) + ["7", "8"] + _block())
    with pytest.raises(VmsParseError, match="inclusion/exclusion"):
        read_vms_blocks(p)


def test_mapping_scan_mode_is_rejected_clearly(tmp_path: Path) -> None:
    p = _write(tmp_path, _header(n_blocks=1, scan="MAPPING") + _block())
    with pytest.raises(VmsParseError, match="MAPPING"):
        read_vms_blocks(p)


def test_ordinate_count_must_match_variables(tmp_path: Path) -> None:
    lines = _header(n_blocks=1) + _block(corr_vars=[("counts", "d"), ("Transmission", "d")], columns=[[1.0, 2.0], [1.0, 1.0]])
    i = lines.index("4", len(_header(n_blocks=1)) + 30)  # total ordinate count line
    lines[i] = "3"
    p = _write(tmp_path, lines)
    with pytest.raises(VmsParseError, match="multiple"):
        read_vms_blocks(p)


def test_acquisition_endpoint_and_mcp_tool(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import asyncio
    import json
    import os

    import httpx
    from fastapi.testclient import TestClient

    from sersflow.api.schemas.datasets import DatasetMetadata, SpectrumRef
    from sersflow.infra.datasets_store import create_dataset

    monkeypatch.setenv("SERSFLOW_DB_PATH", str(tmp_path / "db.sqlite"))
    monkeypatch.setenv("SERSFLOW_UPLOAD_DIR", str(tmp_path))
    monkeypatch.setenv("SERSFLOW_DATA_DIR", str(tmp_path / "data"))
    os.environ["SERSFLOW_AUTH_DISABLED"] = "1"
    (tmp_path / "b1").mkdir()
    _write(
        tmp_path / "b1",
        _header(n_blocks=1)
        + _block(corr_vars=[("counts", "d"), ("Transmission", "d")], columns=[[1.0, 2.0, 3.0], [0.5, 0.6, 0.7]]),
        name="t.vms",
    )
    ds = create_dataset(
        owner_user_id="dev",
        metadata=DatasetMetadata(name="t"),
        spectra=[SpectrumRef(spectrum_id="sp0", relative_path="b1/t.vms", record_index=0)],
    )
    from sersflow.api.main import app

    client = TestClient(app)
    r = client.get(f"/datasets/{ds.dataset_id}/spectra/sp0/acquisition")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["y_unit"] == "counts" and body["counts_scale"] == 1.0
    assert body["aux"]["transmission"] == [0.5, 0.6, 0.7]
    assert body["aux_arrays"] == ["transmission"]
    assert client.get(f"/datasets/{ds.dataset_id}/spectra/nope/acquisition").status_code == 404

    from sersflow.mcp.server import create_server
    from tests.sersflow_mcp.test_tool_handlers import _ready_ctx, _tool_fn

    def handle(request: httpx.Request) -> httpx.Response:
        resp = client.get(request.url.path, params=dict(request.url.params))
        return httpx.Response(resp.status_code, json=resp.json())

    ctx = _ready_ctx(tmp_path, httpx.MockTransport(handle))
    fn = _tool_fn(create_server(ctx), "get_datasets_spectrum_acquisition")
    data = json.loads(asyncio.run(fn(dataset_id=ds.dataset_id, spectrum_id="sp0")))
    assert data["ok"] is True and data["y_unit"] == "counts" and "aux" not in data

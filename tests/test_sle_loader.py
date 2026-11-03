from __future__ import annotations

import sqlite3
import zlib
from pathlib import Path

import numpy as np
import pytest

from sersflow.core.io.formats import get_format_for_path
from sersflow.core.io.load_file import load_dataset
from sersflow.core.io.read_sle import (
    _parse_timestamp,
    _region_from_name,
    _xas_region_from_name,
    read_file_sle,
    read_sle_blocks_with_report,
)
from sersflow.core.io.technique import infer_technique_family
from sersflow.core.models.datasets import MultiSpectrumDataset

N_CHN = 25
HEAD, TAIL = 4, 2
STEP = 0.5
EPASS = 20.0
N_VALUES = 40
# Linear per-channel calibration (fraction of pass energy), like the real actual-shifts.calib1d.
SHIFTS = np.linspace(-0.03, 0.17, N_CHN)

_SCHEDULE = """<Experiment><Schedule ID="1" Name="t">
<MetaInfo><Parameter name="sample identifier" type="string">S1</Parameter></MetaInfo>
<XPS ID="2" Name="XPS"><GroupingNode ID="3" Name="Group">
<SpectrumGroup ID="4" Name="g"><CommonSpectrumSettings><ScanMode Name="FixedAnalyzerTransmission"/></CommonSpectrumSettings>
<Spectrum ID="10" Name="C 1s"><FixedAnalyzerTransmissionSettings DwellTime="0.1" Ebin="300" End="280.5" Epass="20" NumValues="40"/></Spectrum>
<Spectrum ID="11" Name="Valence band_O"><FixedAnalyzerTransmissionSettings DwellTime="0.1" Ebin="300" End="280.5" Epass="20" NumValues="40"/></Spectrum>
</SpectrumGroup>
<SpectrumGroup ID="5" Name="n"><CommonSpectrumSettings><ScanMode Name="ConstantFinalState"/></CommonSpectrumSettings>
<Spectrum ID="12" Name="O K edge actual "><ConstantFinalStateSettings DwellTime="0.1"/><ExternalChannels>
<Channel Offset="0" Scale="1" name="Excitation Energy [eV] (PGM)"/><Channel Offset="0" Scale="1" name="Ring Current [mA] (PGM)"/>
<Channel Offset="0" Scale="-1" name="TEY [A] (Pico)"/><Channel Offset="0" Scale="1" name="I_mirror [A] (Pico)"/>
</ExternalChannels></Spectrum></SpectrumGroup>
<SpectrumGroup ID="6" Name="r"><CommonSpectrumSettings><ScanMode Name="FixedRetardingRatio"/></CommonSpectrumSettings>
<Spectrum ID="13" Name="FRR scan"><FixedRetardingRatioSettings/></Spectrum></SpectrumGroup>
</GroupingNode></XPS></Schedule></Experiment>"""

N_XAS = 60
XAS_START, XAS_STEP, XAS_BE_REF = 510.0, 0.5, -140.0
_K = np.arange(N_XAS)


def _xas_truth() -> dict[str, np.ndarray]:
    """Synthetic raw channels: a TEY step edge, a drifting I0, and slightly jittered readback energy."""
    energy = XAS_START + XAS_STEP * _K + 0.01 * np.sin(_K)
    i0 = 2e-8 * (1.0 + 0.1 * np.sin(_K / 7.0))
    tey_true = 1e-10 * (1.0 + 0.5 / (1.0 + np.exp(-(_K - 30) / 2.0)))
    return {"energy": energy, "i0": i0, "tey_raw": -tey_true * (i0 / 2e-8), "tey_true": tey_true}


def _peak_frames(peak_rel_energy: float, n_frames: int) -> np.ndarray:
    """Counts where every channel sees one Gaussian at the same *true* relative energy."""
    t = np.arange(n_frames) * STEP
    sh = SHIFTS * EPASS
    out = np.zeros((n_frames, N_CHN), dtype="<f4")
    for i in range(N_CHN):
        out[:, i] = 100.0 * np.exp(-0.5 * ((t + sh[i] - peak_rel_energy) / 0.6) ** 2) + 1.0
    return out


def _write_sle(path: Path, *, peak_rel_energy: float = 10.0, n_scans: int = 2, calibration: bool = True) -> None:
    n_frames = N_VALUES + HEAD + TAIL
    con = sqlite3.connect(path)
    con.executescript(
        """
        CREATE TABLE Configuration (Key TEXT, Value TEXT);
        CREATE TABLE Spectrum (Node INTEGER, SpectrumID TEXT, EnergyChns INTEGER, NonEnergyChns INTEGER,
            Samples INTEGER, ElectronEnergy FLOAT, EnergyType TEXT, Step FLOAT, EpassOrRR FLOAT,
            Ubias FLOAT, Udet FLOAT, Wf FLOAT, Timestamp TEXT);
        CREATE TABLE RawData (RawID INTEGER PRIMARY KEY AUTOINCREMENT, Node INTEGER, ScanDate TEXT, Scans INTEGER,
            Eexc FLOAT, Head INTEGER, Tail INTEGER, Trace TEXT, SamplePolarAngle FLOAT, SampleAzimuthAngle FLOAT,
            WriteIndex INTEGER);
        CREATE TABLE CountRateData (RawID INTEGER, Offset INTEGER, NextOffset INTEGER, ChunkSize INTEGER, Data BLOB);
        CREATE TABLE NodeData (Node INTEGER, Data TEXT, Timestamp TEXT);
        CREATE TABLE ExtensionChannelInfo (Node INTEGER, Channel INTEGER, Name TEXT);
        CREATE TABLE ExtensionData (RawID INTEGER, Channel INTEGER, Data BLOB);
        """
    )
    con.execute("INSERT INTO Configuration VALUES ('Schedule', ?)", (_SCHEDULE,))
    if calibration:
        det = "".join(f'<Detector Gain="1" Position="0" Shift="{s}"/>' for s in SHIFTS)
        con.execute(
            "INSERT INTO NodeData VALUES (4, ?, '')", (f"<Data><DetectorCalibration>{det}</DetectorCalibration></Data>",)
        )
    for node, ts in (
        (10, "2025-Mar-21 08:00:00.000000"),
        (11, "2025-Mar-21 09:00:00.000000"),
        (12, "2025-Mar-21 10:00:00.000000"),
        (13, "2025-Mar-21 11:00:00.000000"),
    ):
        if node == 12:
            con.execute(
                "INSERT INTO Spectrum VALUES (?,?,?,?,?,?,?,?,?,0,0,4.0,?)",
                (node, str(node), N_CHN, 1, N_XAS, XAS_BE_REF, "Binding", XAS_STEP, 50.0, ts),
            )
            _write_xas_scan(con, node)
            continue
        con.execute(
            "INSERT INTO Spectrum VALUES (?,?,?,?,?,?,?,?,?,0,0,4.0,?)",
            (node, str(node), N_CHN, 1, n_frames, 300.0, "Binding", STEP, EPASS, ts),
        )
        if node == 13:
            continue
        for s in range(n_scans if node == 10 else 1):
            cur = con.execute(
                "INSERT INTO RawData (Node, ScanDate, Scans, Eexc, Head, Tail, Trace, SamplePolarAngle, "
                "SampleAzimuthAngle, WriteIndex) VALUES (?,?,1,740.0,?,?,?,0,0,?)",
                (node, f"2025-Mar-21 08:0{s}:00.500000", HEAD, TAIL, f"Scan [Idx]={s + 1}u", n_frames),
            )
            blob = zlib.compress(_peak_frames(peak_rel_energy, n_frames).tobytes())
            con.execute(
                "INSERT INTO CountRateData VALUES (?,0,?,?,?)", (cur.lastrowid, n_frames, n_frames * N_CHN, blob)
            )
    con.commit()
    con.close()


def _write_xas_scan(con: sqlite3.Connection, node: int) -> None:
    truth = _xas_truth()
    cur = con.execute(
        "INSERT INTO RawData (Node, ScanDate, Scans, Eexc, Head, Tail, Trace, SamplePolarAngle, "
        "SampleAzimuthAngle, WriteIndex) VALUES (?,?,1,?,0,0,?,0,0,?)",
        (node, "2025-Mar-21 10:00:00.250000", XAS_START, "Scan [Idx]=1u", N_XAS),
    )
    rid = cur.lastrowid
    counts = np.full((N_XAS, N_CHN), 4.0, dtype="<f4")  # PEY = 100 per frame
    con.execute(
        "INSERT INTO CountRateData VALUES (?,0,?,?,?)", (rid, N_XAS, N_XAS * N_CHN, zlib.compress(counts.tobytes()))
    )
    names = ["Excitation Energy [eV] (PGM)", "Ring Current [mA] (PGM)", "TEY [A] (Pico)", "I_mirror [A] (Pico)"]
    series = [truth["energy"], np.full(N_XAS, 300.0), truth["tey_raw"], truth["i0"]]
    for ch, (name, arr) in enumerate(zip(names, series)):
        con.execute("INSERT INTO ExtensionChannelInfo VALUES (?,?,?)", (node, ch, name))
        con.execute("INSERT INTO ExtensionData VALUES (?,?,?)", (rid, ch, arr.astype("<f8").tobytes()))


def test_sle_registered_and_technique(tmp_path: Path) -> None:
    p = tmp_path / "a.sle"
    _write_sle(p)
    assert get_format_for_path(p).id == "specs_sle"
    assert infer_technique_family(p) == "xps"


def test_sle_blocks_regions_roles_and_skips(tmp_path: Path) -> None:
    p = tmp_path / "a.sle"
    _write_sle(p, n_scans=2)
    ds = load_dataset(p)
    assert isinstance(ds, MultiSpectrumDataset)
    # C 1s: average + 2 scans; VB: single scan -> average only; NEXAFS: TEY + PEY; FRR skipped.
    assert [m["block_name"] for m in ds.meta] == [
        "C1s_spectrum",
        "C1s_spectrum_1",
        "C1s_spectrum_2",
        "VB_O_spectrum",
        "OKedge_TEY_spectrum",
        "OKedge_PEY_spectrum",
    ]
    assert [m["spectrum_role"] for m in ds.meta] == ["average"] + ["individual"] * 2 + ["average"] * 3
    assert [m["technique"] for m in ds.meta] == ["XPS"] * 4 + ["XAS"] * 2
    assert ds.meta[0]["xps_region"] == "C1s" and ds.meta[0]["xps_species"] == "C"
    assert ds.meta[0]["excitation_energy_eV"] == 740.0
    assert ds.meta[0]["pass_energy_eV"] == EPASS
    assert ds.meta[0]["acquired_at"] == "2025-03-21T08:00:00.500000"
    assert ds.meta[0]["nxs_skipped_count"] == 1
    assert ds.meta[0]["nxs_skipped_regions"][0]["reason"] == "unsupported_scan_mode:FixedRetardingRatio"
    # NumValues = frames - head - tail, BE descending from the Prodigy start energy.
    assert len(ds.xs[0]) == N_VALUES
    assert ds.xs[0][0] == 300.0 and np.isclose(ds.xs[0][-1], 300.0 - STEP * (N_VALUES - 1))


def test_sle_channel_shift_reconstruction_recovers_peak(tmp_path: Path) -> None:
    p = tmp_path / "a.sle"
    peak = 10.0
    _write_sle(p, peak_rel_energy=peak, n_scans=1)
    blocks, _ = read_sle_blocks_with_report(p)
    y = blocks[0]["y"]
    sh = SHIFTS * EPASS
    k_expected = (peak - sh.max()) / STEP
    assert abs(int(np.argmax(y)) - k_expected) <= 1
    # Shift-aligned sum is far sharper than a naive channel sum of the same raw frames.
    raw = _peak_frames(peak, N_VALUES + HEAD + TAIL).astype(float)
    naive = raw.sum(axis=1)
    assert (y > 0.5 * y.max()).sum() < (naive > 0.5 * naive.max()).sum()


def test_sle_xas_signals_grid_and_flux_correction(tmp_path: Path) -> None:
    p = tmp_path / "a.sle"
    _write_sle(p)
    ds = read_file_sle(p)
    by_name = {m["block_name"]: i for i, m in enumerate(ds.meta)}
    tey_i, pey_i = by_name["OKedge_TEY_spectrum"], by_name["OKedge_PEY_spectrum"]
    truth = _xas_truth()

    # Nominal uniform photon-energy grid, not the jittery readback.
    expected_x = XAS_START + XAS_STEP * _K
    np.testing.assert_allclose(ds.xs[tey_i], expected_x)
    np.testing.assert_allclose(ds.xs[pey_i], expected_x)

    # TEY is sign-corrected (Scale=-1) and divided by I0 / mean(I0): the I0 drift is removed.
    flux = truth["i0"] / truth["i0"].mean()
    expected_tey = np.interp(expected_x, truth["energy"], -truth["tey_raw"] / flux)
    np.testing.assert_allclose(ds.ys[tey_i], expected_tey, rtol=1e-9)
    # The drift really is gone: corrected TEY equals the true edge scaled by a constant.
    np.testing.assert_allclose(
        -truth["tey_raw"] / flux, truth["tey_true"] * (truth["i0"] / 2e-8) / flux, rtol=1e-9
    )
    # PEY: 25 channels x 4 counts = 100 per frame, flux-corrected.
    np.testing.assert_allclose(ds.ys[pey_i], np.interp(expected_x, truth["energy"], 100.0 / flux), rtol=1e-9)

    m = ds.meta[tey_i]
    assert m["technique"] == "XAS" and m["xas_signal"] == "TEY" and m["xas_edge"] == "O K"
    assert m["xps_region"] == "OKedge_TEY" and m["x_label"] == "Photon energy (eV)"
    assert m["xas_i0_normalized"] is True
    assert m["excitation_energy_eV"] is None
    assert m["sle_fixed_kinetic_energy_eV"] == XAS_START - XAS_BE_REF
    assert 0.0 < m["sle_photon_energy_max_dev_eV"] <= 0.011


def test_sle_without_calibration_falls_back_to_channel_sum(tmp_path: Path) -> None:
    p = tmp_path / "a.sle"
    _write_sle(p, calibration=False, n_scans=1)
    ds = read_file_sle(p)
    assert ds.meta[0]["sle_channel_shifts_applied"] is False
    assert len(ds.xs[0]) == N_VALUES


def test_sle_rejects_non_prodigy_sqlite(tmp_path: Path) -> None:
    p = tmp_path / "x.sle"
    con = sqlite3.connect(p)
    con.execute("CREATE TABLE foo (a)")
    con.commit()
    con.close()
    with pytest.raises(ValueError, match="Not a SPECS Prodigy"):
        read_file_sle(p)
    p2 = tmp_path / "y.sle"
    p2.write_text("not sqlite")
    with pytest.raises(ValueError, match="not a readable|Not a readable"):
        read_file_sle(p2)


@pytest.mark.parametrize(
    "name,region,edge",
    [
        ("O K edge actual ", "OKedge", "O K"),
        ("Co L edge", "CoLedge", "Co L"),
        ("C K-edge", "CKedge", "C K"),
        ("Mystery", "Mystery", None),
    ],
)
def test_sle_xas_region_names(name: str, region: str, edge: str | None) -> None:
    assert _xas_region_from_name(name) == (region, edge)


@pytest.mark.parametrize(
    "name,region",
    [
        ("overview", "survey"),
        ("Ir 4f", "Ir4f"),
        ("O 1s ", "O1s"),
        ("valence band_Ir_4s_4p", "VB_Ir4s4p"),
        ("Valence band_C", "VB_C"),
        ("Fe2p3", "Fe2p3"),
    ],
)
def test_sle_region_names(name: str, region: str) -> None:
    assert _region_from_name(name)[0] == region


def test_sle_timestamp_is_locale_free() -> None:
    assert _parse_timestamp("2025-Mar-21 08:47:57.822896") == "2025-03-21T08:47:57.822896"
    assert _parse_timestamp("garbage") is None

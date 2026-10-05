from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from sersflow.core.io.load_file import load_dataset
from sersflow.core.io.read_vms import (
    classify_block_role,
    derive_xps_region,
    filter_blocks_by_mode,
    filter_indices_by_xps_regions,
    filter_meta_indices,
    read_file_vms,
    read_vms_blocks,
)
from sersflow.core.models.datasets import MultiSpectrumDataset
from sersflow.core.spectrum import extract_xy


def _legacy_header(*, n_blocks: int) -> list[str]:
    return [
        "VAMAS Surface Chemical Analysis Standard Data Transfer Format 1988 May 4",
        "TestOrg",
        "TestInstrument",
        "TestOperator",
        "exp-1",
        "0",  # n comment lines
        "REGULAR",  # experiment mode
        "REGULAR",  # scan mode
        "0",  # n regions
        "0",  # n experiment variables
        "0",  # n param exclusions
        "0",  # n manual items
        "0",  # n future experiment items
        "0",  # n future block entries
        str(n_blocks),
    ]


def _casa_header(*, n_blocks: int, n_exp_vars: int = 1) -> list[str]:
    """Minimal CasaXPS-like experiment header (n experiment variables declared)."""
    lines = [
        "VAMAS Surface Chemical Analysis Standard Data Transfer Format 1988 May 4",
        "Not Specified",
        "Not Specified",
        "Not Specified",
        "Not Specified",
        "0",
        "NORM",
        "REGULAR",
        "0",
        str(n_exp_vars),
    ]
    if n_exp_vars > 0:
        lines.extend(["Exp Variable", "d"])
    lines.extend(["0", "0", "0", "0", str(n_blocks)])
    return lines


def _casa_ke_block(
    *,
    block_name: str = "Co 2p",
    species: str = "Co 2p",
    transition: str = "",
    photon_eV: float = 1100.0,
    work_function_eV: float = 3.97,
    ke_start: float = 290.0,
    ke_step: float = 0.1,
    y: list[float] | None = None,
    exp_var_value: str = "24",
    source_label: str = "ISISS PGM",
    n_comment_lines: int = 2,
) -> list[str]:
    """
    Casa/ISO-style XPS block with kinetic-energy abscissa.

    Field order after comments matches ISO 14976 / Casa:
    technique → [exp var…] → source label → source energy (hν) → …
    → analyser work function → … → abscissa label.
    """
    yy = list(y or [10.0, 20.0, 30.0])
    comments = ["Casa Info Follows", "Kinetic energy start = 290"][:n_comment_lines]
    while len(comments) < n_comment_lines:
        comments.append(f"comment-{len(comments)}")
    lines = [
        block_name,
        "sample-1",
        "2025",
        "3",
        "22",
        "14",
        "23",
        "23",
        "0",
        str(len(comments)),
        *comments,
        "XPS",
        exp_var_value,
        source_label,
        str(photon_eV),
        "0",
        "0",
        "0",  # source strength / widths (often zero at synchrotron)
        "45",
        "225",
        "FAT",
        "20",
        "1",
        str(work_function_eV),
        "0",
        "0",
        "0",
        "0",
        "0",
        species,
        transition,
        "-1",
        "kinetic energy",
        "eV",
        str(ke_start),
        str(ke_step),
        "1",
        "counts",
        "d",
        "pulse counting",
        "0.1",
        "1",
        "0",
        "0",
        "0",
        "0",
        "0",
        str(len(yy)),
        str(min(yy)),
        str(max(yy)),
        *[str(v) for v in yy],
    ]
    return lines


def _legacy_block(
    *,
    block_name: str,
    species: str,
    transition: str,
    x_start: float,
    x_step: float,
    y: list[float],
    year: int = 2020,
    month: int = 1,
    day: int = 15,
    hour: int = 12,
    minute: int = 30,
    second: int = 0,
    excitation_energy_eV: float = 1486.6,
    analyser_work_function_eV: float = 4.5,
    x_label: str = "Binding Energy",
    additional_params: list[tuple[str, str, str]] | None = None,
) -> list[str]:
    m = len(y)
    lines = [
        block_name,
        "exp-1",
        str(year),
        str(month),
        str(day),
        str(hour),
        str(minute),
        str(second),
        "0",  # GMT offset
        "0",  # n block comments
        "XPS",
        "Al",  # source label (non-float → no experiment variable heuristic)
        str(excitation_energy_eV),
        "0",
        "0",
        "0",  # legacy source params → is_full_iso=False
        "0",
        "0",  # source angles
        "FAT",
        "20",
        "1",
        str(analyser_work_function_eV),  # analyser work function
        "0",
        "0",
        "0",
        "0",
        "0",  # five zeros
        species,
        transition,
        "-1",
        x_label,
        "eV",
        str(x_start),
        str(x_step),
        "1",
        "counts",
        "d",
        "pulse counting",
        "0.1",
        "1",
        "0",
        "0",
        "0",
        "0",  # time corr + sample angles
    ]
    extras = list(additional_params or [])
    lines.append(str(len(extras)))
    for label, unit, value in extras:
        lines.extend([label, unit, value])
    lines.extend([str(m), str(min(y)), str(max(y))])
    lines.extend(str(v) for v in y)
    return lines


def write_mixed_region_vms(path: Path) -> Path:
    """Two regions with different axis lengths; average + individuals each."""
    c_avg = _legacy_block(
        block_name="C 1s_spectrum",
        species="C",
        transition="1s",
        x_start=290.0,
        x_step=-0.1,
        y=[10.0, 20.0, 30.0, 25.0],
        excitation_energy_eV=1486.6,
    )
    c1 = _legacy_block(
        block_name="C 1s_spectrum_1",
        species="C",
        transition="1s",
        x_start=290.0,
        x_step=-0.1,
        y=[9.0, 19.0, 29.0, 24.0],
        minute=31,
    )
    c2 = _legacy_block(
        block_name="C 1s_spectrum_2",
        species="C",
        transition="1s",
        x_start=290.0,
        x_step=-0.1,
        y=[11.0, 21.0, 31.0, 26.0],
        minute=32,
    )
    o_avg = _legacy_block(
        block_name="O 1s_spectrum",
        species="O",
        transition="1s",
        x_start=540.0,
        x_step=-0.2,
        y=[100.0, 110.0, 105.0],
        day=16,
        excitation_energy_eV=1486.6,
    )
    o1 = _legacy_block(
        block_name="O 1s_spectrum_1",
        species="O",
        transition="1s",
        x_start=540.0,
        x_step=-0.2,
        y=[98.0, 108.0, 103.0],
        day=16,
        minute=31,
    )
    blocks = [c_avg, c1, c2, o_avg, o1]
    lines = _legacy_header(n_blocks=len(blocks))
    for b in blocks:
        lines.extend(b)
    lines.append("end of experiment")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def test_classify_block_role() -> None:
    assert classify_block_role("C 1s_spectrum") == {
        "spectrum_role": "average",
        "replicate_index": None,
        "name_prefix": "C 1s",
    }
    assert classify_block_role("C 1s_spectrum_3") == {
        "spectrum_role": "individual",
        "replicate_index": 3,
        "name_prefix": "C 1s",
    }
    assert classify_block_role("MnO2 survey_spectrum")["spectrum_role"] == "average"


def test_derive_xps_region() -> None:
    assert derive_xps_region("C", "1s") == "C1s"
    assert derive_xps_region("Mn", "2p") == "Mn2p"
    assert derive_xps_region("survey", None) == "survey"
    assert derive_xps_region("survey", "") == "survey"


def test_read_vms_mixed_regions_independent_axes(tmp_path: Path) -> None:
    p = write_mixed_region_vms(tmp_path / "mixed.vms")
    header, blocks = read_vms_blocks(p)
    assert header.declared_n_blocks == 5
    assert len(blocks) == 5
    assert [b.block_name for b in blocks] == [
        "C 1s_spectrum",
        "C 1s_spectrum_1",
        "C 1s_spectrum_2",
        "O 1s_spectrum",
        "O 1s_spectrum_1",
    ]
    assert blocks[0].m == 4 and blocks[3].m == 3
    np.testing.assert_allclose(blocks[0].x, [290.0, 289.9, 289.8, 289.7])
    np.testing.assert_allclose(blocks[3].x, [540.0, 539.8, 539.6])
    assert blocks[0].excitation_energy_eV == pytest.approx(1486.6)
    assert blocks[0].acquired_at is not None
    assert blocks[0].acquired_at.year == 2020

    ds = read_file_vms(p)
    assert isinstance(ds, MultiSpectrumDataset)
    assert ds.kind == "multi"
    assert len(ds.xs) == 5
    assert len(ds.ys[0]) == 4
    assert len(ds.ys[3]) == 3
    assert ds.meta[0]["xps_region"] == "C1s"
    assert ds.meta[0]["spectrum_role"] == "average"
    assert ds.meta[0]["replicate_index"] is None
    assert ds.meta[1]["spectrum_role"] == "individual"
    assert ds.meta[1]["replicate_index"] == 1
    assert ds.meta[3]["xps_region"] == "O1s"
    assert ds.meta[0]["acquired_at"] is not None
    assert ds.meta[0]["excitation_energy_eV"] == pytest.approx(1486.6)
    assert "organization" not in ds.meta[0]
    assert "instrument" not in ds.meta[0]


def test_filter_averages_and_individuals(tmp_path: Path) -> None:
    p = write_mixed_region_vms(tmp_path / "mixed.vms")
    _header, blocks = read_vms_blocks(p)

    avg = filter_blocks_by_mode(blocks, "averages")
    assert [b.block_name for _, b in avg] == ["C 1s_spectrum", "O 1s_spectrum"]
    assert [i for i, _ in avg] == [0, 3]

    ind = filter_blocks_by_mode(blocks, "individuals")
    assert [b.block_name for _, b in ind] == ["C 1s_spectrum_1", "C 1s_spectrum_2", "O 1s_spectrum_1"]
    assert [i for i, _ in ind] == [1, 2, 4]

    ds = load_dataset(p)
    assert filter_meta_indices(ds.meta, "averages") == [0, 3]
    assert filter_meta_indices(ds.meta, "individuals") == [1, 2, 4]
    assert filter_meta_indices(ds.meta, "all") == [0, 1, 2, 3, 4]
    assert filter_indices_by_xps_regions(ds.meta, [0, 1, 2, 3, 4], ["C1s"]) == [0, 1, 2]
    assert filter_indices_by_xps_regions(ds.meta, [0, 3], ["O1s"]) == [3]
    assert filter_indices_by_xps_regions(ds.meta, [0, 3], []) == [0, 3]


def test_filter_indices_by_xps_regions_all_valence_bands() -> None:
    meta = (
        {"xps_region": "C1s"},
        {"xps_region": "vb-O1s"},
        {"xps_region": "valence band"},
        {"xps_region": "O1s"},
        {"xps_region": "Fermi edge"},
    )
    assert filter_indices_by_xps_regions(meta, [0, 1, 2, 3, 4], ["all valence bands"]) == [1, 2, 4]
    assert filter_indices_by_xps_regions(meta, [0, 1, 2, 3, 4], ["C1s", "all valence bands"]) == [0, 1, 2, 4]


def test_filter_when_only_one_role_present(tmp_path: Path) -> None:
    only_avg_lines = _legacy_header(n_blocks=1) + _legacy_block(
        block_name="C 1s_spectrum",
        species="C",
        transition="1s",
        x_start=290.0,
        x_step=-0.1,
        y=[1.0, 2.0],
    )
    p = tmp_path / "only_avg.vms"
    p.write_text("\n".join(only_avg_lines) + "\n", encoding="utf-8")
    _h, blocks = read_vms_blocks(p)
    # Mode individuals but file has only averages → keep averages
    kept = filter_blocks_by_mode(blocks, "individuals")
    assert len(kept) == 1
    assert kept[0][1].block_name == "C 1s_spectrum"


def test_extract_xy_preserves_independent_axes(tmp_path: Path) -> None:
    p = write_mixed_region_vms(tmp_path / "mixed.vms")
    ds = load_dataset(p)
    c = extract_xy(ds, record_index=0)
    o = extract_xy(ds, record_index=3)
    assert c.x.shape != o.x.shape
    np.testing.assert_allclose(c.x[0], 290.0)
    np.testing.assert_allclose(o.x[0], 540.0)
    np.testing.assert_allclose(c.y, [10.0, 20.0, 30.0, 25.0])
    np.testing.assert_allclose(o.y, [100.0, 110.0, 105.0])


def test_metadata_keys_round_trip_on_multi(tmp_path: Path) -> None:
    p = write_mixed_region_vms(tmp_path / "mixed.vms")
    ds = load_dataset(p)
    expected = {
        "xps_region",
        "xps_species",
        "xps_transition",
        "block_name",
        "spectrum_role",
        "replicate_index",
        "technique",
        "acquired_at",
        "excitation_energy_eV",
    }
    for m in ds.meta:
        assert expected.issubset(m.keys())
        assert m["technique"] == "XPS"


def test_create_dataset_vms_averages_and_labels(tmp_path: Path, monkeypatch) -> None:
    from sersflow.api.schemas.datasets import DatasetCreateRequest, DatasetMetadata
    from sersflow.api.services.datasets_service import create_dataset_from_uploads
    from sersflow.infra.upload_labels_store import fetch_upload_labels_for_paths, with_connection

    monkeypatch.setenv("SERSFLOW_DB_PATH", str(tmp_path / "vms.db"))
    monkeypatch.setenv("SERSFLOW_DATA_DIR", str(tmp_path / "data"))
    upload_root = tmp_path / ".sersflow_uploads"
    monkeypatch.setenv("SERSFLOW_UPLOAD_DIR", str(upload_root))

    batch = "vmsbatch"
    dest = upload_root / batch / "mixed.vms"
    dest.parent.mkdir(parents=True, exist_ok=True)
    write_mixed_region_vms(dest)
    rel = f"{batch}/mixed.vms"

    rec, skipped = create_dataset_from_uploads(
        DatasetCreateRequest(
            relative_paths=[rel],
            metadata=DatasetMetadata(name="vms-avg"),
            vms_spectrum_mode="averages",
        ),
        owner_user_id="dev",
    )
    assert not skipped
    assert len(rec.spectra) == 2
    assert sorted(int(s.record_index) for s in rec.spectra) == [0, 3]

    con = with_connection()
    try:
        labels = fetch_upload_labels_for_paths(con, [rel])[rel]
    finally:
        con.close()
    assert labels.get("vms_spectrum_mode") == "averages"
    # Full block map preserved (mixed fixture has 5 blocks); averages update kept indices.
    assert set(labels["vms_spectra"].keys()) == {"0", "1", "2", "3", "4"}
    assert labels["vms_spectra"]["0"]["xps_region"] == "C1s"
    assert labels["vms_spectra"]["3"]["xps_region"] == "O1s"
    assert labels["vms_spectra"]["0"]["spectrum_role"] == "average"
    assert labels["vms_spectra"]["0"]["excitation_energy_eV"] == pytest.approx(1486.6)

    rec_ind, _ = create_dataset_from_uploads(
        DatasetCreateRequest(
            relative_paths=[rel],
            metadata=DatasetMetadata(name="vms-ind"),
            vms_spectrum_mode="individuals",
        ),
        owner_user_id="dev",
    )
    assert len(rec_ind.spectra) == 3
    assert sorted(int(s.record_index) for s in rec_ind.spectra) == [1, 2, 4]

    rec_all, _ = create_dataset_from_uploads(
        DatasetCreateRequest(
            relative_paths=[rel],
            metadata=DatasetMetadata(name="vms-all"),
            vms_spectrum_mode="all",
        ),
        owner_user_id="dev",
    )
    assert len(rec_all.spectra) == 5
    assert sorted(int(s.record_index) for s in rec_all.spectra) == [0, 1, 2, 3, 4]

    rec_c1s, skipped_c1s = create_dataset_from_uploads(
        DatasetCreateRequest(
            relative_paths=[rel],
            metadata=DatasetMetadata(name="vms-c1s"),
            vms_spectrum_mode="averages",
            xps_regions=["C1s"],
        ),
        owner_user_id="dev",
    )
    assert not skipped_c1s
    assert len(rec_c1s.spectra) == 1
    assert int(rec_c1s.spectra[0].record_index) == 0

    con2 = with_connection()
    try:
        labels_c1s = fetch_upload_labels_for_paths(con2, [rel])[rel]
    finally:
        con2.close()
    assert labels_c1s.get("xps_regions_filter") == ["C1s"]
    # Region-subset dataset create must not wipe other blocks from the upload picker map.
    assert set(labels_c1s["vms_spectra"].keys()) == {"0", "1", "2", "3", "4"}
    assert labels_c1s["vms_spectra"]["0"]["xps_region"] == "C1s"


def test_create_dataset_vms_region_miss_raises(tmp_path: Path, monkeypatch) -> None:
    from sersflow.api.schemas.datasets import DatasetCreateRequest, DatasetMetadata
    from sersflow.api.services.datasets_service import create_dataset_from_uploads

    monkeypatch.setenv("SERSFLOW_DB_PATH", str(tmp_path / "vms2.db"))
    monkeypatch.setenv("SERSFLOW_DATA_DIR", str(tmp_path / "data2"))
    upload_root = tmp_path / ".sersflow_uploads2"
    monkeypatch.setenv("SERSFLOW_UPLOAD_DIR", str(upload_root))

    batch = "vmsbatch2"
    dest = upload_root / batch / "mixed.vms"
    dest.parent.mkdir(parents=True, exist_ok=True)
    write_mixed_region_vms(dest)
    rel = f"{batch}/mixed.vms"

    with pytest.raises(ValueError, match="No spectra"):
        create_dataset_from_uploads(
            DatasetCreateRequest(
                relative_paths=[rel],
                metadata=DatasetMetadata(name="vms-none"),
                vms_spectrum_mode="averages",
                xps_regions=["Au4f"],
            ),
            owner_user_id="dev",
        )


def test_create_dataset_rejects_mixed_techniques(tmp_path: Path, monkeypatch) -> None:
    from sersflow.api.schemas.datasets import DatasetCreateRequest, DatasetMetadata
    from sersflow.api.services.datasets_service import create_dataset_from_uploads

    monkeypatch.setenv("SERSFLOW_DB_PATH", str(tmp_path / "vms3.db"))
    monkeypatch.setenv("SERSFLOW_DATA_DIR", str(tmp_path / "data3"))
    upload_root = tmp_path / ".sersflow_uploads3"
    monkeypatch.setenv("SERSFLOW_UPLOAD_DIR", str(upload_root))

    batch = "mixtech"
    vms = upload_root / batch / "x.vms"
    txt = upload_root / batch / "r.txt"
    vms.parent.mkdir(parents=True, exist_ok=True)
    write_mixed_region_vms(vms)
    txt.write_text("wn\tint\n100\t1\n200\t2\n", encoding="utf-8")

    with pytest.raises(ValueError, match="Cannot mix"):
        create_dataset_from_uploads(
            DatasetCreateRequest(
                relative_paths=[f"{batch}/x.vms", f"{batch}/r.txt"],
                metadata=DatasetMetadata(name="mixed-tech"),
            ),
            owner_user_id="dev",
        )


def test_additional_params_before_m(tmp_path: Path) -> None:
    """CasaXPS-style n_additional_params triplets must not be read as m."""
    y = [10.0, 20.0, 30.0]
    lines = _legacy_header(n_blocks=1) + _legacy_block(
        block_name="Co 2p_spectrum",
        species="Co",
        transition="2p",
        x_start=800.0,
        x_step=-0.1,
        y=y,
        additional_params=[
            ("PROPAGATION_CONVERGED", "d", "1"),
            ("ESCAPE DEPTH TYPE", "d", "1"),
            ("MFP Exponent", "d", "0"),
        ],
    )
    p = tmp_path / "casa_add.vms"
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    _h, blocks = read_vms_blocks(p)
    assert len(blocks) == 1
    assert blocks[0].m == 3
    np.testing.assert_allclose(blocks[0].y, y)
    extras = blocks[0].extra_fields.get("additional_params") or []
    assert len(extras) == 3
    assert extras[0]["label"] == "PROPAGATION_CONVERGED"


def test_kinetic_energy_converted_to_binding_energy(tmp_path: Path) -> None:
    """When abscissa is kinetic energy, convert with BE = hv − KE − φ per block."""
    from sersflow.core.io.read_vms import abscissa_is_kinetic_energy, kinetic_to_binding_energy

    assert abscissa_is_kinetic_energy("Kinetic Energy")
    assert abscissa_is_kinetic_energy("KE")
    assert not abscissa_is_kinetic_energy("Binding Energy")
    assert not abscissa_is_kinetic_energy("BE")

    hv = 1486.6
    wf = 4.5
    ke = [1200.0, 1190.0, 1180.0]
    y = [1.0, 2.0, 3.0]
    expected_be = kinetic_to_binding_energy(
        np.asarray(ke, dtype=float),
        photon_energy_eV=hv,
        analyser_work_function_eV=wf,
    )

    lines = _legacy_header(n_blocks=1) + _legacy_block(
        block_name="C 1s_spectrum",
        species="C",
        transition="1s",
        x_start=ke[0],
        x_step=-10.0,
        y=y,
        excitation_energy_eV=hv,
        analyser_work_function_eV=wf,
        x_label="Kinetic Energy",
    )
    p = tmp_path / "ke.vms"
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    _h, blocks = read_vms_blocks(p)
    assert len(blocks) == 1
    b = blocks[0]
    np.testing.assert_allclose(b.x, expected_be)
    assert b.x_label == "Binding Energy"
    assert b.analyser_work_function_eV == pytest.approx(wf)
    assert b.extra_fields.get("x_axis_converted_from") == "kinetic_energy"
    # start/step rewritten in BE space (step flips sign)
    assert b.x_start == pytest.approx(float(expected_be[0]))
    assert b.x_step == pytest.approx(10.0)

    ds = read_file_vms(p)
    assert ds.meta[0]["x_axis_converted_from"] == "kinetic_energy"
    assert ds.meta[0]["analyser_work_function_eV"] == pytest.approx(wf)
    assert ds.meta[0]["x_label"] == "Binding Energy"


def test_kinetic_energy_missing_work_function_raises(tmp_path: Path) -> None:
    from sersflow.core.io.read_vms import VmsParseError

    bad = _legacy_header(n_blocks=1) + _legacy_block(
        block_name="C 1s_spectrum",
        species="C",
        transition="1s",
        x_start=1200.0,
        x_step=-10.0,
        y=[1.0, 2.0],
        analyser_work_function_eV=4.5,
        x_label="Kinetic Energy",
    )
    # Analyser lines after mode: resolution, magnification, work function.
    idx = bad.index("FAT")
    assert bad[idx + 3] == "4.5"
    bad[idx + 3] = "not-a-number"
    p = tmp_path / "ke_bad.vms"
    p.write_text("\n".join(bad) + "\n", encoding="utf-8")
    with pytest.raises(VmsParseError, match="work function"):
        read_vms_blocks(p)


def test_casa_iso_hv_and_work_function_after_comments(tmp_path: Path) -> None:
    """
    CasaXPS layout: after block comments → technique → exp-var → source label → hν;
    analyser work function is the 4th analyser line (mode/res/mag/φ).
    """
    hv = 1100.0
    wf = 3.97
    ke0 = 290.0
    lines = _casa_header(n_blocks=1, n_exp_vars=1) + _casa_ke_block(
        photon_eV=hv,
        work_function_eV=wf,
        ke_start=ke0,
        ke_step=0.1,
        y=[1.0, 2.0, 3.0],
        exp_var_value="24",
        source_label="ISISS PGM",
        n_comment_lines=3,
    )
    p = tmp_path / "casa_ke.vms"
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    header, blocks = read_vms_blocks(p)
    assert header.declared_n_experiment_variables == 1
    assert len(blocks) == 1
    b = blocks[0]
    assert b.source_label == "ISISS PGM"
    assert b.excitation_energy_eV == pytest.approx(hv)
    assert b.analyser_work_function_eV == pytest.approx(wf)
    assert b.extra_fields.get("experiment_variable_value") == "24"
    assert b.extra_fields.get("x_axis_converted_from") == "kinetic_energy"
    assert b.x_label == "Binding Energy"
    # BE = hv − KE − φ
    np.testing.assert_allclose(b.x[0], hv - ke0 - wf)
    np.testing.assert_allclose(b.x, [hv - ke0 - wf, hv - (ke0 + 0.1) - wf, hv - (ke0 + 0.2) - wf])

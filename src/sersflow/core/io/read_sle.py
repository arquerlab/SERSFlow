"""Load SPECS Prodigy ``.sle`` XPS files (SQLite containers) as MultiSpectrumDataset.

An ``.sle`` file is a SQLite database written by SpecsLab Prodigy. Relevant tables:

- ``Spectrum``: one row per acquired spectrum (frames, channels, step, start energy, ...).
- ``RawData`` / ``CountRateData``: one row per scan; counts are zlib-compressed float32
  arranged as ``(frames, energy_channels)``.
- ``NodeData``: XML blobs, among them the ``DetectorCalibration`` (per-channel energy
  shifts as a fraction of the pass energy).
- ``Configuration.Schedule``: the acquisition schedule XML (spectrum names, scan mode).

Constant-final-state scans (NEXAFS / XAS, photon-energy scans) become ``technique="XAS"``
blocks: one block per detected signal (TEY from the picoammeter, PEY from the detector
counts), both corrected for the incident-flux monitor (``I_mirror``) when present.

For fixed-analyzer-transmission (FAT) scans with a delay-line detector, each of the
``EnergyChns`` channels sees the spectrum shifted in energy. The final spectrum is built
like Prodigy does it: shift every channel by its calibrated offset, interpolate linearly
onto one common grid of ``NumValues`` points, and sum the channels.
"""

from __future__ import annotations

import logging
import re
import sqlite3
import xml.etree.ElementTree as ET
import zlib
from contextlib import closing
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np

from sersflow.core.io.read_vms import classify_block_role, derive_xps_region

logger = logging.getLogger(__name__)

_MONTHS = {
    m: i
    for i, m in enumerate(
        ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"),
        start=1,
    )
}
_TIMESTAMP_RE = re.compile(
    r"^(?P<y>\d{4})-(?P<mon>[A-Za-z]{3})-(?P<d>\d{1,2})\s+(?P<H>\d{2}):(?P<M>\d{2}):(?P<S>\d{2})(?:\.(?P<f>\d+))?"
)
_CORE_LEVEL_RE = re.compile(r"^(?P<sp>[A-Z][a-z]?)\s*(?P<tr>\d[spdf])$")
_XAS_SCAN_MODE = "ConstantFinalState"
_SUPPORTED_SCAN_MODES = frozenset({"FixedAnalyzerTransmission", _XAS_SCAN_MODE})
_EDGE_RE = re.compile(r"^(?P<el>[A-Z][a-z]?)\s*(?P<edge>[KLM][1-5]?)[\s_-]*edge", re.IGNORECASE)


def _parse_timestamp(raw: Any) -> str | None:
    """Prodigy timestamps look like ``2025-Mar-21 08:47:57.822896`` (English month, locale-free)."""
    m = _TIMESTAMP_RE.match(str(raw or "").strip())
    if not m:
        return None
    mon = _MONTHS.get(m.group("mon").lower())
    if mon is None:
        return None
    try:
        micro = int((m.group("f") or "0")[:6].ljust(6, "0"))
        return datetime(
            int(m.group("y")), mon, int(m.group("d")),
            int(m.group("H")), int(m.group("M")), int(m.group("S")), micro,
        ).isoformat()
    except ValueError:
        return None


def _region_from_name(name: str) -> tuple[str, str | None, str | None]:
    """Map a Prodigy spectrum name to ``(xps_region, species, transition)``."""
    clean = re.sub(r"\s+", " ", str(name or "").strip())
    low = clean.lower()
    if not clean:
        return "unknown", None, None
    if low in {"overview", "survey", "wide", "wide scan"}:
        return "survey", None, None
    m = _CORE_LEVEL_RE.match(clean)
    if m:
        return derive_xps_region(m.group("sp"), m.group("tr")), m.group("sp"), m.group("tr")
    vb = re.match(r"^valence[\s_]*band[\s_]*(?P<rest>.*)$", clean, re.IGNORECASE)
    if vb:
        # Valence bands at different photon energies are not comparable, so keep the suffix.
        rest = re.sub(r"[^a-zA-Z0-9]+", "", vb.group("rest"))
        return (f"VB_{rest}" if rest else "VB"), None, None
    return derive_xps_region(clean, None), None, None


def _float_or(raw: Any, default: float) -> float:
    try:
        v = float(raw)
    except (TypeError, ValueError):
        return default
    return v if np.isfinite(v) else default


def _xas_region_from_name(name: str) -> tuple[str, str | None]:
    """``"O K edge actual"`` -> (``"OKedge"``, ``"O K"``); other names keep a sanitized token."""
    clean = re.sub(r"\s+", " ", str(name or "").strip())
    m = _EDGE_RE.match(clean)
    if m:
        el, edge = m.group("el").capitalize(), m.group("edge").upper()
        return f"{el}{edge}edge", f"{el} {edge}"
    return derive_xps_region(clean, None), None


def _open_readonly(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)


def _decode_counts(blob: bytes) -> np.ndarray:
    """CountRateData blobs are zlib-compressed float32; tolerate uncompressed ones."""
    try:
        blob = zlib.decompress(blob)
    except zlib.error:
        pass
    return np.frombuffer(blob, dtype="<f4").astype(float)


def _parse_schedule(con: sqlite3.Connection) -> tuple[dict[int, dict[str, Any]], dict[str, str]]:
    """Return ``({spectrum_xml_id: info}, metainfo)`` from the Schedule XML (best effort)."""
    info: dict[int, dict[str, Any]] = {}
    meta: dict[str, str] = {}
    row = con.execute("SELECT Value FROM Configuration WHERE Key = 'Schedule'").fetchone()
    if not row or not row[0]:
        return info, meta
    try:
        root = ET.fromstring(row[0])
    except ET.ParseError:
        logger.warning("SLE Schedule XML could not be parsed; falling back to SQL metadata")
        return info, meta
    mi = root.find(".//MetaInfo")
    if mi is not None:
        for p in mi.findall("Parameter"):
            if p.get("name") and (p.text or "").strip():
                meta[str(p.get("name"))] = str(p.text).strip()
    for group in root.iter("SpectrumGroup"):
        mode_el = group.find("./CommonSpectrumSettings/ScanMode")
        scan_mode = mode_el.get("Name") if mode_el is not None else None
        for spec in group.findall("Spectrum"):
            try:
                sid = int(spec.get("ID", ""))
            except ValueError:
                continue
            settings: dict[str, str] = {}
            for child in spec:
                if child.tag.endswith("Settings") and child.tag not in {"UserSettings", "ViewSettings"}:
                    settings = dict(child.attrib)
                    break
            try:
                group_id = int(group.get("ID", ""))
            except ValueError:
                group_id = None
            ext = [
                {
                    "name": ch.get("name") or "",
                    "scale": _float_or(ch.get("Scale"), 1.0),
                    "offset": _float_or(ch.get("Offset"), 0.0),
                }
                for ch in spec.findall("./ExternalChannels/Channel")
            ]
            info[sid] = {
                "ext_channels": ext,
                "name": spec.get("Name") or "",
                "scan_mode": scan_mode,
                "group_id": group_id,
                "settings": settings,
            }
    return info, meta


def _detector_shifts(con: sqlite3.Connection) -> dict[int, np.ndarray]:
    """``{node: per-channel shift (fraction of pass energy)}`` for nodes holding a DetectorCalibration."""
    out: dict[int, np.ndarray] = {}
    for node, data in con.execute("SELECT Node, Data FROM NodeData WHERE Data LIKE '%DetectorCalibration%'"):
        try:
            root = ET.fromstring(data)
            vals = [float(d.get("Shift")) for d in root.iter("Detector") if d.get("Shift") is not None]
        except (ET.ParseError, TypeError, ValueError):
            continue
        if vals:
            out[int(node)] = np.asarray(vals, dtype=float)
    return out


def _reconstruct_fat(
    frames: np.ndarray,
    *,
    step: float,
    pass_energy: float,
    shifts_frac: np.ndarray | None,
    n_values: int,
) -> tuple[np.ndarray, bool]:
    """
    Collapse ``(frames, channels)`` counts into ``n_values`` points on the kinetic-energy grid
    (ascending, relative to the analyzer setting). Returns ``(counts, shift_applied)``.
    """
    n_frames, n_chn = frames.shape
    if n_chn == 1:
        return frames[:n_values, 0].copy(), False
    if shifts_frac is None or shifts_frac.size != n_chn:
        # No usable calibration: plain channel sum (broader peaks) over the first n_values frames.
        return frames.sum(axis=1)[:n_values], False
    sh = shifts_frac * pass_energy
    t = np.arange(n_frames) * step
    xmin = float(sh.max())
    xmax = float(t[-1] + sh.min())
    grid = xmin + np.arange(n_values) * step
    if grid[-1] > xmax + 0.5 * step:
        grid = np.linspace(xmin, xmax, n_values)
    y = np.zeros(n_values, dtype=float)
    for i in range(n_chn):
        y += np.interp(grid, t + sh[i], frames[:, i])
    return y, True


def _ext_channel(con: sqlite3.Connection, raw_id: int, channel: int) -> np.ndarray | None:
    row = con.execute(
        "SELECT Data FROM ExtensionData WHERE RawID = ? AND Channel = ?", (raw_id, channel)
    ).fetchone()
    if not row or not row[0]:
        return None
    try:
        return np.frombuffer(row[0], dtype="<f8").astype(float)
    except ValueError:
        return None


def _find_channel(names: list[str], *patterns: str) -> int | None:
    for pat in patterns:
        rx = re.compile(pat, re.IGNORECASE)
        for i, n in enumerate(names):
            if rx.search(n):
                return i
    return None


def _on_grid(grid: np.ndarray, x: np.ndarray, y: np.ndarray) -> np.ndarray:
    """Resample ``y(x)`` onto ``grid`` (readback energies jitter around the nominal grid)."""
    order = np.argsort(x, kind="stable")
    return np.interp(grid, x[order], y[order])


def _xas_blocks(
    con: sqlite3.Connection,
    *,
    node: int,
    name: str,
    sched_info: dict[str, Any],
    raws: list[tuple],
    n_chn: int,
    step: float,
    e_start: float,
    final_state_be: float,
    epass: float,
    metainfo: dict[str, str],
    seen_prefix: dict[str, int],
) -> list[dict[str, Any]]:
    """Blocks (TEY and/or PEY; average + one per scan) for one constant-final-state scan."""
    ext_cfg = list(sched_info.get("ext_channels") or [])
    names = [
        str(r[0])
        for r in con.execute(
            "SELECT Name FROM ExtensionChannelInfo WHERE Node = ? ORDER BY Channel", (node,)
        )
    ] or [c["name"] for c in ext_cfg]
    i_energy = _find_channel(names, r"^excitation energy", r"photon")
    i_tey = _find_channel(names, r"^tey\b")
    i_i0 = _find_channel(names, r"i[_ ]?mirror", r"\bi0\b")
    if i_energy is None:
        raise ValueError("no photon-energy channel in ExtensionChannelInfo")

    def scale_offset(idx: int | None) -> tuple[float, float]:
        if idx is None or idx >= len(ext_cfg):
            return 1.0, 0.0
        return ext_cfg[idx]["scale"], ext_cfg[idx]["offset"]

    per_signal: dict[str, list[np.ndarray]] = {"TEY": [], "PEY": []}
    dates: list[str | None] = []
    max_dev = 0.0
    i0_used = False
    grid: np.ndarray | None = None
    for rid, scan_date, _eexc, _h, _t in raws:
        e = _ext_channel(con, rid, i_energy)
        rows = con.execute(
            "SELECT Data FROM CountRateData WHERE RawID = ? ORDER BY Offset", (rid,)
        ).fetchall()
        if e is None or not rows:
            continue
        counts = np.concatenate([_decode_counts(r[0]) for r in rows])
        if counts.size % n_chn:
            raise ValueError(f"count array size {counts.size} not divisible by {n_chn} channels")
        # Constant final state: every channel sees the same kinetic energy, so just sum them.
        pey = counts.reshape(-1, n_chn).sum(axis=1)
        n = min(e.size, pey.size)
        e, pey = e[:n], pey[:n]
        if grid is None:
            grid = e_start + np.arange(n) * step
        if n != grid.size:
            raise ValueError(f"scan length {n} differs from first scan ({grid.size})")
        max_dev = max(max_dev, float(np.max(np.abs(e - grid))))
        flux = None
        if i_i0 is not None:
            f = _ext_channel(con, rid, i_i0)
            if f is not None and f.size >= n and np.all(np.isfinite(f[:n])) and np.all(f[:n] > 0):
                flux = f[:n] / float(np.mean(f[:n]))
        i0_used = flux is not None
        signals = {"PEY": pey}
        if i_tey is not None:
            t = _ext_channel(con, rid, i_tey)
            if t is not None and t.size >= n:
                scale, offset = scale_offset(i_tey)
                signals["TEY"] = t[:n] * scale + offset
        for sig, y in signals.items():
            if flux is not None:
                y = y / flux
            per_signal[sig].append(_on_grid(grid, e, y))
        dates.append(_parse_timestamp(scan_date))
    if grid is None:
        return []

    region_base, edge = _xas_region_from_name(name)
    dwell = _float_or((sched_info.get("settings") or {}).get("DwellTime"), 0.0) or None
    units = {"TEY": "A", "PEY": "counts"}
    out: list[dict[str, Any]] = []
    for sig in ("TEY", "PEY"):
        scans = per_signal[sig]
        if not scans:
            continue
        region = f"{region_base}_{sig}"
        n_seen = seen_prefix.get(region, 0) + 1
        seen_prefix[region] = n_seen
        prefix = region if n_seen == 1 else f"{region}_{n_seen}"
        common = {
            "xps_region": region,
            "xps_species": None,
            "xps_transition": None,
            "technique": "XAS",
            "xas_signal": sig,
            "xas_edge": edge,
            "xas_i0_normalized": bool(i0_used),
            "excitation_energy_eV": None,
            "pass_energy_eV": float(epass) or None,
            "step_time": dwell,
            "total_steps": int(grid.size),
            "number_of_iterations": len(scans),
            "sle_node": node,
            "sle_spectrum_name": name,
            "sle_scan_mode": _XAS_SCAN_MODE,
            "sle_fixed_kinetic_energy_eV": float(e_start - final_state_be),
            "sle_photon_energy_max_dev_eV": round(max_dev, 4),
            "sle_sample_identifier": metainfo.get("sample identifier"),
            "x_label": "Photon energy (eV)",
            "y_label": f"{sig} ({units[sig]}" + (", I0-corrected)" if i0_used else ")"),
        }
        entries = [(f"{prefix}_spectrum", np.mean(scans, axis=0), dates[0])]
        if len(scans) > 1:
            entries += [
                (f"{prefix}_spectrum_{i}", y, dates[i - 1]) for i, y in enumerate(scans, start=1)
            ]
        for block_name, y, acquired in entries:
            role = classify_block_role(block_name)
            out.append(
                {
                    "x": grid.copy(),
                    "y": np.asarray(y, dtype=float),
                    "meta": {
                        **common,
                        "block_name": block_name,
                        "spectrum_role": role["spectrum_role"],
                        "replicate_index": role["replicate_index"],
                        "acquired_at": acquired,
                    },
                }
            )
    return out


def read_sle_blocks_with_report(path: str | Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """
    Parse a SPECS Prodigy ``.sle`` file into block dicts plus a skip report.

    Per spectrum: one ``average`` block (mean over scans) followed by one ``individual``
    block per scan when there is more than one scan. Report keys: ``skipped_regions``
    (list of {key, reason}), ``skipped_count``.
    """
    p = Path(path)
    blocks: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []
    try:
        con = _open_readonly(p)
    except sqlite3.Error as e:
        raise ValueError(f"Not a readable SPECS .sle (SQLite) file: {p}") from e
    with closing(con):
        try:
            tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        except sqlite3.DatabaseError as e:
            raise ValueError(f"Not a readable SPECS .sle (SQLite) file: {p}") from e
        if not {"Spectrum", "RawData", "CountRateData"} <= tables:
            raise ValueError(f"Not a SPECS Prodigy .sle file (missing Spectrum/RawData tables): {p}")

        sched, metainfo = _parse_schedule(con) if "Configuration" in tables else ({}, {})
        shifts_by_node = _detector_shifts(con) if "NodeData" in tables else {}
        fallback_shifts = next(iter(shifts_by_node.values()), None)

        spectra = con.execute(
            "SELECT Node, EnergyChns, NonEnergyChns, Samples, ElectronEnergy, EnergyType, Step, "
            "EpassOrRR, Wf, Timestamp FROM Spectrum ORDER BY Timestamp, Node"
        ).fetchall()
        seen_prefix: dict[str, int] = {}

        for node, e_chn, ne_chn, samples, e_start, e_type, step, epass, wf, _ts in spectra:
            node = int(node)
            s = sched.get(node, {})
            name = str(s.get("name") or "").strip() or f"Spectrum{node}"
            try:
                scan_mode = s.get("scan_mode")
                if scan_mode is not None and scan_mode not in _SUPPORTED_SCAN_MODES:
                    skipped.append({"key": name, "reason": f"unsupported_scan_mode:{scan_mode}"})
                    continue
                if int(ne_chn) != 1:
                    skipped.append({"key": name, "reason": "unsupported_non_energy_channels"})
                    continue
                raws = con.execute(
                    "SELECT RawID, ScanDate, Eexc, Head, Tail FROM RawData WHERE Node = ? ORDER BY RawID",
                    (node,),
                ).fetchall()
                if not raws:
                    skipped.append({"key": name, "reason": "no_raw_data"})
                    continue
                n_chn = int(e_chn)
                if scan_mode == _XAS_SCAN_MODE:
                    xas = _xas_blocks(
                        con,
                        node=node,
                        name=name,
                        sched_info=s,
                        raws=raws,
                        n_chn=n_chn,
                        step=abs(float(step)),
                        e_start=float(raws[0][2]),
                        final_state_be=float(e_start),
                        epass=float(epass),
                        metainfo=metainfo,
                        seen_prefix=seen_prefix,
                    )
                    if xas:
                        blocks.extend(xas)
                    else:
                        skipped.append({"key": name, "reason": "no_usable_spectra"})
                    continue
                head, tail = int(raws[0][3]), int(raws[0][4])
                n_values = int(samples) - head - tail
                step_f = abs(float(step))
                if n_values <= 0 or step_f <= 0:
                    skipped.append({"key": name, "reason": "invalid_geometry"})
                    continue

                shifts = shifts_by_node.get(s.get("group_id") or -1, fallback_shifts)
                scans: list[np.ndarray] = []
                dates: list[str | None] = []
                shift_applied = False
                for rid, scan_date, _eexc, _h, _t in raws:
                    row = con.execute(
                        "SELECT Data FROM CountRateData WHERE RawID = ? ORDER BY Offset", (rid,)
                    ).fetchall()
                    if not row:
                        continue
                    flat = np.concatenate([_decode_counts(r[0]) for r in row])
                    if flat.size % n_chn:
                        raise ValueError(f"count array size {flat.size} not divisible by {n_chn} channels")
                    y, shift_applied = _reconstruct_fat(
                        flat.reshape(-1, n_chn),
                        step=step_f,
                        pass_energy=float(epass),
                        shifts_frac=shifts,
                        n_values=n_values,
                    )
                    scans.append(y)
                    dates.append(_parse_timestamp(scan_date))
                if not scans:
                    skipped.append({"key": name, "reason": "no_usable_spectra"})
                    continue

                eexc = float(raws[0][2])
                k = np.arange(len(scans[0]))
                converted_from = None
                if str(e_type).strip().lower().startswith("kin"):
                    x = eexc - (float(e_start) + k * step_f) - float(wf)
                    converted_from = "kinetic energy"
                else:
                    x = float(e_start) - k * step_f

                region, species, transition = _region_from_name(name)
                prefix = region
                n_seen = seen_prefix.get(region, 0) + 1
                seen_prefix[region] = n_seen
                if n_seen > 1:
                    prefix = f"{region}_{n_seen}"

                dwell = None
                try:
                    dwell = float(s.get("settings", {}).get("DwellTime", "")) or None
                except ValueError:
                    dwell = None

                common = {
                    "xps_region": region,
                    "xps_species": species,
                    "xps_transition": transition,
                    "technique": "XPS",
                    "excitation_energy_eV": eexc or None,
                    "pass_energy_eV": float(epass) or None,
                    "step_time": dwell,
                    "total_steps": n_values,
                    "number_of_iterations": len(scans),
                    "sle_node": node,
                    "sle_spectrum_name": name,
                    "sle_scan_mode": scan_mode,
                    "sle_channel_shifts_applied": bool(shift_applied),
                    "sle_work_function_eV": float(wf),
                    "sle_sample_identifier": metainfo.get("sample identifier"),
                    "x_label": "Binding energy (eV)",
                }
                if converted_from:
                    common["x_axis_converted_from"] = converted_from

                entries: list[tuple[str, np.ndarray, str | None]] = [
                    (f"{prefix}_spectrum", np.mean(scans, axis=0), dates[0])
                ]
                if len(scans) > 1:
                    entries += [
                        (f"{prefix}_spectrum_{i}", y, dates[i - 1]) for i, y in enumerate(scans, start=1)
                    ]
                for block_name, y, acquired in entries:
                    role = classify_block_role(block_name)
                    blocks.append(
                        {
                            "x": np.asarray(x, dtype=float),
                            "y": np.asarray(y, dtype=float),
                            "meta": {
                                **common,
                                "block_name": block_name,
                                "spectrum_role": role["spectrum_role"],
                                "replicate_index": role["replicate_index"],
                                "acquired_at": acquired,
                            },
                        }
                    )
            except Exception as e:
                logger.warning("Skipping SLE spectrum %r (node %s) in %s", name, node, p, exc_info=True)
                skipped.append({"key": name, "reason": f"read_error:{type(e).__name__}"})
    return blocks, {"skipped_regions": skipped, "skipped_count": len(skipped)}


def read_sle_blocks(path: str | Path) -> list[dict[str, Any]]:
    """Parse a ``.sle`` file into block dicts (x, y, meta); see :func:`read_sle_blocks_with_report`."""
    blocks, _report = read_sle_blocks_with_report(path)
    return blocks


def read_file_sle(file_path: Path):
    """Load a SPECS Prodigy ``.sle`` file as MultiSpectrumDataset (one entry per spectrum block)."""
    from sersflow.core.models.datasets import MultiSpectrumDataset

    blocks, report = read_sle_blocks_with_report(file_path)
    if not blocks:
        raise ValueError(f"SLE file contains no usable spectrum blocks: {file_path}")
    xs = tuple(np.asarray(b["x"], dtype=float) for b in blocks)
    ys = tuple(np.asarray(b["y"], dtype=float) for b in blocks)
    meta = tuple(dict(b["meta"]) for b in blocks)
    if report.get("skipped_count"):
        # Same label keys as NeXus so Uploads shows the skip summary without a new code path.
        m0 = dict(meta[0])
        m0["nxs_skipped_count"] = int(report["skipped_count"])
        m0["nxs_skipped_regions"] = list(report.get("skipped_regions") or [])
        meta = (m0,) + meta[1:]
    return MultiSpectrumDataset(kind="multi", xs=xs, ys=ys, meta=meta)

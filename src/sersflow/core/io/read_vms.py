from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Literal

import numpy as np


class VmsParseError(ValueError):
    def __init__(self, message: str, *, line_no: int | None = None, path: Path | None = None):
        where = []
        if path is not None:
            where.append(str(path))
        if line_no is not None:
            where.append(f"line {line_no}")
        prefix = f"[{' | '.join(where)}] " if where else ""
        super().__init__(prefix + message)
        self.line_no = line_no
        self.path = path


@dataclass(frozen=True)
class VamasHeader:
    raw_lines: list[str]
    signature: str | None = None
    organization: str | None = None
    instrument: str | None = None
    operator: str | None = None
    experiment_id: str | None = None
    format_flags: dict[str, str] = field(default_factory=dict)
    declared_n_experiments: int | None = None  # ISO field: # regions
    declared_n_experiment_variables: int | None = None
    experiment_variable_label: str | None = None
    experiment_variable_unit: str | None = None
    declared_n_blocks: int | None = None


@dataclass
class VamasBlock:
    block_name: str
    experiment_id: str | None
    acquired_at: datetime | None
    technique: str | None
    source_label: str | None
    excitation_energy_eV: float | None
    analyser_work_function_eV: float | None
    species: str | None
    transition: str | None
    x_label: str | None
    x_unit: str | None
    x_start: float | None
    x_step: float | None
    m: int | None
    y_min_declared: float | None
    y_max_declared: float | None
    y: np.ndarray
    x: np.ndarray
    extra_fields: dict[str, Any] = field(default_factory=dict)


def _is_float(s: str) -> bool:
    try:
        float(s)
        return True
    except Exception:
        return False


def _is_int(s: str) -> bool:
    try:
        int(s)
        return True
    except Exception:
        return False


_SPECTRUM_AVG_RE = re.compile(r"^(?P<prefix>.*)_spectrum$", re.IGNORECASE)
_SPECTRUM_IND_RE = re.compile(r"^(?P<prefix>.*)_spectrum_(?P<idx>\d+)$", re.IGNORECASE)

VmsSpectrumMode = Literal["averages", "individuals", "all"]


def classify_block_role(block_name: str) -> dict[str, Any]:
    """
    Classify average vs individual from CasaXPS / diamond_analysis naming.

    - ``…_spectrum`` → average (replicate_index null)
    - ``…_spectrum_<n>`` → individual (replicate_index = n)
    - otherwise → average (best-effort; treat as standalone spectrum)
    """
    name = str(block_name or "").strip()
    m_ind = _SPECTRUM_IND_RE.match(name)
    if m_ind:
        return {
            "spectrum_role": "individual",
            "replicate_index": int(m_ind.group("idx")),
            "name_prefix": m_ind.group("prefix"),
        }
    m_avg = _SPECTRUM_AVG_RE.match(name)
    if m_avg:
        return {
            "spectrum_role": "average",
            "replicate_index": None,
            "name_prefix": m_avg.group("prefix"),
        }
    return {"spectrum_role": "average", "replicate_index": None, "name_prefix": name}


def derive_xps_region(species: str | None, transition: str | None) -> str:
    """Sanitize species+transition into a compact region token (e.g. C1s, Mn2p, survey)."""
    sp = (species or "").strip()
    tr = (transition or "").strip()
    raw = f"{sp}{tr}" if tr else sp
    token = re.sub(r"[^a-zA-Z0-9]+", "", raw)
    return token or "unknown"


def _as_optional_float(raw: Any) -> float | None:
    if raw is None:
        return None
    s = str(raw).strip()
    if not s or not _is_float(s):
        return None
    v = float(s)
    if v != v:  # NaN
        return None
    return v


def abscissa_is_kinetic_energy(x_label: str | None) -> bool:
    """True when the VAMAS abscissa label denotes kinetic energy (not binding energy)."""
    label = re.sub(r"[\s_]+", " ", str(x_label or "").strip().lower())
    if not label:
        return False
    if "binding" in label:
        return False
    if "kinetic" in label:
        return True
    # Compact tokens used by some exporters
    compact = label.replace(" ", "")
    return compact in {"ke", "ekin", "ekinetic", "kineticenergy"}


def kinetic_to_binding_energy(
    kinetic_eV: np.ndarray,
    *,
    photon_energy_eV: float,
    analyser_work_function_eV: float,
) -> np.ndarray:
    """
    Convert kinetic energy to binding energy:

        BE = hν − KE − φ
    """
    return np.asarray(photon_energy_eV, dtype=float) - np.asarray(kinetic_eV, dtype=float) - float(
        analyser_work_function_eV
    )


def block_meta_dict(block: VamasBlock) -> dict[str, Any]:
    """A+B spectrum metadata fields for persistence / UI."""
    role = classify_block_role(block.block_name)
    acquired = None
    if block.acquired_at is not None:
        acquired = block.acquired_at.isoformat()
    out: dict[str, Any] = {
        "xps_region": derive_xps_region(block.species, block.transition),
        "xps_species": block.species,
        "xps_transition": block.transition,
        "block_name": block.block_name,
        "spectrum_role": role["spectrum_role"],
        "replicate_index": role["replicate_index"],
        "technique": block.technique,
        "acquired_at": acquired,
        "excitation_energy_eV": block.excitation_energy_eV,
        "analyser_work_function_eV": block.analyser_work_function_eV,
        "x_label": block.x_label,
    }
    # FAT / CA analyser_resolution is typically the pass energy in eV.
    res_raw = (block.extra_fields or {}).get("analyser_resolution")
    try:
        pe = float(res_raw) if res_raw is not None and str(res_raw).strip() != "" else None
    except (TypeError, ValueError):
        pe = None
    if pe is not None and math.isfinite(pe) and pe > 0:
        out["pass_energy_eV"] = pe
    converted_from = (block.extra_fields or {}).get("x_axis_converted_from")
    if converted_from:
        out["x_axis_converted_from"] = converted_from
    return out


def filter_blocks_by_mode(
    blocks: list[VamasBlock],
    mode: VmsSpectrumMode,
) -> list[tuple[int, VamasBlock]]:
    """
    Return (original_index, block) pairs kept for the given load mode.

    If the file has only one role present, returns all blocks of that role
    (mode is ignored when the other role is absent), except mode ``all``
    which always keeps every block.
    """
    indexed = list(enumerate(blocks))
    if mode == "all":
        return indexed
    avgs = [(i, b) for i, b in indexed if classify_block_role(b.block_name)["spectrum_role"] == "average"]
    inds = [(i, b) for i, b in indexed if classify_block_role(b.block_name)["spectrum_role"] == "individual"]
    if mode == "averages":
        if avgs:
            return avgs
        return inds  # file has only individuals
    # individuals
    if inds:
        return inds
    return avgs  # file has only averages


def filter_meta_indices(meta: tuple[dict[str, Any], ...] | list[dict[str, Any]], mode: VmsSpectrumMode) -> list[int]:
    """Select original block indices from MultiSpectrumDataset.meta for a load mode."""
    indexed = list(enumerate(meta))
    if mode == "all":
        return [i for i, _ in indexed]
    avgs = [i for i, m in indexed if str(m.get("spectrum_role") or "average") == "average"]
    inds = [i for i, m in indexed if str(m.get("spectrum_role") or "") == "individual"]
    if mode == "averages":
        return avgs if avgs else inds
    return inds if inds else avgs


def filter_indices_by_xps_regions(
    meta: tuple[dict[str, Any], ...] | list[dict[str, Any]],
    indices: list[int],
    regions: list[str] | tuple[str, ...] | None,
) -> list[int]:
    """
    Further restrict block indices to those whose ``xps_region`` is in ``regions``.

    Empty / None ``regions`` leaves ``indices`` unchanged.
    """
    if not regions:
        return list(indices)
    allowed = {str(r) for r in regions if str(r).strip()}
    if not allowed:
        return list(indices)
    out: list[int] = []
    n = len(meta)
    for i in indices:
        if i < 0 or i >= n:
            continue
        region = str((meta[i] or {}).get("xps_region") or "")
        if region in allowed:
            out.append(i)
    return out


class _LineReader:
    def __init__(self, lines: Iterable[str], *, path: Path | None = None):
        self._it = iter(lines)
        self.line_no = 0
        self.path = path

    def next_raw(self) -> str:
        # If a line was peeked, consume it first.
        buffered = self.pop_peeked()
        if buffered is not None:
            return buffered
        try:
            line = next(self._it)
        except StopIteration as e:
            raise VmsParseError("Unexpected end of file.", line_no=self.line_no, path=self.path) from e
        self.line_no += 1
        return line.rstrip("\n")

    def next_stripped(self) -> str:
        return self.next_raw().strip()

    def try_peek(self) -> str | None:
        # Minimal lookahead by buffering one line
        if hasattr(self, "_buffer"):
            return self._buffer  # type: ignore[attr-defined]
        try:
            line = next(self._it)
        except StopIteration:
            return None
        self._buffer = line  # type: ignore[attr-defined]
        return line

    def pop_peeked(self) -> str | None:
        if hasattr(self, "_buffer"):
            line = self._buffer  # type: ignore[attr-defined]
            delattr(self, "_buffer")
            self.line_no += 1
            return str(line).rstrip("\n")
        return None

    def next_with_peek_support(self) -> str:
        line = self.pop_peeked()
        if line is not None:
            return line
        return self.next_raw()


def _read_all_lines(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8", errors="replace").splitlines(True)


def _parse_header(r: _LineReader) -> VamasHeader:
    raw: list[str] = []

    signature = r.next_raw().rstrip("\n")
    raw.append(signature)

    organization = r.next_raw().strip()
    instrument = r.next_raw().strip()
    operator = r.next_raw().strip()
    experiment_id = r.next_raw().strip()
    raw.extend([organization + "\n", instrument + "\n", operator + "\n", experiment_id + "\n"])

    # ISO 14976 experiment header fields (CasaXPS manual Appendix 1)
    n_comment_lines_s = r.next_raw().strip()
    raw.append(n_comment_lines_s)
    n_comment_lines = int(n_comment_lines_s) if _is_int(n_comment_lines_s) else 0
    for _ in range(n_comment_lines):
        raw.append(r.next_raw().rstrip("\n"))

    experiment_mode = r.next_raw().strip()
    scan_mode = r.next_raw().strip()
    raw.extend([experiment_mode + "\n", scan_mode + "\n"])

    n_regions_s = r.next_raw().strip()
    n_exp_vars_s = r.next_raw().strip()
    raw.extend([n_regions_s + "\n", n_exp_vars_s + "\n"])

    n_regions = int(n_regions_s) if _is_int(n_regions_s) else None
    n_exp_vars = int(n_exp_vars_s) if _is_int(n_exp_vars_s) else 0

    exp_var_label = None
    exp_var_unit = None
    if n_exp_vars > 0:
        exp_var_label = r.next_raw().strip()
        exp_var_unit = r.next_raw().strip()
        raw.extend([exp_var_label + "\n", exp_var_unit + "\n"])

    n_param_exclusions = r.next_raw().strip()
    n_manual_items = r.next_raw().strip()
    n_future_experiment_items = r.next_raw().strip()
    n_future_block_entries = r.next_raw().strip()
    n_blocks_s = r.next_raw().strip()
    raw.extend(
        [
            n_param_exclusions + "\n",
            n_manual_items + "\n",
            n_future_experiment_items + "\n",
            n_future_block_entries + "\n",
            n_blocks_s + "\n",
        ]
    )

    declared_n_blocks = int(n_blocks_s) if _is_int(n_blocks_s) else None
    format_flags = {"experiment_mode": experiment_mode, "scan_mode": scan_mode}

    return VamasHeader(
        raw_lines=[l.rstrip("\n") for l in raw],
        signature=signature,
        organization=organization or None,
        instrument=instrument or None,
        operator=operator or None,
        experiment_id=experiment_id or None,
        format_flags=format_flags,
        declared_n_experiments=n_regions,
        declared_n_experiment_variables=n_exp_vars if n_exp_vars else 0,
        experiment_variable_label=exp_var_label or None,
        experiment_variable_unit=exp_var_unit or None,
        declared_n_blocks=declared_n_blocks,
    )


def _parse_datetime_fields(fields: list[str], *, r: _LineReader) -> datetime | None:
    if len(fields) < 6 or not all(_is_int(x) for x in fields[:6]):
        return None
    year, month, day, hour, minute, second = (int(x) for x in fields[:6])
    try:
        return datetime(year, month, day, hour, minute, second)
    except Exception:
        raise VmsParseError("Invalid date/time fields in block header.", line_no=r.line_no, path=r.path)


def _read_expected(r: _LineReader, *, allow_empty: bool = True) -> str:
    s = r.next_raw().rstrip("\n")
    s2 = s.strip()
    if not allow_empty and s2 == "":
        raise VmsParseError("Unexpected blank line.", line_no=r.line_no, path=r.path)
    return s2


def _parse_block(
    r: _LineReader,
    header_experiment_id: str | None,
    *,
    n_experiment_variables: int = 0,
) -> VamasBlock | None:
    # Skip blank lines between blocks
    while True:
        nxt = r.try_peek()
        if nxt is None:
            return None
        if nxt.strip() == "":
            r.next_with_peek_support()
            continue
        break

    first = r.next_with_peek_support().strip()
    if first.lower() == "end of experiment":
        return None

    block_name = first
    experiment_id = _read_expected(r)

    # Date/time (6 lines)
    dt_fields = [_read_expected(r) for _ in range(6)]
    acquired_at = _parse_datetime_fields(dt_fields, r=r)

    # ISO block header: GMT offset and block comment lines
    gmt_offset = _read_expected(r)
    n_block_comment_lines_s = _read_expected(r)
    n_block_comment_lines = int(n_block_comment_lines_s) if _is_int(n_block_comment_lines_s) else 0
    block_comments = []
    for _ in range(n_block_comment_lines):
        block_comments.append(_read_expected(r))

    technique = _read_expected(r)
    # ISO 14976 / CasaXPS: after technique, one value per declared experiment variable.
    # Example (Casa file): XPS → 24 → source label → source energy (hν).
    exp_var_values: list[str] = []
    n_exp = max(0, int(n_experiment_variables or 0))
    for _ in range(n_exp):
        exp_var_values.append(_read_expected(r))
    exp_var_value = exp_var_values[0] if len(exp_var_values) == 1 else (exp_var_values or None)

    source_label = _read_expected(r)
    source_energy_s = _read_expected(r)
    excitation_energy_eV = float(source_energy_s) if _is_float(source_energy_s) else None

    # After source energy, ISO and legacy diamond layouts both consume 5 numeric/source
    # geometry lines before analyser_mode. Prefer ISO field names; values may be 0.
    # (Do not gate on source_strength != 0 — Casa synchrotron files often write 0 here.)
    _source_strength = _read_expected(r)
    _source_width_x = _read_expected(r)
    _source_width_y = _read_expected(r)
    _source_polar = _read_expected(r)
    _source_azimuth = _read_expected(r)

    analyser_mode = _read_expected(r)
    analyser_resolution = _read_expected(r)
    analyser_magnification = _read_expected(r)
    analyser_work_function = _read_expected(r)
    # Next five lines: target bias + analysis widths + analyser axis angles (ISO),
    # or five placeholder zeros (legacy). Same count either way.
    target_bias = _read_expected(r)
    analysis_width_x = _read_expected(r)
    analysis_width_y = _read_expected(r)
    analyser_axis_polar = _read_expected(r)
    analyser_axis_azimuth = _read_expected(r)

    species = _read_expected(r)  # could be 'survey' or 'Co 2p'
    transition = _read_expected(r)  # could be blank in some files

    charge = _read_expected(r)
    x_label = _read_expected(r)  # abscissa label (Binding Energy / kinetic energy)
    x_unit = _read_expected(r)
    x_start_s = _read_expected(r)
    x_step_s = _read_expected(r)
    x_start = float(x_start_s) if _is_float(x_start_s) else None
    x_step = float(x_step_s) if _is_float(x_step_s) else None

    # Corresponding variables + acquisition (shared by legacy and ISO layouts).
    n_corr_vars_s = _read_expected(r)
    n_corr_vars = int(n_corr_vars_s) if _is_int(n_corr_vars_s) else 1
    if n_corr_vars > 1:
        raise VmsParseError(
            f"VAMAS block has n_corresponding_variables={n_corr_vars}; "
            "only single-channel (n=1) blocks are supported.",
            line_no=r.line_no,
            path=r.path,
        )
    corr_var_label = _read_expected(r)
    corr_var_unit = _read_expected(r)
    signal_mode = _read_expected(r)
    dwell_time = _read_expected(r)
    n_scans = _read_expected(r)

    # Unified ISO trailer. Legacy diamond files write five zeros here
    # (time/tilt/azimuth/rotation + n_additional_params=0), then m.
    # CasaXPS often sets n_additional_params > 0 with label/unit/value triplets
    # (e.g. PROPAGATION_CONVERGED) that must be consumed before m.
    signal_time_correction = _read_expected(r)
    sample_tilt = _read_expected(r)
    sample_azimuth = _read_expected(r)
    sample_rotation = _read_expected(r)
    n_additional_params_s = _read_expected(r)
    n_additional_params = int(n_additional_params_s) if _is_int(n_additional_params_s) else 0
    additional_params: list[dict[str, str]] = []
    for _ in range(max(0, n_additional_params)):
        additional_params.append(
            {
                "label": _read_expected(r),
                "unit": _read_expected(r),
                "value": _read_expected(r),
            }
        )

    m_s = _read_expected(r, allow_empty=False)
    if not _is_int(m_s):
        raise VmsParseError(f"Expected integer m (#points) but got {m_s!r}.", line_no=r.line_no, path=r.path)
    m = int(m_s)

    y_min_s = _read_expected(r)
    y_max_s = _read_expected(r)
    y_min_declared = float(y_min_s) if _is_float(y_min_s) else None
    y_max_declared = float(y_max_s) if _is_float(y_max_s) else None

    # Payload: your writer is 1 value per line (y). For broader variants, we can detect x,y pairs.
    payload: list[float] = []
    for _ in range(m):
        val_s = _read_expected(r, allow_empty=False)
        if not _is_float(val_s):
            raise VmsParseError(
                f"Expected numeric y value in payload but got {val_s!r}.",
                line_no=r.line_no,
                path=r.path,
            )
        payload.append(float(val_s))

    y = np.asarray(payload, dtype=float)
    if x_start is None or x_step is None:
        x = np.arange(len(y), dtype=float)
    else:
        x = x_start + x_step * np.arange(len(y), dtype=float)

    analyser_work_function_eV = _as_optional_float(analyser_work_function)
    x_axis_converted_from: str | None = None
    # XPS convention in SERSFlow: always store Binding Energy on the x-axis.
    if (technique or "").strip().upper() == "XPS" and abscissa_is_kinetic_energy(x_label):
        if excitation_energy_eV is None:
            raise VmsParseError(
                f"Block {block_name!r} uses kinetic energy but source/photon energy is missing.",
                line_no=r.line_no,
                path=r.path,
            )
        if analyser_work_function_eV is None:
            raise VmsParseError(
                f"Block {block_name!r} uses kinetic energy but analyser work function is missing.",
                line_no=r.line_no,
                path=r.path,
            )
        x = kinetic_to_binding_energy(
            x,
            photon_energy_eV=float(excitation_energy_eV),
            analyser_work_function_eV=float(analyser_work_function_eV),
        )
        if x_start is not None and x_step is not None:
            x_start = float(excitation_energy_eV) - float(x_start) - float(analyser_work_function_eV)
            x_step = -float(x_step)
        x_label = "Binding Energy"
        if not x_unit:
            x_unit = "eV"
        x_axis_converted_from = "kinetic_energy"

    # Fill from header if block experiment_id is blank
    if not experiment_id:
        experiment_id = header_experiment_id

    # Derive spectrum_name from block_name suffix if present (e.g. "O 1s_spectrum_3")
    spectrum_name = None
    role_info = classify_block_role(block_name)
    if role_info["spectrum_role"] == "individual" and role_info["replicate_index"] is not None:
        spectrum_name = str(role_info["replicate_index"])
    elif role_info["spectrum_role"] == "average":
        spectrum_name = "spectrum"
    elif "_" in block_name:
        spectrum_name = block_name.split("_")[-1] or None

    return VamasBlock(
        block_name=block_name,
        experiment_id=experiment_id or header_experiment_id,
        acquired_at=acquired_at,
        technique=technique or None,
        source_label=source_label or None,
        excitation_energy_eV=excitation_energy_eV,
        analyser_work_function_eV=analyser_work_function_eV,
        species=(None if species == "" else species),
        transition=(None if transition == "" else transition),
        x_label=x_label or None,
        x_unit=x_unit or None,
        x_start=x_start,
        x_step=x_step,
        m=m,
        y_min_declared=y_min_declared,
        y_max_declared=y_max_declared,
        y=y,
        x=x,
        extra_fields={
            "gmt_offset": gmt_offset,
            "declared_experiment_id": header_experiment_id,
            "spectrum_name": spectrum_name,
            "block_comments": block_comments,
            "experiment_variable_value": exp_var_value,
            "experiment_variable_values": exp_var_values,
            "source_strength": _source_strength,
            "source_beam_width_x": _source_width_x,
            "source_beam_width_y": _source_width_y,
            "source_polar_angle": _source_polar,
            "source_azimuth": _source_azimuth,
            "analyser_mode": analyser_mode,
            "analyser_resolution": analyser_resolution,
            "analyser_magnification": analyser_magnification,
            "analyser_work_function": analyser_work_function,
            "analyser_work_function_eV": analyser_work_function_eV,
            "target_bias": target_bias,
            "analysis_width_x": analysis_width_x,
            "analysis_width_y": analysis_width_y,
            "analyser_axis_polar": analyser_axis_polar,
            "analyser_axis_azimuth": analyser_axis_azimuth,
            "n_corresponding_variables": n_corr_vars,
            "corr_var_label": corr_var_label,
            "corr_var_unit": corr_var_unit,
            "signal_mode": signal_mode,
            "dwell_time": dwell_time,
            "n_scans": n_scans,
            "signal_time_correction": signal_time_correction,
            "sample_tilt": sample_tilt,
            "sample_azimuth": sample_azimuth,
            "sample_rotation": sample_rotation,
            "n_additional_params": n_additional_params,
            "additional_params": additional_params,
            "charge": charge,
            "x_axis_converted_from": x_axis_converted_from,
        },
    )


def read_vms_blocks(path: str | Path) -> tuple[VamasHeader, list[VamasBlock]]:
    """
    Read a VAMAS/CasaXPS-style `.vms` file and return header + blocks.

    Handles legacy diamond_analysis writer layout and full ISO/v2 variants.
    """
    p = Path(path)
    lines = _read_all_lines(p)
    r = _LineReader(lines, path=p)
    header = _parse_header(r)
    blocks: list[VamasBlock] = []
    target_blocks = header.declared_n_blocks
    while True:
        if target_blocks is not None and len(blocks) >= target_blocks:
            break
        b = _parse_block(
            r,
            header.experiment_id,
            n_experiment_variables=int(header.declared_n_experiment_variables or 0),
        )
        if b is None:
            break
        blocks.append(b)
    return header, blocks


def read_file_vms(file_path: Path):
    """
    Load a `.vms` file as MultiSpectrumDataset (one entry per block, independent axes).

    Average/individual filtering is applied at dataset-create time via record_index selection.
    """
    from sersflow.core.models.datasets import MultiSpectrumDataset

    _header, blocks = read_vms_blocks(file_path)
    if not blocks:
        raise ValueError(f"VAMAS file contains no spectrum blocks: {file_path}")

    xs = tuple(np.asarray(b.x, dtype=float) for b in blocks)
    ys = tuple(np.asarray(b.y, dtype=float) for b in blocks)
    meta = tuple(block_meta_dict(b) for b in blocks)
    return MultiSpectrumDataset(kind="multi", xs=xs, ys=ys, meta=meta)


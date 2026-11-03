"""CasaXPS fit components stored in the VAMAS files of a dataset (read on demand)."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from sersflow.infra.datasets_store import DatasetRecord
from sersflow.api.services.spectrum_context import labels_for_spectrum
from sersflow.core.io.casa_fit import parse_casa_comments
from sersflow.core.io.read_vms import derive_xps_region, read_vms_blocks
from sersflow.core.pipeline.engine import _resolve_ref_path
from sersflow.infra.upload_labels_store import fetch_upload_labels_for_paths, with_connection

logger = logging.getLogger(__name__)

BE_CONVENTION = (
    "be_eV = photon energy - kinetic energy (CasaXPS convention; analyser work function NOT subtracted). "
    "The loader's binding-energy axis subtracts the work function, so offsets of a few eV are expected "
    "until the pipeline's x-axis calibration is applied."
)


def casa_fits_payload(dataset: DatasetRecord, *, region: str | None = None) -> dict[str, Any]:
    """
    Per-spectrum CasaXPS fits of a dataset whose spectra come from ``.vms`` files.

    Files are parsed on demand (no re-import needed). Spectra without CasaXPS components are omitted.
    ``region`` filters on the derived ``xps_region`` (e.g. ``"Co2p"``).
    """
    wanted = (region or "").strip().lower() or None
    refs = [s for s in dataset.spectra if str(s.relative_path).lower().endswith(".vms")]
    paths = sorted({str(s.relative_path) for s in refs})
    con = with_connection()
    try:
        labels_by_path = fetch_upload_labels_for_paths(con, paths)
    finally:
        con.close()

    blocks_by_path: dict[str, list[Any]] = {}
    items: list[dict[str, Any]] = []
    for ref in refs:
        key = str(ref.relative_path)
        if key not in blocks_by_path:
            try:
                path: Path = _resolve_ref_path(ref)
                blocks_by_path[key] = read_vms_blocks(path)[1]
            except Exception as e:  # missing/unreadable file: report nothing for it
                logger.warning("casa-fits: cannot read %s: %s", key, e)
                blocks_by_path[key] = []
        blocks = blocks_by_path[key]
        idx = ref.record_index
        if idx is None or not (0 <= int(idx) < len(blocks)):
            continue
        block = blocks[int(idx)]
        comments = (block.extra_fields or {}).get("block_comments") or []
        fit = parse_casa_comments(comments, photon_energy_eV=block.excitation_energy_eV)
        if fit is None:
            continue
        xps_region = derive_xps_region(block.species, block.transition)
        if wanted and (xps_region or "").strip().lower() != wanted:
            continue
        flat = labels_for_spectrum(labels_by_path.get(key) or {}, record_index=int(idx))
        items.append(
            {
                "spectrum_id": ref.spectrum_id,
                "record_index": int(idx),
                "xps_region": xps_region,
                "experiment_id": block.experiment_id,
                "current_density_A_cm2": flat.get("current_density_A_cm2"),
                "excitation_energy_eV": block.excitation_energy_eV,
                "casa_region": fit["region"],
                "components": fit["components"],
            }
        )
    return {"be_convention": BE_CONVENTION, "n_spectra": len(items), "items": items}

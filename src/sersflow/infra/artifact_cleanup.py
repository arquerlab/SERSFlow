"""Removal of on-disk job artifacts when the database rows that own them are deleted."""

from __future__ import annotations

import logging
import os
import shutil
from pathlib import Path
from typing import Iterable

logger = logging.getLogger(__name__)


def _artifacts_root() -> Path:
    # Same rule as explore_store.artifacts_root (kept local: both stores import this module).
    return Path(os.environ.get("SERSFLOW_ARTIFACTS_DIR", os.path.join(os.getcwd(), ".sersflow_artifacts"))).resolve()


def remove_artifact_dirs(relative_dirs: Iterable[str]) -> int:
    """
    Delete artifact folders given relative to the artifacts root (e.g. ``fit_curve_jobs/<job_id>``).

    Best effort: a folder that is missing, outside the root, or locked is skipped (and logged), never raised.
    Returns how many folders were removed.
    """
    root = _artifacts_root()
    removed = 0
    for rel in dict.fromkeys(str(r) for r in relative_dirs if r):
        try:
            target = (root / rel).resolve()
            if target == root or root not in target.parents or not target.is_dir():
                continue
            shutil.rmtree(target)
            removed += 1
        except OSError as e:
            logger.warning("could not remove artifact folder %s: %s", rel, e)
    return removed

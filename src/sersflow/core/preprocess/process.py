from typing import List

import numpy as np

from sersflow.core.preprocess.baseline import correct_baseline


def process_baseline(
    intensities: List[np.ndarray],
    method: str = "derpsalsa",
    x: np.ndarray | None = None,
    **kwargs,
) -> tuple[list[np.ndarray], list[dict]]:
    """Apply baseline correction to a list of intensity arrays (legacy helper)."""
    corrected_int: list[np.ndarray] = []
    infos: list[dict] = []
    for array in intensities:
        corrected, info = correct_baseline(array, method=method, x=x, **kwargs)
        corrected_int.append(corrected)
        infos.append(info)
    return corrected_int, infos

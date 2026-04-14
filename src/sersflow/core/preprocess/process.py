from typing import List
import numpy as np
from sersflow.core.preprocess.baseline import correct_baseline


def process_baseline(int: List[np.ndarray], method: str = 'derpsalsa', **kwargs) -> tuple[np.ndarray, np.ndarray]:
    corrected_int = []
    params = []
    for array in int:
        array, params = correct_baseline(array, method=method, **kwargs)
        corrected_int.append(array)
        params.append(params)
    return corrected_int, params
import numpy as np

def normalize_spectrum(
    wn: np.ndarray,
    int: np.ndarray,
    method: str = 'max',
    baseline: np.ndarray | None = None,
    baseline_point: float | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    """
    Normalize a spectrum based on the intensity range.
    """
    if method == 'max':
        return wn, int / int.max()
    elif method == 'min':
        return wn, int / int.min()
    elif method == 'mean':
        return wn, int / int.mean()
    elif method == 'median':
        return wn, int / int.median()
    elif method == 'baseline':
        if baseline is None:
            raise ValueError("Baseline is required for baseline normalization")
        if baseline_point is None:
            raise ValueError("Baseline point is required for baseline normalization")
        baseline_index = np.argmin(np.abs(wn - baseline_point))
        return wn, int / baseline[baseline_index]
    else:
        raise ValueError(f"Invalid normalization method: {method}")
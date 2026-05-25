import numpy as np

def normalize_spectrum(
    wn: np.ndarray,
    int: np.ndarray,
    method: str = 'max',
    baseline: np.ndarray | None = None,
    baseline_point: float | None = None,
    point_x: float | None = None,
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
        return wn, int / np.median(int)
    elif method in ('vector', 'l2'):
        denom = float(np.linalg.norm(int))
        if denom == 0.0:
            denom = 1.0
        return wn, int / denom
    elif method in ('spectrum_point', 'baseline'):
        px = point_x if point_x is not None else baseline_point
        if px is None:
            raise ValueError("point_x is required for spectrum point normalization")
        idx = int(np.argmin(np.abs(wn - float(px))))
        denom = float(int[idx])
        if denom == 0.0:
            denom = 1.0
        return wn, int / denom
    elif method == 'baseline_point':
        if baseline is None:
            raise ValueError("Baseline is required for baseline point normalization")
        px = point_x if point_x is not None else baseline_point
        if px is None:
            raise ValueError("point_x is required for baseline point normalization")
        baseline_index = int(np.argmin(np.abs(wn - float(px))))
        denom = float(baseline[baseline_index])
        if denom == 0.0:
            denom = 1.0
        return wn, int / denom
    else:
        raise ValueError(f"Invalid normalization method: {method}")
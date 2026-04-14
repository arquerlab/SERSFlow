import numpy as np
from pybaselines import Baseline


def correct_baseline(int: np.ndarray, method: str = 'derpsalsa', **kwargs) -> tuple[np.ndarray, dict]:
    """
    Apply baseline correction to a spectrum.
    
    Args:
        int: Array of intensity values
        method: Baseline correction method. Options:
            'derpsalsa' - Derivative Peak-Screening Asymmetric Least Squares (default)
            'asls' - Asymmetric Least Squares
            'arpls' - Asymmetric Reweighted Penalized Least Squares
            'mor' - Morphological baseline
            'snip' - Statistics-sensitive Non-linear Iterative Peak-clipping
        **kwargs: Additional parameters for the specific method
            For 'derpsalsa': lam (smoothness), p (asymmetry), default: lam=10**5.5, p=0.001
            For 'asls': lam, p, default: lam=10**6, p=0.01
            For 'arpls': lam, default: lam=10**5
            For 'mor': half_window, default: half_window=30
            For 'snip': max_half_window, default: max_half_window=40
    
    Returns:
        corrected_int: Baseline-corrected intensity
        params: Dictionary with baseline and other parameters returned by the method
    """
    # New Baseline() per call: pybaselines stores input length on the instance; a shared
    # singleton breaks when spectrum length changes (e.g. crop reorder vs full length).
    fitter = Baseline()
    if method == 'derpsalsa':
        lam = kwargs.get('lam', 10**5.5)
        p = kwargs.get('p', 0.001)
        baseline, params = fitter.derpsalsa(int, lam=lam, p=p)
    elif method == 'asls':
        lam = kwargs.get('lam', 10**6)
        p = kwargs.get('p', 0.01)
        baseline, params = fitter.asls(int, lam=lam, p=p)
    elif method == 'arpls':
        lam = kwargs.get('lam', 10**5)
        baseline, params = fitter.arpls(int, lam=lam)
    elif method == 'mor':
        half_window = kwargs.get('half_window', 30)
        baseline, params = fitter.mor(int, half_window=half_window)
    elif method == 'mormol':
        half_window = kwargs.get('half_window', 30)
        baseline, params = fitter.mormol(int, half_window=half_window)
    elif method == 'snip':
        max_half_window = kwargs.get('max_half_window', 40)
        baseline, params = fitter.snip(int, max_half_window=max_half_window)
    else:
        raise ValueError(f"Unknown baseline correction method: {method}")
    
    corrected_int = int - baseline
    params['baseline'] = baseline
    
    return corrected_int, params
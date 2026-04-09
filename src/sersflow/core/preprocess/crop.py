import numpy as np

def crop_spectrum(
    wn: np.ndarray, 
    int: np.ndarray, 
    min_wn: float,
    max_wn: float,
) -> np.ndarray:
    """
    Crop a spectrum based on the wavenumber range.
    """
    mask = (wn >= min_wn) & (wn <= max_wn)
    return wn[mask], int[mask]
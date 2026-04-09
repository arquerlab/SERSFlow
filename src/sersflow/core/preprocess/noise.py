import numpy as np
from scipy.signal import savgol_filter


def apply_savitzky_golay(intensity: np.ndarray, window_length: int = 11, 
                         polyorder: int = 3, deriv: int = 0, 
                         delta: float = 1.0, mode: str = 'interp') -> np.ndarray:
    """
    Apply Savitzky-Golay filter to smooth a spectrum.
    
    Args:
        intensity: 1D array of intensity values
        window_length: The length of the filter window (must be odd and positive).
                      Should be less than or equal to the size of the input array.
                      Typical values: 5, 7, 9, 11, 13, 15, 21, 25, 31
        polyorder: The order of the polynomial used to fit the samples.
                   Must be less than window_length. Typical values: 2, 3, 4, 5
        deriv: The order of the derivative to compute (default: 0 = smoothing only).
               If deriv > 0, returns the derivative instead of smoothed values.
        delta: The spacing of the samples to which the filter will be applied.
               This is only used if deriv > 0. Default: 1.0
        mode: Must be 'mirror', 'constant', 'nearest', 'interp', or 'wrap'.
              Determines how the input array is extended when the filter overlaps a border.
              Default: 'interp' (interpolation at edges)
    
    Returns:
        filtered_intensity: Smoothed intensity array (or derivative if deriv > 0)
    
    Notes:
        - window_length must be odd
        - polyorder must be < window_length
        - For Raman spectra, typical values are window_length=11-25, polyorder=2-4
        - Larger window_length = more smoothing but may blur sharp peaks
        - Higher polyorder = preserves more features but less noise reduction
    """
    n = len(intensity)
    
    # Validate parameters
    if window_length < 3:
        raise ValueError(f"window_length must be >= 3, got {window_length}")
    if window_length > n:
        raise ValueError(f"window_length ({window_length}) must be <= array length ({n})")
    if window_length % 2 == 0:
        raise ValueError(f"window_length must be odd, got {window_length}")
    if polyorder >= window_length:
        raise ValueError(f"polyorder ({polyorder}) must be < window_length ({window_length})")
    if polyorder < 0:
        raise ValueError(f"polyorder must be >= 0, got {polyorder}")
    
    # Apply Savitzky-Golay filter
    filtered = savgol_filter(intensity, window_length=window_length, 
                            polyorder=polyorder, deriv=deriv, 
                            delta=delta, mode=mode)
    
    return filtered
import numpy as np
from scipy.signal import medfilt
from scipy.ndimage import median_filter


def detect_cosmic_rays_zscore(intensity, threshold=5.0, window=5):
    """
    Detect cosmic rays using modified Z-score method.
    
    This method calculates the modified Z-score (based on median absolute deviation)
    for each point relative to its local neighborhood. Points with Z-score > threshold
    are flagged as cosmic rays.
    
    Args:
        intensity: 1D array of intensity values
        threshold: Modified Z-score threshold (default: 5.0, higher = less sensitive)
        window: Window size for local statistics (default: 5)
        
    Returns:
        mask: Boolean array where True indicates a cosmic ray spike
    """
    n = len(intensity)
    mask = np.zeros(n, dtype=bool)
    
    # Use median filter to estimate the true signal without spikes
    filtered = medfilt(intensity, kernel_size=window)
    
    # Calculate residuals
    residuals = intensity - filtered
    
    # Modified Z-score using Median Absolute Deviation (MAD)
    # MAD is robust to outliers unlike standard deviation
    median_residual = np.median(residuals)
    mad = np.median(np.abs(residuals - median_residual))
    
    if mad == 0:
        # If MAD is zero, use a fallback method
        # This can happen if the spectrum is very flat
        std = np.std(residuals)
        if std > 0:
            z_scores = np.abs(residuals - median_residual) / std
        else:
            return mask  # No spikes detected
    else:
        # Modified Z-score = 0.6745 * (x - median) / MAD
        # The constant 0.6745 makes MAD consistent with std for normal distribution
        z_scores = 0.6745 * np.abs(residuals - median_residual) / mad
    
    # Flag points exceeding threshold
    mask = z_scores > threshold
    
    return mask


def detect_cosmic_rays_derivative(intensity, threshold=3.0, window=3):
    """
    Detect cosmic rays using first derivative method.
    
    Cosmic rays cause sharp changes in the derivative. This method detects
    points where the derivative changes abruptly.
    
    Args:
        intensity: 1D array of intensity values
        threshold: Threshold in units of MAD (default: 3.0)
        window: Window size for smoothing derivative (default: 3)
        
    Returns:
        mask: Boolean array where True indicates a cosmic ray spike
    """
    n = len(intensity)
    mask = np.zeros(n, dtype=bool)
    
    # Calculate first derivative
    derivative = np.gradient(intensity)
    
    # Smooth derivative
    if window > 1:
        derivative = medfilt(derivative, kernel_size=window)
    
    # Calculate second derivative (rate of change of slope)
    second_derivative = np.gradient(derivative)
    
    # Use MAD for robust threshold
    median_val = np.median(np.abs(second_derivative))
    mad = np.median(np.abs(second_derivative - median_val))
    
    if mad == 0:
        std = np.std(second_derivative)
        if std > 0:
            threshold_val = median_val + threshold * std
        else:
            return mask
    else:
        threshold_val = median_val + threshold * mad / 0.6745
    
    # Flag points with extreme second derivative
    mask = np.abs(second_derivative) > threshold_val
    
    return mask


def remove_cosmic_rays(intensity, method='zscore', threshold=5.0, window=5, 
                       interpolation='median', max_width=10, min_intensity_ratio=2.0,
                       n_iterations=3):
    """
    Detect and remove cosmic rays from a Raman spectrum.
    
    Applies the cosmic ray removal iteratively (default: 3 times) to catch
    spikes that might be missed on the first pass or artifacts from previous corrections.
    
    Args:
        intensity: 1D array of intensity values
        method: Detection method ('zscore' or 'derivative')
        threshold: Detection threshold (higher = less sensitive)
        window: Window size for detection algorithm
        interpolation: Method to replace spikes ('median', 'linear', 'cubic')
        max_width: Maximum width of spike to remove in data points (default: 10)
        min_intensity_ratio: Minimum ratio of spike intensity to local median (default: 2.0)
                            Helps filter out noise by requiring spikes to be significantly higher
        n_iterations: Number of iterations to apply (default: 3)
        
    Returns:
        corrected: Intensity array with cosmic rays removed
        mask: Boolean array indicating which points were cosmic rays (combined from all iterations)
        n_spikes: Total number of cosmic ray events detected across all iterations
    """
    n = len(intensity)
    corrected = intensity.copy()
    combined_mask = np.zeros(n, dtype=bool)
    total_spikes = 0
    
    # Apply iteratively
    for iteration in range(n_iterations):
        # Detect cosmic rays on current corrected spectrum
        if method == 'zscore':
            mask = detect_cosmic_rays_zscore(corrected, threshold, window)
        elif method == 'derivative':
            mask = detect_cosmic_rays_derivative(corrected, threshold, window)
        else:
            raise ValueError(f"Unknown method: {method}. Use 'zscore' or 'derivative'")
        
        # Group consecutive spike points and filter by width and intensity
        # This prevents removing broad real peaks and filters out noise
        filtered_mask = np.zeros_like(mask)
        i = 0
        iteration_spikes = 0
        
        # Calculate local median for intensity filtering
        local_median = medfilt(corrected, kernel_size=window)
        
        while i < n:
            if mask[i]:
                # Find the extent of this spike
                j = i
                while j < n and mask[j]:
                    j += 1
                
                spike_width = j - i
                spike_indices = np.arange(i, j)
                
                # Get the maximum intensity in this spike region
                spike_max = np.max(corrected[spike_indices])
                
                # Get the local median around this spike (excluding the spike itself)
                # Use points before and after the spike
                context_before = max(0, i - window)
                context_after = min(n, j + window)
                
                # Create context mask (exclude the spike itself)
                context_indices = list(range(context_before, i)) + list(range(j, context_after))
                if len(context_indices) > 0:
                    local_background = np.median(corrected[context_indices])
                else:
                    local_background = np.median(corrected)
                
                # Check if spike meets criteria:
                # 1. Not too wide (prevents removing real peaks)
                # 2. Significantly higher than local background (filters out noise)
                is_narrow_enough = spike_width <= max_width
                is_significant = (local_background > 0 and 
                                spike_max / local_background >= min_intensity_ratio)
                
                if is_narrow_enough and is_significant:
                    filtered_mask[i:j] = True
                    iteration_spikes += 1
                
                i = j
            else:
                i += 1
        
        # Update combined mask
        combined_mask = combined_mask | filtered_mask
        total_spikes += iteration_spikes
        
        # Replace cosmic ray points with interpolated values
        if np.any(filtered_mask):
            # Process each spike region individually for better interpolation
            spike_regions = []
            i = 0
            while i < n:
                if filtered_mask[i]:
                    j = i
                    while j < n and filtered_mask[j]:
                        j += 1
                    spike_regions.append((i, j))
                    i = j
                else:
                    i += 1
            
            # Interpolate each spike region
            for spike_start, spike_end in spike_regions:
                # Get context points around the spike for better interpolation
                context_size = max(window * 2, 10)  # Use more points for stable interpolation
                
                # Define range for interpolation (exclude spike itself)
                context_before_start = max(0, spike_start - context_size)
                context_after_end = min(n, spike_end + context_size)
                
                # Get good points (not part of any spike)
                context_indices = []
                context_values = []
                
                # Add points before spike
                for idx in range(context_before_start, spike_start):
                    if not combined_mask[idx]:  # Use combined_mask to avoid using previously corrected spikes
                        context_indices.append(idx)
                        context_values.append(corrected[idx])
                
                # Add points after spike
                for idx in range(spike_end, context_after_end):
                    if not combined_mask[idx]:
                        context_indices.append(idx)
                        context_values.append(corrected[idx])
                
                if len(context_indices) >= 2:
                    # Interpolate the spike region
                    spike_indices = np.arange(spike_start, spike_end)
                    
                    if interpolation == 'median':
                        # Use median of surrounding points
                        corrected[spike_start:spike_end] = np.median(context_values)
                    
                    elif interpolation in ['linear', 'cubic']:
                        from scipy.interpolate import interp1d
                        # Use interpolation from surrounding good points
                        kind = 'cubic' if len(context_indices) > 3 and interpolation == 'cubic' else 'linear'
                        try:
                            interp_func = interp1d(context_indices, context_values, 
                                                  kind=kind, fill_value='extrapolate')
                            corrected[spike_start:spike_end] = interp_func(spike_indices)
                        except:
                            # Fallback to linear if cubic fails
                            interp_func = interp1d(context_indices, context_values, 
                                                  kind='linear', fill_value='extrapolate')
                            corrected[spike_start:spike_end] = interp_func(spike_indices)
                    else:
                        raise ValueError(f"Unknown interpolation method: {interpolation}")
                elif len(context_indices) == 1:
                    # Only one neighbor - use that value
                    corrected[spike_start:spike_end] = context_values[0]
                else:
                    # No good neighbors - use median filter as fallback
                    corrected[spike_start:spike_end] = medfilt(corrected, kernel_size=window)[spike_start:spike_end]
    
    return corrected, combined_mask, total_spikes


def remove_cosmic_rays_batch(spectra_list, method='zscore', threshold=5.0, window=5,
                              interpolation='median', max_width=10, min_intensity_ratio=2.0, 
                              n_iterations=3, verbose=True):
    """
    Remove cosmic rays from multiple spectra.
    
    Args:
        spectra_list: List of 1D intensity arrays
        method: Detection method ('zscore' or 'derivative')
        threshold: Detection threshold
        window: Window size for detection
        interpolation: Method to replace spikes
        max_width: Maximum spike width to remove
        min_intensity_ratio: Minimum intensity ratio for spike detection
        n_iterations: Number of iterations to apply (default: 3)
        verbose: Print statistics
        
    Returns:
        corrected_list: List of corrected intensity arrays
        stats: Dictionary with statistics
    """
    corrected_list = []
    total_spikes = 0
    spectra_with_spikes = 0
    
    for i, intensity in enumerate(spectra_list):
        corrected, mask, n_spikes = remove_cosmic_rays(
            intensity, method=method, threshold=threshold, window=window,
            interpolation=interpolation, max_width=max_width, min_intensity_ratio=min_intensity_ratio,
            n_iterations=n_iterations
        )
        
        corrected_list.append(corrected)
        total_spikes += n_spikes
        
        if n_spikes > 0:
            spectra_with_spikes += 1
    
    stats = {
        'total_spectra': len(spectra_list),
        'spectra_with_spikes': spectra_with_spikes,
        'total_spikes': total_spikes,
        'avg_spikes_per_spectrum': total_spikes / len(spectra_list) if spectra_list else 0
    }
    
    if verbose:
        print(f"\nCosmic Ray Removal Statistics:")
        print(f"  Method: {method}, Threshold: {threshold}, Window: {window}")
        print(f"  Total spectra processed: {stats['total_spectra']}")
        print(f"  Spectra with cosmic rays: {stats['spectra_with_spikes']}")
        print(f"  Total cosmic ray events removed: {stats['total_spikes']}")
        print(f"  Average spikes per spectrum: {stats['avg_spikes_per_spectrum']:.2f}")
    
    return corrected_list, stats
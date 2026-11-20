# Clustering / Segmentation along an ordered axis (depth alignment, contiguous segmentation, k-means)

Splits spectra along depth (or time, distance) from fitted features, **without PCA**. UI: Analyze > *Clustering / Segmentation*.
REST `POST /explore/segments`, `POST /explore/depth-align`; MCP `post_explore_depth_segments`, `post_explore_depth_align`.
Code: `core/multivariate/depth.py` (pure numpy), wrappers in `api/services/explore_stats.py`
(`compute_depth_alignment`, `compute_segments`, `run_depth_*`), tests `tests/test_depth_segments.py`.

## Features
Per column: upper winsorise (default 99th pct), robust scale (median/IQR), clip to +-5 IQR, z-score. This keeps isolated
failed-fit spikes from dominating distances. Rows with a missing z or feature are skipped and counted (`n_dropped_rows`).

## Contiguous segmentation (`method="contiguous"`)
z is binned (`bin_width`, default 5; 0 = every distinct z), bins carry weight = number of spectra, and the exact dynamic
programme (O(K n^2)) returns the K consecutive zones with minimum weighted within-segment SSE, for K = 1..`k_max`
(cost curve; there is not always a sharp elbow). Boundary = midpoint between neighbouring bin centres. With
`per_position_check` the split is repeated independently at every map position: tight spread = well-defined boundary.

## k-means (`method="kmeans"`)
Plain k-means (>= 20 restarts) on the same features, clusters numbered by median z. Reports silhouette versus K and
`contiguity` (fraction of z-sorted neighbours sharing a label). Not contiguous in z by construction.

## z alignment (optional, `align`)
Per map position the half-height crossing ("edge") of one feature (e.g. the membrane amplitude) along z is located:
3-point smoothing, plateau = mean of the 6 largest values with z <= `plateau_z_max`, low = minimum over `low_z_range`,
half = (plateau+low)/2, first downward crossing for z >= `search_z_min`. Shift = edge - edge(reference); aligned
z = z - shift. The **reference position keeps its z** (default: position closest to the map centre, i.e. the focus).
Defaults are generic (plateau = lowest third of z, low = everything above); set the windows for your sample.
`mode="argmax"` is available but noisy. Positions without a detectable edge are left unshifted and counted.

## Reference check (PH_volume_test, run `arun_22399f02591345109ece8092d77be1fb`)
Windows plateau z <= -40, low -30..60, search from -60, reference (0,0): edge -21.295, shifts -5.25..+8.39;
K=4 boundaries -62.5 / -27.5 / +82.5 (segments 390/343/1078/1129); k-means k=4 sizes 661/866/1195/218.
Asserted in `test_real_ph_volume_reference_numbers` (skipped when the export is absent).

## Zone names
Names are free text in the UI (and `zone_names` in the request, bottom to top); defaults are "Segment N".

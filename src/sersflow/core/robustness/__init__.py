"""Robustness study: multi-factor analyst-choice analysis of a fit (factorial design + ANOVA).

Modules
-------
* ``patches``   - pure edits of a pipeline step (fit components, windows, upstream step params) that a factor level applies.
* ``design``    - factors, levels, full-factorial cells, caps, cost estimate, design hash.
* ``responses`` - response definitions evaluated from a fit (area %, positions, widths, ratios, group fractions).
* ``cell_fit``  - fit one spectrum under one design cell: multi-start, diagnostics, common-window score.
* ``anova``     - exact variance decomposition of a balanced factorial (main effects and interactions).
* ``study``     - aggregation: ANOVA per spectrum, trend preservation, noise comparison, filters.
* ``presets``   - ready-made factor templates (XPS Co 2p, SERS baseline); data, not engine code.
"""

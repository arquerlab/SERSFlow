from __future__ import annotations

import numpy as np

from sersflow.api.services.fit_curve_plot import render_fit_residual_png


def test_render_fit_residual_png_nonempty() -> None:
    x = np.linspace(0, 10, 40).tolist()
    y = [float(v) for v in np.sin(x)]
    y_hat = [float(v) * 0.9 for v in y]
    residual = [a - b for a, b in zip(y, y_hat)]
    png = render_fit_residual_png(
        x=x,
        y=y,
        y_hat=y_hat,
        residual=residual,
        components=[
            {"component_id": "bg", "component_type": "polynomial_background", "y_hat": [0.1] * len(x)},
            {"component_id": "pk", "component_type": "gaussian", "y_hat": [0.5] * len(x)},
        ],
        title="spec1",
        diagnostics={"rmse": 0.1, "r2": 0.9, "bic": 12.0},
        include_components=True,
    )
    assert isinstance(png, (bytes, bytearray))
    assert len(png) > 100

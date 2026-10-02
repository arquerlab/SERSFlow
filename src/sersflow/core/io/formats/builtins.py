"""Import side-effect: register all built-in formats."""

from __future__ import annotations

from sersflow.core.io.formats import ascii_xy as _ascii_xy  # noqa: F401
from sersflow.core.io.formats import nexus_xps as _nexus_xps  # noqa: F401
from sersflow.core.io.formats import renishaw_wdf as _renishaw_wdf  # noqa: F401
from sersflow.core.io.formats import vamas as _vamas  # noqa: F401

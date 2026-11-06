"""
CasaXPS line-shape strings <-> SpecFlow line-shape kinds (L1; shared with the recipes and, later, IO3).

``parse_casaxps_lineshape("LA(1.1,2.2,10)")`` -> ``{"kind": "la", "params": {"alpha": 1.1, "beta": 2.2, "m": 10}}``.
The params use the recipe ``lineshape.params`` convention (CasaXPS-level numbers; e.g. LA ``m`` is the Gaussian
index, converted to an eV width by the recipe apply step, not here). ``format_casaxps_lineshape`` is the inverse, so
parse/format round-trips every string used in the recipes.

Supported: GL(m), SGL(m), GL(m,n) (product GL convolved with a Gaussian, ``n`` = Gaussian width as stored in
recipes), LA(a,b[,m]), LF(a,b,w,m), A(a,n,m)GL(m) / A(a,n,m)SGL(m), DS(alpha[,n]), and the SB(0) prefix (Shirley
profile component). Not supported (not defined in the project literature): T(k), ST(...), PHI(...), TP(...).
"""

from __future__ import annotations

import re
from typing import Any

_NUM = r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?"


class LineshapeParseError(ValueError):
    pass


def _nums(s: str) -> list[float]:
    parts = [p.strip() for p in s.split(",")]
    out: list[float] = []
    for p in parts:
        if not re.fullmatch(_NUM, p):
            raise LineshapeParseError(f"not a number: {p!r}")
        out.append(float(p))
    return out


def _clean(v: float) -> float | int:
    return int(v) if float(v).is_integer() else float(v)


def parse_casaxps_lineshape(text: str) -> dict[str, Any]:
    """Parse one CasaXPS line-shape string; raises LineshapeParseError for unsupported or malformed strings."""
    s = re.sub(r"\s+", "", str(text or ""))
    if not s:
        raise LineshapeParseError("empty line shape")
    prefixes: list[str] = []
    m = re.match(r"^SB\((" + _NUM + r")\)", s, re.IGNORECASE)
    if m:
        prefixes.append(f"SB({m.group(1)})")
        s = s[m.end() :]
    for bad in ("ST(", "T(", "PHI(", "TP("):
        if s.upper().startswith(bad):
            raise LineshapeParseError(f"{bad[:-1]} line shapes/modifiers are not supported yet")

    asym = re.match(r"^A\(([^()]*)\)(S?GL)\(([^()]*)\)$", s, re.IGNORECASE)
    if asym:
        a, n, m_asym = _nums(asym.group(1))
        (mm,) = _nums(asym.group(3))
        kind = "a_sgl" if asym.group(2).upper() == "SGL" else "a_gl"
        out = {"kind": kind, "params": {"a": _clean(a), "n": _clean(n), "m_asym": _clean(m_asym), "m": _clean(mm)}}
        return _with_prefixes(out, prefixes)

    fm = re.match(r"^([A-Za-z]+)\(([^()]*)\)$", s)
    if not fm:
        raise LineshapeParseError(f"cannot parse line shape {text!r}")
    name, args = fm.group(1).upper(), _nums(fm.group(2))
    if name == "GL" and len(args) == 1:
        out = {"kind": "gl", "params": {"m": _clean(args[0])}}
    elif name == "GL" and len(args) == 2:
        out = {"kind": "gl_gauss", "params": {"m": _clean(args[0]), "n": _clean(args[1])}}
    elif name == "SGL" and len(args) == 1:
        out = {"kind": "sgl", "params": {"m": _clean(args[0])}}
    elif name == "LA" and len(args) in (2, 3):
        p = {"alpha": _clean(args[0]), "beta": _clean(args[1])}
        if len(args) == 3:
            p["m"] = _clean(args[2])
        out = {"kind": "la", "params": p}
    elif name == "LF" and len(args) == 4:
        out = {"kind": "lf", "params": {"alpha": _clean(args[0]), "beta": _clean(args[1]), "w": _clean(args[2]), "m": _clean(args[3])}}
    elif name == "DS" and len(args) in (1, 2):
        p = {"alpha": _clean(args[0])}
        if len(args) == 2:
            p["n"] = _clean(args[1])
        out = {"kind": "ds", "params": p}
    else:
        raise LineshapeParseError(f"unsupported line shape {text!r}")
    return _with_prefixes(out, prefixes)


def _with_prefixes(out: dict[str, Any], prefixes: list[str]) -> dict[str, Any]:
    if prefixes:
        out["prefixes"] = prefixes
        out["shirley_profile"] = any(p.upper().startswith("SB(") for p in prefixes)
    return out


def _fmt(v: Any) -> str:
    f = float(v)
    return str(int(f)) if f.is_integer() else f"{f:g}"


def format_casaxps_lineshape(kind: str, params: dict[str, Any], *, prefixes: list[str] | None = None, spaced: bool = False) -> str:
    """Inverse of ``parse_casaxps_lineshape`` (``spaced`` puts ', ' between LF arguments as in some recipes)."""
    k = str(kind or "").strip().lower()
    p = params or {}
    sep = ", " if spaced else ","
    if k == "gl":
        body = f"GL({_fmt(p['m'])})"
    elif k == "gl_gauss":
        body = f"GL({_fmt(p['m'])},{_fmt(p['n'])})"
    elif k == "sgl":
        body = f"SGL({_fmt(p['m'])})"
    elif k == "la":
        args = [p["alpha"], p["beta"]] + ([p["m"]] if "m" in p else [])
        body = "LA(" + sep.join(_fmt(a) for a in args) + ")"
    elif k == "lf":
        body = "LF(" + sep.join(_fmt(p[a]) for a in ("alpha", "beta", "w", "m")) + ")"
    elif k in ("a_gl", "a_sgl"):
        form = "SGL" if k == "a_sgl" else "GL"
        body = f"A({_fmt(p['a'])},{_fmt(p['n'])},{_fmt(p['m_asym'])}){form}({_fmt(p['m'])})"
    elif k == "ds":
        body = "DS(" + ",".join(_fmt(p[a]) for a in ("alpha", "n") if a in p) + ")"
    else:
        raise LineshapeParseError(f"no CasaXPS notation for kind {kind!r}")
    return "".join(prefixes or []) + body

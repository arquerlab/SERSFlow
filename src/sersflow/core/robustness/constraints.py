"""Exclusion rules of a robustness design: drop implausible cells BEFORE anything is fitted.

A rule removes the cells that break it from the full factorial, so the fits are spent on the reasonable region only.
Two kinds, both plain JSON (reproducible from the study spec):

* ``{"exclude_when": {"<factor>": ["<level>", ...], ...}}`` removes a cell when, for EVERY listed factor, the cell's
  level is one of the listed levels (a combination of choices nobody would make).
* ``{"require": "<expression>"}`` keeps a cell only when the expression is true. The expression is evaluated on the
  numbers the cell's levels carry in their ``values`` ({"name": "x", "values": {"fwhm_co3": 2.6}, "patches": [...]}),
  e.g. ``"fwhm_co3 * ratio + extra <= 3.2 and fwhm_co3 >= 1.8"``.

Expressions are a whitelisted subset of Python (numbers, value names, + - * /, comparisons, and/or/not, abs/min/max);
no attribute access, indexing or other calls. Comparisons carry a 1e-9 tolerance so that ``3.0 * 1.0 <= 3.0`` holds.
An optional ``name`` labels the rule in the excluded-by-rule counts.
"""

from __future__ import annotations

import ast
import keyword
import math
from dataclasses import dataclass
from typing import Any, Callable

EPS = 1e-9
MAX_RULES = 50
_FUNCS: dict[str, Callable[..., float]] = {"abs": abs, "min": min, "max": max}
_ALLOWED_NODES = (
    ast.Expression, ast.BoolOp, ast.And, ast.Or, ast.UnaryOp, ast.Not, ast.USub, ast.UAdd, ast.BinOp, ast.Add,
    ast.Sub, ast.Mult, ast.Div, ast.Compare, ast.Lt, ast.LtE, ast.Gt, ast.GtE, ast.Eq, ast.NotEq, ast.Constant,
    ast.Name, ast.Load, ast.Call,
)


class ConstraintError(ValueError):
    pass


def valid_value_name(name: str) -> bool:
    return name.isidentifier() and not keyword.iskeyword(name) and name not in _FUNCS and name not in ("True", "False")


@dataclass(frozen=True)
class Rule:
    name: str
    excludes: Callable[[tuple[int, ...]], bool]


def _num(v: Any, what: str) -> float:
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(float(v)):
        raise ConstraintError(f"{what} must be a finite number")
    return float(v)


def _compare(op: ast.cmpop, a: Any, b: Any) -> bool:
    if isinstance(op, ast.Lt):
        return a < b - EPS
    if isinstance(op, ast.LtE):
        return a <= b + EPS
    if isinstance(op, ast.Gt):
        return a > b + EPS
    if isinstance(op, ast.GtE):
        return a >= b - EPS
    if isinstance(op, ast.Eq):
        return abs(a - b) <= EPS
    return abs(a - b) > EPS


def _ev(n: ast.AST, env: dict[str, float]) -> Any:
    if isinstance(n, ast.Expression):
        return _ev(n.body, env)
    if isinstance(n, ast.Constant):
        return n.value
    if isinstance(n, ast.Name):
        return env[n.id]
    if isinstance(n, ast.UnaryOp):
        v = _ev(n.operand, env)
        if isinstance(n.op, ast.Not):
            return not v
        return -v if isinstance(n.op, ast.USub) else +v
    if isinstance(n, ast.BinOp):
        a, b = _ev(n.left, env), _ev(n.right, env)
        if isinstance(n.op, ast.Add):
            return a + b
        if isinstance(n.op, ast.Sub):
            return a - b
        if isinstance(n.op, ast.Mult):
            return a * b
        if b == 0:
            raise ConstraintError("division by zero in a constraint expression")
        return a / b
    if isinstance(n, ast.BoolOp):
        if isinstance(n.op, ast.And):
            return all(_ev(v, env) for v in n.values)
        return any(_ev(v, env) for v in n.values)
    if isinstance(n, ast.Compare):
        left = _ev(n.left, env)
        for op, comp in zip(n.ops, n.comparators):
            right = _ev(comp, env)
            if not _compare(op, left, right):
                return False
            left = right
        return True
    if isinstance(n, ast.Call):
        return _FUNCS[n.func.id](*[_ev(a, env) for a in n.args])  # type: ignore[union-attr]
    raise ConstraintError(f"unsupported expression element {type(n).__name__}")


def _compile_expr(src: str, known: set[str]) -> ast.Expression:
    try:
        tree = ast.parse(src.strip(), mode="eval")
    except SyntaxError as e:
        raise ConstraintError(f"constraint expression {src!r} is not valid: {e.msg}") from e
    for node in ast.walk(tree):
        if not isinstance(node, _ALLOWED_NODES):
            raise ConstraintError(f"constraint expression {src!r}: {type(node).__name__} is not allowed")
        if isinstance(node, ast.Constant) and (isinstance(node.value, bool) or not isinstance(node.value, (int, float))):
            raise ConstraintError(f"constraint expression {src!r}: only numbers are allowed as constants")
        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name) or node.func.id not in _FUNCS or node.keywords:
                raise ConstraintError(f"constraint expression {src!r}: only abs / min / max may be called")
        if isinstance(node, ast.Name) and node.id not in known and node.id not in _FUNCS:
            raise ConstraintError(
                f"constraint expression {src!r}: unknown name {node.id!r} "
                f"(names come from level 'values': {sorted(known) or 'none defined'})"
            )
    return tree


def parse_constraints(
    raw: Any,
    factor_names: list[str],
    level_names: list[list[str]],
    level_values: list[list[dict[str, float]]],
) -> list[Rule]:
    """Compile the rules; ``level_values[f][l]`` are the numbers carried by level ``l`` of factor ``f``."""
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ConstraintError("constraints must be a list of rules")
    if len(raw) > MAX_RULES:
        raise ConstraintError(f"too many constraints ({len(raw)} > {MAX_RULES})")
    known = {k for fv in level_values for lv in fv for k in lv}
    rules: list[Rule] = []
    seen: set[str] = set()
    for i, item in enumerate(raw):
        if not isinstance(item, dict):
            raise ConstraintError(f"constraint {i + 1}: must be an object")
        kinds = [k for k in ("exclude_when", "require") if k in item]
        if len(kinds) != 1:
            raise ConstraintError(f"constraint {i + 1}: give exactly one of 'exclude_when' or 'require'")
        name = str(item.get("name") or f"rule {i + 1}").strip()
        if name in seen:
            raise ConstraintError(f"duplicate constraint name {name!r}")
        seen.add(name)
        if kinds[0] == "exclude_when":
            spec = item["exclude_when"]
            if not isinstance(spec, dict) or not spec:
                raise ConstraintError(f"constraint {name!r}: exclude_when needs {{factor: [levels]}}")
            allowed: dict[int, set[int]] = {}
            for fname, lvls in spec.items():
                if fname not in factor_names:
                    raise ConstraintError(f"constraint {name!r}: unknown factor {fname!r}")
                fi = factor_names.index(fname)
                wanted = [lvls] if isinstance(lvls, str) else lvls
                if not isinstance(wanted, list) or not wanted:
                    raise ConstraintError(f"constraint {name!r}: factor {fname!r} needs a list of level names")
                sel: set[int] = set()
                for ln in wanted:
                    if ln not in level_names[fi]:
                        raise ConstraintError(f"constraint {name!r}: factor {fname!r} has no level {ln!r}")
                    sel.add(level_names[fi].index(ln))
                allowed[fi] = sel

            def _excl(idx: tuple[int, ...], _a: dict[int, set[int]] = allowed) -> bool:
                return all(idx[fi] in sel for fi, sel in _a.items())

            rules.append(Rule(name=name, excludes=_excl))
        else:
            src = item["require"]
            if not isinstance(src, str) or not src.strip():
                raise ConstraintError(f"constraint {name!r}: require needs an expression string")
            tree = _compile_expr(src, known)

            def _req(idx: tuple[int, ...], _t: ast.Expression = tree, _s: str = src, _n: str = name) -> bool:
                env: dict[str, float] = {}
                for fi, li in enumerate(idx):
                    env.update(level_values[fi][li])
                try:
                    ok = _ev(_t, env)
                except KeyError as e:
                    raise ConstraintError(f"constraint {_n!r}: value {e.args[0]!r} is not defined for this cell") from e
                return not bool(ok)

            rules.append(Rule(name=name, excludes=_req))
    return rules


def first_hit(rules: list[Rule], idx: tuple[int, ...]) -> str | None:
    """Name of the first rule that excludes the cell, else None."""
    for r in rules:
        if r.excludes(idx):
            return r.name
    return None

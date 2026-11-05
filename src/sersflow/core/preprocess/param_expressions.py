"""
General relational constraints between fit parameters (F4).

A fitting step's ``param_links`` define dependent parameters. Besides the one-to-one modes (equal, scale, offset,
area_ratio) a link may use ``mode: "expr"`` with a free expression over other components' parameters::

    {"source_component_id": "C", "source_key": "pos", "mode": "expr",
     "expr": "{A.pos} + 0.5*({B.pos} - {A.pos})"}

* References are ``{<component id>.<parameter key>}``; the id is everything before the LAST dot, so ids such as
  ``Co3+`` or ``2p3/2_sat`` work. ``{A.area}`` is the peak AREA (amp x area-per-height of its line shape).
* ``"defines": "area"`` on an ``amp`` link makes the expression the dependent peak's AREA (CasaXPS constraints are
  on area); the amplitude is solved through the line-shape factor.
* Allowed: numbers, + - * / **, unary +/-, parentheses and abs, sqrt, exp, log, min, max. Nothing else is evaluated
  (the expression is parsed with ``ast`` against a whitelist before it is handed to lmfit).
* ``validate_param_links`` rejects unknown ids/keys, a parameter defined twice, self references and cycles (the error
  names the loop, e.g. ``C.pos -> B.pos -> C.pos``).
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from typing import Any, Callable

REF_RE = re.compile(r"\{([^{}]+)\.([A-Za-z_][A-Za-z0-9_]*)\}")
SAFE_FUNCTIONS = frozenset({"abs", "sqrt", "exp", "log", "min", "max"})
LINK_MODES = frozenset({"equal", "scale", "offset", "area_ratio", "expr"})
AREA_KEY = "area"


@dataclass(frozen=True)
class ParsedExpression:
    refs: list[tuple[str, str]]
    """(component id, key) in order of first appearance."""
    template: str
    """Expression with each reference replaced by ``__r<i>`` (index into ``refs``)."""


def expression_refs(expr: str) -> list[tuple[str, str]]:
    """``{A.pos}`` references of an expression (unique, in order)."""
    out: list[tuple[str, str]] = []
    for m in REF_RE.finditer(str(expr or "")):
        ref = (m.group(1).strip(), m.group(2))
        if ref not in out:
            out.append(ref)
    return out


def parse_expression(expr: str) -> ParsedExpression:
    """Parse and whitelist-check an expression; raises ValueError with a readable message."""
    text = str(expr or "").strip()
    if not text:
        raise ValueError("expression is empty")
    refs = expression_refs(text)

    def repl(m: re.Match[str]) -> str:
        return f"__r{refs.index((m.group(1).strip(), m.group(2)))}"

    template = REF_RE.sub(repl, text)
    if "{" in template or "}" in template:
        raise ValueError(f"malformed reference in {text!r}; write references as {{peak.param}}, e.g. {{A.pos}}")
    try:
        tree = ast.parse(template, mode="eval")
    except SyntaxError as e:
        raise ValueError(f"syntax error in {text!r}: {e.msg}") from e
    _check_node(tree, text)
    return ParsedExpression(refs=refs, template=template)


def _check_node(node: ast.AST, text: str) -> None:
    if isinstance(node, ast.Expression):
        _check_node(node.body, text)
    elif isinstance(node, ast.Constant):
        if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
            raise ValueError(f"only numbers are allowed as constants in {text!r}")
    elif isinstance(node, ast.Name):
        if not re.fullmatch(r"__r\d+", node.id):
            raise ValueError(
                f"unknown name {node.id!r} in {text!r}; reference parameters as {{peak.param}}, e.g. {{A.pos}}"
            )
    elif isinstance(node, ast.UnaryOp):
        if not isinstance(node.op, (ast.UAdd, ast.USub)):
            raise ValueError(f"operator not allowed in {text!r}")
        _check_node(node.operand, text)
    elif isinstance(node, ast.BinOp):
        if not isinstance(node.op, (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Pow)):
            raise ValueError(f"operator not allowed in {text!r} (use + - * / **)")
        _check_node(node.left, text)
        _check_node(node.right, text)
    elif isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name) or node.func.id not in SAFE_FUNCTIONS or node.keywords:
            allowed = ", ".join(sorted(SAFE_FUNCTIONS))
            raise ValueError(f"function not allowed in {text!r} (allowed: {allowed})")
        if not node.args:
            raise ValueError(f"{node.func.id}() needs an argument in {text!r}")
        for a in node.args:
            _check_node(a, text)
    else:
        raise ValueError(f"construct not allowed in {text!r}: {type(node).__name__}")


def render_expression(parsed: ParsedExpression, name_for_ref: Callable[[str, str], str]) -> str:
    """Replace the ``__r<i>`` placeholders by ``name_for_ref(component id, key)`` (an lmfit sub-expression)."""

    def repl(m: re.Match[str]) -> str:
        cid, key = parsed.refs[int(m.group(1))]
        return f"({name_for_ref(cid, key)})"

    return re.sub(r"__r(\d+)", repl, parsed.template)


def remap_expression_ids(expr: str, mapping: dict[str, str]) -> str:
    """Rename component ids inside ``{id.key}`` references (recipe merge, peak rename)."""

    def repl(m: re.Match[str]) -> str:
        cid = m.group(1).strip()
        return "{" + mapping.get(cid, cid) + "." + m.group(2) + "}"

    return REF_RE.sub(repl, str(expr or ""))


# --------------------------------------------------------------------------------------------- validation


def _component_keys(components: list[dict[str, Any]]) -> dict[str, tuple[str, list[str]]]:
    from sersflow.core.preprocess.fitting_specs import component_param_specs

    out: dict[str, tuple[str, list[str]]] = {}
    for c in components:
        if not isinstance(c, dict):
            continue
        cid = str(c.get("component_id") or "")
        ctype = str(c.get("component_type") or "").strip().lower()
        try:
            keys = [s.key for s in component_param_specs(ctype, degree=c.get("degree"))]
        except ValueError:
            keys = []
        out[cid] = (ctype, keys)
    return out


def _shape_keys(keys: list[str]) -> list[str]:
    return [k for k in keys if k not in ("pos", "amp")]


def link_dependencies(
    link: dict[str, Any], comps: dict[str, tuple[str, list[str]]]
) -> tuple[tuple[str, str], list[tuple[str, str]]]:
    """(defined parameter, parameters its value is computed from) for one link; raises ValueError when invalid."""
    from sersflow.core.preprocess.fitting_specs import AREA_EXPORT_COMPONENT_TYPES

    src = (str(link.get("source_component_id") or ""), str(link.get("source_key") or ""))
    mode = str(link.get("mode") or "equal").strip().lower()
    label = f"{src[0]}.{src[1]}"
    if mode not in LINK_MODES:
        raise ValueError(f"{label}: unknown link mode {mode!r}")
    if src[0] not in comps:
        raise ValueError(f"{label}: unknown component {src[0]!r}")
    s_type, s_keys = comps[src[0]]
    if src[1] not in s_keys:
        raise ValueError(f"{label}: component {src[0]!r} has no parameter {src[1]!r} (has: {', '.join(s_keys)})")

    def area_deps(cid: str) -> list[tuple[str, str]]:
        ctype, keys = comps[cid]
        if ctype not in AREA_EXPORT_COMPONENT_TYPES:
            raise ValueError(f"{label}: {cid!r} ({ctype}) has no finite area")
        return [(cid, "amp"), *[(cid, k) for k in _shape_keys(keys)]]

    deps: list[tuple[str, str]] = []
    if mode == "expr":
        parsed = parse_expression(str(link.get("expr") or ""))
        if not parsed.refs:
            raise ValueError(f"{label}: expression has no {{peak.param}} reference; use the parameter's value instead")
        for cid, key in parsed.refs:
            if cid not in comps:
                raise ValueError(f"{label}: unknown component {cid!r} in expression")
            if key == AREA_KEY:
                deps.extend(area_deps(cid))
            elif key not in comps[cid][1]:
                raise ValueError(f"{label}: component {cid!r} has no parameter {key!r} in expression")
            else:
                deps.append((cid, key))
        defines = str(link.get("defines") or "value").strip().lower()
        if defines == AREA_KEY:
            if src[1] != "amp":
                raise ValueError(f"{label}: defines=area needs the link on an amp parameter")
            deps.extend(d for d in area_deps(src[0]) if d != (src[0], "amp"))
        elif defines != "value":
            raise ValueError(f"{label}: defines must be 'value' or 'area'")
    else:
        tgt = (str(link.get("target_component_id") or ""), str(link.get("target_key") or ""))
        if tgt[0] not in comps:
            raise ValueError(f"{label}: unknown target component {tgt[0]!r}")
        if tgt[1] not in comps[tgt[0]][1]:
            raise ValueError(f"{label}: target {tgt[0]!r} has no parameter {tgt[1]!r}")
        deps.append(tgt)
        if mode == "area_ratio":
            if src[1] != "amp" or tgt[1] != "amp":
                raise ValueError(f"{label}: area_ratio links connect amp parameters")
            deps.extend(area_deps(tgt[0]))
            deps.extend(d for d in area_deps(src[0]) if d != src)
    if src in deps:
        raise ValueError(f"{label}: a parameter cannot depend on itself")
    uniq: list[tuple[str, str]] = []
    for d in deps:
        if d not in uniq:
            uniq.append(d)
    return src, uniq


def validate_param_links(components: list[dict[str, Any]], param_links: list[dict[str, Any]] | None) -> list[str]:
    """All problems of a step's links (empty list = valid): unknown names, duplicates, self references, cycles."""
    comps = _component_keys(list(components or []))
    errors: list[str] = []
    graph: dict[tuple[str, str], list[tuple[str, str]]] = {}
    for link in param_links or []:
        if not isinstance(link, dict):
            errors.append(f"link is not an object: {link!r}")
            continue
        try:
            src, deps = link_dependencies(link, comps)
        except ValueError as e:
            errors.append(str(e))
            continue
        if src in graph:
            errors.append(f"{src[0]}.{src[1]} is defined by more than one link")
            continue
        graph[src] = deps
    errors.extend(_cycles(graph))
    return errors


def _cycles(graph: dict[tuple[str, str], list[tuple[str, str]]]) -> list[str]:
    """One message per dependency loop between linked parameters."""
    state: dict[tuple[str, str], int] = {}
    stack: list[tuple[str, str]] = []
    found: list[str] = []
    seen_loops: set[frozenset[tuple[str, str]]] = set()

    def visit(n: tuple[str, str]) -> None:
        state[n] = 1
        stack.append(n)
        for d in graph.get(n, []):
            if state.get(d) == 1:
                loop = stack[stack.index(d) :] + [d]
                key = frozenset(loop)
                if key not in seen_loops:
                    seen_loops.add(key)
                    found.append("cyclic constraint: " + " -> ".join(f"{c}.{k}" for c, k in loop))
            elif state.get(d, 0) == 0 and d in graph:
                visit(d)
        stack.pop()
        state[n] = 2

    for n in list(graph):
        if state.get(n, 0) == 0:
            visit(n)
    return found


def link_driver_ids(link: dict[str, Any]) -> list[str]:
    """Component ids a link follows (target, or every id referenced in an expression)."""
    if str(link.get("mode") or "").strip().lower() == "expr":
        out: list[str] = []
        for cid, _k in expression_refs(str(link.get("expr") or "")):
            if cid not in out:
                out.append(cid)
        return out
    t = str(link.get("target_component_id") or "")
    return [t] if t else []

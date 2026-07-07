from __future__ import annotations

import ast
import math
import re
from dataclasses import dataclass
from typing import Any

from sersflow.core.metrics.key_dedupe import dedupe_parallel
from sersflow.core.pipeline.step_nums import assign_pipeline_step_nums

_PLACEHOLDER_RE = re.compile(r"\{([^{}]+)\}")
_SAFE_FUNCTIONS = {
    "abs": abs,
    "sqrt": math.sqrt,
    "log": math.log,
    "log10": math.log10,
    "exp": math.exp,
    "min": min,
    "max": max,
}


@dataclass(frozen=True)
class FeatureOperationSpec:
    id: str
    formula: str


def _safe_id_fragment(s: str) -> str:
    t = re.sub(r"[^a-zA-Z0-9_]+", "_", s.strip())
    return t or "op"


def default_operation_id(index: int) -> str:
    return f"op{index + 1}"


def operation_feature_key(operation_id: str) -> str:
    return f"op_{_safe_id_fragment(operation_id)}"


def parse_feature_operations(params: dict[str, Any]) -> list[FeatureOperationSpec]:
    raw = params.get("operations")
    if not isinstance(raw, list) or not raw:
        raise ValueError("feature_operations requires params.operations as a non-empty list")
    out: list[FeatureOperationSpec] = []
    for i, row in enumerate(raw):
        if not isinstance(row, dict):
            raise ValueError(f"feature_operations.operations[{i}] must be an object")
        formula = str(row.get("formula") or "").strip()
        if not formula:
            raise ValueError(f"feature_operations.operations[{i}] requires formula")
        op_id = str(row.get("id") or "").strip() or default_operation_id(i)
        out.append(FeatureOperationSpec(id=op_id, formula=formula))
    return out


def feature_keys_for_operations(params: dict[str, Any]) -> list[str]:
    return [operation_feature_key(op.id) for op in parse_feature_operations(params)]


def formula_variables(formula: str) -> list[str]:
    return list(dict.fromkeys(m.group(1).strip() for m in _PLACEHOLDER_RE.finditer(formula) if m.group(1).strip()))


def _as_finite_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(out):
        return None
    return out


def _placeholder_expression(formula: str, variables: dict[str, float]) -> tuple[str, dict[str, float]] | None:
    env: dict[str, float] = {}
    name_by_feature: dict[str, str] = {}
    for feature_name in formula_variables(formula):
        value = _as_finite_float(variables.get(feature_name))
        if value is None:
            return None
        var_name = f"v{len(name_by_feature)}"
        name_by_feature[feature_name] = var_name
        env[var_name] = value

    def repl(match: re.Match[str]) -> str:
        feature_name = match.group(1).strip()
        return name_by_feature.get(feature_name, "__missing__")

    return _PLACEHOLDER_RE.sub(repl, formula), env


def _eval_safe_node(node: ast.AST, env: dict[str, float]) -> float:
    if isinstance(node, ast.Expression):
        return _eval_safe_node(node.body, env)
    if isinstance(node, ast.Constant):
        if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
            raise ValueError("only numeric constants are allowed")
        return float(node.value)
    if isinstance(node, ast.Name):
        if node.id not in env:
            raise ValueError(f"unknown variable {node.id!r}")
        return float(env[node.id])
    if isinstance(node, ast.UnaryOp):
        operand = _eval_safe_node(node.operand, env)
        if isinstance(node.op, ast.UAdd):
            return +operand
        if isinstance(node.op, ast.USub):
            return -operand
        raise ValueError("unsupported unary operator")
    if isinstance(node, ast.BinOp):
        left = _eval_safe_node(node.left, env)
        right = _eval_safe_node(node.right, env)
        if isinstance(node.op, ast.Add):
            return left + right
        if isinstance(node.op, ast.Sub):
            return left - right
        if isinstance(node.op, ast.Mult):
            return left * right
        if isinstance(node.op, ast.Div):
            return left / right
        if isinstance(node.op, ast.Pow):
            return left**right
        if isinstance(node.op, ast.Mod):
            return left % right
        raise ValueError("unsupported binary operator")
    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name) or node.func.id not in _SAFE_FUNCTIONS:
            raise ValueError("unsupported function")
        if node.keywords:
            raise ValueError("keyword arguments are not allowed")
        args = [_eval_safe_node(arg, env) for arg in node.args]
        return float(_SAFE_FUNCTIONS[node.func.id](*args))
    raise ValueError(f"unsupported expression node: {type(node).__name__}")


def evaluate_formula(formula: str, variables: dict[str, Any]) -> float | None:
    prepared = _placeholder_expression(formula, variables)
    if prepared is None:
        return None
    expression, env = prepared
    try:
        tree = ast.parse(expression, mode="eval")
        result = _eval_safe_node(tree, env)
    except (SyntaxError, ValueError, ArithmeticError, ZeroDivisionError, OverflowError, TypeError):
        return None
    if not isinstance(result, (int, float)) or not math.isfinite(float(result)):
        return None
    return float(result)


def evaluate_feature_operations(params: dict[str, Any], variables: dict[str, Any]) -> dict[str, float | None]:
    out: dict[str, float | None] = {}
    for op in parse_feature_operations(params):
        out[operation_feature_key(op.id)] = evaluate_formula(op.formula, variables)
    return out


def _raw_operation_keys_and_nums(pipeline: Any) -> tuple[list[str], list[int]]:
    steps = getattr(pipeline, "steps", None) or []
    sns = assign_pipeline_step_nums(steps)
    raw: list[str] = []
    nums: list[int] = []
    operation_indices = [i for i, s in enumerate(steps) if getattr(s, "enabled", True) and s.name == "feature_operations"]
    multi = len(operation_indices) > 1
    for i in operation_indices:
        step = steps[i]
        prefix = f"s{i}_" if multi else ""
        for k in feature_keys_for_operations(step.params):
            raw.append(f"{prefix}{k}")
            nums.append(sns[i])
    return raw, nums


def preview_operation_feature_keys_for_pipeline(pipeline: Any) -> list[str]:
    raw, nums = _raw_operation_keys_and_nums(pipeline)
    return dedupe_parallel(raw, nums)


def operation_feature_key_groups_for_pipeline(pipeline: Any) -> dict[int, tuple[list[str], list[str]]]:
    """
    Map step_num -> (base_keys, final_keys) for enabled feature_operations steps.
    """
    steps = getattr(pipeline, "steps", None) or []
    sns = assign_pipeline_step_nums(steps)
    raw, nums = _raw_operation_keys_and_nums(pipeline)
    final_keys = dedupe_parallel(raw, nums)
    operation_indices = [i for i, s in enumerate(steps) if getattr(s, "enabled", True) and s.name == "feature_operations"]
    multi = len(operation_indices) > 1
    out: dict[int, tuple[list[str], list[str]]] = {}
    cursor = 0
    for i in operation_indices:
        step = steps[i]
        base_keys = feature_keys_for_operations(step.params)
        prefix = f"s{i}_" if multi else ""
        step_raw = [f"{prefix}{k}" for k in base_keys]
        final = final_keys[cursor : cursor + len(step_raw)]
        cursor += len(step_raw)
        out[sns[i]] = (base_keys, final)
    return out

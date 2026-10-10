"""Safe structured draft reads and preservation-style in-memory patches."""

from __future__ import annotations

import copy
from typing import Any

from .field_registry import field_spec
from .models import FieldChange, ProductFieldSpec


class PatchError(ValueError):
    """The requested field location cannot be safely and uniquely resolved."""


def parse_selector(text: str) -> dict[str, str]:
    """Parse ``key=value;key=value`` without silently accepting ambiguity."""
    if not text or not text.strip():
        return {}
    result: dict[str, str] = {}
    for item in text.split(";"):
        part = item.strip()
        if not part or "=" not in part:
            raise PatchError("selector 必须由 key=value 项组成")
        key, value = (piece.strip() for piece in part.split("=", 1))
        if not key or not value:
            raise PatchError("selector 必须由 key=value 项组成")
        if key in result:
            raise PatchError(f"selector contains duplicate key: {key}")
        result[key] = value
    return result


def apply_field_change(draft: dict[str, Any], change: FieldChange) -> dict[str, Any]:
    """Return a deep-copied draft with exactly one registered field updated.

    This is intentionally an in-memory planning operation.  It cannot send a
    request, add missing ancestor objects, choose an array item by position, or
    overwrite adjacent packages/resources.
    """
    if not isinstance(draft, dict):
        raise PatchError("draft 必须是对象")
    spec = field_spec(change.field_code)
    selectors = parse_selector(change.selector)
    _validate_selectors(spec, selectors)
    patched = copy.deepcopy(draft)
    _set_path(patched, spec.path.split("."), selectors, change.new_value)
    return patched


def get_field_value(draft: dict[str, Any], field_code: str, selector: str = "") -> Any:
    """Resolve one registered field without mutating the source draft."""
    if not isinstance(draft, dict):
        raise PatchError("draft 必须是对象")
    spec = field_spec(field_code)
    selectors = parse_selector(selector)
    _validate_selectors(spec, selectors)
    value = _get_path(draft, spec.path.split("."), selectors)
    return copy.deepcopy(value)


def _validate_selectors(spec: ProductFieldSpec, selectors: dict[str, str]) -> None:
    expected = set(spec.selector_keys)
    actual = set(selectors)
    if not expected and actual:
        raise PatchError(f"字段 {spec.code} 不接受 selector")
    missing = expected - actual
    extras = actual - expected
    if missing:
        raise PatchError(f"字段 {spec.code} 缺少 selector key: {', '.join(sorted(missing))}")
    if extras:
        raise PatchError(f"字段 {spec.code} 包含未知 selector key: {', '.join(sorted(extras))}")


def _set_path(value: Any, segments: list[str], selectors: dict[str, str], replacement: Any) -> None:
    if not segments:
        raise PatchError("字段路径为空")
    segment = segments[0]
    is_array = segment.endswith("[]")
    key = segment[:-2] if is_array else segment
    if not isinstance(value, dict):
        raise PatchError(f"路径 {key} 的父节点不是对象")
    if key not in value:
        raise PatchError(f"草稿中缺少路径节点：{key}")
    target = value[key]
    if is_array:
        target = _select_one(target, selectors, key)
    if len(segments) == 1:
        if is_array:
            raise PatchError("不支持直接整体替换数组元素；请注册具体字段路径")
        value[key] = copy.deepcopy(replacement)
        return
    _set_path(target, segments[1:], selectors, replacement)


def _get_path(value: Any, segments: list[str], selectors: dict[str, str]) -> Any:
    if not segments:
        return value
    segment = segments[0]
    is_array = segment.endswith("[]")
    key = segment[:-2] if is_array else segment
    if not isinstance(value, dict) or key not in value:
        raise PatchError(f"草稿中缺少路径节点：{key}")
    target = value[key]
    if is_array:
        target = _select_one(target, selectors, key)
    return _get_path(target, segments[1:], selectors)


def _select_one(value: Any, selectors: dict[str, str], path_key: str) -> dict[str, Any]:
    if not isinstance(value, list):
        raise PatchError(f"路径 {path_key} 不是列表")
    candidates: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        available_keys = tuple(key for key in selectors if key in item)
        if not available_keys:
            continue
        if all(str(item[key]) == selectors[key] for key in available_keys):
            candidates.append(item)
    if not candidates:
        raise PatchError(f"selector 未在 {path_key} 中定位目标")
    if len(candidates) > 1:
        raise PatchError(f"selector matched multiple items in {path_key}")
    return candidates[0]

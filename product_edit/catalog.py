"""Transport-free full-field catalog inspection types.

The catalog deliberately stores summaries rather than raw payload values.  This
keeps the UI useful for large responses while ensuring credentials and contact
data cannot accidentally be rendered or retained by the tree model.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import re
from typing import Any, Callable, Mapping


_SENSITIVE_KEY = re.compile(
    r"(?:cookie|auth|token|secret|signature|nonce|trace|phone|mobile|email|"
    r"idcard|identity)",
    re.IGNORECASE,
)


def parse_catalog_product_ids(text: str) -> tuple[str, ...]:
    """Parse comma/whitespace/semicolon-separated numeric product IDs."""

    if not isinstance(text, str):
        raise ValueError("product IDs must be text")
    tokens = [token for token in re.split(r"[,;\s]+", text.strip()) if token]
    if any(not token.isdigit() for token in tokens):
        raise ValueError("product IDs must contain digits only")
    return tuple(dict.fromkeys(tokens))


def _is_sensitive(key: str) -> bool:
    return bool(_SENSITIVE_KEY.search(key))


def _summary(value: Any) -> tuple[str, str]:
    if isinstance(value, Mapping):
        return "object", f"{len(value)} keys"
    if isinstance(value, (list, tuple)):
        return "array", f"{len(value)} items"
    if value is None:
        return "null", "null"
    if isinstance(value, bool):
        return "boolean", str(value).lower()
    if isinstance(value, (int, float)):
        return "number", str(value)
    if isinstance(value, str):
        return "string", value
    return type(value).__name__, str(value)


@dataclass
class CatalogTreeNode:
    source: str
    path: str
    key: str
    type: str
    value_summary: str
    sensitive: bool = False
    _child_factory: Callable[[], tuple["CatalogTreeNode", ...]] | None = field(default=None, repr=False)
    _children: tuple["CatalogTreeNode", ...] | None = field(default=None, repr=False)

    @property
    def children_materialized(self) -> bool:
        return self._children is not None

    @property
    def children(self) -> tuple["CatalogTreeNode", ...]:
        return self.expand_children()

    def expand_children(self) -> tuple["CatalogTreeNode", ...]:
        if self._children is None:
            self._children = self._child_factory() if self._child_factory else ()
            self._child_factory = None
        return self._children


def build_catalog_tree(source: str, payload: Any, *, path: str = "") -> CatalogTreeNode:
    """Turn a decoded source payload into a lazy, redacted node tree."""

    root_path = path or source

    def make_node(key: str, value: Any, node_path: str, sensitive: bool = False) -> CatalogTreeNode:
        key_sensitive = sensitive or _is_sensitive(key)
        node_type, summary = _summary(value)
        if key_sensitive:
            summary = "[REDACTED]"

        def children() -> tuple[CatalogTreeNode, ...]:
            if key_sensitive:
                return ()
            if isinstance(value, Mapping):
                return tuple(make_node(str(child_key), child_value, f"{node_path}.{child_key}")
                             for child_key, child_value in value.items())
            if isinstance(value, (list, tuple)):
                return tuple(make_node(str(index), child_value, f"{node_path}[{index}]")
                             for index, child_value in enumerate(value))
            return ()

        return CatalogTreeNode(source, node_path, key, node_type, summary, key_sensitive, children)

    return make_node(source, payload, root_path)


@dataclass(frozen=True)
class CatalogSourceOutcome:
    source: str
    status: str
    node: CatalogTreeNode | None = None
    error: str | None = None


@dataclass(frozen=True)
class FullFieldReadResult:
    product_ids: tuple[str, ...]
    outcomes: Mapping[str, CatalogSourceOutcome]
    created_at: str

    @property
    def source_outcomes(self) -> Mapping[str, CatalogSourceOutcome]:
        return self.outcomes

    @classmethod
    def from_payloads(cls, product_ids: tuple[str, ...], payloads: Mapping[str, Any]) -> "FullFieldReadResult":
        outcomes: dict[str, CatalogSourceOutcome] = {}
        for source, payload in payloads.items():
            if isinstance(payload, BaseException):
                outcomes[source] = CatalogSourceOutcome(source, "error", error=str(payload))
            else:
                outcomes[source] = CatalogSourceOutcome(source, "ok", build_catalog_tree(source, payload))
        return cls(tuple(product_ids), outcomes, datetime.now(timezone.utc).isoformat())


# Descriptive aliases for callers that prefer the transformation wording.
transform_source_payload = build_catalog_tree

"""Stable, transport-free product editing types."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal


ValueType = Literal[
    "string", "integer", "decimal", "boolean", "enum", "date", "time",
    "date_range", "list", "object", "rich_text", "image_list", "video", "file",
]
RiskLevel = Literal["normal", "sensitive", "high"]
Availability = Literal[
    "verified_write", "implemented_needs_recheck", "observed_needs_write_test",
]


@dataclass(frozen=True)
class ProductFieldSpec:
    """One operator-visible field and its evidence-backed draft location.

    ``availability`` is intentionally metadata, not permission.  A later write
    service must gate non-verified fields before it creates an HTTP request.
    """

    code: str
    label: str
    draft_type: str
    module: str
    path: str
    value_type: ValueType
    risk: RiskLevel
    availability: Availability
    readback_path: str
    options_loader: str | None = None
    validators: tuple[str, ...] = ()
    selector_keys: tuple[str, ...] = ()


@dataclass(frozen=True)
class FieldChange:
    """A requested in-memory change; it carries no transport semantics."""

    field_code: str
    new_value: Any
    selector: str = ""

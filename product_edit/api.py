"""Narrow product-draft API boundary for the product-edit workbench.

The concrete Ctrip session remains outside this package.  Callers inject only
the two operations needed for a preservation-style field write, which prevents
this business module from depending on the application shell or another
workbench.
"""

from __future__ import annotations

import copy
import threading
from collections.abc import Mapping
from typing import Any, Protocol


class ProductDraftTransport(Protocol):
    """Minimum transport contract required for one product draft type."""

    def load_draft(
        self,
        product_id: str,
        draft_type: str,
        stop_event: threading.Event,
    ) -> dict[str, Any]: ...

    def save_draft(
        self,
        product_id: str,
        draft_type: str,
        draft: dict[str, Any],
        stop_event: threading.Event,
    ) -> dict[str, Any]: ...


class ProductEditApiClient:
    """Copies mutable boundary data so workflow snapshots remain immutable."""

    def __init__(self, transport: ProductDraftTransport) -> None:
        self._transport = transport

    def load_latest_draft(
        self,
        product_id: str,
        draft_type: str,
        stop_event: threading.Event,
    ) -> dict[str, Any]:
        response = self._transport.load_draft(product_id, draft_type, stop_event)
        if not isinstance(response, Mapping):
            raise TypeError("草稿读取结果必须是对象")
        return copy.deepcopy(dict(response))

    def save_draft(
        self,
        product_id: str,
        draft_type: str,
        draft: dict[str, Any],
        stop_event: threading.Event,
    ) -> dict[str, Any]:
        response = self._transport.save_draft(
            product_id,
            draft_type,
            copy.deepcopy(draft),
            stop_event,
        )
        if not isinstance(response, Mapping):
            raise TypeError("草稿保存结果必须是对象")
        return copy.deepcopy(dict(response))

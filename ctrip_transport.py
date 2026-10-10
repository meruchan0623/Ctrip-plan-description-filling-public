"""Narrow transport boundary used by Ctrip business-domain clients."""

from __future__ import annotations

import threading
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class CtripJsonTransport(Protocol):
    def post_json(
        self,
        url: str,
        product_id: str,
        body: dict[str, Any],
        stop_event: threading.Event,
        *,
        timeout: int = 90,
    ) -> dict[str, Any]: ...


def is_ctrip_json_transport(value: object) -> bool:
    return isinstance(value, CtripJsonTransport)

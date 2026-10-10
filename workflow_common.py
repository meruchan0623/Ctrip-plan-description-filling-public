"""Shared, UI-agnostic contracts for the three Ctrip workbenches."""

from __future__ import annotations

import threading
from dataclasses import dataclass
from enum import Enum
from typing import Any, Literal, Protocol


WorkbenchArea = Literal["translation", "product_edit", "product_images", "docking_config"]


@dataclass(frozen=True)
class RuntimeRequestSnapshot:
    request_interval_seconds: float
    parallel_requests: int
    timeout_seconds: int = 90


class RuntimeRequestSettings:
    """Thread-safe settings shared by a workbench and its worker threads."""

    def __init__(
        self,
        request_interval_seconds: float = 0.0,
        parallel_requests: int = 1,
        timeout_seconds: int = 90,
    ) -> None:
        self._lock = threading.Lock()
        self._request_interval_seconds = max(0.0, float(request_interval_seconds))
        self._parallel_requests = max(1, int(parallel_requests))
        self._timeout_seconds = max(1, int(timeout_seconds))

    def update(
        self,
        request_interval_seconds: float | None = None,
        parallel_requests: int | None = None,
        timeout_seconds: int | None = None,
    ) -> RuntimeRequestSnapshot:
        with self._lock:
            if request_interval_seconds is not None:
                self._request_interval_seconds = max(0.0, float(request_interval_seconds))
            if parallel_requests is not None:
                self._parallel_requests = max(1, int(parallel_requests))
            if timeout_seconds is not None:
                self._timeout_seconds = max(1, int(timeout_seconds))
            return self._snapshot_unlocked()

    def _snapshot_unlocked(self) -> RuntimeRequestSnapshot:
        return RuntimeRequestSnapshot(
            self._request_interval_seconds,
            self._parallel_requests,
            self._timeout_seconds,
        )

    def snapshot(self) -> RuntimeRequestSnapshot:
        with self._lock:
            return self._snapshot_unlocked()

    def request_interval_seconds(self) -> float:
        return self.snapshot().request_interval_seconds

    def parallel_requests(self) -> int:
        return self.snapshot().parallel_requests

    def timeout_seconds(self) -> int:
        return self.snapshot().timeout_seconds


@dataclass(frozen=True)
class WriteGateRequest:
    area: WorkbenchArea
    operation: str
    product_ids: tuple[str, ...] = ()


class ApplicationWriteGate(Protocol):
    def acquire(self, request: WriteGateRequest) -> bool: ...

    def release(self, area: str) -> None: ...


class InMemoryApplicationWriteGate:
    """Process-local exclusive gate for state-changing Ctrip operations."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._owner: str | None = None

    def acquire(self, request: WriteGateRequest) -> bool:
        with self._lock:
            if self._owner not in (None, request.area):
                return False
            self._owner = request.area
            return True

    def release(self, area: str) -> None:
        with self._lock:
            if self._owner == area:
                self._owner = None

    @property
    def owner(self) -> str | None:
        with self._lock:
            return self._owner


class WorkbenchLifecycle(Protocol):
    def is_running(self) -> bool: ...

    def stop(self) -> None: ...

    def request_close(self, parent: Any) -> bool: ...

    def shutdown(self) -> None: ...


class WriteStatus(str, Enum):
    DRY_RUN = "dry_run"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    UNKNOWN = "unknown"
    CONFLICT = "conflict"
    AUTH_EXPIRED = "auth_expired"


def response_business_success(response: Any) -> bool:
    if not isinstance(response, dict):
        return False
    status = response.get("ResponseStatus")
    if isinstance(status, dict) and str(status.get("Ack") or "").lower() != "success":
        return False
    base = response.get("responseBaseData")
    return not (isinstance(base, dict) and base.get("success") is False)


def response_message(response: Any) -> str:
    if not isinstance(response, dict):
        return ""
    base = response.get("responseBaseData")
    if isinstance(base, dict) and base.get("message"):
        return str(base["message"])
    status = response.get("ResponseStatus")
    if isinstance(status, dict):
        return str(status.get("Message") or status.get("message") or "")
    return ""


def classify_write_outcome(response: Any, *, readback_matches: bool | None) -> WriteStatus:
    if not response_business_success(response):
        return WriteStatus.FAILED
    if readback_matches is None:
        return WriteStatus.UNKNOWN
    return WriteStatus.SUCCEEDED if readback_matches else WriteStatus.FAILED

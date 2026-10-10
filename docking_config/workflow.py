"""Batch write workflow for docking template changes."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

from .api import DockingConfigApi, MAX_DOCKING_PAGE_SIZE
from .models import DockingQueryResult
from .template import DockingTemplateChange


@dataclass(frozen=True)
class DockingBatchFailure:
    batch_number: int
    item_start: int
    item_end: int
    source_row_start: int
    source_row_end: int
    message: str


@dataclass(frozen=True)
class DockingBatchResult:
    succeeded: int
    failed: int
    unsubmitted: int
    failure: DockingBatchFailure | None


class DockingConfigWorkflow:
    def __init__(self, api: DockingConfigApi) -> None:
        self._api = api

    def query_many(
        self,
        target_ids: tuple[str, ...] | list[str],
        vendor_id: int,
        connect_no_id: int,
        stop_event: threading.Event,
        *,
        parallel_requests: int = 1,
        request_interval_seconds: float = 0.0,
        progress: Callable[[str], None] | None = None,
    ) -> DockingQueryResult:
        return self._api.query_many(
            target_ids,
            vendor_id,
            connect_no_id,
            stop_event,
            parallel_requests=parallel_requests,
            request_interval_seconds=request_interval_seconds,
            progress=progress,
        )

    def apply_template_changes(
        self,
        changes: tuple[DockingTemplateChange, ...],
        stop_event: threading.Event,
        *,
        request_interval_seconds: float = 0.0,
    ) -> DockingBatchResult:
        total = len(changes)
        if total == 0:
            return DockingBatchResult(0, 0, 0, None)

        payloads = tuple(
            change.baseline.write_payload(**change.changes)
            for change in changes
        )

        succeeded = 0
        for start in range(0, total, MAX_DOCKING_PAGE_SIZE):
            if stop_event.is_set():
                unsubmitted = total - succeeded
                return DockingBatchResult(succeeded, 0, unsubmitted, None)

            end = min(start + MAX_DOCKING_PAGE_SIZE, total)
            chunk_payloads = payloads[start:end]
            chunk_changes = changes[start:end]
            try:
                self._api.update_batch(chunk_payloads, stop_event)
                succeeded += end - start
            except Exception as error:
                failure = DockingBatchFailure(
                    batch_number=start // MAX_DOCKING_PAGE_SIZE + 1,
                    item_start=start + 1,
                    item_end=end,
                    source_row_start=chunk_changes[0].source_row,
                    source_row_end=chunk_changes[-1].source_row,
                    message=str(error),
                )
                failed = len(chunk_changes)
                unsubmitted = total - start - len(chunk_changes)
                return DockingBatchResult(succeeded, failed, unsubmitted, failure)
            if request_interval_seconds > 0 and start + MAX_DOCKING_PAGE_SIZE < total:
                if stop_event.wait(request_interval_seconds):
                    return DockingBatchResult(succeeded, 0, total - succeeded, None)

        return DockingBatchResult(succeeded=total, failed=0, unsubmitted=0, failure=None)

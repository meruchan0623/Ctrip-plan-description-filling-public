"""Small, injectable translation save workflow with mandatory readback."""

from __future__ import annotations

import queue
import threading
from collections import defaultdict
from collections.abc import Callable
from typing import Any, Protocol

from .models import (
    TranslationDiffPlan,
    TranslationResultRow,
    TranslationSnapshot,
    build_translation_snapshot_from_response,
    translation_field_key,
)


class TranslationWorkflowClient(Protocol):
    def save_translation(self, product_id: str, locale: str, raw_translation: dict[str, Any], changed_plans: list[TranslationDiffPlan], online: bool, stop_event: threading.Event) -> tuple[dict[str, Any], dict[str, Any]]: ...
    def load_translation_list(self, product_id: str, locales: list[str], stop_event: threading.Event) -> dict[str, Any]: ...


def _response_success(response: dict[str, Any]) -> bool:
    ack = response.get("ResponseStatus", {}).get("Ack") if isinstance(response.get("ResponseStatus"), dict) else None
    if str(ack).lower() in {"success", "true", "ok"}:
        return True
    base = response.get("responseBaseData")
    return isinstance(base, dict) and bool(base.get("success"))


class TranslationWorkflowWorker:
    def __init__(
        self,
        out_queue: queue.Queue[Any],
        stop_event: threading.Event,
        snapshots: dict[str, TranslationSnapshot],
        pending_plans: list[TranslationDiffPlan],
        client_factory: Callable[[], TranslationWorkflowClient],
    ) -> None:
        self.out_queue = out_queue
        self.stop_event = stop_event
        self.snapshots = snapshots
        self.pending_plans = pending_plans
        self.client_factory = client_factory
        self.results: list[TranslationResultRow] = []

    def _result(self, plan: TranslationDiffPlan, status: str, message: str = "") -> TranslationResultRow:
        result = TranslationResultRow(
            product_id=plan.product_id, locale=plan.locale, module_code=plan.module_code,
            field_code=plan.field_code, field_name=plan.field_name, self_key=plan.self_key,
            status=status, old_value=plan.old_value, new_value=plan.new_value, online=plan.online,
            message=message, row_number=plan.row.row_number,
        )
        self.results.append(result)
        self.out_queue.put(("result", result))
        return result

    def run_save(self) -> list[TranslationResultRow]:
        grouped: dict[tuple[str, str], list[TranslationDiffPlan]] = defaultdict(list)
        for plan in self.pending_plans:
            if plan.status == "pending":
                grouped[(plan.product_id, plan.locale)].append(plan)
        client = self.client_factory()
        for (product_id, locale), plans in grouped.items():
            if self.stop_event.is_set():
                for plan in plans:
                    self._result(plan, "unknown", "任务已停止，未确认写入结果")
                break
            snapshot = self.snapshots.get(product_id)
            raw = snapshot.raw_by_locale.get(locale) if snapshot else None
            if not raw:
                for plan in plans:
                    self._result(plan, "failed", "缺少可保存的翻译原始快照")
                continue
            _payload, response = client.save_translation(product_id, locale, raw, plans, plans[0].online, self.stop_event)
            if not _response_success(response):
                for plan in plans:
                    self._result(plan, "failed", "翻译保存接口返回业务失败")
                continue
            readback = client.load_translation_list(product_id, [locale], self.stop_event)
            verified = build_translation_snapshot_from_response(product_id, [locale], readback)
            for plan in plans:
                field = verified.fields.get(translation_field_key(product_id, locale, plan.self_key))
                if field is not None and field.old_translation == plan.new_value:
                    self._result(plan, "succeeded")
                else:
                    self._result(plan, "unknown", "保存响应成功，但回读未确认目标译文")
        return list(self.results)

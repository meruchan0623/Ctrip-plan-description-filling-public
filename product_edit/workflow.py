"""Safe single-field product-edit execution workflow.

This module deliberately owns no Qt objects and starts no thread.  The caller
supplies a narrow draft transport through :class:`ProductEditApiClient`; the
workflow then makes each status decision from the actual read, save and
readback results.
"""

from __future__ import annotations

import copy
import threading
from dataclasses import dataclass
from typing import Any, Literal

from .adapters import PatchError, apply_field_change, get_field_value
from .api import ProductDraftTransport, ProductEditApiClient
from .field_registry import field_spec
from .models import FieldChange, ProductFieldSpec


ExecutionStatus = Literal["succeeded", "failed", "unknown", "blocked", "dry_run"]


@dataclass(frozen=True)
class ProductEditPolicy:
    """Explicit opt-ins for evidence and high-risk write gates."""

    allow_recheck_fields: bool = False
    allow_observed_fields: bool = False
    acknowledge_high_risk: bool = False


@dataclass(frozen=True)
class ProductEditExecution:
    """Outcome of one proposed field write, including its safe planned draft."""

    product_id: str
    field: ProductFieldSpec
    status: ExecutionStatus
    message: str
    planned_draft: dict[str, Any] | None = None
    save_response: dict[str, Any] | None = None
    readback_value: Any = None


class ProductEditWorkflow:
    """Run a guarded field edit against the freshest draft and verify it."""

    def __init__(self, transport: ProductDraftTransport | ProductEditApiClient) -> None:
        self._api = transport if isinstance(transport, ProductEditApiClient) else ProductEditApiClient(transport)

    def execute(
        self,
        product_id: str,
        change: FieldChange,
        *,
        policy: ProductEditPolicy | None = None,
        dry_run: bool = False,
        stop_event: threading.Event | None = None,
    ) -> ProductEditExecution:
        spec = field_spec(change.field_code)
        effective_policy = policy or ProductEditPolicy()
        rejection = _write_gate_message(spec, effective_policy)
        if rejection:
            return ProductEditExecution(product_id, spec, "blocked", rejection)

        event = stop_event or threading.Event()
        if event.is_set():
            return ProductEditExecution(product_id, spec, "unknown", "操作已停止")

        try:
            latest = self._api.load_latest_draft(product_id, spec.draft_type, event)
        except Exception as exc:
            return ProductEditExecution(product_id, spec, "unknown", f"读取最新草稿失败：{exc}")

        try:
            planned = apply_field_change(latest, change)
        except PatchError as exc:
            return ProductEditExecution(product_id, spec, "failed", str(exc))

        if dry_run:
            return ProductEditExecution(
                product_id,
                spec,
                "dry_run",
                "已基于最新草稿生成预览，未发送保存请求",
                planned_draft=planned,
            )

        if event.is_set():
            return ProductEditExecution(product_id, spec, "unknown", "操作已停止", planned_draft=planned)

        try:
            save_response = self._api.save_draft(product_id, spec.draft_type, planned, event)
        except Exception as exc:
            return ProductEditExecution(
                product_id,
                spec,
                "unknown",
                f"保存请求状态未知：{exc}",
                planned_draft=planned,
            )

        if not business_success(save_response):
            return ProductEditExecution(
                product_id,
                spec,
                "failed",
                response_message(save_response) or "保存接口未返回业务成功",
                planned_draft=planned,
                save_response=save_response,
            )

        try:
            readback = self._api.load_latest_draft(product_id, spec.draft_type, event)
            actual = get_field_value(readback, change.field_code, change.selector)
        except Exception as exc:
            return ProductEditExecution(
                product_id,
                spec,
                "unknown",
                f"保存后回读失败：{exc}",
                planned_draft=planned,
                save_response=save_response,
            )

        if actual != change.new_value:
            return ProductEditExecution(
                product_id,
                spec,
                "failed",
                "保存后回读值与目标值不一致",
                planned_draft=planned,
                save_response=save_response,
                readback_value=copy.deepcopy(actual),
            )

        return ProductEditExecution(
            product_id,
            spec,
            "succeeded",
            "保存成功且目标字段已回读验证",
            planned_draft=planned,
            save_response=save_response,
            readback_value=copy.deepcopy(actual),
        )


def business_success(response: dict[str, Any]) -> bool:
    """Require both Ctrip acknowledgement and explicit business success."""
    status = response.get("ResponseStatus")
    if isinstance(status, dict):
        acknowledged = str(status.get("Ack") or "").lower() == "success"
    else:
        acknowledged = str(status or "").lower() in {"ack", "success"}
    if not acknowledged:
        return False
    base = response.get("responseBaseData")
    return isinstance(base, dict) and base.get("success") is True


def response_message(response: dict[str, Any]) -> str:
    base = response.get("responseBaseData")
    if isinstance(base, dict):
        message = base.get("message") or base.get("msg")
        if message:
            return str(message)
    message = response.get("message") or response.get("msg")
    return str(message) if message else ""


def _write_gate_message(spec: ProductFieldSpec, policy: ProductEditPolicy) -> str:
    if spec.availability == "implemented_needs_recheck" and not policy.allow_recheck_fields:
        return "字段尚需当前产品 no-op 与回读复核，未授权写入"
    if spec.availability == "observed_needs_write_test" and not policy.allow_observed_fields:
        return "字段尚未完成单字段保存与回读验证，未授权写入"
    if spec.risk == "high" and not policy.acknowledge_high_risk:
        return "高风险字段需要独立二次确认"
    return ""

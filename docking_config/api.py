"""Ctrip docking query and update API boundary."""

from __future__ import annotations

import concurrent.futures
import threading
import time
from collections.abc import Callable
from typing import Any

from ctrip_transport import CtripJsonTransport
from workflow_common import response_business_success, response_message

from .models import DockingQueryResult, DockingResource, parse_docking_response


DOCKING_QUERY_URL = "https://m.ctrip.com/restapi/soa2/16359/mixProductDockInfoQuery"
DOCKING_UPDATE_URL = "https://m.ctrip.com/restapi/soa2/16359/batchEditDockSetting"
PRODUCT_LIST_QUERY_URL = "https://m.ctrip.com/restapi/soa2/16359/json/mixProductQuery"
MAX_DOCKING_PAGE_SIZE = 10_000
PRODUCT_LIST_PAGE_SIZE = 1_000
MAX_PARALLEL_REQUESTS = 5
ALL_SITE_QUERY_TARGET = "__ALL_SITE__"


class DockingConfigApi:
    def __init__(self, transport: CtripJsonTransport) -> None:
        self._transport = transport
        self._request_lock = threading.Lock()
        self._last_request_at = 0.0

    def _wait_for_request_slot(
        self,
        stop_event: threading.Event,
        request_interval_seconds: float,
    ) -> None:
        interval = max(0.0, float(request_interval_seconds))
        if interval <= 0:
            return
        with self._request_lock:
            remaining = interval - (time.monotonic() - self._last_request_at)
            if remaining > 0 and stop_event.wait(remaining):
                raise RuntimeError("查询已停止")
            self._last_request_at = time.monotonic()

    def _query_one_page(
        self,
        product_or_resource_id: str,
        vendor_id: int,
        connect_no_id: int,
        stop_event: threading.Event,
        page_no: int,
        page_size: int = MAX_DOCKING_PAGE_SIZE,
    ) -> DockingQueryResult:
        target = str(product_or_resource_id).strip()
        if not target.isdigit():
            raise ValueError("产品/资源 ID 必须是数字")
        if not 1 <= int(page_size) <= MAX_DOCKING_PAGE_SIZE:
            raise ValueError(f"单页数量必须在 1 到 {MAX_DOCKING_PAGE_SIZE} 之间")
        body = {
            "requestBaseData": {"locale": "zh-CN", "extParameterList": []},
            "opType": 0,
            "vendorId": int(vendor_id),
            "connectNoId": int(connect_no_id),
            "bussinessId": int(target),
            "bussinessName": "",
            "productVendorId": "",
            "saleStatus": None,
            "maintainStatus": None,
            "pageNo": int(page_no),
            "pageSize": int(page_size),
        }
        response = self._transport.post_json(
            DOCKING_QUERY_URL,
            target,
            body,
            stop_event,
            timeout=120,
        )
        if not response_business_success(response):
            raise RuntimeError(response_message(response) or "产品对接配置查询失败")
        return parse_docking_response(response)

    def _query_all_product_ids(
        self,
        stop_event: threading.Event,
        request_interval_seconds: float,
    ) -> tuple[str, ...]:
        product_ids: list[str] = []
        seen: set[str] = set()
        page_no = 1
        total_count = 0

        while True:
            if stop_event.is_set():
                raise RuntimeError("查询已停止")
            self._wait_for_request_slot(stop_event, request_interval_seconds)
            body = {
                "requestBaseData": {"locale": "zh-CN", "extParameterList": []},
                "pageNo": page_no,
                "pageSize": PRODUCT_LIST_PAGE_SIZE,
                "mixProductId": None,
                "mixProductName": None,
                "poiId": None,
                "saleUnitId": None,
                "source": None,
                "resourceSaleStatus": None,
                "online": None,
                "active": None,
                "categoryId": None,
                "vendorId": None,
                "regionId": None,
                "productManagerEid": None,
                "productAssistantEid": None,
                "departureDistrictId": None,
                "destinationDistrictId": None,
                "ticketPackType": None,
                "saleMode": None,
                "status": None,
                "vendorProductCode": None,
                "vendorProductName": None,
                "productNote": None,
                "creationMode": None,
                "vendorContractId": None,
                "productSaleChannel": None,
                "originLocale": None,
                "priceMode": None,
                "preSale": None,
                "medalType": None,
                "currentMedalList": None,
            }
            response = self._transport.post_json(
                PRODUCT_LIST_QUERY_URL,
                "0",
                body,
                stop_event,
                timeout=120,
            )
            if not response_business_success(response):
                raise RuntimeError(response_message(response) or "全站产品清单查询失败")

            total_count = int(response.get("totalCount") or 0)
            page_rows = response.get("productList") or ()
            for row in page_rows:
                if not isinstance(row, dict):
                    continue
                product_id = str(row.get("mixProductId") or "").strip()
                if not product_id.isdigit() or product_id in seen:
                    continue
                seen.add(product_id)
                product_ids.append(product_id)

            if len(seen) >= total_count:
                break
            if not page_rows:
                raise RuntimeError(
                    f"全站产品清单分页提前结束：应返回 {total_count} 个产品，实际取得 {len(seen)} 个"
                )
            if page_no * PRODUCT_LIST_PAGE_SIZE >= total_count:
                raise RuntimeError(
                    f"全站产品清单结果不完整：应返回 {total_count} 个产品，实际取得 {len(seen)} 个"
                )
            page_no += 1

        return tuple(product_ids)

    def query_many(
        self,
        product_or_resource_ids: tuple[str, ...] | list[str],
        vendor_id: int,
        connect_no_id: int,
        stop_event: threading.Event,
        *,
        parallel_requests: int = 1,
        request_interval_seconds: float = 0.0,
        progress: Callable[[str], None] | None = None,
    ) -> DockingQueryResult:
        if not product_or_resource_ids:
            raise ValueError("至少需要一个产品/资源 ID，或使用全站查询标记")
        resources: list[DockingResource] = []
        seen: set[tuple[int, int, int, int]] = set()
        seen_ids: set[str] = set()
        normalized_parallel_requests = max(1, min(int(parallel_requests), MAX_PARALLEL_REQUESTS))
        normalized_interval = max(0.0, float(request_interval_seconds))

        normalized_targets: list[str] = []
        all_site_query = False
        for target_id in product_or_resource_ids:
            target = str(target_id).strip()
            if target == ALL_SITE_QUERY_TARGET:
                if len(product_or_resource_ids) != 1:
                    raise ValueError("全站查询不能与产品/资源 ID 混合使用")
                all_site_query = True
            elif not target.isdigit():
                raise ValueError("产品/资源 ID 必须是数字")
            if target in seen_ids:
                continue
            seen_ids.add(target)
            normalized_targets.append(target)

        if all_site_query:
            normalized_targets = list(
                self._query_all_product_ids(stop_event, normalized_interval)
            )
            if progress is not None:
                progress(f"全站产品清单已获取 {len(normalized_targets)} 个产品，开始逐产品读取对接配置")
        if not normalized_targets:
            return DockingQueryResult((), 0, 1, MAX_DOCKING_PAGE_SIZE)

        if len(normalized_targets) == 1:
            # 保留原有串行行为（单 ID 时无并发意义，减少调度开销）
            results = [
                self._query_one_product(
                    normalized_targets[0],
                    vendor_id,
                    connect_no_id,
                    stop_event,
                    normalized_interval,
                )
            ]
            if all_site_query and progress is not None:
                progress("全站预载进度 1/1")
        else:
            with concurrent.futures.ThreadPoolExecutor(max_workers=normalized_parallel_requests) as executor:
                futures = {
                    executor.submit(
                        self._query_one_product,
                        target_id,
                        vendor_id,
                        connect_no_id,
                        stop_event,
                        normalized_interval,
                    ): target_id
                    for target_id in normalized_targets
                }
                result_by_target: dict[str, DockingQueryResult] = {}
                completed = 0
                for future in concurrent.futures.as_completed(futures):
                    target_id = futures[future]
                    try:
                        result_by_target[target_id] = future.result()
                    except Exception as exc:
                        stop_event.set()
                        target_label = (
                            "全站"
                            if target_id == ALL_SITE_QUERY_TARGET
                            else f"产品/资源 ID {target_id}"
                        )
                        raise RuntimeError(f"{target_label} 查询失败：{exc}") from exc
                    completed += 1
                    if (
                        all_site_query
                        and progress is not None
                        and (completed == len(normalized_targets) or completed % 10 == 0)
                    ):
                        progress(f"全站预载进度 {completed}/{len(normalized_targets)}")
                results = [result_by_target[target_id] for target_id in normalized_targets]

        for result in results:
            for resource in result.resources:
                key = (
                    resource.product_id,
                    resource.resource_id,
                    resource.vendor_id,
                    resource.connect_no_id,
                )
                if key in seen:
                    continue
                seen.add(key)
                resources.append(resource)

        return DockingQueryResult(
            resources=tuple(resources),
            total_count=len(resources),
            page_no=1,
            page_size=MAX_DOCKING_PAGE_SIZE,
        )

    def _query_one_product(
        self,
        target_id: str,
        vendor_id: int,
        connect_no_id: int,
        stop_event: threading.Event,
        request_interval_seconds: float = 0.0,
    ) -> DockingQueryResult:
        target = str(target_id).strip()
        resources: list[DockingResource] = []
        seen: set[tuple[int, int, int, int]] = set()
        page_no = 1
        total_count = 0

        while True:
            if stop_event.is_set():
                raise RuntimeError("查询已停止")
            self._wait_for_request_slot(stop_event, request_interval_seconds)
            result = self._query_one_page(
                target,
                vendor_id,
                connect_no_id,
                stop_event,
                page_no=page_no,
                page_size=MAX_DOCKING_PAGE_SIZE,
            )
            total_count = result.total_count
            for resource in result.resources:
                key = (
                    resource.product_id,
                    resource.resource_id,
                    resource.vendor_id,
                    resource.connect_no_id,
                )
                if key in seen:
                    continue
                seen.add(key)
                resources.append(resource)

            if len(seen) >= total_count:
                break
            if not result.resources:
                raise RuntimeError(
                    f"产品/资源 ID {target} 分页查询提前结束："
                    f"应返回 {total_count} 条，实际取得 {len(seen)} 条"
                )
            if page_no * MAX_DOCKING_PAGE_SIZE >= total_count:
                raise RuntimeError(
                    f"产品/资源 ID {target} 查询结果不完整："
                    f"应返回 {total_count} 条，实际取得 {len(seen)} 条"
                )
            page_no += 1

        return DockingQueryResult(
            resources=tuple(resources),
            total_count=len(resources),
            page_no=1,
            page_size=MAX_DOCKING_PAGE_SIZE,
        )

    def update_batch(
        self,
        payloads: tuple[dict[str, Any], ...] | list[dict[str, Any]],
        stop_event: threading.Event,
        *,
        batch_size: int = MAX_DOCKING_PAGE_SIZE,
    ) -> dict[str, Any]:
        if not payloads:
            raise ValueError("没有可提交的批量数据")
        payloads_list = list(payloads)
        if batch_size <= 0 or batch_size > MAX_DOCKING_PAGE_SIZE:
            raise ValueError(f"批处理大小必须在 1 到 {MAX_DOCKING_PAGE_SIZE} 之间")
        if len(payloads_list) > batch_size:
            raise ValueError(f"单批最大可处理 {batch_size} 条")

        if stop_event.is_set():
            raise RuntimeError("写入已停止")
        body = {"batch": True, "batchEditDockSettingDtoList": payloads_list}
        response = self._transport.post_json(
            DOCKING_UPDATE_URL,
            str(payloads_list[0]["productId"]),
            body,
            stop_event,
            timeout=120,
        )
        if not response_business_success(response):
            raise RuntimeError(response_message(response) or "产品对接配置保存失败")
        return response

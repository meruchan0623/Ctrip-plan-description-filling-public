"""Transport-free models for the product docking configuration workbench."""

from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any


def _integer(value: Any, field_name: str) -> int:
    try:
        return int(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{field_name} 必须是整数") from error


def _sync_value(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _preorder_code(properties: tuple[dict[str, Any], ...]) -> str:
    item = next((row for row in properties if str(row.get("key") or "") == "203"), None)
    if not item:
        return ""
    current = str(item.get("value") or "")
    for option in item.get("valueList") or ():
        if not isinstance(option, dict):
            continue
        if current in {str(option.get("name") or ""), str(option.get("value") or "")}:
            return str(option.get("value") or "")
    return {"是": "1", "否": "0"}.get(current, current)


@dataclass(frozen=True)
class DockingResource:
    product_id: int
    product_name: str
    resource_id: int
    resource_name: str
    vendor_id: int
    connect_no_id: int
    vendor_resource_id: str
    allow_sync_sale_price: int
    allow_sync_cost_price: int
    allow_sync_stock: int
    allow_sync_sale_status: int
    connection_properties: tuple[dict[str, Any], ...]
    product_definition_codes: tuple[Any, ...] = ()
    resource_sale_status: bool = False
    docking_code: str = ""

    @property
    def current_docking_code(self) -> str:
        return self.docking_code or self.vendor_resource_id

    @property
    def ticket_code(self) -> str:
        item = next(
            (row for row in self.connection_properties if str(row.get("key") or "") == "4"),
            None,
        )
        return str(item.get("value") or "") if item else ""

    @property
    def preorder_code(self) -> str:
        return _preorder_code(self.connection_properties)

    @property
    def preorder_label(self) -> str:
        return {"1": "是", "0": "否"}.get(self.preorder_code, self.preorder_code or "未配置")

    def write_payload(
        self,
        *,
        vendor_resource_id: str,
        ticket_code: str,
        preorder_code: str,
        allow_sync_sale_price: int,
        allow_sync_cost_price: int,
        allow_sync_sale_status: int,
    ) -> dict[str, Any]:
        properties: list[dict[str, Any]] = []
        found_ticket = False
        found_preorder = False
        for original in self.connection_properties:
            key = str(original.get("key") or "")
            item = {
                field: copy.deepcopy(original[field])
                for field in ("relateId", "key", "value")
                if field in original
            }
            if key == "4":
                item["value"] = ticket_code
                found_ticket = True
            elif key == "203":
                item["value"] = preorder_code
                found_preorder = True
            properties.append(item)
        if not found_ticket:
            raise ValueError("当前资源缺少票种代码属性，不能安全写入")
        if not found_preorder:
            raise ValueError("当前资源缺少支付前对接属性，不能安全写入")
        return {
            "productId": self.product_id,
            "resourceId": self.resource_id,
            "allowSyncSalePrice": int(allow_sync_sale_price),
            "allowSyncCostPrice": int(allow_sync_cost_price),
            "allowSyncStock": self.allow_sync_stock,
            "allowSyncSaleStatus": int(allow_sync_sale_status),
            "connectionSystemKey": vendor_resource_id,
            "connectionPropertyList": properties,
            "productDefinitionCodeList": copy.deepcopy(list(self.product_definition_codes)),
        }


@dataclass(frozen=True)
class DockingQueryResult:
    resources: tuple[DockingResource, ...]
    total_count: int
    page_no: int
    page_size: int


def parse_docking_response(response: dict[str, Any]) -> DockingQueryResult:
    resources: list[DockingResource] = []
    for product in response.get("productDockInfoList") or ():
        if not isinstance(product, dict):
            continue
        product_id = _integer(product.get("productId"), "productId")
        vendor_id = _integer(product.get("vendorId"), "vendorId")
        connect_no_id = _integer(product.get("connectNoId"), "connectNoId")
        for resource in product.get("resourceInfoList") or ():
            if not isinstance(resource, dict):
                continue
            properties = tuple(
                copy.deepcopy(item)
                for item in resource.get("connectionPropertyList") or ()
                if isinstance(item, dict)
            )
            resources.append(
                DockingResource(
                    product_id=product_id,
                    product_name=str(product.get("productName") or ""),
                    resource_id=_integer(resource.get("resourceId"), "resourceId"),
                    resource_name=str(resource.get("resourceName") or ""),
                    vendor_id=vendor_id,
                    connect_no_id=connect_no_id,
                    vendor_resource_id=str(resource.get("vendorResourceId") or ""),
                    allow_sync_sale_price=_sync_value(resource.get("allowSyncSalePrice")),
                    allow_sync_cost_price=_sync_value(resource.get("allowSyncCostPrice")),
                    allow_sync_stock=_sync_value(resource.get("allowSyncStock")),
                    allow_sync_sale_status=_sync_value(resource.get("allowSyncSaleStatus")),
                    connection_properties=properties,
                    product_definition_codes=tuple(
                        copy.deepcopy(resource.get("productDefinitionCodeList") or ())
                    ),
                    resource_sale_status=bool(resource.get("resourceSaleStatus")),
                    docking_code=str(
                        resource.get("connectionSystemKey")
                        or resource.get("vendorResourceId")
                        or ""
                    ),
                )
            )
    return DockingQueryResult(
        resources=tuple(resources),
        total_count=_sync_value(response.get("totalCount")),
        page_no=_sync_value(response.get("pageNo")) or 1,
        page_size=_sync_value(response.get("pageSize")),
    )

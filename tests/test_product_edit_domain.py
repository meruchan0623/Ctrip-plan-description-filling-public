"""Contract tests for the independently importable product-edit domain.

Breaks caught here:
* a field disappears from an operator-visible field group;
* a selector targets the wrong package/resource or an ambiguous array item;
* a patch accidentally replaces neighbouring package data;
* unverified or high-risk changes are sent without their required gate.
"""

from __future__ import annotations

import unittest

from product_edit.adapters import PatchError, apply_field_change, parse_selector
from product_edit.field_registry import FIELD_SPECS, field_spec, field_specs_for_module
from product_edit.models import FieldChange


class FieldRegistryTests(unittest.TestCase):
    def test_registry_covers_each_approved_operator_field_group(self) -> None:
        expected_modules = {
            "产品信息",
            "视频与描述",
            "活动与上下线",
            "游客与联系人",
            "预订限制",
            "预订模式与有效期",
            "订单处理",
            "对接与续订",
            "退改规则",
            "适用人群",
            "套餐与销售属性",
            "价格与库存",
        }

        self.assertTrue(expected_modules.issubset({spec.module for spec in FIELD_SPECS}))
        self.assertGreaterEqual(len(FIELD_SPECS), 100)
        self.assertTrue(any(spec.code == "product_name" and spec.path == "productBasicInfo.name" for spec in FIELD_SPECS))
        self.assertTrue(any(spec.code == "refund_policy_cost_list" and spec.risk == "high" for spec in FIELD_SPECS))
        self.assertTrue(any(spec.code == "resource_cost_price" and spec.draft_type == "PriceAndStock" for spec in FIELD_SPECS))
        self.assertTrue(field_specs_for_module("套餐与销售属性"))

    def test_registry_preserves_operator_label_and_selector_for_nested_fields(self) -> None:
        unavailable_dates = field_spec("unavailable_date_list")
        connection_code = field_spec("connection_code")

        self.assertEqual(unavailable_dates.label, "不可使用日期")
        self.assertEqual(unavailable_dates.path, "productReserveMode.unavailableDateList")
        self.assertEqual(connection_code.selector_keys, ("packageId", "resourceId", "key"))


class StructuredPatchTests(unittest.TestCase):
    def test_patch_changes_only_selected_resource_and_preserves_neighbours(self) -> None:
        draft = {
            "productPackageInfo": {
                "packageResourceInfo": [
                    {
                        "packageId": "p-1",
                        "packageName": "keep",
                        "resourceInfoList": [
                            {"resourceId": "r-1", "vendorPackageId": "before", "untouched": "one"},
                            {"resourceId": "r-2", "vendorPackageId": "other", "untouched": "two"},
                        ],
                    },
                    {"packageId": "p-2", "packageName": "other package", "resourceInfoList": []},
                ],
            },
            "productVersion": 7,
        }

        patched = apply_field_change(
            draft,
            FieldChange(
                field_code="vendor_package_id",
                selector="packageId=p-1;resourceId=r-1",
                new_value="after",
            ),
        )

        resources = patched["productPackageInfo"]["packageResourceInfo"][0]["resourceInfoList"]
        self.assertEqual(resources[0]["vendorPackageId"], "after")
        self.assertEqual(resources[0]["untouched"], "one")
        self.assertEqual(resources[1], {"resourceId": "r-2", "vendorPackageId": "other", "untouched": "two"})
        self.assertEqual(patched["productPackageInfo"]["packageResourceInfo"][1]["packageName"], "other package")
        self.assertEqual(draft["productPackageInfo"]["packageResourceInfo"][0]["resourceInfoList"][0]["vendorPackageId"], "before")

    def test_patch_rejects_ambiguous_selector_instead_of_guessing_a_target(self) -> None:
        draft = {
            "productPackageInfo": {
                "packageResourceInfo": [
                    {"packageId": "p-1", "resourceInfoList": [{"resourceId": "r-1"}]},
                    {"packageId": "p-1", "resourceInfoList": [{"resourceId": "r-2"}]},
                ]
            }
        }

        with self.assertRaisesRegex(PatchError, "selector.*multiple"):
            apply_field_change(
                draft,
                FieldChange(field_code="package_name", selector="packageId=p-1", new_value="new"),
            )

    def test_selector_requires_key_value_pairs_and_rejects_duplicates(self) -> None:
        self.assertEqual(parse_selector("packageId=p-1;resourceId=r-1"), {"packageId": "p-1", "resourceId": "r-1"})
        with self.assertRaisesRegex(PatchError, "key=value"):
            parse_selector("packageId")
        with self.assertRaisesRegex(PatchError, "duplicate"):
            parse_selector("packageId=p-1;packageId=p-2")

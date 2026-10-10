"""Runtime contract tests for the isolated product-edit workbench.

Breaks caught here:
* a dry-run writes a product draft;
* an evidence or high-risk gate is bypassed;
* a save reports success without a business-success response and matching
  readback; or
* a write is based on an obsolete caller snapshot instead of the latest draft.
"""

from __future__ import annotations

import copy
import unittest

from product_edit.models import FieldChange
from product_edit.field_registry import field_spec
from product_edit.workflow import ProductEditPolicy, ProductEditWorkflow


class MemoryDraftClient:
    """Small complete fake at the transport boundary; it has no UI behavior."""

    def __init__(self, draft: dict, *, save_response: dict | None = None) -> None:
        self.draft = copy.deepcopy(draft)
        self.save_response = save_response or {
            "ResponseStatus": "Ack",
            "responseBaseData": {"success": True},
        }
        self.save_calls: list[dict] = []
        self.read_calls = 0

    def load_draft(self, product_id: str, draft_type: str, stop_event: object) -> dict:
        self.read_calls += 1
        return copy.deepcopy(self.draft)

    def save_draft(
        self,
        product_id: str,
        draft_type: str,
        draft: dict,
        stop_event: object,
    ) -> dict:
        self.save_calls.append(copy.deepcopy(draft))
        if self.save_response.get("responseBaseData", {}).get("success"):
            self.draft = copy.deepcopy(draft)
        return copy.deepcopy(self.save_response)


class ProductEditWorkflowTests(unittest.TestCase):
    def test_captured_product_info_fields_use_the_product_basic_info_root(self) -> None:
        expected_paths = {
            "district_list": "productBasicInfo.districtList",
            "dest_district_list": "productBasicInfo.destDistrictList",
            "poi_list": "productBasicInfo.poiList",
            "sale_channel_list": "productBasicInfo.saleChannelList",
            "trip_sales_status": "productBasicInfo.tripSalesStatus",
            "brand_info": "productBasicInfo.brandInfo",
            "emergency_contact": "productBasicInfo.emergencyContact",
            "service_phone": "productBasicInfo.servicePhone",
            "emergency_phone_list": "productBasicInfo.emergencyPhoneList",
            "distribution_phone": "productBasicInfo.distributionContactPhoneList",
            "im_contact": "productBasicInfo.imId",
            "local_service_org": "productBasicInfo.localAgencyId",
        }

        self.assertEqual(
            {code: field_spec(code).path for code in expected_paths},
            expected_paths,
        )

    def test_dry_run_uses_latest_draft_but_never_saves(self) -> None:
        client = MemoryDraftClient(
            {"productBasicInfo": {"name": "latest", "untouched": "keep"}, "productVersion": 9}
        )
        workflow = ProductEditWorkflow(client)

        result = workflow.execute(
            "1001",
            FieldChange("product_name", "planned"),
            dry_run=True,
        )

        self.assertEqual(result.status, "dry_run")
        self.assertEqual(result.planned_draft["productBasicInfo"], {"name": "planned", "untouched": "keep"})
        self.assertEqual(client.save_calls, [])

    def test_unverified_field_is_blocked_before_loading_or_saving(self) -> None:
        client = MemoryDraftClient({"productBasicInfo": {"subTitle": "before"}})

        result = ProductEditWorkflow(client).execute(
            "1001",
            FieldChange("product_subtitle", "after"),
        )

        self.assertEqual(result.status, "blocked")
        self.assertEqual(client.read_calls, 0)
        self.assertEqual(client.save_calls, [])

    def test_high_risk_field_requires_separate_operator_acknowledgement(self) -> None:
        client = MemoryDraftClient({"productBookingRule": {"cancelType": "rule"}})
        workflow = ProductEditWorkflow(client)

        result = workflow.execute(
            "1001",
            FieldChange("cancel_type", "no_refund"),
            policy=ProductEditPolicy(allow_observed_fields=True),
        )

        self.assertEqual(result.status, "blocked")
        self.assertEqual(client.read_calls, 0)
        self.assertEqual(client.save_calls, [])

    def test_success_requires_latest_snapshot_business_ack_and_matching_readback(self) -> None:
        client = MemoryDraftClient(
            {"productBasicInfo": {"name": "latest", "description": "preserve"}, "productVersion": 8}
        )
        workflow = ProductEditWorkflow(client)

        result = workflow.execute("1001", FieldChange("product_name", "after"))

        self.assertEqual(result.status, "succeeded")
        self.assertEqual(client.save_calls[0]["productBasicInfo"], {"name": "after", "description": "preserve"})
        self.assertEqual(client.save_calls[0]["productVersion"], 8)
        self.assertEqual(result.readback_value, "after")
        self.assertEqual(client.read_calls, 2)

    def test_real_ctrip_ack_mapping_is_accepted_only_with_business_success(self) -> None:
        client = MemoryDraftClient(
            {"productBasicInfo": {"name": "before"}},
            save_response={
                "ResponseStatus": {"Ack": "Success"},
                "responseBaseData": {"success": True},
            },
        )

        result = ProductEditWorkflow(client).execute(
            "1001",
            FieldChange("product_name", "after"),
        )

        self.assertEqual(result.status, "succeeded")

    def test_business_failure_never_reports_success_even_when_transport_returns_a_mapping(self) -> None:
        client = MemoryDraftClient(
            {"productBasicInfo": {"name": "before"}},
            save_response={"ResponseStatus": "Ack", "responseBaseData": {"success": False, "message": "rejected"}},
        )

        result = ProductEditWorkflow(client).execute("1001", FieldChange("product_name", "after"))

        self.assertEqual(result.status, "failed")
        self.assertEqual(client.read_calls, 1)
        self.assertIsNone(result.readback_value)


if __name__ == "__main__":
    unittest.main()

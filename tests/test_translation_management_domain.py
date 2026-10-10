import copy
import csv
import queue
import threading
import tempfile
import unittest
from pathlib import Path

from translation_management.api import TranslationApiClient
from translation_management.models import (
    TranslationDiffPlan,
    TranslationFieldSnapshot,
    TranslationResultRow,
    TranslationTemplateRow,
    apply_translation_to_modules,
    build_translation_diff_plans,
    build_translation_snapshot_from_response,
    default_translation_execution_config,
    translation_execution_config_from_dict,
    translation_execution_config_to_dict,
    write_translation_report,
)
from translation_management.workflow import TranslationWorkflowWorker


class TranslationManagementDomainTests(unittest.TestCase):
    def _snapshot_response(self):
        return {
            "translations": [
                {
                    "targetLocale": "en-US",
                    "translationModules": [
                        {
                            "moduleCode": "ProductInfo",
                            "moduleName": "产品信息",
                            "fields": [
                                {
                                    "fieldCode": "productName",
                                    "fieldName": "产品名称",
                                    "selfKey": "name-key",
                                    "translation": "Old name",
                                    "origin": "原始名称",
                                    "aiGen": True,
                                }
                            ],
                        }
                    ],
                }
            ]
        }

    def test_snapshot_and_diff_plan_locate_current_translation_by_self_key(self):
        snapshot = build_translation_snapshot_from_response(
            "1001", ["en-US"], self._snapshot_response(), {"en-US": {"operableLocales": True}}
        )
        row = TranslationTemplateRow(
            row_number=2,
            product_id="1001",
            locale="en-US",
            module_code="ProductInfo",
            field_code="productName",
            field_name="产品名称",
            value_key="translation",
            self_key="name-key",
            origin="原始名称",
            old_translation="Old name",
            target_translation="New name",
        )

        plans = build_translation_diff_plans({"1001": snapshot}, [row])

        self.assertEqual(1, len(plans))
        self.assertEqual("pending", plans[0].status)
        self.assertEqual("Old name", plans[0].old_value)
        self.assertEqual("New name", plans[0].new_value)
        self.assertEqual("name-key", plans[0].self_key)

    def test_apply_translation_updates_only_target_field_and_marks_it_manual(self):
        modules = self._snapshot_response()["translations"][0]["translationModules"]
        untouched = copy.deepcopy(modules)

        changed = apply_translation_to_modules(modules, "name-key", "translation", "New name")

        field = modules[0]["fields"][0]
        self.assertTrue(changed)
        self.assertEqual("New name", field["translation"])
        self.assertFalse(field["aiGen"])
        self.assertEqual(untouched[0]["moduleCode"], modules[0]["moduleCode"])

    def test_execution_config_discards_unknown_options_and_preserves_valid_options(self):
        config = translation_execution_config_from_dict(
            {
                "selected_languages": ["en", "not-a-language"],
                "selected_modules": ["product_name", "not-a-module"],
                "sales_attr_mode": "ai_translation",
                "long_day_package_template_mode": "throttle",
                "online": False,
            }
        )

        serialized = translation_execution_config_to_dict(config)

        self.assertEqual(["en"], serialized["selected_languages"])
        self.assertEqual(["product_name"], serialized["selected_modules"])
        self.assertEqual("ai_translation", serialized["sales_attr_mode"])
        self.assertEqual("throttle", serialized["long_day_package_template_mode"])
        self.assertFalse(serialized["online"])
        self.assertTrue(default_translation_execution_config().selected_languages)


class TranslationManagementApiAndWorkflowTests(unittest.TestCase):
    def _plan(self):
        row = TranslationTemplateRow(
            row_number=2,
            product_id="1001",
            locale="en-US",
            module_code="ProductInfo",
            field_code="productName",
            field_name="产品名称",
            value_key="translation",
            self_key="name-key",
            origin="原始名称",
            old_translation="Old name",
            target_translation="New name",
        )
        return TranslationDiffPlan(
            row=row,
            product_id="1001",
            locale="en-US",
            module_code="ProductInfo",
            field_code="productName",
            field_name="产品名称",
            self_key="name-key",
            old_value="Old name",
            new_value="New name",
            online=True,
        )

    def test_api_builds_complete_push_payload_and_preserves_unedited_module_data(self):
        client = TranslationApiClient(lambda *_args, **_kwargs: {})
        raw = {
            "translationModules": [
                {
                    "moduleCode": "ProductInfo",
                    "fields": [
                        {
                            "fieldCode": "productName",
                            "selfKey": "name-key",
                            "translation": "Old name",
                            "origin": "原始名称",
                            "aiGen": True,
                        },
                        {
                            "fieldCode": "feeInclude",
                            "selfKey": "fee-key",
                            "translation": "Included",
                            "origin": "费用包含",
                        },
                    ],
                }
            ],
            "tour": {"id": "tour-1"},
        }

        payload = client.build_push_payload("1001", "en-US", raw, [self._plan()], online=True)

        fields = payload["translationModules"][0]["fields"]
        self.assertEqual("New name", fields[0]["translation"])
        self.assertFalse(fields[0]["aiGen"])
        self.assertEqual("Included", fields[1]["translation"])
        self.assertEqual({"id": "tour-1"}, payload["tour"])
        self.assertEqual("1001", payload["productId"])
        self.assertEqual("en-US", payload["locale"])
        self.assertTrue(payload["online"])

    def test_worker_reports_save_success_only_after_readback_matches_target(self):
        plan = self._plan()
        raw = {
            "translationModules": [
                {
                    "moduleCode": "ProductInfo",
                    "fields": [
                        {
                            "fieldCode": "productName",
                            "selfKey": "name-key",
                            "translation": "Old name",
                            "origin": "原始名称",
                        }
                    ],
                }
            ]
        }

        class FakeClient:
            def save_translation(self, *_args, **_kwargs):
                return {}, {"ResponseStatus": {"Ack": "Success"}}

            def load_translation_list(self, *_args, **_kwargs):
                return {
                    "translations": [
                        {
                            "targetLocale": "en-US",
                            "translationModules": [
                                {
                                    "moduleCode": "ProductInfo",
                                    "fields": [
                                        {
                                            "fieldCode": "productName",
                                            "selfKey": "name-key",
                                            "translation": "New name",
                                            "origin": "原始名称",
                                        }
                                    ],
                                }
                            ],
                        }
                    ]
                }

        worker = TranslationWorkflowWorker(
            out_queue=queue.Queue(),
            stop_event=threading.Event(),
            snapshots={
                "1001": build_translation_snapshot_from_response(
                    "1001", ["en-US"], {"translations": [{"targetLocale": "en-US", **raw}]}, retain_raw=True
                )
            },
            pending_plans=[plan],
            client_factory=FakeClient,
        )

        results = worker.run_save()

        self.assertEqual(1, len(results))
        self.assertEqual("succeeded", results[0].status)
        self.assertEqual("New name", results[0].new_value)

    def test_csv_report_keeps_translation_columns_and_user_product_order(self):
        first = self._plan()
        second = copy.deepcopy(first)
        second.product_id = "1002"
        second.row.product_id = "1002"
        second.new_value = "Second product"
        results = [
            TranslationResultRow("1002", "en-US", "ProductInfo", "productName", "产品名称", "name-key", "succeeded", "Old name", "Second product"),
            TranslationResultRow("1001", "en-US", "ProductInfo", "productName", "产品名称", "name-key", "succeeded", "Old name", "New name"),
        ]
        with tempfile.TemporaryDirectory() as directory:
            report = Path(directory) / "translation.csv"
            write_translation_report(str(report), results, product_order={"1001": 0, "1002": 1})
            with report.open(encoding="utf-8-sig", newline="") as handle:
                rows = list(csv.reader(handle))

        self.assertEqual("产品ID", rows[0][0])
        self.assertEqual("修改后译文", rows[0][7])
        self.assertEqual("1001", rows[1][0])
        self.assertEqual("New name", rows[1][7])


if __name__ == "__main__":
    unittest.main()

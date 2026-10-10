# -*- coding: utf-8 -*-
import copy
import os
import threading
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import app
from product_image_workspace_state import (
    copy_site_plan,
    make_product_editor_state,
    workspace_image_from_api,
)
from tests.fixtures.product_image_27_sites import (
    LANGUAGE_SITES,
    make_product_info_27_sites,
)


class WorkspacePayloadTests(unittest.TestCase):
    def setUp(self):
        self.product_info = {
            "productVersion": 12,
            "productBasicInfo": {
                "productName": "keep me",
                "getImageLocaleInfo": {
                    "imageSetting": 2,
                    "allSitesShared": False,
                    "useLanguageCode": True,
                    "images": [
                        {
                            "languageCode": "zh-CN",
                            "languagelocale": "zh-CN",
                            "imageList": [
                                {
                                    "imageId": 1,
                                    "imageUrl": "https://img/1.jpg",
                                    "keepField": "yes",
                                }
                            ],
                        },
                        {
                            "languageCode": "en-US",
                            "languagelocale": "en-US",
                            "imageList": [
                                {
                                    "imageId": 9,
                                    "imageUrl": "https://img/9.jpg",
                                }
                            ],
                        },
                    ],
                },
            },
            "productDescInfo": {"description": "unchanged"},
        }

    def test_payload_replaces_each_site_with_exact_planned_order(self):
        original = copy.deepcopy(self.product_info)
        planned = {
            "zh-CN": [
                workspace_image_from_api(
                    {"imageId": 2, "imageUrl": "https://img/2.jpg"}
                ),
                workspace_image_from_api(
                    {
                        "imageId": 1,
                        "imageUrl": "https://img/1.jpg",
                        "keepField": "yes",
                    }
                ),
            ],
            "en-US": [
                workspace_image_from_api(
                    {"imageId": 9, "imageUrl": "https://img/9.jpg"}
                )
            ],
        }
        payload = app.build_product_info_workspace_image_payload(
            "100",
            self.product_info,
            planned,
        )
        rows = app.product_image_language_rows(payload)
        self.assertEqual(
            [item["imageId"] for item in rows[0]["imageList"]],
            [2, 1],
        )
        self.assertEqual(
            [item["imageId"] for item in rows[1]["imageList"]],
            [9],
        )
        self.assertEqual(rows[0]["imageList"][1]["keepField"], "yes")
        self.assertEqual(payload["productBasicInfo"]["productName"], "keep me")
        self.assertEqual(
            payload["productDescInfo"],
            {"description": "unchanged"},
        )
        self.assertEqual(self.product_info, original)

    def test_unknown_site_is_rejected(self):
        with self.assertRaisesRegex(RuntimeError, "接口当前未返回"):
            app.build_product_info_workspace_image_payload(
                "100",
                self.product_info,
                {
                    "ja-JP": [
                        workspace_image_from_api({"imageId": 3})
                    ]
                },
            )

    def test_trip_image_fallback_becomes_exact_locale_rows(self):
        product_info = {
            "productBasicInfo": {
                "getImageLocaleInfo": {"images": []},
                "tripImageList": [
                    {
                        "locale": "zh-CN",
                        "imageId": 1,
                        "imageUrl": "https://img/1.jpg",
                    },
                    {
                        "locale": "en-US",
                        "imageId": 9,
                        "imageUrl": "https://img/9.jpg",
                    },
                ],
            }
        }
        planned = {
            "zh-CN": [
                workspace_image_from_api(
                    {"imageId": 2, "imageUrl": "https://img/2.jpg"}
                )
            ],
            "en-US": [
                workspace_image_from_api(
                    {"imageId": 9, "imageUrl": "https://img/9.jpg"}
                )
            ],
        }
        payload = app.build_product_info_workspace_image_payload(
            "100",
            product_info,
            planned,
        )
        rows = payload["productBasicInfo"]["getImageLocaleInfo"]["images"]
        self.assertEqual(
            [row["languageCode"] for row in rows],
            ["zh-CN", "en-US"],
        )
        self.assertEqual(rows[0]["imageList"][0]["imageId"], 2)
        self.assertNotIn("_imageRowSource", rows[0])


class WorkspaceVerificationTests(unittest.TestCase):
    def _product_info(self, ids):
        return {
            "productBasicInfo": {
                "getImageLocaleInfo": {
                    "images": [
                        {
                            "languageCode": "zh-CN",
                            "imageList": [
                                {"imageId": image_id}
                                for image_id in ids
                            ],
                        }
                    ]
                }
            }
        }

    def test_exact_ids_and_order_pass(self):
        expected = {
            "zh-CN": [
                workspace_image_from_api({"imageId": 1}),
                workspace_image_from_api({"imageId": 2}),
            ]
        }
        result = app.verify_product_image_workspace(
            expected,
            self._product_info([1, 2]),
        )
        self.assertTrue(result.ok)
        self.assertEqual(result.site_errors, {})

    def test_order_mismatch_fails(self):
        expected = {
            "zh-CN": [
                workspace_image_from_api({"imageId": 1}),
                workspace_image_from_api({"imageId": 2}),
            ]
        }
        result = app.verify_product_image_workspace(
            expected,
            self._product_info([2, 1]),
        )
        self.assertFalse(result.ok)
        self.assertIn("zh-CN", result.site_errors)
        self.assertIn("顺序", result.site_errors["zh-CN"])

    def test_missing_expected_site_fails(self):
        expected = {
            "en-US": [workspace_image_from_api({"imageId": 9})]
        }
        result = app.verify_product_image_workspace(
            expected,
            self._product_info([1]),
        )
        self.assertFalse(result.ok)
        self.assertIn("en-US", result.site_errors)


class WorkspaceSaveTests(unittest.TestCase):
    def _product_info(self, ids, version=1):
        return {
            "productVersion": version,
            "productBasicInfo": {
                "productName": "keep",
                "getImageLocaleInfo": {
                    "images": [
                        {
                            "languageCode": "zh-CN",
                            "imageList": [
                                {"imageId": image_id} for image_id in ids
                            ],
                        }
                    ]
                },
            },
        }

    def _state(self):
        info = self._product_info([1])
        state = make_product_editor_state(
            "100",
            info,
            app.product_image_effective_language_rows(info),
        )
        state.sites["zh-CN"].planned.append(
            workspace_image_from_api({"imageId": 2})
        )
        return state

    def test_strict_save_response_requires_ack_no_errors_and_success_true(self):
        ok = {
            "ResponseStatus": {"Ack": "Success", "Errors": []},
            "responseBaseData": {"success": True},
        }
        self.assertTrue(app.strict_product_image_save_response(ok))
        for bad in (
            {"responseBaseData": {"success": True}},
            {"ResponseStatus": {"Ack": "Success", "Errors": []}},
            {
                "ResponseStatus": {"Ack": "Failure", "Errors": []},
                "responseBaseData": {"success": True},
            },
            {
                "ResponseStatus": {"Ack": "Success", "Errors": ["bad"]},
                "responseBaseData": {"success": True},
            },
        ):
            self.assertFalse(app.strict_product_image_save_response(bad))

    def test_save_rereads_baseline_saves_and_verifies_exact_order(self):
        state = self._state()
        reads = [self._product_info([1], 2), self._product_info([1, 2], 3)]

        class Client:
            saved_payload = None

            def load_product_info_draft(self, product_id, stop_event):
                return reads.pop(0)

            def save_product_info_draft(self, product_id, payload, stop_event):
                self.saved_payload = payload
                return {
                    "ResponseStatus": {"Ack": "Success", "Errors": []},
                    "responseBaseData": {"success": True},
                }

        client = Client()
        result = app.save_and_verify_product_image_workspace(
            client,
            state,
            threading.Event(),
        )
        self.assertTrue(result.ok)
        self.assertEqual(
            [
                item["imageId"]
                for item in app.product_image_language_rows(
                    client.saved_payload
                )[0]["imageList"]
            ],
            [1, 2],
        )
        self.assertEqual(client.saved_payload["productVersion"], 2)

    def test_stale_baseline_aborts_before_save(self):
        state = self._state()

        class Client:
            save_calls = 0

            def load_product_info_draft(self, product_id, stop_event):
                return WorkspaceSaveTests()._product_info([9])

            def save_product_info_draft(self, product_id, payload, stop_event):
                self.save_calls += 1
                return {}

        client = Client()
        with self.assertRaisesRegex(RuntimeError, "线上图片已变化"):
            app.save_and_verify_product_image_workspace(
                client,
                state,
                threading.Event(),
            )
        self.assertEqual(client.save_calls, 0)

    def test_response_failure_aborts_before_verify_read(self):
        state = self._state()

        class Client:
            reads = 0

            def load_product_info_draft(self, product_id, stop_event):
                self.reads += 1
                return WorkspaceSaveTests()._product_info([1])

            def save_product_info_draft(self, product_id, payload, stop_event):
                return {
                    "ResponseStatus": {"Ack": "Success", "Errors": []},
                    "responseBaseData": {"success": False},
                }

        client = Client()
        with self.assertRaisesRegex(RuntimeError, "保存接口返回失败"):
            app.save_and_verify_product_image_workspace(
                client,
                state,
                threading.Event(),
            )
        self.assertEqual(client.reads, 1)

    def test_backend_adapter_loads_uploads_and_exposes_save(self):
        info = self._product_info([1])

        class Client:
            def load_product_info_draft(self, product_id, stop_event):
                return info

            def load_product_currency_context(self, product_id, stop_event):
                return {"currency": product_id}

        client = Client()
        advanced = lambda: None
        backend = app.make_product_image_workspace_backend(
            client,
            open_advanced_config=advanced,
        )
        loaded = backend.load_product("100", threading.Event())
        self.assertEqual(loaded.product_id, "100")
        self.assertEqual(loaded.site_rows[0]["languageCode"], "zh-CN")
        self.assertEqual(loaded.currency_context, {"currency": "100"})
        upload_result = type(
            "Upload",
            (),
            {
                "image_id": "8",
                "image_url": "https://img/8.jpg",
                "image_name": "8.jpg",
            },
        )()
        with patch.object(app, "read_plain_cookie", return_value="cookie"), patch.object(
            app,
            "ctrip_upload_image",
            return_value=upload_result,
        ) as upload:
            image = backend.upload_image("100", app.Path("/tmp/8.jpg"))
        self.assertEqual(image.image_id, "8")
        upload.assert_called_once_with(
            app.Path("/tmp/8.jpg"),
            "100",
            "cookie",
        )
        self.assertIsNotNone(backend.save_and_verify)
        self.assertIs(backend.open_advanced_config, advanced)

    def test_backend_upload_records_an_image_request(self):
        recorded = []
        backend = app.make_product_image_workspace_backend(
            object(),
            request_recorder=recorded.append,
        )
        upload_result = type(
            "Upload",
            (),
            {
                "image_id": "8",
                "image_url": "https://img/8.jpg",
                "image_name": "8.jpg",
            },
        )()

        with patch.object(app, "read_plain_cookie", return_value="cookie"), patch.object(
            app,
            "ctrip_upload_image",
            return_value=upload_result,
        ):
            backend.upload_image("100000001", app.Path("/tmp/8.jpg"))

        self.assertEqual(recorded, ["image"])


class AllSitePreloadAndPayloadTests(unittest.TestCase):
    """Task 1: 锁定 27 站点完整预载与保存契约。"""

    def test_empty_all_placeholder_falls_back_to_trip_image_sites(self):
        product_info = {
            "productBasicInfo": {
                "getImageLocaleInfo": {
                    "images": [
                        {
                            "languageCode": "all",
                            "languagelocale": "all",
                            "imageList": [],
                        }
                    ]
                },
                "tripImageList": [
                    {
                        "locale": "da-DK",
                        "imageId": 300000002,
                        "imageUrl": "https://img/300000002.jpg",
                    },
                    {
                        "locale": "en-US",
                        "imageId": 300000003,
                        "imageUrl": "https://img/300000003.jpg",
                    },
                ],
            }
        }

        rows = app.product_image_effective_language_rows(product_info)

        self.assertEqual(
            [row["languageCode"] for row in rows],
            ["da-DK", "en-US"],
        )
        self.assertEqual(
            [row["imageList"][0]["imageId"] for row in rows],
            [300000002, 300000003],
        )

    def test_id_only_site_rows_do_not_collapse_to_all_trip_fallback(self):
        product_info = {
            "productBasicInfo": {
                "getImageLocaleInfo": {
                    "images": [
                        {
                            "languageCode": "chinese",
                            "languagelocale": "简体中文",
                            "imageList": [{"imageId": 101}],
                        },
                        {
                            "languageCode": "english",
                            "languagelocale": "英语",
                            "imageList": [{"imageId": 202}],
                        },
                    ]
                },
                "tripImageList": [{"imageId": 999}],
            }
        }

        rows = app.product_image_effective_language_rows(product_info)

        self.assertEqual(
            [row["languageCode"] for row in rows],
            ["chinese", "english"],
        )
        self.assertEqual(
            [row["imageList"][0]["imageId"] for row in rows],
            [101, 202],
        )

    def test_effective_rows_preload_all_27_language_sites(self):
        product_info = make_product_info_27_sites()
        rows = app.product_image_effective_language_rows(product_info)
        self.assertEqual(len(rows), 27)
        self.assertEqual(
            [row["languageCode"] for row in rows],
            [code for _label, code in LANGUAGE_SITES],
        )
        self.assertNotEqual(
            rows,
            product_info["productBasicInfo"]["imageList"],
        )

    def test_payload_changes_all_27_sites_and_preserves_unknown_fields(self):
        product_info = make_product_info_27_sites()
        replacement = workspace_image_from_api({
            "imageId": 999001,
            "imageUrl": "https://img.example/new-head.jpg",
            "imageName": "new-head.jpg",
            "imageSource": "ttd",
        })
        planned = {
            code: [replacement]
            for _label, code in LANGUAGE_SITES
        }
        payload = app.build_product_info_workspace_image_payload(
            "100000004",
            product_info,
            planned,
        )
        rows = payload["productBasicInfo"]["getImageLocaleInfo"]["images"]
        self.assertEqual(len(rows), 27)
        self.assertTrue(
            all(row["imageList"][0]["imageId"] == 999001 for row in rows)
        )
        self.assertTrue(
            all(
                row["unknownLocaleField"].startswith("keep-")
                for row in rows
            )
        )
        self.assertEqual(
            payload["productBasicInfo"]["unknownProductField"],
            "keep-product",
        )

    def test_verification_compares_all_27_sites(self):
        original = make_product_info_27_sites(images_per_site=1)
        rows = original["productBasicInfo"]["getImageLocaleInfo"]["images"]
        state = make_product_editor_state("100000004", original, rows)
        verification = app.verify_product_image_workspace(
            state.planned_by_site(),
            original,
        )
        self.assertTrue(verification.ok)
        self.assertEqual(len(verification.actual_by_site), 27)
        for _label, code in LANGUAGE_SITES:
            self.assertIn(code, verification.actual_by_site)

    def test_save_and_verify_round_trip_covers_all_27_sites(self):
        original = make_product_info_27_sites(images_per_site=1)
        replacement_id = 999001

        class Client:
            def __init__(self):
                self.reads = 0
                self.saved_payload = None

            def load_product_info_draft(self, product_id, stop_event):
                self.reads += 1
                if self.reads == 1:
                    return copy.deepcopy(original)
                return copy.deepcopy(self.saved_payload)

            def save_product_info_draft(self, product_id, payload, stop_event):
                self.saved_payload = copy.deepcopy(payload)
                return {
                    "ResponseStatus": {"Ack": "Success", "Errors": []},
                    "responseBaseData": {"success": True},
                }

        rows = original["productBasicInfo"]["getImageLocaleInfo"]["images"]
        state = make_product_editor_state("100000004", original, rows)
        replacement = workspace_image_from_api({
            "imageId": replacement_id,
            "imageUrl": "https://img.example/new-head.jpg",
            "imageName": "new-head.jpg",
        })
        # First copy source to all, then set source itself
        copy_site_plan(
            state,
            "chinese",
            [code for code in state.sites if code != "chinese"],
        )
        state.sites["chinese"].planned = [replacement]
        copy_site_plan(
            state,
            "chinese",
            [code for code in state.sites if code != "chinese"],
        )

        verification = app.save_and_verify_product_image_workspace(
            Client(),
            state,
            threading.Event(),
        )
        self.assertTrue(verification.ok)
        self.assertEqual(len(verification.actual_by_site), 27)
        self.assertTrue(all(
            keys == (("id", str(replacement_id)),)
            for keys in verification.actual_by_site.values()
        ))


if __name__ == "__main__":
    unittest.main()

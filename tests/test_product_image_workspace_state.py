# -*- coding: utf-8 -*-
import unittest

from product_image_workspace_state import (
    ProductImageEditHistory,
    add_image_to_site,
    copy_site_plan,
    make_product_editor_state,
    move_image_in_site,
    remove_image_from_site,
    restore_product,
    site_image_diff,
    workspace_image_from_api,
    workspace_image_key,
)
from tests.fixtures.product_image_27_sites import (
    LANGUAGE_SITES,
    make_product_info_27_sites,
)


class WorkspaceImageIdentityTests(unittest.TestCase):
    def test_image_id_is_preferred_over_url(self):
        image = workspace_image_from_api(
            {
                "imageId": 101,
                "imageUrl": " https://img.example/a.jpg ",
                "imageName": "a.jpg",
            }
        )
        self.assertEqual(workspace_image_key(image), ("id", "101"))

    def test_url_is_fallback_identity(self):
        image = workspace_image_from_api(
            {"imageUrl": "https://img.example/a.jpg"}
        )
        self.assertEqual(
            workspace_image_key(image),
            ("url", "https://img.example/a.jpg"),
        )

    def test_missing_id_and_url_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "imageId/imageUrl"):
            workspace_image_from_api({"imageName": "broken.jpg"})


class ProductStateInitializationTests(unittest.TestCase):
    def test_planned_sequences_are_deep_copies_of_baseline(self):
        raw = {"productBasicInfo": {}, "productVersion": 7}
        rows = [
            {
                "languageCode": "zh-CN",
                "languagelocale": "zh-CN",
                "imageList": [
                    {"imageId": 1, "imageUrl": "https://img/1.jpg"}
                ],
            }
        ]
        state = make_product_editor_state("100", raw, rows)
        self.assertEqual(
            state.sites["zh-CN"].baseline,
            state.sites["zh-CN"].planned,
        )
        self.assertIsNot(
            state.sites["zh-CN"].baseline,
            state.sites["zh-CN"].planned,
        )
        state.sites["zh-CN"].planned.clear()
        self.assertEqual(len(state.sites["zh-CN"].baseline), 1)
        self.assertTrue(state.dirty)

    def test_input_product_info_is_copied(self):
        raw = {
            "productBasicInfo": {"name": "before"},
            "productVersion": 7,
        }
        state = make_product_editor_state("100", raw, [])
        raw["productBasicInfo"]["name"] = "after"
        self.assertEqual(
            state.product_info["productBasicInfo"]["name"],
            "before",
        )

    def test_currency_context_is_kept_for_payload_adapter(self):
        marker = object()
        state = make_product_editor_state(
            "100",
            {"productBasicInfo": {}},
            [],
            currency_context=marker,
        )
        self.assertIs(state.currency_context, marker)

    def test_state_exposes_independent_baseline_and_planned_site_maps(self):
        state = make_product_editor_state(
            "100",
            {},
            [{"languageCode": "zh-CN", "imageList": [{"imageId": 1}]}],
        )
        baseline = state.baseline_by_site()
        planned = state.planned_by_site()
        baseline["zh-CN"].clear()
        planned["zh-CN"].clear()
        self.assertEqual(len(state.sites["zh-CN"].baseline), 1)
        self.assertEqual(len(state.sites["zh-CN"].planned), 1)


class ProductImageEditTests(unittest.TestCase):
    def setUp(self):
        rows = [
            {
                "languageCode": "zh-CN",
                "imageList": [{"imageId": 1}, {"imageId": 2}],
            },
            {
                "languageCode": "en-US",
                "imageList": [{"imageId": 9}],
            },
        ]
        self.state = make_product_editor_state(
            "100",
            {"productBasicInfo": {}},
            rows,
        )
        self.new_image = workspace_image_from_api(
            {"imageId": 3, "imageUrl": "https://img/3.jpg"}
        )

    def test_add_and_remove_report_member_diff(self):
        add_image_to_site(self.state, "zh-CN", self.new_image, 1)
        removed = remove_image_from_site(self.state, "zh-CN", 0)
        self.assertEqual(removed.image_id, "1")
        diff = site_image_diff(self.state.sites["zh-CN"])
        self.assertEqual(diff.added, (("id", "3"),))
        self.assertEqual(diff.removed, (("id", "1"),))
        self.assertFalse(diff.order_changed)

    def test_move_reports_order_change(self):
        move_image_in_site(self.state, "zh-CN", 1, 0)
        diff = site_image_diff(self.state.sites["zh-CN"])
        self.assertEqual(diff.added, ())
        self.assertEqual(diff.removed, ())
        self.assertTrue(diff.order_changed)

    def test_duplicate_image_is_rejected_within_same_site(self):
        duplicate = workspace_image_from_api(
            {"imageId": 1, "imageUrl": "https://other/1.jpg"}
        )
        with self.assertRaisesRegex(ValueError, "已在站点"):
            add_image_to_site(self.state, "zh-CN", duplicate)

    def test_copy_site_and_restore_product(self):
        add_image_to_site(self.state, "zh-CN", self.new_image)
        copy_site_plan(self.state, "zh-CN", ["en-US"])
        self.assertEqual(
            [image.image_id for image in self.state.sites["en-US"].planned],
            ["1", "2", "3"],
        )
        restore_product(self.state)
        self.assertFalse(self.state.dirty)

    def test_history_undo_redo_restores_all_sites(self):
        history = ProductImageEditHistory(self.state)
        history.perform(
            lambda: add_image_to_site(
                self.state,
                "zh-CN",
                self.new_image,
            )
        )
        self.assertTrue(self.state.dirty)
        self.assertTrue(history.undo())
        self.assertFalse(self.state.dirty)
        self.assertTrue(history.redo())
        self.assertTrue(self.state.dirty)

    def test_history_ignores_noop_and_honors_limit(self):
        history = ProductImageEditHistory(self.state, limit=1)
        history.perform(lambda: None)
        self.assertFalse(history.undo())
        history.perform(
            lambda: move_image_in_site(self.state, "zh-CN", 1, 0)
        )
        history.perform(
            lambda: move_image_in_site(self.state, "zh-CN", 1, 0)
        )
        self.assertTrue(history.undo())
        self.assertFalse(history.undo())


class AllSiteCopyTests(unittest.TestCase):
    """Task 2: 全站点复制状态测试。"""

    def test_copy_one_head_image_sequence_to_all_27_sites_is_undoable(self):
        info = make_product_info_27_sites(images_per_site=2)
        state = make_product_editor_state(
            "100000004",
            info,
            info["productBasicInfo"]["getImageLocaleInfo"]["images"],
        )
        history = ProductImageEditHistory(state)
        source_code = "chinese"
        targets = [code for code in state.sites if code != source_code]
        history.perform(lambda: copy_site_plan(state, source_code, targets))
        expected = [
            workspace_image_key(image)
            for image in state.sites[source_code].planned
        ]
        self.assertEqual(len(state.sites), 27)
        self.assertTrue(all(
            [workspace_image_key(image) for image in site.planned] == expected
            for site in state.sites.values()
        ))
        self.assertTrue(history.undo())
        self.assertEqual(
            state.sites["english"].planned[0].image_name,
            "english-1.jpg",
        )


if __name__ == "__main__":
    unittest.main()

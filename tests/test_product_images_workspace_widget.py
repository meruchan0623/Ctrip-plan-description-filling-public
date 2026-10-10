# -*- coding: utf-8 -*-
import os
import time
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QApplication, QDialog, QFrame, QLabel, QWidget

from product_images.workspace import (
    LoadedProductImages,
    ProductImageWorkspace,
    ProductImageWorkspaceBackend,
)
from tests.fixtures.product_image_27_sites import make_product_info_27_sites


class ProductImageWorkspaceWidgetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_workspace_is_embeddable_and_has_no_legacy_advanced_button(self):
        backend = ProductImageWorkspaceBackend(load_product=lambda *_args: None)

        workspace = ProductImageWorkspace(backend)
        try:
            self.assertIsInstance(workspace, QWidget)
            self.assertFalse(hasattr(workspace, "advanced_config_btn"))
            self.assertEqual(workspace.windowTitle(), "")
        finally:
            workspace.shutdown()
            workspace.deleteLater()

    def test_workspace_uses_the_same_staged_workflow_language_as_peer_features(self):
        workspace = ProductImageWorkspace(
            ProductImageWorkspaceBackend(load_product=lambda *_args: None)
        )
        try:
            header = workspace.findChild(QFrame, "productImageWorkflowHeader")
            read_stage = workspace.findChild(QFrame, "productImageReadStage")
            results_stage = workspace.findChild(QFrame, "productImageResultsStage")
            delivery_stage = workspace.findChild(QFrame, "productImageDeliveryStage")

            self.assertIsNotNone(header)
            self.assertIsNotNone(read_stage)
            self.assertIsNotNone(results_stage)
            self.assertIsNotNone(delivery_stage)
            self.assertTrue(read_stage.isAncestorOf(workspace.product_ids_edit))
            self.assertTrue(read_stage.isAncestorOf(workspace.load_btn))
            self.assertTrue(results_stage.isAncestorOf(workspace.tabs))
            self.assertTrue(delivery_stage.isAncestorOf(workspace.submit_current_btn))
            self.assertTrue(delivery_stage.isAncestorOf(workspace.submit_all_btn))
            line_height = workspace.product_ids_edit.fontMetrics().lineSpacing()
            self.assertEqual(
                workspace.product_ids_edit.minimumHeight(),
                workspace.product_ids_edit.maximumHeight(),
            )
            self.assertGreaterEqual(
                workspace.product_ids_edit.viewport().height(),
                line_height * 3,
            )
            self.assertLess(
                workspace.product_ids_edit.viewport().height(),
                line_height * 4,
            )
            header_text = " ".join(
                label.text() for label in header.findChildren(QLabel)
            )
            self.assertIn("产品图片工作台", header_text)
            self.assertIn("读取 → 上传 → 编排 → 保存回读", header_text)
        finally:
            workspace.shutdown()
            workspace.deleteLater()

    def test_workspace_operation_guide_explains_the_real_four_step_gate(self):
        workspace = ProductImageWorkspace(
            ProductImageWorkspaceBackend(load_product=lambda *_args: None)
        )
        try:
            self.assertEqual(
                workspace.guide_btn.property("productImageActionRole"),
                "guide",
            )

            dialog = workspace.open_operation_guide()
            self.assertIsInstance(dialog, QDialog)
            self.assertEqual(
                dialog.objectName(),
                "productImageOperationGuideDialog",
            )
            guide_text = " ".join(
                label.text() for label in dialog.findChildren(QLabel)
            )
            for expected in (
                "01 读取产品",
                "02 选择并上传",
                "03 拖入具体站点",
                "04 保存并回读",
                "只有显示“已上传”的候选图片才能拖入第三栏",
            ):
                self.assertIn(expected, guide_text)
            dialog.close()
        finally:
            workspace.shutdown()
            workspace.deleteLater()

    def test_key_workflow_buttons_expose_distinct_semantic_roles(self):
        def load_product(product_id, _stop_event):
            return LoadedProductImages(
                product_id=product_id,
                product_info={},
                site_rows=[
                    {
                        "languageCode": "Danish",
                        "languagelocale": "丹麦语",
                        "imageList": [{"imageId": 1}],
                    }
                ],
            )

        workspace = ProductImageWorkspace(
            ProductImageWorkspaceBackend(load_product=load_product)
        )
        try:
            workspace.load_products(["100000001"])
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline:
                self.app.processEvents()
                if "100000001" in workspace.product_panes:
                    break
                time.sleep(0.01)

            candidate_panel = workspace.product_panes[
                "100000001"
            ].candidate_panel
            self.assertEqual(
                workspace.load_btn.property("productImageActionRole"),
                "read",
            )
            self.assertEqual(
                candidate_panel.choose_btn.property("productImageActionRole"),
                "choose",
            )
            for button in (
                candidate_panel.upload_selected_btn,
                candidate_panel.upload_all_btn,
            ):
                self.assertEqual(
                    button.property("productImageActionRole"),
                    "upload",
                )
            for button in (
                workspace.submit_current_btn,
                workspace.submit_all_btn,
            ):
                self.assertEqual(
                    button.property("productImageActionRole"),
                    "commit",
                )
            self.assertIn("已上传", candidate_panel.drop_hint.text())
        finally:
            workspace.shutdown()
            workspace.deleteLater()

    def test_workspace_exposes_lifecycle_and_focus_api(self):
        backend = ProductImageWorkspaceBackend(load_product=lambda *_args: None)
        workspace = ProductImageWorkspace(backend)
        try:
            self.assertFalse(workspace.has_unsaved_changes())
            self.assertEqual(workspace.dirty_product_ids(), ())
            self.assertIsInstance(workspace._event_timer, QTimer)
            workspace.focus_product_input()
            self.assertIs(workspace.product_ids_edit, workspace.focusWidget())
            self.assertTrue(workspace.request_close(workspace))
            self.assertTrue(workspace._closed)
            self.assertFalse(workspace._event_timer.isActive())
        finally:
            workspace.shutdown()
            workspace.deleteLater()

    def test_workspace_keeps_multiple_products_in_independent_tabs(self):
        def load_product(product_id, _stop_event):
            return LoadedProductImages(
                product_id=product_id,
                product_info={"productVersion": 1},
                site_rows=[
                    {
                        "languageCode": "zh-CN",
                        "imageList": [{"imageId": int(product_id)}],
                    }
                ],
            )

        workspace = ProductImageWorkspace(
            ProductImageWorkspaceBackend(load_product=load_product)
        )
        try:
            workspace.load_products(["100", "200", "100"])
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline:
                self.app.processEvents()
                if len(workspace.product_panes) == 2:
                    break
                time.sleep(0.01)
            self.assertEqual(workspace.product_order, ["100", "200"])
            self.assertEqual(set(workspace.product_panes), {"100", "200"})
            workspace.product_states["100"].sites["zh-CN"].planned.clear()
            self.assertEqual(
                len(workspace.product_states["200"].sites["zh-CN"].planned),
                1,
            )
        finally:
            workspace.shutdown()
            workspace.deleteLater()

    def test_widget_close_cancels_upload_coordinators(self):
        canceled = []

        class Coordinator:
            def cancel(self):
                canceled.append(True)

        workspace = ProductImageWorkspace(
            ProductImageWorkspaceBackend(load_product=lambda *_args: None)
        )
        try:
            workspace.upload_coordinators["100"] = Coordinator()
            workspace.close()
            self.assertEqual(canceled, [True])
            self.assertTrue(workspace._closed)
        finally:
            workspace.shutdown()
            workspace.deleteLater()

    def test_workspace_preloads_all_27_sites_for_one_product(self):
        info = make_product_info_27_sites()

        def load_product(product_id, _stop_event):
            return LoadedProductImages(
                product_id=product_id,
                product_info=info,
                site_rows=info["productBasicInfo"]["getImageLocaleInfo"]["images"],
            )

        workspace = ProductImageWorkspace(
            ProductImageWorkspaceBackend(load_product=load_product)
        )
        try:
            workspace.load_products(["100000004"])
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline:
                self.app.processEvents()
                pane = workspace.product_panes.get("100000004")
                if pane is not None:
                    break
                time.sleep(0.01)
            pane = workspace.product_panes["100000004"]
            self.assertEqual(len(pane.state.sites), 27)
            self.assertEqual(len(pane.site_panels), 27)
        finally:
            workspace.shutdown()
            workspace.deleteLater()

    def test_runtime_status_keeps_image_request_stats_after_loading(self):
        def load_product(product_id, _stop_event):
            return LoadedProductImages(
                product_id=product_id,
                product_info={},
                site_rows=[],
            )

        workspace = ProductImageWorkspace(
            ProductImageWorkspaceBackend(load_product=load_product)
        )
        try:
            workspace.set_request_stats_text(
                "请求 累计 7/2 | 今日 3/1 | 本次 1/0"
            )
            workspace.load_products(["100000001"])
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline:
                self.app.processEvents()
                if "100000001" in workspace.product_panes:
                    break
                time.sleep(0.01)

            self.assertIn("已读取 1 / 1 个产品", workspace.status_label.text())
            self.assertTrue(
                workspace.status_label.text().endswith(
                    "请求 累计 7/2 | 今日 3/1 | 本次 1/0"
                )
            )
        finally:
            workspace.shutdown()
            workspace.deleteLater()

    def test_load_failure_emits_one_image_request_error(self):
        def load_product(_product_id, _stop_event):
            raise RuntimeError("request failed")

        workspace = ProductImageWorkspace(
            ProductImageWorkspaceBackend(load_product=load_product)
        )
        failures = []
        workspace.request_failed.connect(
            lambda area, count: failures.append((area, count))
        )
        try:
            workspace.load_products(["100000001"])
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline and not failures:
                self.app.processEvents()
                time.sleep(0.01)

            self.assertEqual(failures, [("image", 1)])
        finally:
            workspace.shutdown()
            workspace.deleteLater()


if __name__ == "__main__":
    unittest.main()

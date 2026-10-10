# -*- coding: utf-8 -*-
import os
import tempfile
import threading
import time
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QImage
from PyQt6.QtWidgets import QApplication, QMessageBox, QPushButton

import app as app_module
from product_image_workspace import (
    WORKSPACE_IMAGE_MIME,
    ImageCardList,
    LoadedProductImages,
    ProductImageEditorPane,
    SitePlanPanel,
    ProductUploadCoordinator,
    ProductImageWorkspaceBackend,
    ProductImageWorkspace,
    RemoteThumbnailCache,
    CandidateImagePanel,
    decode_drag_payload,
    encode_drag_payload,
    inspect_local_image,
    workspace_image_detail_text,
    product_image_change_summary,
)
from product_image_workspace_state import (
    CandidateImage,
    LocalImageInspection,
    add_candidate,
    candidate_path_key,
    make_product_editor_state,
    workspace_image_from_api,
)
from tests.fixtures.product_image_27_sites import make_product_info_27_sites


QT_APP = QApplication.instance() or QApplication([])


class LocalImageInspectionTests(unittest.TestCase):
    def _image(
        self,
        width: int,
        height: int,
        suffix: str = ".jpg",
    ) -> Path:
        handle = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
        handle.close()
        path = Path(handle.name)
        self.addCleanup(lambda: path.unlink(missing_ok=True))
        image = QImage(width, height, QImage.Format.Format_RGB32)
        image.fill(QColor("#336699"))
        self.assertTrue(image.save(str(path)))
        return path

    def test_recommended_ratio_has_no_warning(self):
        result = inspect_local_image(self._image(1080, 608))
        self.assertTrue(result.allowed)
        self.assertEqual((result.width, result.height), (1080, 608))
        self.assertEqual(result.warning, "")
        self.assertEqual(result.mime_type, "image/jpeg")

    def test_small_or_wrong_ratio_is_warning_not_hard_failure(self):
        result = inspect_local_image(self._image(600, 600))
        self.assertTrue(result.allowed)
        self.assertIn("建议", result.warning)
        self.assertIn("16:9", result.warning)

    def test_invalid_file_is_rejected(self):
        handle = tempfile.NamedTemporaryFile(suffix=".jpg", delete=False)
        handle.write(b"not-image")
        handle.close()
        path = Path(handle.name)
        self.addCleanup(lambda: path.unlink(missing_ok=True))
        result = inspect_local_image(path)
        self.assertFalse(result.allowed)
        self.assertTrue(result.error)

    def test_missing_file_is_rejected_without_secondary_exception(self):
        path = Path(tempfile.gettempdir()) / "missing-workspace-image.jpg"
        path.unlink(missing_ok=True)
        result = inspect_local_image(path)
        self.assertFalse(result.allowed)
        self.assertIn("不存在", result.error)

    def test_candidate_is_deduplicated_within_product(self):
        inspection = inspect_local_image(self._image(1080, 608))
        state = make_product_editor_state(
            "100",
            {"productBasicInfo": {}},
            [],
        )
        candidate = add_candidate(state, inspection)
        self.assertEqual(candidate.status, "local")
        with self.assertRaisesRegex(ValueError, "已在候选区"):
            add_candidate(state, inspection)

    def test_warning_candidate_remains_uploadable(self):
        inspection = inspect_local_image(self._image(600, 600))
        state = make_product_editor_state(
            "100",
            {"productBasicInfo": {}},
            [],
        )
        candidate = add_candidate(state, inspection)
        self.assertEqual(candidate.status, "warning")
        self.assertTrue(candidate.warning)


class RemoteThumbnailCacheTests(unittest.TestCase):
    def test_remote_thumbnail_is_loaded_off_thread_and_cached(self):
        handle = tempfile.NamedTemporaryFile(suffix=".jpg", delete=False)
        handle.close()
        path = Path(handle.name)
        self.addCleanup(lambda: path.unlink(missing_ok=True))
        image = QImage(320, 180, QImage.Format.Format_RGB32)
        image.fill(QColor("#24567a"))
        self.assertTrue(image.save(str(path)))
        calls = []
        worker_threads = []

        def fetch(url):
            calls.append(url)
            worker_threads.append(threading.get_ident())
            return path.read_bytes()

        cache = RemoteThumbnailCache(fetch=fetch)
        self.addCleanup(cache.close)
        changed = []
        cache.changed.connect(changed.append)
        main_thread = threading.get_ident()
        self.assertTrue(cache.request("https://img/1.jpg"))
        self.assertFalse(cache.request("https://img/1.jpg"))
        deadline = time.monotonic() + 2
        while cache.icon("https://img/1.jpg").isNull() and time.monotonic() < deadline:
            QT_APP.processEvents()
            time.sleep(0.01)
        self.assertFalse(cache.icon("https://img/1.jpg").isNull())
        self.assertEqual(calls, ["https://img/1.jpg"])
        self.assertNotEqual(worker_threads, [main_thread])
        self.assertEqual(changed, ["https://img/1.jpg"])


class ProductImageEditorPaneTests(unittest.TestCase):
    def _state(self):
        return make_product_editor_state(
            "100",
            {"productBasicInfo": {}},
            [
                {
                    "languageCode": "zh-CN",
                    "languagelocale": "简体中文",
                    "imageList": [{"imageId": 1}],
                },
                {
                    "languageCode": "en-US",
                    "languagelocale": "English",
                    "imageList": [{"imageId": 9}],
                },
            ],
        )

    def test_pane_has_three_named_columns_and_site_groups(self):
        pane = ProductImageEditorPane(self._state())
        self.addCleanup(pane.close)
        self.assertEqual(pane.online_title.text(), "① 当前线上图片")
        self.assertEqual(pane.candidate_title.text(), "② 当前产品候选图片")
        self.assertEqual(pane.planned_title.text(), "③ 待提交配置")
        self.assertEqual(set(pane.site_panels), {"zh-CN", "en-US"})
        self.assertEqual(pane.splitter.count(), 3)
        self.assertFalse(pane.splitter.childrenCollapsible())
        pane.resize(1200, 720)
        pane.show()
        QT_APP.processEvents()
        column_widths = pane.splitter.sizes()
        self.assertGreater(
            column_widths[2],
            column_widths[0],
        )
        self.assertGreater(
            column_widths[2],
            column_widths[1],
        )

    def test_site_plan_actions_fit_a_compact_editor_column(self):
        state = self._state()
        panel = SitePlanPanel(
            "100",
            state.sites["zh-CN"],
            lambda *_args: True,
            lambda *_args: True,
            lambda: True,
            lambda: None,
            lambda *_args: None,
        )
        self.addCleanup(panel.close)

        panel.show()
        QT_APP.processEvents()

        self.assertLessEqual(panel.minimumSizeHint().width(), 360)

    def test_three_columns_use_source_and_target_card_modes(self):
        pane = ProductImageEditorPane(self._state())
        self.addCleanup(pane.close)

        self.assertEqual(
            pane.online_image_lists["zh-CN"].property("displayMode"),
            "sequence",
        )
        self.assertEqual(
            pane.candidate_panel.image_list.property("displayMode"),
            "grid",
        )
        self.assertEqual(
            pane.site_panels["zh-CN"].image_list.property("displayMode"),
            "sequence",
        )

    def test_workspace_exposes_semantic_column_card_and_site_states(self):
        pane = ProductImageEditorPane(self._state())
        self.addCleanup(pane.close)

        self.assertEqual(pane.online_panel.property("columnRole"), "online")
        self.assertEqual(
            pane.candidate_container.property("columnRole"),
            "candidate",
        )
        self.assertEqual(
            pane.planned_container.property("columnRole"),
            "planned",
        )
        self.assertEqual(
            pane.online_image_lists["zh-CN"].property("workspaceCardRole"),
            "online",
        )
        self.assertEqual(
            pane.candidate_panel.image_list.property("workspaceCardRole"),
            "candidate",
        )
        site_panel = pane.site_panels["zh-CN"]
        self.assertEqual(
            site_panel.image_list.property("workspaceCardRole"),
            "planned",
        )
        self.assertEqual(site_panel.property("sitePlanState"), "clean")

        site_panel.site.planned.append(
            workspace_image_from_api({"imageId": 77})
        )
        site_panel.refresh()
        self.assertEqual(site_panel.property("sitePlanState"), "changed")

    def test_online_and_site_lists_show_one_complete_card_row(self):
        state = self._state()
        second_image = workspace_image_from_api({"imageId": 2})
        state.sites["zh-CN"].baseline.append(second_image)
        state.sites["zh-CN"].planned.append(second_image)
        pane = ProductImageEditorPane(state)
        self.addCleanup(pane.close)
        pane.resize(1200, 720)
        pane.show()
        QT_APP.processEvents()

        online_list = pane.online_image_lists["zh-CN"]
        site_list = pane.site_panels["zh-CN"].image_list
        self.assertGreaterEqual(
            online_list.viewport().height(),
            online_list.gridSize().height(),
        )
        self.assertEqual(online_list.verticalScrollBar().maximum(), 0)
        self.assertGreaterEqual(
            site_list.viewport().height(),
            site_list.gridSize().height(),
        )

    def test_site_plan_buttons_do_not_replace_site_code_with_checked_state(self):
        pane = ProductImageEditorPane(self._state())
        self.addCleanup(pane.close)
        copied = []
        restored = []
        pane.choose_copy_targets = (
            lambda site_code: copied.append(site_code) or True
        )
        pane.restore_site_plan = restored.append

        panel = pane.site_panels["zh-CN"]
        buttons = {
            button.text(): button
            for button in panel.findChildren(QPushButton)
        }
        buttons["复制到其他站点"].click()
        buttons["恢复本站"].click()

        self.assertEqual(copied, ["zh-CN"])
        self.assertEqual(restored, ["zh-CN"])

    def test_online_and_planned_cards_receive_remote_thumbnails(self):
        handle = tempfile.NamedTemporaryFile(suffix=".jpg", delete=False)
        handle.close()
        path = Path(handle.name)
        self.addCleanup(lambda: path.unlink(missing_ok=True))
        image = QImage(320, 180, QImage.Format.Format_RGB32)
        image.fill(QColor("#24567a"))
        self.assertTrue(image.save(str(path)))
        state = self._state()
        state.sites["zh-CN"].baseline[0] = workspace_image_from_api(
            {"imageId": 1, "imageUrl": "https://img/1.jpg"}
        )
        state.sites["zh-CN"].planned[0] = state.sites["zh-CN"].baseline[0]
        pane = ProductImageEditorPane(
            state,
            thumbnail_fetch=lambda _url: path.read_bytes(),
        )
        self.addCleanup(pane.close)
        deadline = time.monotonic() + 2
        while (
            pane.online_image_lists["zh-CN"].item(0).icon().isNull()
            and time.monotonic() < deadline
        ):
            QT_APP.processEvents()
            time.sleep(0.01)
        self.assertFalse(
            pane.online_image_lists["zh-CN"].item(0).icon().isNull()
        )
        self.assertFalse(
            pane.site_panels["zh-CN"].image_list.item(0).icon().isNull()
        )

    def test_open_image_detail_shows_interface_fields(self):
        pane = ProductImageEditorPane(self._state())
        self.addCleanup(pane.close)
        image = pane.state.sites["zh-CN"].planned[0]
        detail = pane.open_image_detail(image)
        self.addCleanup(detail.close)
        text = detail.findChild(app_module.QTextEdit).toPlainText()
        self.assertIn("imageId: 1", text)

    def test_unuploaded_candidate_cannot_be_added(self):
        pane = ProductImageEditorPane(self._state())
        self.addCleanup(pane.close)
        path = Path("/tmp/workspace-local.jpg")
        key = candidate_path_key(path)
        pane.state.candidates[key] = CandidateImage(
            path=path,
            status="local",
        )
        self.assertFalse(
            pane.add_candidate_to_site(key, "zh-CN", 0)
        )
        self.assertEqual(
            [image.image_id for image in pane.state.sites["zh-CN"].planned],
            ["1"],
        )

    def test_remove_candidates_keeps_uploading_item_and_removes_safe_items(self):
        pane = ProductImageEditorPane(self._state())
        self.addCleanup(pane.close)
        local = candidate_path_key("/tmp/local-remove.jpg")
        active = candidate_path_key("/tmp/active-upload.jpg")
        pane.state.candidates[local] = CandidateImage(
            path=Path(local), status="local"
        )
        pane.state.candidates[active] = CandidateImage(
            path=Path(active), status="uploading"
        )
        removed = pane.remove_candidates([local, active])
        self.assertEqual(removed, 1)
        self.assertNotIn(local, pane.state.candidates)
        self.assertIn(active, pane.state.candidates)

    def test_uploaded_candidate_can_be_added_and_undone(self):
        pane = ProductImageEditorPane(self._state())
        self.addCleanup(pane.close)
        path = Path("/tmp/workspace-uploaded.jpg")
        key = candidate_path_key(path)
        pane.state.candidates[key] = CandidateImage(
            path=path,
            status="uploaded",
            uploaded=workspace_image_from_api(
                {
                    "imageId": 2,
                    "imageUrl": "https://img/2.jpg",
                    "imageName": "2.jpg",
                }
            ),
        )
        changed = []
        pane.state_changed.connect(changed.append)
        self.assertTrue(
            pane.add_candidate_to_site(key, "zh-CN", 1)
        )
        self.assertEqual(
            [image.image_id for image in pane.state.sites["zh-CN"].planned],
            ["1", "2"],
        )
        self.assertEqual(changed, ["100"])
        self.assertTrue(pane.undo())
        self.assertEqual(
            [image.image_id for image in pane.state.sites["zh-CN"].planned],
            ["1"],
        )

    def test_move_and_restore_update_site_summary(self):
        state = self._state()
        state.sites["zh-CN"].planned.append(
            workspace_image_from_api({"imageId": 2})
        )
        pane = ProductImageEditorPane(state)
        self.addCleanup(pane.close)
        pane.move_site_image("zh-CN", 1, 0)
        self.assertIn("已修改", pane.site_panels["zh-CN"].title.text())
        pane.restore_site_plan("zh-CN")
        self.assertIn("未修改", pane.site_panels["zh-CN"].title.text())

    def test_product_change_summary_lists_site_level_diff(self):
        state = self._state()
        state.sites["zh-CN"].planned.clear()
        summary = product_image_change_summary(state)
        self.assertIn("产品 100", summary)
        self.assertIn("zh-CN", summary)
        self.assertIn("删除 1", summary)

    def test_remove_selected_and_copy_site_to_other_sites_are_undoable(self):
        pane = ProductImageEditorPane(self._state())
        self.addCleanup(pane.close)
        self.assertTrue(pane.remove_site_image("zh-CN", 0))
        self.assertEqual(
            [image.image_id for image in pane.state.sites["zh-CN"].planned],
            [],
        )
        self.assertTrue(pane.copy_site_to_other_sites("zh-CN"))
        self.assertEqual(
            [image.image_id for image in pane.state.sites["en-US"].planned],
            [],
        )
        self.assertTrue(pane.undo())
        self.assertEqual(
            [image.image_id for image in pane.state.sites["en-US"].planned],
            ["9"],
        )

    def test_copy_site_to_selected_targets_does_not_change_unselected_site(self):
        state = make_product_editor_state(
            "100",
            {},
            [
                {"languageCode": "zh-CN", "imageList": [{"imageId": 1}]},
                {"languageCode": "en-US", "imageList": [{"imageId": 9}]},
                {"languageCode": "ja-JP", "imageList": [{"imageId": 7}]},
            ],
        )
        pane = ProductImageEditorPane(state)
        self.addCleanup(pane.close)
        self.assertTrue(pane.copy_site_to_sites("zh-CN", ["en-US"]))
        self.assertEqual(
            [image.image_id for image in state.sites["en-US"].planned],
            ["1"],
        )
        self.assertEqual(
            [image.image_id for image in state.sites["ja-JP"].planned],
            ["7"],
        )

    def test_candidate_drag_payload_adds_only_to_same_product(self):
        pane = ProductImageEditorPane(self._state())
        self.addCleanup(pane.close)
        path = Path("/tmp/workspace-drag.jpg")
        key = candidate_path_key(path)
        pane.state.candidates[key] = CandidateImage(
            path=path,
            status="uploaded",
            uploaded=workspace_image_from_api({"imageId": 2}),
        )
        payload = encode_drag_payload(
            kind="candidate",
            product_id="100",
            source=key,
        )
        self.assertTrue(
            pane.handle_workspace_drop(payload, "en-US", 1)
        )
        self.assertEqual(
            [image.image_id for image in pane.state.sites["en-US"].planned],
            ["9", "2"],
        )
        wrong_product = encode_drag_payload(
            kind="candidate",
            product_id="200",
            source=key,
        )
        self.assertFalse(
            pane.handle_workspace_drop(wrong_product, "zh-CN", 0)
        )

    def test_site_drag_reorders_same_site_and_copies_to_other_site(self):
        pane = ProductImageEditorPane(self._state())
        self.addCleanup(pane.close)
        pane.state.sites["zh-CN"].planned.append(
            workspace_image_from_api({"imageId": 2})
        )
        reorder = encode_drag_payload(
            kind="site",
            product_id="100",
            source="zh-CN",
            index=1,
        )
        self.assertTrue(
            pane.handle_workspace_drop(reorder, "zh-CN", 0)
        )
        self.assertEqual(
            [image.image_id for image in pane.state.sites["zh-CN"].planned],
            ["2", "1"],
        )
        copy_payload = encode_drag_payload(
            kind="site",
            product_id="100",
            source="zh-CN",
            index=0,
        )
        self.assertTrue(
            pane.handle_workspace_drop(copy_payload, "en-US", 1)
        )
        self.assertEqual(
            [image.image_id for image in pane.state.sites["en-US"].planned],
            ["9", "2"],
        )

    def test_online_drag_uses_baseline_image_not_current_planned_index(self):
        pane = ProductImageEditorPane(self._state())
        self.addCleanup(pane.close)
        pane.state.sites["zh-CN"].planned.clear()
        payload = encode_drag_payload("online", "100", "zh-CN", 0)
        self.assertTrue(pane.handle_workspace_drop(payload, "zh-CN", 0))
        self.assertEqual(
            [image.image_id for image in pane.state.sites["zh-CN"].planned],
            ["1"],
        )

    def test_editor_renders_27_sites_and_applies_source_to_all(self):
        info = make_product_info_27_sites(images_per_site=2)
        state = make_product_editor_state(
            "100000004",
            info,
            info["productBasicInfo"]["getImageLocaleInfo"]["images"],
        )
        pane = ProductImageEditorPane(state)
        self.addCleanup(pane.close)
        self.assertEqual(len(pane.site_panels), 27)
        self.assertTrue(pane.apply_site_to_all_sites("chinese"))
        expected = [
            image.image_id for image in state.sites["chinese"].planned
        ]
        self.assertTrue(all(
            [image.image_id for image in site.planned] == expected
            for site in state.sites.values()
        ))

    def test_card_list_mime_data_uses_workspace_protocol(self):
        cards = ImageCardList(
            product_id="100",
            kind="candidate",
        )
        self.addCleanup(cards.close)
        cards.add_workspace_item("a.jpg", source="/tmp/a.jpg")
        mime = cards.mimeData([cards.item(0)])
        self.assertTrue(mime.hasFormat(WORKSPACE_IMAGE_MIME))
        decoded = decode_drag_payload(
            bytes(mime.data(WORKSPACE_IMAGE_MIME))
        )
        self.assertEqual(decoded["productId"], "100")
        self.assertEqual(decoded["source"], "/tmp/a.jpg")

    def test_site_drop_target_reports_and_clears_insertion_position(self):
        target = ImageCardList(
            product_id="100",
            kind="site",
            source="zh-CN",
            drop_handler=lambda *_args: True,
            display_mode="sequence",
        )
        self.addCleanup(target.close)
        target.add_workspace_item("第一张", "zh-CN", 0)
        target.add_workspace_item("第二张", "zh-CN", 1)

        target._set_drop_target(0)
        self.assertEqual(target.drop_target_text(), "放到这里，成为第 1 张")
        target._set_drop_target(1)
        self.assertEqual(target.drop_target_index, 1)
        self.assertEqual(target.drop_target_text(), "放到这里，成为第 2 张")
        target._set_drop_target(target.count())
        self.assertEqual(target.drop_target_text(), "放到这里，成为第 3 张")
        target._set_drop_target(None)
        self.assertIsNone(target.drop_target_index)
        self.assertEqual(target.drop_target_text(), "")

    def test_candidate_inspection_runs_off_main_thread(self):
        pane = ProductImageEditorPane(self._state())
        self.addCleanup(pane.close)
        started = threading.Event()
        release = threading.Event()
        thread_ids = []
        main_thread_id = threading.get_ident()
        path = Path("/tmp/workspace-async.jpg")

        def fake_inspector(received_path):
            thread_ids.append(threading.get_ident())
            started.set()
            self.assertTrue(release.wait(2))
            return LocalImageInspection(
                path=Path(received_path),
                mime_type="image/jpeg",
                size_bytes=100,
                width=1080,
                height=608,
                allowed=True,
            )

        before = time.monotonic()
        pane.enqueue_candidate_paths([path], inspector=fake_inspector)
        elapsed = time.monotonic() - before
        self.assertLess(elapsed, 0.2)
        self.assertTrue(started.wait(2))
        self.assertNotEqual(thread_ids[0], main_thread_id)
        release.set()
        deadline = time.monotonic() + 2
        key = candidate_path_key(path)
        while key not in pane.state.candidates and time.monotonic() < deadline:
            QT_APP.processEvents()
            time.sleep(0.01)
        self.assertIn(key, pane.state.candidates)


class ProductImageWorkspaceTests(unittest.TestCase):
    def _wait_until(self, predicate, timeout=3):
        deadline = time.monotonic() + timeout
        while not predicate() and time.monotonic() < deadline:
            QT_APP.processEvents()
            time.sleep(0.01)
        self.assertTrue(predicate(), "等待工作区异步状态超时")

    def _backend(self):
        def load(product_id, _stop_event):
            return LoadedProductImages(
                product_id=product_id,
                product_info={
                    "productVersion": 1,
                    "productBasicInfo": {},
                },
                site_rows=[
                    {
                        "languageCode": "zh-CN",
                        "imageList": [
                            {"imageId": int(product_id)}
                        ],
                    }
                ],
                currency_context={"product": product_id},
            )

        return ProductImageWorkspaceBackend(load_product=load)

    def test_duplicate_product_ids_are_removed_and_states_are_isolated(self):
        dialog = ProductImageWorkspace(self._backend())
        self.addCleanup(dialog.shutdown)
        dialog.load_products(["100", "200", "100"])
        self._wait_until(lambda: len(dialog.product_panes) == 2)
        self.assertEqual(dialog.product_order, ["100", "200"])
        self.assertEqual(set(dialog.product_panes), {"100", "200"})
        dialog.product_panes["100"].state.sites["zh-CN"].planned.clear()
        self.assertEqual(
            len(dialog.product_panes["200"].state.sites["zh-CN"].planned),
            1,
        )
        self.assertEqual(
            dialog.product_states["100"].currency_context,
            {"product": "100"},
        )

    def test_multiline_product_input_is_parsed_and_deduplicated(self):
        dialog = ProductImageWorkspace(self._backend())
        self.addCleanup(dialog.shutdown)
        dialog.product_ids_edit.setPlainText("100\n200, 100")
        dialog._load_from_input()
        self._wait_until(lambda: len(dialog.product_states) == 2)
        self.assertEqual(dialog.product_order, ["100", "200"])

    def test_workspace_does_not_expose_legacy_advanced_config(self):
        dialog = ProductImageWorkspace(self._backend())
        self.addCleanup(dialog.shutdown)
        self.assertFalse(hasattr(dialog, "advanced_config_btn"))

    def test_switching_tabs_keeps_product_state(self):
        dialog = ProductImageWorkspace(self._backend())
        self.addCleanup(dialog.shutdown)
        dialog.load_products(["100", "200"])
        self._wait_until(lambda: len(dialog.product_panes) == 2)
        dialog.product_panes["100"].state.sites["zh-CN"].planned.clear()
        dialog.tabs.setCurrentIndex(dialog.tab_index("200"))
        dialog.tabs.setCurrentIndex(dialog.tab_index("100"))
        self.assertEqual(
            dialog.product_panes["100"].state.sites["zh-CN"].planned,
            [],
        )

    def test_switching_tabs_refreshes_current_submit_button(self):
        dialog = ProductImageWorkspace(self._backend())
        self.addCleanup(dialog.shutdown)
        dialog.load_products(["100", "200"])
        self._wait_until(lambda: len(dialog.product_panes) == 2)
        dialog.product_states["100"].sites["zh-CN"].planned.clear()
        dialog.product_panes["100"]._finish_edit()
        dialog.tabs.setCurrentIndex(dialog.tab_index("200"))
        self.assertFalse(dialog.submit_current_btn.isEnabled())
        dialog.tabs.setCurrentIndex(dialog.tab_index("100"))
        self.assertTrue(dialog.submit_current_btn.isEnabled())

    def test_product_tab_status_distinguishes_pending_upload_and_ready_submit(self):
        dialog = ProductImageWorkspace(self._backend())
        self.addCleanup(dialog.shutdown)
        dialog.load_products(["100"])
        self._wait_until(lambda: "100" in dialog.product_states)
        state = dialog.product_states["100"]
        path = Path("/tmp/pending-status.jpg")
        state.candidates[candidate_path_key(path)] = CandidateImage(
            path=path,
            status="local",
        )
        dialog._on_product_state_changed("100")
        self.assertIn(
            "待上传",
            dialog.tabs.tabText(dialog.tab_index("100")),
        )
        state.candidates.clear()
        state.sites["zh-CN"].planned.clear()
        dialog._on_product_state_changed("100")
        self.assertIn(
            "可提交",
            dialog.tabs.tabText(dialog.tab_index("100")),
        )

    def test_failed_product_keeps_retryable_tab(self):
        attempts = []

        def load(product_id, _stop_event):
            attempts.append(product_id)
            if len(attempts) == 1:
                raise RuntimeError("denied")
            return self._backend().load_product(product_id, _stop_event)

        dialog = ProductImageWorkspace(
            ProductImageWorkspaceBackend(load_product=load)
        )
        self.addCleanup(dialog.shutdown)
        dialog.load_products(["100"])
        self._wait_until(lambda: "100" in dialog.failed_products)
        self.assertIn("denied", dialog.failed_products["100"])
        self.assertGreaterEqual(dialog.tab_index("100"), 0)
        dialog.retry_product("100")
        self._wait_until(lambda: "100" in dialog.product_panes)
        self.assertEqual(attempts, ["100", "100"])

    def test_reread_dirty_product_requires_discard_confirmation(self):
        attempts = []

        def load(product_id, _stop_event):
            attempts.append(product_id)
            return self._backend().load_product(product_id, _stop_event)

        dialog = ProductImageWorkspace(
            ProductImageWorkspaceBackend(load_product=load)
        )
        self.addCleanup(dialog.shutdown)
        dialog.load_products(["100"])
        self._wait_until(lambda: "100" in dialog.product_panes)
        dialog.product_states["100"].sites["zh-CN"].planned.clear()
        self.assertFalse(
            dialog.reread_product(
                "100",
                answer=QMessageBox.StandardButton.Cancel,
            )
        )
        self.assertEqual(attempts, ["100"])
        self.assertTrue(
            dialog.reread_product(
                "100",
                answer=QMessageBox.StandardButton.Discard,
            )
        )
        self._wait_until(lambda: len(attempts) == 2)

    def test_close_is_rejected_when_dirty_and_user_cancels(self):
        dialog = ProductImageWorkspace(self._backend())
        self.addCleanup(dialog.shutdown)
        dialog.load_products(["100"])
        self._wait_until(lambda: "100" in dialog.product_panes)
        dialog.product_panes["100"].state.sites["zh-CN"].planned.clear()
        self.assertFalse(
            dialog.confirm_discard_dirty_products(
                ["100"],
                answer=QMessageBox.StandardButton.Cancel,
            )
        )
        self.assertTrue(
            dialog.confirm_discard_dirty_products(
                ["100"],
                answer=QMessageBox.StandardButton.Discard,
            )
        )

    def test_candidate_library_is_included_in_unsaved_product_protection(self):
        dialog = ProductImageWorkspace(self._backend())
        self.addCleanup(dialog.shutdown)
        dialog.load_products(["100"])
        self._wait_until(lambda: "100" in dialog.product_states)
        path = Path("/tmp/not-yet-used.jpg")
        dialog.product_states["100"].candidates[candidate_path_key(path)] = (
            CandidateImage(path=path, status="local")
        )
        self.assertEqual(dialog.unsaved_product_ids(), ["100"])

    def test_dialog_uploads_selected_candidate_and_refreshes_status(self):
        uploaded = []

        def upload(product_id, path):
            uploaded.append((product_id, path.name))
            return workspace_image_from_api(
                {
                    "imageId": 77,
                    "imageUrl": "https://img/selected.jpg",
                    "imageName": path.name,
                }
            )

        base = self._backend()
        dialog = ProductImageWorkspace(
            ProductImageWorkspaceBackend(
                load_product=base.load_product,
                upload_image=upload,
            )
        )
        self.addCleanup(dialog.shutdown)
        dialog.load_products(["100"])
        self._wait_until(lambda: "100" in dialog.product_panes)
        state = dialog.product_states["100"]
        path = Path("/tmp/selected.jpg")
        key = candidate_path_key(path)
        state.candidates[key] = CandidateImage(path=path, status="local")

        self.assertTrue(dialog.start_upload("100", [key]))
        self._wait_until(
            lambda: state.candidates[key].status == "uploaded"
            and dialog.product_panes["100"].candidate_panel.image_list.count()
            == 1
        )
        self.assertEqual(uploaded, [("100", "selected.jpg")])
        self.assertIn(
            "已上传",
            dialog.product_panes["100"].candidate_panel.image_list.item(0).text(),
        )

    def test_retry_failed_uploads_only_requeues_failed_candidates(self):
        calls = []

        def upload(product_id, path):
            calls.append(path.name)
            return workspace_image_from_api({"imageId": len(calls)})

        base = self._backend()
        dialog = ProductImageWorkspace(
            ProductImageWorkspaceBackend(
                load_product=base.load_product,
                upload_image=upload,
            )
        )
        self.addCleanup(dialog.shutdown)
        dialog.load_products(["100"])
        self._wait_until(lambda: "100" in dialog.product_panes)
        state = dialog.product_states["100"]
        failed_path = Path("/tmp/failed.jpg")
        local_path = Path("/tmp/local.jpg")
        failed_key = candidate_path_key(failed_path)
        local_key = candidate_path_key(local_path)
        state.candidates[failed_key] = CandidateImage(
            path=failed_path,
            status="failed",
        )
        state.candidates[local_key] = CandidateImage(
            path=local_path,
            status="local",
        )

        self.assertTrue(dialog.retry_failed_uploads("100"))
        self._wait_until(
            lambda: state.candidates[failed_key].status == "uploaded"
        )
        self.assertEqual(calls, ["failed.jpg"])
        self.assertEqual(state.candidates[local_key].status, "local")

    def test_verified_save_advances_baseline_and_clears_dirty_state(self):
        base = self._backend()
        verification = type(
            "Verification",
            (),
            {"ok": True, "site_errors": {}},
        )()
        saved = []

        def save(state, _stop_event):
            saved.append(state.product_id)
            return verification

        dialog = ProductImageWorkspace(
            ProductImageWorkspaceBackend(
                load_product=base.load_product,
                save_and_verify=save,
            )
        )
        self.addCleanup(dialog.shutdown)
        dialog.load_products(["100"])
        self._wait_until(lambda: "100" in dialog.product_states)
        state = dialog.product_states["100"]
        state.sites["zh-CN"].planned.clear()
        dialog.product_panes["100"]._finish_edit()
        self.assertTrue(state.dirty)

        self.assertTrue(dialog.start_save_products(["100"]))
        self._wait_until(lambda: not state.dirty)
        self.assertEqual(saved, ["100"])
        self.assertIn("已验证", dialog.tabs.tabText(dialog.tab_index("100")))

    def test_verify_failure_keeps_dirty_plan_for_retry(self):
        base = self._backend()
        verification = type(
            "Verification",
            (),
            {"ok": False, "site_errors": {"zh-CN": "顺序不一致"}},
        )()
        dialog = ProductImageWorkspace(
            ProductImageWorkspaceBackend(
                load_product=base.load_product,
                save_and_verify=lambda state, stop: verification,
            )
        )
        self.addCleanup(dialog.shutdown)
        dialog.load_products(["100"])
        self._wait_until(lambda: "100" in dialog.product_states)
        state = dialog.product_states["100"]
        state.sites["zh-CN"].planned.clear()
        dialog.product_panes["100"]._finish_edit()

        self.assertTrue(dialog.start_save_products(["100"]))
        self._wait_until(lambda: "顺序不一致" in dialog.status_label.text())
        self.assertTrue(state.dirty)

    def test_save_locks_product_editing_until_result_returns(self):
        base = self._backend()
        started = threading.Event()
        release = threading.Event()
        verification = type(
            "Verification",
            (),
            {"ok": False, "site_errors": {"zh-CN": "测试失败"}},
        )()

        def save(_state, _stop_event):
            started.set()
            self.assertTrue(release.wait(2))
            return verification

        dialog = ProductImageWorkspace(
            ProductImageWorkspaceBackend(
                load_product=base.load_product,
                save_and_verify=save,
            )
        )
        self.addCleanup(dialog.shutdown)
        dialog.load_products(["100"])
        self._wait_until(lambda: "100" in dialog.product_states)
        state = dialog.product_states["100"]
        state.sites["zh-CN"].planned.clear()
        pane = dialog.product_panes["100"]
        self.assertTrue(dialog.start_save_products(["100"]))
        self.assertTrue(started.wait(2))
        self.assertFalse(pane.editing_enabled)
        self.assertFalse(pane.remove_site_image("zh-CN", 0))
        release.set()
        self._wait_until(lambda: pane.editing_enabled)

    def test_save_is_rejected_while_candidate_upload_is_active(self):
        base = self._backend()
        dialog = ProductImageWorkspace(
            ProductImageWorkspaceBackend(
                load_product=base.load_product,
                save_and_verify=lambda state, stop: None,
            )
        )
        self.addCleanup(dialog.shutdown)
        dialog.load_products(["100"])
        self._wait_until(lambda: "100" in dialog.product_states)
        state = dialog.product_states["100"]
        state.sites["zh-CN"].planned.clear()
        state.candidates["active"] = CandidateImage(
            path=Path("/tmp/active.jpg"),
            status="uploading",
        )
        self.assertFalse(dialog.start_save_products(["100"]))
        self.assertIn("上传", dialog.status_label.text())

    def test_close_cancels_each_product_upload_queue(self):
        canceled = []

        class Coordinator:
            def cancel(self):
                canceled.append(True)

        dialog = ProductImageWorkspace(self._backend())
        dialog.upload_coordinators["100"] = Coordinator()
        dialog.shutdown()
        self.assertEqual(canceled, [True])

    def test_save_all_processes_dirty_products_sequentially(self):
        base = self._backend()
        saved = []
        verification = type(
            "Verification",
            (),
            {"ok": True, "site_errors": {}},
        )()

        def save(state, _stop_event):
            saved.append(state.product_id)
            return verification

        dialog = ProductImageWorkspace(
            ProductImageWorkspaceBackend(
                load_product=base.load_product,
                save_and_verify=save,
            )
        )
        self.addCleanup(dialog.shutdown)
        dialog.load_products(["100", "200"])
        self._wait_until(lambda: len(dialog.product_states) == 2)
        for state in dialog.product_states.values():
            state.sites["zh-CN"].planned.clear()
        self.assertTrue(dialog.start_save_products(["100", "200"]))
        self._wait_until(
            lambda: all(not state.dirty for state in dialog.product_states.values())
        )
        self.assertEqual(saved, ["100", "200"])

    def test_save_batch_done_reports_success_failure_and_verify_failure(self):
        base = self._backend()
        verification_ok = type(
            "Verification", (), {"ok": True, "site_errors": {}}
        )()
        verification_bad = type(
            "Verification",
            (),
            {"ok": False, "site_errors": {"zh-CN": "顺序不一致"}},
        )()

        def save(state, _stop_event):
            if state.product_id == "100":
                return verification_ok
            if state.product_id == "200":
                return verification_bad
            raise RuntimeError("denied")

        dialog = ProductImageWorkspace(
            ProductImageWorkspaceBackend(
                load_product=base.load_product,
                save_and_verify=save,
            )
        )
        self.addCleanup(dialog.shutdown)
        dialog.load_products(["100", "200", "300"])
        self._wait_until(lambda: len(dialog.product_states) == 3)
        for state in dialog.product_states.values():
            state.sites["zh-CN"].planned.clear()
        self.assertTrue(dialog.start_save_products(["100", "200", "300"]))
        self._wait_until(lambda: dialog.save_thread is None)
        self.assertEqual(
            dialog.save_results,
            {"100": "verified", "200": "verify_failed", "300": "failed"},
        )
        self.assertIn("成功 1", dialog.status_label.text())
        self.assertIn("验证失败 1", dialog.status_label.text())
        self.assertIn("提交失败 1", dialog.status_label.text())


class CandidateImagePanelTests(unittest.TestCase):
    def test_only_uploaded_candidate_cards_create_workspace_drag_payloads(self):
        state = make_product_editor_state("100", {}, [])
        local_path = Path("/tmp/local-card.jpg")
        uploaded_path = Path("/tmp/uploaded-card.jpg")
        state.candidates[candidate_path_key(local_path)] = CandidateImage(
            path=local_path,
            status="local",
        )
        state.candidates[candidate_path_key(uploaded_path)] = CandidateImage(
            path=uploaded_path,
            status="uploaded",
            uploaded=workspace_image_from_api({"imageId": 88}),
        )
        panel = CandidateImagePanel(state)
        self.addCleanup(panel.close)

        local_mime = panel.image_list.mimeData([panel.image_list.item(0)])
        uploaded_mime = panel.image_list.mimeData([panel.image_list.item(1)])

        self.assertFalse(local_mime.hasFormat(WORKSPACE_IMAGE_MIME))
        self.assertTrue(uploaded_mime.hasFormat(WORKSPACE_IMAGE_MIME))

    def test_local_candidate_card_uses_real_thumbnail(self):
        handle = tempfile.NamedTemporaryFile(suffix=".jpg", delete=False)
        handle.close()
        path = Path(handle.name)
        self.addCleanup(lambda: path.unlink(missing_ok=True))
        image = QImage(320, 180, QImage.Format.Format_RGB32)
        image.fill(QColor("#24567a"))
        self.assertTrue(image.save(str(path)))
        state = make_product_editor_state("100", {}, [])
        state.candidates[candidate_path_key(path)] = CandidateImage(
            path=path,
            status="local",
            width=320,
            height=180,
        )
        panel = CandidateImagePanel(state)
        self.addCleanup(panel.close)
        self.assertFalse(panel.image_list.item(0).icon().isNull())

    def test_image_detail_text_contains_identity_url_and_raw_fields(self):
        image = workspace_image_from_api(
            {
                "imageId": 8,
                "imageUrl": "https://img/8.jpg",
                "imageName": "8.jpg",
                "customField": "kept",
            }
        )
        text = workspace_image_detail_text(image)
        self.assertIn("imageId: 8", text)
        self.assertIn("https://img/8.jpg", text)
        self.assertIn('"customField": "kept"', text)

    def test_selected_keys_and_action_callbacks_use_current_product(self):
        state = make_product_editor_state("100", {}, [])
        paths = [Path("/tmp/a.jpg"), Path("/tmp/b.jpg")]
        for path in paths:
            state.candidates[candidate_path_key(path)] = CandidateImage(
                path=path,
                status="local",
            )
        selected = []
        panel = CandidateImagePanel(
            state,
            add_paths=lambda values: selected.append(("paths", values)),
            upload_candidates=lambda keys: selected.append(("upload", keys)),
            retry_failed=lambda: selected.append(("retry", None)),
            cancel_uploads=lambda: selected.append(("cancel", None)),
            remove_candidates=lambda keys: selected.append(("remove", keys)),
        )
        self.addCleanup(panel.close)
        panel.image_list.item(0).setSelected(True)
        panel.upload_selected_btn.click()
        panel.select_all_btn.click()
        self.assertEqual(len(panel.selected_keys()), 2)
        panel.clear_selection_btn.click()
        self.assertEqual(panel.selected_keys(), [])
        panel.image_list.item(1).setSelected(True)
        panel.remove_btn.click()
        panel.retry_btn.click()
        panel.cancel_btn.click()
        self.assertEqual(
            selected,
            [
                ("upload", [candidate_path_key(paths[0])]),
                ("remove", [candidate_path_key(paths[1])]),
                ("retry", None),
                ("cancel", None),
            ],
        )

    def test_failed_candidate_card_exposes_failure_detail(self):
        state = make_product_editor_state("100", {}, [])
        path = Path("/tmp/failed-detail.jpg")
        state.candidates[candidate_path_key(path)] = CandidateImage(
            path=path,
            status="failed",
            error="接口拒绝：尺寸不符合",
        )
        panel = CandidateImagePanel(state)
        self.addCleanup(panel.close)
        self.assertIn("接口拒绝", panel.image_list.item(0).toolTip())


class ProductUploadCoordinatorTests(unittest.TestCase):
    def _state_with_candidates(self, names):
        state = make_product_editor_state(
            "100",
            {"productBasicInfo": {}},
            [],
        )
        keys = []
        for name in names:
            path = Path("/tmp") / name
            key = candidate_path_key(path)
            keys.append(key)
            state.candidates[key] = CandidateImage(
                path=path,
                status="local",
            )
        return state, keys

    def test_success_failure_and_retry_are_per_image(self):
        calls = []

        def upload(product_id, path):
            calls.append((product_id, path.name))
            bad_attempts = len(
                [call for call in calls if call[1] == "bad.jpg"]
            )
            if path.name == "bad.jpg" and bad_attempts == 1:
                raise RuntimeError("temporary")
            return workspace_image_from_api(
                {
                    "imageId": len(calls),
                    "imageUrl": f"https://img/{path.name}",
                    "imageName": path.name,
                }
            )

        state, keys = self._state_with_candidates(
            ["good.jpg", "bad.jpg"]
        )
        coordinator = ProductUploadCoordinator(
            "100",
            state,
            upload,
            max_workers=2,
        )
        coordinator.run(keys)
        self.assertEqual(state.candidates[keys[0]].status, "uploaded")
        self.assertEqual(state.candidates[keys[1]].status, "failed")
        coordinator.run(keys)
        self.assertEqual(state.candidates[keys[1]].status, "uploaded")
        self.assertEqual(
            len([call for call in calls if call[1] == "good.jpg"]),
            1,
        )

    def test_cancel_only_skips_not_started_candidates(self):
        started = threading.Event()
        release = threading.Event()
        calls = []

        def upload(product_id, path):
            calls.append((product_id, path.name))
            started.set()
            self.assertTrue(release.wait(2))
            return workspace_image_from_api(
                {
                    "imageId": 1,
                    "imageUrl": "https://img/1.jpg",
                    "imageName": path.name,
                }
            )

        state, keys = self._state_with_candidates(
            ["first.jpg", "second.jpg"]
        )
        coordinator = ProductUploadCoordinator(
            "100",
            state,
            upload,
            max_workers=1,
        )
        thread = threading.Thread(
            target=lambda: coordinator.run(keys),
            daemon=True,
        )
        thread.start()
        self.assertTrue(started.wait(2))
        coordinator.cancel()
        release.set()
        thread.join(2)
        self.assertFalse(thread.is_alive())
        self.assertEqual(calls, [("100", "first.jpg")])
        self.assertEqual(state.candidates[keys[0]].status, "uploaded")
        self.assertEqual(state.candidates[keys[1]].status, "canceled")

    def test_invalid_candidate_is_never_uploaded(self):
        state, keys = self._state_with_candidates(["invalid.jpg"])
        state.candidates[keys[0]].status = "invalid"
        calls = []
        coordinator = ProductUploadCoordinator(
            "100",
            state,
            lambda product_id, path: calls.append((product_id, path)),
            max_workers=2,
        )
        coordinator.run(keys)
        self.assertEqual(calls, [])
        self.assertEqual(state.candidates[keys[0]].status, "invalid")


if __name__ == "__main__":
    unittest.main()

import os
import unittest


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import app
from docking_config import DockingConfigWidget
from product_edit import FIELD_SPECS, ProductEditWidget
from product_image_workspace import ProductImageWorkspace
from PyQt6.QtGui import QCloseEvent


QT_APP = app.QApplication.instance() or app.QApplication([])


class AppImageWorkspaceIntegrationTests(unittest.TestCase):
    def test_product_tab_exposes_registry_and_translation_has_no_secondary_tabs(self):
        window = app.App()
        self.addCleanup(window.close)

        tabs = window.findChild(app.QTabWidget)
        titles = [tabs.tabText(index) for index in range(tabs.count())]
        product_tab = tabs.widget(titles.index("产品信息接口修改"))
        translation_tab = tabs.widget(titles.index("翻译件管理"))

        self.assertIs(product_tab.findChild(ProductEditWidget), window.product_edit_component)
        self.assertEqual(len(FIELD_SPECS), sum(
            len(window.product_edit_component.fields_for_module(module))
            for module in window.product_edit_component.available_modules()
        ))
        self.assertIs(translation_tab, window.translation_workbench_tab)
        self.assertIsNone(
            translation_tab.findChild(app.QTabWidget, "translationManagementPages")
        )
        self.assertFalse(hasattr(window, "translation_management_component"))

    def test_image_tab_directly_contains_the_multi_product_workspace(self):
        window = app.App()
        self.addCleanup(window.close)

        tabs = window.findChild(app.QTabWidget)
        titles = [tabs.tabText(index) for index in range(tabs.count())]
        image_tab = tabs.widget(titles.index("产品图片配置"))
        workspace = image_tab.findChild(ProductImageWorkspace)

        self.assertIsNotNone(workspace)
        self.assertIs(workspace, window.product_image_workspace)
        button_texts = {button.text() for button in image_tab.findChildren(app.QPushButton)}
        self.assertNotIn("打开图片工作区", button_texts)
        self.assertNotIn("高级图片配置", button_texts)
        self.assertNotIn("生成请求预览", button_texts)
        self.assertNotIn("导出图片报告", button_texts)
        self.assertIn("提交全部已修改产品", button_texts)

    def test_main_window_exposes_independent_docking_config_tab(self):
        window = app.App()
        self.addCleanup(window.close)

        tabs = window.findChild(app.QTabWidget)
        titles = [tabs.tabText(index) for index in range(tabs.count())]
        docking_tab = tabs.widget(titles.index("产品对接单独配置"))
        widget = docking_tab.findChild(DockingConfigWidget)

        self.assertIs(widget, window.docking_config_widget)
        self.assertIsNotNone(widget.findChild(app.QTableView, "dockingResultTable"))
        self.assertIsNotNone(widget.findChild(app.QLineEdit, "dockingTemplatePath"))
        self.assertEqual(
            "输入产品/资源ID并预载",
            widget.findChild(app.QPushButton, "dockingStartPreloadButton").text(),
        )
        self.assertEqual(
            "传出修改",
            widget.findChild(app.QPushButton, "dockingApplyButton").text(),
        )
        self.assertIsNotNone(widget.findChild(app.QPlainTextEdit, "dockingRuntimeLog"))
        self.assertIsNotNone(widget.findChild(app.QPlainTextEdit, "dockingDetailText"))
        self.assertIn(
            window.request_stats.summary_text("docking"),
            widget.status_label.text(),
        )
        widget._set_status("正在预载...")
        self.assertEqual(
            f"正在预载... | {window.request_stats.summary_text('docking')}",
            widget.status_label.text(),
        )

        window._set_auth_status_text("登录态：有效")
        self.assertEqual("登录态：有效", widget.product_auth_status_label.text())

    def test_close_is_cancelled_when_image_workspace_rejects_close(self):
        class Workspace:
            def request_close(self, _parent):
                return False

        window = app.App()
        window.product_image_workspace = Workspace()
        event = QCloseEvent()

        window.closeEvent(event)

        self.assertFalse(event.isAccepted())


if __name__ == "__main__":
    unittest.main()

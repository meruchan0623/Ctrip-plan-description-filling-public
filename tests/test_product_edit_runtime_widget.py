"""Widget-level contracts for the independently usable field browser.

Breaks caught here:
* the field registry stops being available to an operator by module; or
* the workbench lifecycle cannot stop a local run and expose settings without
  a dependency on the application shell.
"""

from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication

from product_edit.widget import ProductEditWidget


class ProductEditWidgetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.application = QApplication.instance() or QApplication([])

    def test_module_browser_exposes_registered_fields_and_lifecycle(self) -> None:
        widget = ProductEditWidget()
        try:
            self.assertIn("产品信息", widget.available_modules())
            self.assertTrue(any(field.code == "product_name" for field in widget.fields_for_module("产品信息")))
            self.assertFalse(widget.is_running())
            self.assertEqual(widget.export_settings()["selected_module"], "产品信息")
            self.assertTrue(widget.request_close(widget))
            widget.shutdown()
            self.assertFalse(widget.is_running())
        finally:
            widget.deleteLater()


if __name__ == "__main__":
    unittest.main()

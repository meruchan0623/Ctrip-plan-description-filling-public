import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication

from translation_management.widget import TranslationManagementWidget


class TranslationManagementWidgetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_widget_exposes_independent_lifecycle_and_settings_without_a_main_window(self):
        widget = TranslationManagementWidget(client_factory=lambda: object())

        self.assertFalse(widget.is_running())
        self.assertEqual({}, widget.export_settings())
        self.assertTrue(widget.request_close(widget))

        widget.stop()
        widget.shutdown()
        self.assertFalse(widget.is_running())


if __name__ == "__main__":
    unittest.main()

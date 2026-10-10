import os
import time
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication

from translation_management.widget import TranslationManagementWidget


class _Workflow:
    def __init__(self, out_queue, stop_event, client_factory):
        self._out_queue = out_queue
        self._stop_event = stop_event
        self._client_factory = client_factory

    def preview(self, product_ids, template_path):
        self._out_queue.put(("log", f"预览 {','.join(product_ids)} | {template_path}"))
        return [{"operation": "preview", "product_ids": list(product_ids), "template_path": template_path}]

    def apply(self, product_ids, template_path):
        return [{"operation": "apply", "product_ids": list(product_ids), "template_path": template_path}]


class _StreamingWorkflow(_Workflow):
    def preview(self, product_ids, template_path):
        self._out_queue.put(("result", {"source": "stream", "product_id": product_ids[0]}))
        return [{"source": "return", "template_path": template_path}]


class TranslationManagementRuntimeWidgetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _wait_until_finished(self, widget):
        deadline = time.monotonic() + 2
        while widget.is_running() and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(0.01)
        self.app.processEvents()
        self.assertFalse(widget.is_running(), "翻译工作区应在工作流完成后恢复空闲")

    def test_preview_uses_its_own_runtime_and_control_values(self):
        widget = TranslationManagementWidget(
            client_factory=lambda: object(),
            workflow_factory=_Workflow,
        )
        widget.product_ids_edit.setText("1001, 1002\n1001")
        widget.task_template_edit.setText("/tmp/translation-task.xlsx")

        widget.start_preview()
        self._wait_until_finished(widget)

        self.assertEqual(
            [{
                "operation": "preview",
                "product_ids": ["1001", "1002"],
                "template_path": "/tmp/translation-task.xlsx",
            }],
            widget.results,
        )
        self.assertIn("预览 1001,1002", widget.log_text.toPlainText())
        self.assertEqual("preview", widget.last_operation)
        self.assertFalse(widget.stop_event.is_set())

    def test_stopping_one_widget_does_not_stop_another_widgets_runtime(self):
        first = TranslationManagementWidget(client_factory=lambda: object(), workflow_factory=_Workflow)
        second = TranslationManagementWidget(client_factory=lambda: object(), workflow_factory=_Workflow)

        first.stop()

        self.assertTrue(first.stop_event.is_set())
        self.assertFalse(second.stop_event.is_set())
        self.assertIsNot(first.out_queue, second.out_queue)
        self.assertIsNot(first.stop_event, second.stop_event)

    def test_preview_keeps_streamed_results_when_workflow_returns_a_summary(self):
        widget = TranslationManagementWidget(
            client_factory=lambda: object(),
            workflow_factory=_StreamingWorkflow,
        )
        widget.product_ids_edit.setText("1001")
        widget.task_template_edit.setText("/tmp/translation-task.xlsx")

        widget.start_preview()
        self._wait_until_finished(widget)

        self.assertEqual(
            [
                {"source": "stream", "product_id": "1001"},
                {"source": "return", "template_path": "/tmp/translation-task.xlsx"},
            ],
            widget.results,
        )

    def test_report_button_exports_its_own_results_and_current_controls(self):
        exported = []

        def write_report(results, settings):
            exported.append((results, settings))
            return "/tmp/translation-report.xlsx"

        widget = TranslationManagementWidget(
            client_factory=lambda: object(),
            workflow_factory=_Workflow,
            report_writer=write_report,
        )
        widget.product_ids_edit.setText("1001,1002")
        widget.task_template_edit.setText("/tmp/translation-task.xlsx")
        widget.start_preview()
        self._wait_until_finished(widget)

        widget.report_button.click()

        self.assertEqual(
            [(
                [{
                    "operation": "preview",
                    "product_ids": ["1001", "1002"],
                    "template_path": "/tmp/translation-task.xlsx",
                }],
                {"product_ids": ["1001", "1002"], "task_template_path": "/tmp/translation-task.xlsx"},
            )],
            exported,
        )
        self.assertEqual("/tmp/translation-report.xlsx", widget.last_report)
        self.assertEqual("翻译报告已导出", widget.status_label.text())


if __name__ == "__main__":
    unittest.main()

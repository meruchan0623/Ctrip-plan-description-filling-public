"""Self-contained Qt workbench for translation tasks.

The main window injects factories but never owns this widget's queue, worker
thread, stop event, result list, or log.  This keeps a translation operation
isolated from product and image workbenches.
"""

from __future__ import annotations

import queue
import threading
from collections.abc import Callable, Iterable
from typing import Any, Protocol

from PyQt6.QtCore import QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class TranslationWorkbenchWorkflow(Protocol):
    def preview(self, product_ids: list[str], template_path: str) -> Iterable[Any]: ...
    def apply(self, product_ids: list[str], template_path: str) -> Iterable[Any]: ...


TranslationWorkflowFactory = Callable[
    [queue.Queue[Any], threading.Event, Callable[[], Any]], TranslationWorkbenchWorkflow
]
TranslationReportWriter = Callable[[list[Any], dict[str, Any]], Any]


def _product_ids_from_text(text: str) -> list[str]:
    product_ids: list[str] = []
    for part in text.replace("\n", ",").split(","):
        product_id = part.strip()
        if product_id and product_id not in product_ids:
            product_ids.append(product_id)
    return product_ids


class TranslationManagementWidget(QWidget):
    """Translation workbench whose operational state is local to the widget."""

    write_started = pyqtSignal(str)
    write_finished = pyqtSignal(str)
    auth_refresh_requested = pyqtSignal()
    settings_changed = pyqtSignal()

    def __init__(
        self,
        client_factory: Callable[[], Any],
        parent: QWidget | None = None,
        *,
        workflow_factory: TranslationWorkflowFactory | None = None,
        report_writer: TranslationReportWriter | None = None,
    ) -> None:
        super().__init__(parent)
        self._client_factory = client_factory
        self._workflow_factory = workflow_factory
        self._report_writer = report_writer
        self.out_queue: queue.Queue[Any] = queue.Queue()
        self.stop_event = threading.Event()
        self.worker_thread: threading.Thread | None = None
        self.results: list[Any] = []
        self.last_operation = ""
        self.last_report: Any = None
        self._running = False
        self._shutdown = False
        self._build_ui()

        self._queue_timer = QTimer(self)
        self._queue_timer.setInterval(20)
        self._queue_timer.timeout.connect(self._drain_queue)
        self._queue_timer.start()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        title = QLabel("翻译件管理", self)
        title.setStyleSheet("font-size: 18px; font-weight: 700;")
        layout.addWidget(title)

        self.product_ids_edit = QLineEdit(self)
        self.product_ids_edit.setObjectName("translationProductIdsEdit")
        self.product_ids_edit.setPlaceholderText("产品 ID，使用逗号或换行分隔")
        self.product_ids_edit.textChanged.connect(self._emit_settings_changed)
        layout.addWidget(self.product_ids_edit)

        self.task_template_edit = QLineEdit(self)
        self.task_template_edit.setObjectName("translationTaskTemplateEdit")
        self.task_template_edit.setPlaceholderText("翻译任务模板路径")
        self.task_template_edit.textChanged.connect(self._emit_settings_changed)
        layout.addWidget(self.task_template_edit)

        action_row = QHBoxLayout()
        self.preview_button = QPushButton("生成预览", self)
        self.preview_button.clicked.connect(self.start_preview)
        self.apply_button = QPushButton("应用翻译", self)
        self.apply_button.clicked.connect(self.start_apply)
        self.stop_button = QPushButton("停止", self)
        self.stop_button.clicked.connect(self.stop)
        self.report_button = QPushButton("导出报告", self)
        self.report_button.clicked.connect(self.export_report)
        action_row.addWidget(self.preview_button)
        action_row.addWidget(self.apply_button)
        action_row.addWidget(self.stop_button)
        action_row.addWidget(self.report_button)
        action_row.addStretch(1)
        layout.addLayout(action_row)

        self.status_label = QLabel("就绪", self)
        self.status_label.setObjectName("translationRuntimeStatus")
        layout.addWidget(self.status_label)

        self.log_text = QPlainTextEdit(self)
        self.log_text.setObjectName("translationRuntimeLog")
        self.log_text.setReadOnly(True)
        layout.addWidget(self.log_text, 1)
        self._refresh_controls()

    def _emit_settings_changed(self, _value: str = "") -> None:
        self.settings_changed.emit()

    def _refresh_controls(self) -> None:
        can_start = not self._running and not self._shutdown and self._workflow_factory is not None
        self.preview_button.setEnabled(can_start)
        self.apply_button.setEnabled(can_start)
        self.stop_button.setEnabled(self._running)
        self.report_button.setEnabled(not self._running and bool(self.results))
        self.product_ids_edit.setEnabled(not self._running and not self._shutdown)
        self.task_template_edit.setEnabled(not self._running and not self._shutdown)

    def is_running(self) -> bool:
        return self._running

    def start_preview(self) -> None:
        self._start_operation("preview")

    def start_apply(self) -> None:
        self._start_operation("apply")

    def _start_operation(self, operation: str) -> None:
        if self._running or self._shutdown:
            return
        if self._workflow_factory is None:
            self._append_log("未配置翻译工作流，无法执行任务")
            self.status_label.setText("未配置工作流")
            return
        product_ids = _product_ids_from_text(self.product_ids_edit.text())
        if not product_ids:
            self._append_log("请先输入至少一个产品 ID")
            self.status_label.setText("缺少产品 ID")
            return
        template_path = self.task_template_edit.text().strip()
        if not template_path:
            self._append_log("请先选择翻译任务模板")
            self.status_label.setText("缺少任务模板")
            return

        self.stop_event.clear()
        self.results = []
        self.last_operation = operation
        self._running = True
        self.status_label.setText("预览运行中" if operation == "preview" else "翻译写入运行中")
        self._refresh_controls()
        if operation == "apply":
            self.write_started.emit("translation")

        def run() -> None:
            try:
                workflow = self._workflow_factory(self.out_queue, self.stop_event, self._client_factory)
                returned = workflow.preview(product_ids, template_path) if operation == "preview" else workflow.apply(product_ids, template_path)
                self.out_queue.put(("completed", operation, list(returned or [])))
            except Exception as exc:  # queue errors for the UI thread
                self.out_queue.put(("failed", operation, str(exc)))

        self.worker_thread = threading.Thread(target=run, daemon=True, name=f"translation-{operation}")
        self.worker_thread.start()

    def stop(self) -> None:
        self.stop_event.set()
        if self._running:
            self.status_label.setText("正在停止翻译任务…")
            self._append_log("已请求停止翻译任务")
        self._refresh_controls()

    def export_report(self) -> Any:
        if not self.results:
            self.status_label.setText("没有可导出的翻译结果")
            return None
        if self._report_writer is None:
            self.status_label.setText("翻译报告导出尚未配置")
            return None
        self.last_report = self._report_writer(list(self.results), self.export_settings())
        self.status_label.setText("翻译报告已导出")
        self._append_log("已调用翻译报告导出器")
        return self.last_report

    def export_settings(self) -> dict[str, Any]:
        product_ids = _product_ids_from_text(self.product_ids_edit.text())
        template_path = self.task_template_edit.text().strip()
        settings: dict[str, Any] = {}
        if product_ids:
            settings["product_ids"] = product_ids
        if template_path:
            settings["task_template_path"] = template_path
        return settings

    def request_close(self, parent: QWidget) -> bool:
        del parent
        return not self._running

    def shutdown(self) -> None:
        self._shutdown = True
        self.stop()
        self._queue_timer.stop()
        self._refresh_controls()

    def closeEvent(self, event: Any) -> None:
        if not self.request_close(self):
            event.ignore()
            return
        self.shutdown()
        event.accept()

    def _drain_queue(self) -> None:
        if self._shutdown:
            return
        while True:
            try:
                event = self.out_queue.get_nowait()
            except queue.Empty:
                return
            self._handle_event(event)

    def _handle_event(self, event: Any) -> None:
        if not isinstance(event, tuple) or not event:
            return
        kind, *payload = event
        if kind == "log":
            self._append_log(str(payload[0]) if payload else "")
        elif kind == "result":
            if payload:
                self.results.append(payload[0])
        elif kind == "result_batch":
            self.results.extend(list(payload[0] or []) if payload else [])
        elif kind == "completed":
            operation, rows = payload
            self._merge_returned_results(list(rows))
            self._finish_operation(str(operation), "预览完成" if operation == "preview" else "翻译写入完成")
        elif kind == "failed":
            operation, message = payload
            self._append_log(str(message))
            self._finish_operation(str(operation), f"执行失败：{message}")

    def _finish_operation(self, operation: str, status: str) -> None:
        self._running = False
        self.status_label.setText(status)
        if operation == "apply":
            self.write_finished.emit("translation")
        self._refresh_controls()

    def _merge_returned_results(self, returned_rows: list[Any]) -> None:
        for row in returned_rows:
            if not any(row == existing for existing in self.results):
                self.results.append(row)

    def _append_log(self, message: str) -> None:
        if message:
            self.log_text.appendPlainText(message)

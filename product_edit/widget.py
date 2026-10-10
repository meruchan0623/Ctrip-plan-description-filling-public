"""Independent product-edit field registry browser.

The widget is intentionally a usable browse-and-inspect surface only at this
stage.  It has no HTTP dependency and owns no application-wide queue; a later
integration layer can attach its own worker without changing the browser's
public lifecycle contract.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .field_registry import FIELD_SPECS, field_specs_for_module
from .models import ProductFieldSpec
from .catalog import CatalogTreeNode, FullFieldReadResult, parse_catalog_product_ids


class ProductEditWidget(QWidget):
    """Browse fields by business module without depending on ``app.py``."""

    write_started = pyqtSignal(str)
    write_finished = pyqtSignal(str)
    auth_refresh_requested = pyqtSignal()
    settings_changed = pyqtSignal()
    read_requested = pyqtSignal(tuple)
    read_stopped = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._running = False
        self._selected_module = self.available_modules()[0] if self.available_modules() else ""
        self._catalog_nodes: dict[int, object] = {}
        self._catalog_item_loaded: set[int] = set()
        self._catalog_results: dict[str, FullFieldReadResult] = {}
        self._build_ui()
        self._render_module(self._selected_module)

    def available_modules(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(spec.module for spec in FIELD_SPECS))

    def fields_for_module(self, module: str) -> tuple[ProductFieldSpec, ...]:
        return field_specs_for_module(module)

    def is_running(self) -> bool:
        return self._running

    def stop(self) -> None:
        if not self._running:
            return
        self._running = False
        self.catalog_read_button.setEnabled(True)
        self.catalog_stop_button.setEnabled(False)
        self.catalog_progress_label.setText("已停止")
        self.catalog_summary_label.setText("读取已停止；已展示的本地结果会保留。")
        self.read_stopped.emit()
        self.write_finished.emit("stopped")

    def export_settings(self) -> dict[str, str]:
        return {"selected_module": self._selected_module}

    def request_close(self, parent: QWidget) -> bool:
        del parent
        return not self._running

    def shutdown(self) -> None:
        self.stop()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        heading = QLabel("产品字段注册表", self)
        layout.addWidget(heading)

        self._build_catalog_ui(layout)

        chooser_row = QFormLayout()
        self._module_chooser = QComboBox(self)
        self._module_chooser.addItems(self.available_modules())
        self._module_chooser.currentTextChanged.connect(self._render_module)
        chooser_row.addRow("业务模块", self._module_chooser)
        layout.addLayout(chooser_row)

        self._table = QTableWidget(self)
        self._table.setColumnCount(6)
        self._table.setHorizontalHeaderLabels(["字段", "路径", "草稿类型", "值类型", "风险", "可写状态"])
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        layout.addWidget(self._table)

    def _build_catalog_ui(self, layout: QVBoxLayout) -> None:
        catalog_box = QGroupBox("全字段读取目录", self)
        catalog_layout = QVBoxLayout(catalog_box)

        input_row = QFormLayout()
        self.catalog_product_ids_input = QPlainTextEdit(catalog_box)
        self.catalog_product_ids_input.setObjectName("catalog_product_ids_input")
        self.catalog_product_ids_input.setPlaceholderText("每行一个商品 ID，或用逗号、空格分隔")
        self.catalog_product_ids_input.setMaximumHeight(58)
        input_row.addRow("商品 ID", self.catalog_product_ids_input)
        catalog_layout.addLayout(input_row)

        actions = QHBoxLayout()
        self.catalog_read_button = QPushButton("读取全部字段", catalog_box)
        self.catalog_read_button.setObjectName("catalog_read_button")
        self.catalog_read_button.clicked.connect(self._request_catalog_read)
        actions.addWidget(self.catalog_read_button)
        self.catalog_stop_button = QPushButton("停止读取", catalog_box)
        self.catalog_stop_button.setObjectName("catalog_stop_button")
        self.catalog_stop_button.setEnabled(False)
        self.catalog_stop_button.clicked.connect(self.stop)
        actions.addWidget(self.catalog_stop_button)
        actions.addStretch()
        catalog_layout.addLayout(actions)

        self.catalog_progress_bar = QProgressBar(catalog_box)
        self.catalog_progress_bar.setObjectName("catalog_progress_bar")
        self.catalog_progress_bar.setRange(0, 1)
        self.catalog_progress_bar.setValue(0)
        catalog_layout.addWidget(self.catalog_progress_bar)
        self.catalog_progress_label = QLabel("等待读取", catalog_box)
        self.catalog_progress_label.setObjectName("catalog_progress_label")
        catalog_layout.addWidget(self.catalog_progress_label)
        self.catalog_summary_label = QLabel("尚未读取商品字段。", catalog_box)
        self.catalog_summary_label.setObjectName("catalog_summary_label")
        self.catalog_summary_label.setWordWrap(True)
        catalog_layout.addWidget(self.catalog_summary_label)

        self.catalog_filter_input = QLineEdit(catalog_box)
        self.catalog_filter_input.setObjectName("catalog_filter_input")
        self.catalog_filter_input.setPlaceholderText("筛选已读取的字段路径、名称或摘要")
        self.catalog_filter_input.textChanged.connect(self._apply_catalog_filter)
        catalog_layout.addWidget(self.catalog_filter_input)

        self.catalog_tree = QTreeWidget(catalog_box)
        self.catalog_tree.setObjectName("catalog_tree")
        self.catalog_tree.setColumnCount(5)
        self.catalog_tree.setHeaderLabels(["字段", "路径", "类型", "值摘要", "敏感"])
        self.catalog_tree.setEditTriggers(QTreeWidget.EditTrigger.NoEditTriggers)
        self.catalog_tree.itemExpanded.connect(self._load_catalog_item_children)
        catalog_layout.addWidget(self.catalog_tree)
        layout.addWidget(catalog_box)

    def _request_catalog_read(self) -> None:
        try:
            product_ids = parse_catalog_product_ids(self.catalog_product_ids_input.toPlainText())
        except ValueError as error:
            self.catalog_summary_label.setText(str(error))
            return
        if not product_ids:
            self.catalog_summary_label.setText("请输入至少一个有效的商品 ID。")
            return

        self._running = True
        self.catalog_read_button.setEnabled(False)
        self.catalog_stop_button.setEnabled(True)
        self.catalog_progress_bar.setRange(0, len(product_ids))
        self.catalog_progress_bar.setValue(0)
        self.catalog_progress_label.setText(f"准备读取 0/{len(product_ids)} 个商品")
        self.catalog_summary_label.setText("已发出读取请求，等待读取层回传本地结果。")
        self.read_requested.emit(product_ids)

    def set_catalog_progress(self, completed: int, total: int, message: str | None = None) -> None:
        """Reflect progress reported by an external read controller; perform no I/O."""
        total = max(total, 1)
        self.catalog_progress_bar.setRange(0, total)
        self.catalog_progress_bar.setValue(min(max(completed, 0), total))
        self.catalog_progress_label.setText(message or f"已读取 {completed}/{total} 个商品")

    def finish_catalog_read(self, stopped: bool = False) -> None:
        self._running = False
        self.catalog_read_button.setEnabled(True)
        self.catalog_stop_button.setEnabled(False)
        if not stopped:
            self.catalog_progress_label.setText("读取完成")

    def show_catalog_read_result(self, result: FullFieldReadResult) -> None:
        """Render an already-read result without coupling the widget to transport."""
        product_ids = tuple(str(product_id) for product_id in result.product_ids)
        if product_ids:
            self._catalog_results[product_ids[0]] = result
        self._render_catalog_results()

    def _render_catalog_results(self) -> None:
        self.catalog_tree.clear()
        self._catalog_nodes.clear()
        self._catalog_item_loaded.clear()

        source_count = 0
        errors: list[str] = []
        for product_id, result in self._catalog_results.items():
            product_item = QTreeWidgetItem([product_id, "", "", "", ""])
            product_item.setExpanded(True)
            self.catalog_tree.addTopLevelItem(product_item)
            for source_name, outcome in self._catalog_sources(result):
                root = self._catalog_root(outcome)
                status = self._catalog_value(outcome, "status", "")
                error = self._catalog_value(outcome, "error", "")
                source_item = QTreeWidgetItem([str(source_name), "", str(status), str(error or ""), ""])
                source_item.setExpanded(True)
                product_item.addChild(source_item)
                if root is None:
                    if error:
                        errors.append(f"{product_id}/{source_name}: {error}")
                    continue
                self._add_catalog_node_item(source_item, root)
                source_count += 1

        error_suffix = f"；失败来源：{'；'.join(errors)}" if errors else ""
        self.catalog_summary_label.setText(
            f"已读取 {len(self._catalog_results)} 个商品，展示 {source_count} 个已读取来源；展开节点可继续查看子字段。{error_suffix}"
        )
        self._apply_catalog_filter(self.catalog_filter_input.text())

    def _catalog_sources(self, result: object) -> tuple[tuple[str, object], ...]:
        sources = self._catalog_value(result, "sources", None)
        if isinstance(sources, Mapping):
            return tuple((str(name), outcome) for name, outcome in sources.items())
        if sources:
            return tuple((str(index + 1), outcome) for index, outcome in enumerate(sources))

        outcomes = self._catalog_value(result, "outcomes", ())
        if isinstance(outcomes, Mapping):
            return tuple((str(name), outcome) for name, outcome in outcomes.items())
        return tuple((str(self._catalog_value(outcome, "source", index + 1)), outcome) for index, outcome in enumerate(outcomes))

    def _catalog_root(self, outcome: object) -> CatalogTreeNode | None:
        for name in ("node", "root", "tree", "catalog"):
            candidate = self._catalog_value(outcome, name, None)
            if candidate is not None:
                return candidate
        if self._catalog_value(outcome, "key", None) is not None:
            return outcome
        return None

    def _add_catalog_node_item(self, parent: QTreeWidgetItem, node: CatalogTreeNode) -> QTreeWidgetItem:
        item = QTreeWidgetItem(
            [
                str(self._catalog_value(node, "key", "")),
                str(self._catalog_value(node, "path", "")),
                str(self._catalog_value(node, "type", self._catalog_value(node, "value_type", ""))),
                str(self._catalog_value(node, "value_summary", "")),
                "是" if self._catalog_value(node, "sensitive", False) else "否",
            ]
        )
        item.setChildIndicatorPolicy(QTreeWidgetItem.ChildIndicatorPolicy.ShowIndicator)
        parent.addChild(item)
        self._catalog_nodes[id(item)] = node
        return item

    def _load_catalog_item_children(self, item: QTreeWidgetItem) -> None:
        item_id = id(item)
        if item_id in self._catalog_item_loaded or item_id not in self._catalog_nodes:
            return
        self._catalog_item_loaded.add(item_id)
        for child in self._catalog_children(self._catalog_nodes[item_id]):
            self._add_catalog_node_item(item, child)
        self._apply_catalog_filter(self.catalog_filter_input.text())

    def _catalog_children(self, node: object) -> tuple[CatalogTreeNode, ...]:
        expand_children = self._catalog_value(node, "expand_children", None)
        if callable(expand_children):
            children = expand_children()
        else:
            children = self._catalog_value(node, "children", None)
            if children is None:
                children = self._catalog_value(node, "iter_children", ())
            if callable(children):
                children = children()
        return tuple(children or ())

    @staticmethod
    def _catalog_value(value: object, name: str, default: object) -> object:
        if isinstance(value, Mapping):
            return value.get(name, default)
        return getattr(value, name, default)

    def _apply_catalog_filter(self, query: str) -> None:
        needle = query.strip().casefold()

        def update_visibility(item: QTreeWidgetItem) -> bool:
            own_text = " ".join(item.text(column) for column in range(item.columnCount())).casefold()
            child_matches = any(update_visibility(item.child(index)) for index in range(item.childCount()))
            visible = not needle or needle in own_text or child_matches
            item.setHidden(not visible)
            return visible

        for index in range(self.catalog_tree.topLevelItemCount()):
            update_visibility(self.catalog_tree.topLevelItem(index))

    def _render_module(self, module: str) -> None:
        self._selected_module = module
        fields = self.fields_for_module(module)
        self._table.setRowCount(len(fields))
        for row, spec in enumerate(fields):
            values = (spec.label, spec.path, spec.draft_type, spec.value_type, spec.risk, spec.availability)
            for column, value in enumerate(values):
                self._table.setItem(row, column, QTableWidgetItem(str(value)))
        self._table.resizeColumnsToContents()
        self.settings_changed.emit()

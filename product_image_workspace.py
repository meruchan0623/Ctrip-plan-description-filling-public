# -*- coding: utf-8 -*-
"""产品图片图形化配置工作区。"""
from __future__ import annotations

import json
import queue
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import requests
from PyQt6.QtCore import (
    QEvent,
    QMimeData,
    QObject,
    QPoint,
    QRect,
    QSize,
    QTimer,
    Qt,
    pyqtSignal,
)
from PyQt6.QtGui import QColor, QIcon, QImageReader, QPainter, QPen, QPixmap
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QListView,
    QListWidget,
    QMessageBox,
    QPushButton,
    QPlainTextEdit,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ctrip_image_upload import encode_image_as_data_url
from ui_theme import semantic_colors
from product_image_workspace_state import (
    LocalImageInspection,
    ProductImageEditHistory,
    ProductImageEditorState,
    SiteImagePlan,
    WorkspaceImage,
    add_candidate,
    add_image_to_site,
    copy_site_plan,
    make_product_editor_state,
    move_image_in_site,
    remove_image_from_site,
    restore_product,
    restore_site,
    site_image_diff,
)


WORKSPACE_IMAGE_MIME = "application/x-ctrip-product-image"


def _fetch_thumbnail(url: str) -> bytes:
    response = requests.get(url, timeout=20)
    response.raise_for_status()
    return response.content


class RemoteThumbnailCache(QObject):
    changed = pyqtSignal(str)

    def __init__(
        self,
        fetch: Callable[[str], bytes] = _fetch_thumbnail,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.fetch = fetch
        self._icons: dict[str, QIcon] = {}
        self._pending: set[str] = set()
        self._failed: set[str] = set()
        self._results: queue.Queue[tuple[str, bytes | None]] = queue.Queue()
        self._executor = ThreadPoolExecutor(max_workers=4)
        self._closed = False
        self._timer = QTimer(self)
        self._timer.setInterval(30)
        self._timer.timeout.connect(self._drain)
        self._timer.start()

    def request(self, url: str) -> bool:
        normalized = str(url or "").strip()
        if (
            not normalized
            or normalized in self._icons
            or normalized in self._pending
            or normalized in self._failed
            or self._closed
        ):
            return False
        self._pending.add(normalized)

        def run() -> None:
            try:
                data = self.fetch(normalized)
            except Exception:
                data = None
            self._results.put((normalized, data))

        self._executor.submit(run)
        return True

    def icon(self, url: str) -> QIcon:
        return self._icons.get(str(url or "").strip(), QIcon())

    def _drain(self) -> None:
        if self._closed:
            return
        while True:
            try:
                url, data = self._results.get_nowait()
            except queue.Empty:
                break
            self._pending.discard(url)
            pixmap = QPixmap()
            if data and pixmap.loadFromData(data):
                self._icons[url] = QIcon(pixmap)
                self.changed.emit(url)
            else:
                self._failed.add(url)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._timer.stop()
        self._executor.shutdown(wait=False, cancel_futures=True)


@dataclass(frozen=True)
class LoadedProductImages:
    product_id: str
    product_info: dict[str, Any]
    site_rows: list[dict[str, Any]]
    currency_context: Any = None


@dataclass(frozen=True)
class ProductImageWorkspaceBackend:
    load_product: Callable[[str, threading.Event], LoadedProductImages]
    upload_image: Callable[[str, Path], Any] | None = None
    save_and_verify: Callable[[ProductImageEditorState, threading.Event], Any] | None = None
    open_advanced_config: Callable[[], None] | None = None


class ProductUploadCoordinator:
    def __init__(
        self,
        product_id: str,
        state: ProductImageEditorState,
        upload: Callable[[str, Path], WorkspaceImage],
        max_workers: int = 2,
        event_sink: Callable[[str, str, object], None] | None = None,
    ) -> None:
        self.product_id = str(product_id)
        self.state = state
        self.upload = upload
        self.max_workers = max(1, int(max_workers))
        self.event_sink = event_sink
        self._cancel_event = threading.Event()
        self._lock = threading.Lock()

    def _emit(self, kind: str, value: object) -> None:
        if self.event_sink is not None:
            self.event_sink(kind, self.product_id, value)

    def cancel(self) -> None:
        self._cancel_event.set()

    def run(self, candidate_keys: list[str]) -> None:
        eligible: list[str] = []
        with self._lock:
            for key in dict.fromkeys(candidate_keys):
                candidate = self.state.candidates.get(key)
                if candidate is None:
                    continue
                if candidate.status not in {
                    "local",
                    "warning",
                    "failed",
                    "canceled",
                }:
                    continue
                candidate.status = "queued"
                candidate.error = ""
                eligible.append(key)
        if not eligible:
            self._emit("upload_batch_done", {"uploaded": 0, "failed": 0, "canceled": 0})
            return

        def upload_one(key: str) -> str:
            with self._lock:
                candidate = self.state.candidates[key]
                if self._cancel_event.is_set():
                    candidate.status = "canceled"
                    self._emit("upload_canceled", key)
                    return "canceled"
                candidate.status = "uploading"
            self._emit("upload_started", key)
            try:
                result = self.upload(self.product_id, candidate.path)
                if not isinstance(result, WorkspaceImage):
                    raise TypeError("上传后端未返回 WorkspaceImage")
            except Exception as exc:
                with self._lock:
                    candidate.status = "failed"
                    candidate.error = str(exc)
                self._emit("upload_failed", {"key": key, "error": str(exc)})
                return "failed"
            with self._lock:
                candidate.uploaded = result
                candidate.status = "uploaded"
                candidate.error = ""
            self._emit("upload_succeeded", key)
            return "uploaded"

        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            statuses = list(executor.map(upload_one, eligible))
        self._emit(
            "upload_batch_done",
            {
                "uploaded": statuses.count("uploaded"),
                "failed": statuses.count("failed"),
                "canceled": statuses.count("canceled"),
            },
        )


def encode_drag_payload(
    kind: str,
    product_id: str,
    source: str,
    index: int = -1,
) -> bytes:
    if kind not in {"candidate", "online", "site"}:
        raise ValueError(f"未知图片拖拽类型：{kind}")
    if not str(product_id).strip() or not str(source).strip():
        raise ValueError("图片拖拽缺少产品或来源")
    return json.dumps(
        {
            "kind": kind,
            "productId": str(product_id),
            "source": str(source),
            "index": int(index),
        },
        ensure_ascii=False,
    ).encode("utf-8")


def decode_drag_payload(data: bytes) -> dict[str, object]:
    try:
        payload = json.loads(data.decode("utf-8"))
    except Exception as exc:
        raise ValueError("图片拖拽数据无效") from exc
    if not isinstance(payload, dict):
        raise ValueError("图片拖拽数据不是对象")
    kind = str(payload.get("kind") or "")
    product_id = str(payload.get("productId") or "")
    source = str(payload.get("source") or "")
    if kind not in {"candidate", "online", "site"} or not product_id or not source:
        raise ValueError("图片拖拽字段不完整")
    try:
        index = int(payload.get("index", -1))
    except (TypeError, ValueError) as exc:
        raise ValueError("图片拖拽索引无效") from exc
    return {
        "kind": kind,
        "productId": product_id,
        "source": source,
        "index": index,
    }


def inspect_local_image(path: str | Path) -> LocalImageInspection:
    normalized = Path(path).expanduser().resolve()
    size_bytes = normalized.stat().st_size if normalized.exists() else 0
    try:
        mime_type, _data_url = encode_image_as_data_url(normalized)
    except Exception as exc:
        return LocalImageInspection(
            path=normalized,
            mime_type="",
            size_bytes=size_bytes,
            width=0,
            height=0,
            allowed=False,
            error=str(exc),
        )

    reader = QImageReader(str(normalized))
    size = reader.size()
    if not reader.canRead() or not size.isValid():
        return LocalImageInspection(
            path=normalized,
            mime_type=mime_type,
            size_bytes=size_bytes,
            width=0,
            height=0,
            allowed=False,
            error="图片无法解码",
        )

    width = size.width()
    height = size.height()
    ratio = width / height if height else 0.0
    warnings: list[str] = []
    if width < 1080 or height < 608:
        warnings.append(f"尺寸 {width}×{height}，建议至少 1080×608")
    if abs(ratio - (16 / 9)) > 0.02:
        warnings.append(f"比例 {ratio:.3f}，建议 16:9")
    return LocalImageInspection(
        path=normalized,
        mime_type=mime_type,
        size_bytes=size_bytes,
        width=width,
        height=height,
        allowed=True,
        warning="；".join(warnings),
    )


class WorkspaceImageCardDelegate(QStyledItemDelegate):
    """Paint image items as compact workspace cards instead of native rows."""

    def paint(
        self,
        painter: QPainter,
        option: QStyleOptionViewItem,
        index,
    ) -> None:
        metadata = index.data(Qt.ItemDataRole.UserRole) or {}
        colors = semantic_colors(option.palette)
        card_rect = option.rect.adjusted(4, 4, -4, -4)
        selected = bool(
            option.state & QStyle.StateFlag.State_Selected
        )
        hovered = bool(
            option.state & QStyle.StateFlag.State_MouseOver
        )
        background = QColor(
            colors["header"] if selected or hovered else colors["card"]
        )
        border = QColor(
            colors["accent"] if selected else colors["strong_border"]
        )

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(border, 2 if selected else 1))
        painter.setBrush(background)
        painter.drawRoundedRect(card_rect, 8, 8)

        image_rect = QRect(
            card_rect.left() + 6,
            card_rect.top() + 6,
            max(20, card_rect.width() - 12),
            max(24, min(58, card_rect.height() - 42)),
        )
        placeholder = QColor(colors["subcard"])
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(placeholder)
        painter.drawRoundedRect(image_rect, 6, 6)
        icon = index.data(Qt.ItemDataRole.DecorationRole)
        if isinstance(icon, QIcon) and not icon.isNull():
            icon.paint(
                painter,
                image_rect.adjusted(2, 2, -2, -2),
                Qt.AlignmentFlag.AlignCenter,
            )
        else:
            painter.setPen(QColor(colors["muted"]))
            painter.drawText(
                image_rect,
                Qt.AlignmentFlag.AlignCenter,
                "图片",
            )

        if metadata.get("draggable", True):
            handle_rect = QRect(
                image_rect.left() + 5,
                image_rect.top() + 5,
                22,
                20,
            )
            handle_color = QColor(colors["text"])
            handle_color.setAlpha(210)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(handle_color)
            painter.drawRoundedRect(handle_rect, 6, 6)
            painter.setPen(QColor(colors["base"]))
            painter.drawText(
                handle_rect,
                Qt.AlignmentFlag.AlignCenter,
                "⠿",
            )

        badge = str(metadata.get("badge") or "")
        if badge:
            badge_font = painter.font()
            badge_font.setPointSize(max(7, badge_font.pointSize() - 2))
            badge_font.setBold(True)
            painter.setFont(badge_font)
            badge_width = min(
                image_rect.width() - 10,
                painter.fontMetrics().horizontalAdvance(badge) + 12,
            )
            badge_rect = QRect(
                image_rect.right() - badge_width - 5,
                image_rect.top() + 5,
                badge_width,
                20,
            )
            badge_color = QColor(colors["accent"])
            if metadata.get("badgeRole") in {
                "failed",
                "invalid",
                "canceled",
            }:
                badge_color = QColor(colors["strong_border"])
            elif metadata.get("badgeRole") in {"local", "warning", "queued"}:
                badge_color = QColor(colors["link"])
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(badge_color)
            painter.drawRoundedRect(badge_rect, 10, 10)
            painter.setPen(QColor(colors["accent_text"]))
            painter.drawText(
                badge_rect,
                Qt.AlignmentFlag.AlignCenter,
                painter.fontMetrics().elidedText(
                    badge,
                    Qt.TextElideMode.ElideRight,
                    badge_rect.width() - 8,
                ),
            )

        title_font = option.font
        title_font.setBold(True)
        painter.setFont(title_font)
        painter.setPen(QColor(colors["text"]))
        title = str(metadata.get("title") or index.data() or "")
        title_rect = QRect(
            card_rect.left() + 7,
            image_rect.bottom() + 5,
            card_rect.width() - 14,
            18,
        )
        painter.drawText(
            title_rect,
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            painter.fontMetrics().elidedText(
                title,
                Qt.TextElideMode.ElideRight,
                title_rect.width(),
            ),
        )
        subtitle = str(metadata.get("subtitle") or "")
        if subtitle:
            subtitle_font = option.font
            subtitle_font.setPointSize(max(7, subtitle_font.pointSize() - 1))
            painter.setFont(subtitle_font)
            painter.setPen(QColor(colors["muted"]))
            subtitle_rect = QRect(
                title_rect.left(),
                title_rect.bottom(),
                title_rect.width(),
                16,
            )
            painter.drawText(
                subtitle_rect,
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                painter.fontMetrics().elidedText(
                    subtitle,
                    Qt.TextElideMode.ElideRight,
                    subtitle_rect.width(),
                ),
            )
        painter.restore()


class ImageCardList(QListWidget):
    def __init__(
        self,
        product_id: str,
        kind: str,
        source: str = "",
        drop_handler: Callable[[bytes, int], bool] | None = None,
        display_mode: str = "grid",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.product_id = str(product_id)
        self.kind = kind
        self.source = source
        self.drop_handler = drop_handler
        self.display_mode = (
            "sequence" if display_mode == "sequence" else "grid"
        )
        self.drop_target_index: int | None = None
        self.setProperty("displayMode", self.display_mode)
        self.setProperty(
            "workspaceCardRole",
            "planned" if kind == "site" else kind,
        )
        self.setItemDelegate(WorkspaceImageCardDelegate(self))
        self.setDragEnabled(True)
        self.setAcceptDrops(drop_handler is not None)
        self.setDropIndicatorShown(drop_handler is not None)
        self.setViewMode(QListView.ViewMode.IconMode)
        self.setResizeMode(QListView.ResizeMode.Adjust)
        self.setFlow(QListView.Flow.LeftToRight)
        self.setIconSize(QSize(120, 66))
        if self.display_mode == "sequence":
            self.setWrapping(False)
            self.setGridSize(QSize(148, 104))
            self.setHorizontalScrollBarPolicy(
                Qt.ScrollBarPolicy.ScrollBarAsNeeded
            )
            self.setVerticalScrollBarPolicy(
                Qt.ScrollBarPolicy.ScrollBarAlwaysOff
            )
        else:
            self.setWrapping(True)
            self.setGridSize(QSize(142, 108))

    def add_workspace_item(
        self,
        text: str,
        source: str,
        index: int = -1,
        thumbnail_path: str | Path | None = None,
        thumbnail_url: str = "",
        thumbnail_cache: RemoteThumbnailCache | None = None,
        title: str = "",
        subtitle: str = "",
        badge: str = "",
        badge_role: str = "neutral",
        draggable: bool = True,
    ) -> None:
        self.addItem(text)
        item = self.item(self.count() - 1)
        item.setData(
            Qt.ItemDataRole.UserRole,
            {
                "source": str(source),
                "index": int(index),
                "title": str(title or text),
                "subtitle": str(subtitle),
                "badge": str(badge),
                "badgeRole": str(badge_role),
                "draggable": bool(draggable),
            },
        )
        if thumbnail_path is not None and Path(thumbnail_path).is_file():
            item.setIcon(QIcon(str(thumbnail_path)))
        elif thumbnail_url and thumbnail_cache is not None:
            icon = thumbnail_cache.icon(thumbnail_url)
            if not icon.isNull():
                item.setIcon(icon)
            else:
                thumbnail_cache.request(thumbnail_url)
        item.setSizeHint(
            QSize(148, 104)
            if self.display_mode == "sequence"
            else QSize(142, 108)
        )

    def mimeData(self, items):
        mime = QMimeData()
        if not items:
            return mime
        metadata = items[0].data(Qt.ItemDataRole.UserRole) or {}
        if not metadata.get("draggable", True):
            return mime
        source = str(metadata.get("source") or self.source)
        index = int(metadata.get("index", -1))
        mime.setData(
            WORKSPACE_IMAGE_MIME,
            encode_drag_payload(
                self.kind,
                self.product_id,
                source,
                index,
            ),
        )
        return mime

    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasFormat(WORKSPACE_IMAGE_MIME):
            self._set_drop_target(
                self._drop_index_at(event.position().toPoint())
            )
            event.acceptProposedAction()
            return
        event.ignore()

    def dragMoveEvent(self, event) -> None:
        if event.mimeData().hasFormat(WORKSPACE_IMAGE_MIME):
            self._set_drop_target(
                self._drop_index_at(event.position().toPoint())
            )
            event.acceptProposedAction()
            return
        event.ignore()

    def dragLeaveEvent(self, event) -> None:
        self._set_drop_target(None)
        super().dragLeaveEvent(event)

    def _drop_index_at(self, point: QPoint) -> int:
        index = self.indexAt(point)
        row = index.row()
        if row < 0:
            return self.count()
        rect = self.visualItemRect(self.item(row))
        if self.display_mode == "sequence":
            return row + int(point.x() > rect.center().x())
        return row + int(point.y() > rect.center().y())

    def _set_drop_target(self, index: int | None) -> None:
        normalized = (
            None
            if index is None
            else max(0, min(int(index), self.count()))
        )
        if normalized == self.drop_target_index:
            return
        self.drop_target_index = normalized
        self.viewport().update()

    def drop_target_text(self) -> str:
        if self.drop_target_index is None:
            return ""
        return f"放到这里，成为第 {self.drop_target_index + 1} 张"

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        if self.drop_target_index is None or self.drop_handler is None:
            return

        viewport_rect = self.viewport().rect()
        if self.count() == 0:
            insertion_x = 10
        elif self.drop_target_index < self.count():
            insertion_x = self.visualItemRect(
                self.item(self.drop_target_index)
            ).left()
        else:
            insertion_x = self.visualItemRect(
                self.item(self.count() - 1)
            ).right() + 5
        insertion_x = max(6, min(insertion_x, viewport_rect.right() - 6))

        painter = QPainter(self.viewport())
        highlight = self.palette().highlight().color()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(
            QPen(highlight, 3, Qt.PenStyle.DashLine)
        )
        painter.drawLine(
            insertion_x,
            8,
            insertion_x,
            max(8, viewport_rect.bottom() - 8),
        )

        label_width = min(170, max(110, viewport_rect.width() - 16))
        label_x = max(
            8,
            min(
                insertion_x + 7,
                viewport_rect.right() - label_width - 8,
            ),
        )
        label_rect = QRect(label_x, 10, label_width, 30)
        fill = self.palette().highlight().color()
        fill.setAlpha(225)
        painter.setBrush(fill)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(label_rect, 7, 7)
        painter.setPen(self.palette().highlightedText().color())
        painter.drawText(
            label_rect,
            Qt.AlignmentFlag.AlignCenter,
            self.drop_target_text(),
        )
        painter.end()

    def dropEvent(self, event) -> None:
        if self.drop_handler is None:
            self._set_drop_target(None)
            event.ignore()
            return
        try:
            data = bytes(event.mimeData().data(WORKSPACE_IMAGE_MIME))
            index = self.drop_target_index
            if index is None:
                index = self._drop_index_at(event.position().toPoint())
            accepted = self.drop_handler(data, index)
        except Exception:
            accepted = False
        finally:
            self._set_drop_target(None)
        if accepted:
            event.acceptProposedAction()
        else:
            event.ignore()


class CandidateImageList(ImageCardList):
    paths_dropped = pyqtSignal(list)

    def __init__(self, product_id: str, parent: QWidget | None = None) -> None:
        super().__init__(product_id, "candidate", parent=parent)
        self.setAcceptDrops(True)
        self.setSelectionMode(
            QAbstractItemView.SelectionMode.ExtendedSelection
        )

    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            return
        super().dragEnterEvent(event)

    def dragMoveEvent(self, event) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            return
        super().dragMoveEvent(event)

    def dropEvent(self, event) -> None:
        if event.mimeData().hasUrls():
            paths = [
                url.toLocalFile()
                for url in event.mimeData().urls()
                if url.isLocalFile()
            ]
            if paths:
                self.paths_dropped.emit(paths)
                event.acceptProposedAction()
                return
        super().dropEvent(event)


def _image_card_text(image) -> str:
    return image.image_name or image.image_id or image.image_url


def workspace_image_detail_text(image: WorkspaceImage) -> str:
    return "\n".join(
        [
            f"imageId: {image.image_id}",
            f"imageUrl: {image.image_url}",
            f"imageName: {image.image_name}",
            f"imageSource: {image.image_source}",
            "",
            "接口原始字段:",
            json.dumps(image.raw, ensure_ascii=False, indent=2),
        ]
    )


def product_image_change_summary(state: ProductImageEditorState) -> str:
    lines = [f"产品 {state.product_id}"]
    for site in state.sites.values():
        diff = site_image_diff(site)
        if not site.dirty:
            continue
        parts = [f"新增 {len(diff.added)}", f"删除 {len(diff.removed)}"]
        if diff.order_changed:
            parts.append("已调序")
        lines.append(f"- {site.label} ({site.code})：" + "，".join(parts))
    return "\n".join(lines)


class WorkspaceImageDetailDialog(QDialog):
    def __init__(
        self,
        image: WorkspaceImage,
        icon: QIcon | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(image.image_name or image.image_id or "图片详情")
        self.resize(760, 620)
        layout = QVBoxLayout(self)
        preview = QLabel(self)
        preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        if icon is not None and not icon.isNull():
            preview.setPixmap(icon.pixmap(QSize(640, 360)))
        else:
            preview.setText("缩略图正在加载或不可用")
        layout.addWidget(preview)
        details = QTextEdit(self)
        details.setReadOnly(True)
        details.setPlainText(workspace_image_detail_text(image))
        layout.addWidget(details, 1)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Close,
            self,
        )
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)


class ProductImageOperationGuideDialog(QDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._theme_refreshing = False
        self.setObjectName("productImageOperationGuideDialog")
        self.setWindowTitle("产品图片操作指南")
        self.resize(720, 570)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(10)

        title = QLabel("产品图片配置流程", self)
        title.setProperty("productImageGuideTitle", True)
        subtitle = QLabel(
            "按顺序完成四步；每一步的结果都会成为下一步的前置条件。",
            self,
        )
        subtitle.setProperty("productImageGuideHint", True)
        layout.addWidget(title)
        layout.addWidget(subtitle)

        steps = (
            (
                "01",
                "读取产品",
                "输入产品 ID 并读取线上图片基线；第三栏会按语言站点分别显示当前配置。",
            ),
            (
                "02",
                "选择并上传",
                "把 JPEG / PNG 加入第二栏，选中后点击上传；等待图片卡片明确显示“已上传”。",
            ),
            (
                "03",
                "拖入具体站点",
                "从第二栏拖到第三栏某个语言站点的图片列表；落点决定插入位置，拖到末尾就是追加。",
            ),
            (
                "04",
                "保存并回读",
                "确认站点标题出现新增或调序提示，再提交当前产品；系统会保存并逐站点回读验证。",
            ),
        )
        for index, (number, heading, description) in enumerate(steps):
            card = QFrame(self)
            card.setProperty("productImageGuideStep", True)
            card_layout = QHBoxLayout(card)
            card_layout.setContentsMargins(12, 9, 12, 9)
            card_layout.setSpacing(10)
            number_label = QLabel(number, card)
            number_label.setProperty("productImageGuideNumber", True)
            copy = QVBoxLayout()
            copy.setSpacing(2)
            heading_label = QLabel(heading, card)
            heading_label.setProperty("productImageGuideHeading", True)
            description_label = QLabel(description, card)
            description_label.setProperty("productImageGuideHint", True)
            description_label.setWordWrap(True)
            copy.addWidget(heading_label)
            copy.addWidget(description_label)
            card_layout.addWidget(number_label)
            card_layout.addLayout(copy, 1)
            layout.addWidget(card)
            if index < len(steps) - 1:
                arrow = QLabel("↓", self)
                arrow.setProperty("productImageGuideArrow", True)
                arrow.setAlignment(Qt.AlignmentFlag.AlignCenter)
                layout.addWidget(arrow)

        reminder = QLabel(
            "关键门禁：只有显示“已上传”的候选图片才能拖入第三栏；“待上传”“上传中”或“上传失败”都会被拒绝。",
            self,
        )
        reminder.setObjectName("productImageGuideReminder")
        reminder.setWordWrap(True)
        layout.addWidget(reminder)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Close,
            self,
        )
        buttons.button(QDialogButtonBox.StandardButton.Close).setText("关闭")
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self._apply_theme()

    def _apply_theme(self) -> None:
        if self._theme_refreshing:
            return
        self._theme_refreshing = True
        try:
            colors = semantic_colors(self.palette())
            self.setStyleSheet(
                f"""
            QDialog#productImageOperationGuideDialog {{
                background-color: {colors['window']};
                color: {colors['text']};
            }}
            QFrame[productImageGuideStep="true"] {{
                background-color: {colors['card']};
                border: 1px solid {colors['strong_border']};
                border-radius: 7px;
            }}
            QLabel[productImageGuideTitle="true"] {{
                color: {colors['text']};
                font-size: 18px;
                font-weight: 700;
            }}
            QLabel[productImageGuideHeading="true"] {{
                color: {colors['text']};
                font-size: 13px;
                font-weight: 700;
            }}
            QLabel[productImageGuideHint="true"] {{
                color: {colors['muted']};
            }}
            QLabel[productImageGuideNumber="true"],
            QLabel[productImageGuideArrow="true"] {{
                color: {colors['accent']};
                font-weight: 700;
            }}
            #productImageGuideReminder {{
                background-color: {colors['subcard']};
                color: {colors['link']};
                border: 1px solid {colors['accent']};
                border-radius: 6px;
                padding: 8px 10px;
                font-weight: 600;
            }}
                """
            )
        finally:
            self._theme_refreshing = False

    def changeEvent(self, event: QEvent) -> None:
        super().changeEvent(event)
        if event.type() == QEvent.Type.PaletteChange:
            self._apply_theme()


class SitePlanPanel(QFrame):
    def __init__(
        self,
        product_id: str,
        site: SiteImagePlan,
        drop_handler: Callable[[bytes, int], bool],
        remove_handler: Callable[[int], bool],
        copy_handler: Callable[[], bool],
        restore_handler: Callable[[], None],
        detail_handler: Callable[[WorkspaceImage], None],
        thumbnail_cache: RemoteThumbnailCache | None = None,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.site = site
        self.thumbnail_cache = thumbnail_cache
        self.setProperty("productImageSitePanel", True)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)
        self.title = QLabel(self)
        self.title.setProperty("productImageSiteTitle", True)
        self.image_list = ImageCardList(
            product_id=product_id,
            kind="site",
            source=site.code,
            drop_handler=drop_handler,
            display_mode="sequence",
            parent=self,
        )
        self.image_list.setFixedHeight(128)
        self.image_list.itemDoubleClicked.connect(
            lambda item: self._open_item_detail(item, detail_handler)
        )
        header = QHBoxLayout()
        header.addWidget(self.title, 1)
        layout.addLayout(header)
        actions = QHBoxLayout()
        actions.addStretch(1)
        remove_btn = QPushButton("删除选中", self)
        copy_btn = QPushButton("复制到其他站点", self)
        restore_btn = QPushButton("恢复本站", self)
        for button in (remove_btn, copy_btn, restore_btn):
            button.setProperty("productImageToolButton", True)
        remove_btn.clicked.connect(
            lambda: remove_handler(self.image_list.currentRow())
            if self.image_list.currentRow() >= 0
            else None
        )
        copy_btn.clicked.connect(
            lambda _checked=False: copy_handler()
        )
        restore_btn.clicked.connect(
            lambda _checked=False: restore_handler()
        )
        actions.addWidget(remove_btn)
        actions.addWidget(copy_btn)
        actions.addWidget(restore_btn)
        layout.addLayout(actions)
        layout.addWidget(self.image_list)
        self.refresh()

    def _open_item_detail(
        self,
        item,
        detail_handler: Callable[[WorkspaceImage], None],
    ) -> None:
        metadata = item.data(Qt.ItemDataRole.UserRole) or {}
        index = int(metadata.get("index", -1))
        if 0 <= index < len(self.site.planned):
            detail_handler(self.site.planned[index])

    def refresh(self) -> None:
        diff = site_image_diff(self.site)
        if self.site.dirty:
            details = [
                f"新增 {len(diff.added)}",
                f"删除 {len(diff.removed)}",
            ]
            if diff.order_changed:
                details.append("已调序")
            status = "已修改 · " + " · ".join(details)
        else:
            status = "未修改"
        self.title.setText(
            f"{self.site.label} ({self.site.code}) · {status}"
        )
        next_state = "changed" if self.site.dirty else "clean"
        if self.property("sitePlanState") != next_state:
            self.setProperty("sitePlanState", next_state)
            self.style().unpolish(self)
            self.style().polish(self)
            self.update()
        self.image_list.clear()
        for index, image in enumerate(self.site.planned, start=1):
            self.image_list.add_workspace_item(
                f"{index}. {_image_card_text(image)}",
                source=self.site.code,
                index=index - 1,
                thumbnail_url=image.image_url,
                thumbnail_cache=self.thumbnail_cache,
                title=_image_card_text(image),
                subtitle=f"imageId: {image.image_id or '—'}",
                badge=f"第 {index} 张",
                badge_role="planned",
            )


class CandidateImagePanel(QFrame):
    def __init__(
        self,
        state: ProductImageEditorState,
        add_paths: Callable[[list[str | Path]], None] | None = None,
        upload_candidates: Callable[[list[str]], None] | None = None,
        retry_failed: Callable[[], None] | None = None,
        cancel_uploads: Callable[[], None] | None = None,
        remove_candidates: Callable[[list[str]], None] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.state = state
        self.setProperty("toolbarRole", "candidate")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)
        self.drop_hint = QLabel(
            "先选图并上传；卡片显示“已上传”后才能拖入右侧站点",
            self,
        )
        self.add_paths = add_paths
        self.upload_candidates = upload_candidates
        self.retry_failed = retry_failed
        self.cancel_uploads = cancel_uploads
        self.remove_candidates = remove_candidates
        self.image_list = CandidateImageList(state.product_id, self)
        self.image_list.paths_dropped.connect(self._add_paths)
        action_grid = QGridLayout()
        action_grid.setHorizontalSpacing(5)
        action_grid.setVerticalSpacing(5)
        self.choose_btn = QPushButton("批量选择图片", self)
        self.upload_selected_btn = QPushButton("上传选中", self)
        self.upload_all_btn = QPushButton("上传全部待上传", self)
        self.retry_btn = QPushButton("重试失败", self)
        self.cancel_btn = QPushButton("取消排队", self)
        self.select_all_btn = QPushButton("全选", self)
        self.clear_selection_btn = QPushButton("取消全选", self)
        self.remove_btn = QPushButton("删除选中", self)
        self.choose_btn.setProperty("productImageActionRole", "choose")
        self.upload_selected_btn.setProperty(
            "productImageActionRole", "upload"
        )
        self.upload_all_btn.setProperty(
            "productImageActionRole", "upload"
        )
        self.choose_btn.clicked.connect(self._choose_files)
        self.upload_selected_btn.clicked.connect(
            lambda: self._upload(self.selected_keys())
        )
        self.upload_all_btn.clicked.connect(
            lambda: self._upload(self.uploadable_keys())
        )
        self.retry_btn.clicked.connect(
            lambda: self.retry_failed and self.retry_failed()
        )
        self.cancel_btn.clicked.connect(
            lambda: self.cancel_uploads and self.cancel_uploads()
        )
        self.select_all_btn.clicked.connect(self.image_list.selectAll)
        self.clear_selection_btn.clicked.connect(
            self.image_list.clearSelection
        )
        self.remove_btn.clicked.connect(
            lambda: self.remove_candidates(self.selected_keys())
            if self.remove_candidates and self.selected_keys()
            else None
        )
        for index, button in enumerate(
            (
                self.choose_btn,
                self.upload_selected_btn,
                self.upload_all_btn,
                self.retry_btn,
                self.select_all_btn,
                self.clear_selection_btn,
                self.remove_btn,
                self.cancel_btn,
            )
        ):
            action_grid.addWidget(button, index // 2, index % 2)
        layout.addWidget(self.drop_hint)
        layout.addLayout(action_grid)
        layout.addWidget(self.image_list)
        self.refresh()

    def _choose_files(self) -> None:
        paths, _filter = QFileDialog.getOpenFileNames(
            self,
            "选择产品图片",
            "",
            "图片 (*.jpg *.jpeg *.png)",
        )
        self._add_paths(paths)

    def _add_paths(self, paths: list[str | Path]) -> None:
        if paths and self.add_paths is not None:
            self.add_paths(paths)

    def selected_keys(self) -> list[str]:
        return [
            str(item.data(Qt.ItemDataRole.UserRole)["source"])
            for item in self.image_list.selectedItems()
        ]

    def uploadable_keys(self) -> list[str]:
        return [
            key
            for key, candidate in self.state.candidates.items()
            if candidate.status in {"local", "warning", "failed", "canceled"}
        ]

    def _upload(self, keys: list[str]) -> None:
        if keys and self.upload_candidates is not None:
            self.upload_candidates(keys)

    def refresh(self) -> None:
        self.image_list.clear()
        status_labels = {
            "local": "待上传",
            "warning": "有建议，可上传",
            "invalid": "不可上传",
            "queued": "排队中",
            "uploading": "上传中",
            "uploaded": "已上传",
            "failed": "上传失败",
            "canceled": "已取消",
        }
        for candidate in self.state.candidates.values():
            size = (
                f"{candidate.width}×{candidate.height}"
                if candidate.width and candidate.height
                else "未读取尺寸"
            )
            self.image_list.add_workspace_item(
                f"{candidate.path.name} · {size} · "
                f"{status_labels.get(candidate.status, candidate.status)}",
                source=str(candidate.path.expanduser().resolve()),
                thumbnail_path=candidate.path,
                title=candidate.path.name,
                subtitle=size,
                badge=status_labels.get(candidate.status, candidate.status),
                badge_role=candidate.status,
                draggable=candidate.status == "uploaded",
            )
            item = self.image_list.item(self.image_list.count() - 1)
            details = [
                f"路径：{candidate.path}",
                f"格式：{candidate.mime_type or '未知'}",
                f"体积：{candidate.size_bytes} bytes",
            ]
            if candidate.warning:
                details.append(f"提示：{candidate.warning}")
            if candidate.error:
                details.append(f"错误：{candidate.error}")
            item.setToolTip("\n".join(details))


class ProductImageEditorPane(QWidget):
    state_changed = pyqtSignal(str)

    def __init__(
        self,
        state: ProductImageEditorState,
        upload_candidates: Callable[[list[str]], None] | None = None,
        retry_failed: Callable[[], None] | None = None,
        cancel_uploads: Callable[[], None] | None = None,
        thumbnail_fetch: Callable[[str], bytes] = _fetch_thumbnail,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.state = state
        self.editing_enabled = True
        self.history = ProductImageEditHistory(state)
        self.site_panels: dict[str, SitePlanPanel] = {}
        self.online_image_lists: dict[str, ImageCardList] = {}
        self._detail_dialogs: list[WorkspaceImageDetailDialog] = []
        self.thumbnail_cache = RemoteThumbnailCache(
            fetch=thumbnail_fetch,
            parent=self,
        )
        self.thumbnail_cache.changed.connect(
            self._refresh_remote_thumbnails
        )
        self._inspection_queue: queue.Queue[LocalImageInspection] = queue.Queue()
        self._inspection_pending: set[str] = set()
        self._inspection_closed = False
        self._inspection_timer = QTimer(self)
        self._inspection_timer.setInterval(20)
        self._inspection_timer.timeout.connect(self._drain_inspection_queue)
        self._inspection_timer.start()

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(8)
        self.summary_label = QLabel(self)
        self.summary_label.setObjectName("productImageProductSummary")
        root.addWidget(self.summary_label)

        self.splitter = QSplitter(self)
        self.splitter.setChildrenCollapsible(False)
        root.addWidget(self.splitter, 1)

        self.online_panel = QFrame(self.splitter)
        self.online_panel.setProperty("productImageEditorColumn", True)
        self.online_panel.setProperty("columnRole", "online")
        online_layout = QVBoxLayout(self.online_panel)
        self.online_title = QLabel("① 当前线上图片", self.online_panel)
        self.online_title.setProperty("productImageColumnTitle", True)
        online_layout.addWidget(self.online_title)
        online_scroll = QScrollArea(self.online_panel)
        online_scroll.setWidgetResizable(True)
        online_body = QWidget(online_scroll)
        online_body_layout = QVBoxLayout(online_body)
        for site in state.sites.values():
            title = QLabel(
                f"{site.label} ({site.code}) · {len(site.baseline)} 张",
                online_body,
            )
            image_list = ImageCardList(
                product_id=state.product_id,
                kind="online",
                source=site.code,
                display_mode="sequence",
                parent=online_body,
            )
            image_list.setFixedHeight(128)
            self.online_image_lists[site.code] = image_list
            image_list.itemDoubleClicked.connect(
                lambda item, target=site: self._open_online_item_detail(
                    target, item
                )
            )
            self._populate_online_image_list(site, image_list)
            online_body_layout.addWidget(title)
            online_body_layout.addWidget(image_list)
        online_body_layout.addStretch(1)
        online_scroll.setWidget(online_body)
        online_layout.addWidget(online_scroll, 1)
        self.splitter.addWidget(self.online_panel)

        self.candidate_container = QFrame(self.splitter)
        self.candidate_container.setProperty("productImageEditorColumn", True)
        self.candidate_container.setProperty("columnRole", "candidate")
        candidate_layout = QVBoxLayout(self.candidate_container)
        self.candidate_title = QLabel(
            "② 当前产品候选图片",
            self.candidate_container,
        )
        self.candidate_title.setProperty("productImageColumnTitle", True)
        candidate_layout.addWidget(self.candidate_title)
        self.candidate_panel = CandidateImagePanel(
            state,
            add_paths=self.enqueue_candidate_paths,
            upload_candidates=upload_candidates,
            retry_failed=retry_failed,
            cancel_uploads=cancel_uploads,
            remove_candidates=self.remove_candidates,
            parent=self.candidate_container,
        )
        candidate_layout.addWidget(self.candidate_panel, 1)
        self.splitter.addWidget(self.candidate_container)

        self.planned_container = QFrame(self.splitter)
        self.planned_container.setProperty("productImageEditorColumn", True)
        self.planned_container.setProperty("columnRole", "planned")
        planned_layout = QVBoxLayout(self.planned_container)
        planned_header = QHBoxLayout()
        self.planned_title = QLabel(
            "③ 待提交配置",
            self.planned_container,
        )
        self.planned_title.setProperty("productImageColumnTitle", True)
        planned_header.addWidget(self.planned_title)
        planned_header.addStretch(1)
        undo_btn = QPushButton("撤销", self.planned_container)
        redo_btn = QPushButton("重做", self.planned_container)
        restore_btn = QPushButton("恢复线上", self.planned_container)
        for button in (undo_btn, redo_btn, restore_btn):
            button.setProperty("productImageToolButton", True)
        undo_btn.clicked.connect(self.undo)
        redo_btn.clicked.connect(self.redo)
        restore_btn.clicked.connect(self.restore_product_plan)
        planned_header.addWidget(undo_btn)
        planned_header.addWidget(redo_btn)
        planned_header.addWidget(restore_btn)
        planned_layout.addLayout(planned_header)

        planned_scroll = QScrollArea(self.planned_container)
        planned_scroll.setWidgetResizable(True)
        planned_body = QWidget(planned_scroll)
        self.planned_body_layout = QVBoxLayout(planned_body)
        for code, site in state.sites.items():
            panel = SitePlanPanel(
                state.product_id,
                site,
                lambda payload, index, target=code: self.handle_workspace_drop(
                    payload,
                    target,
                    index,
                ),
                lambda index, target=code: self.remove_site_image(
                    target, index
                ),
                lambda target=code: self.choose_copy_targets(target),
                lambda target=code: self.restore_site_plan(target),
                self.open_image_detail,
                thumbnail_cache=self.thumbnail_cache,
                parent=planned_body,
            )
            self.site_panels[code] = panel
            self.planned_body_layout.addWidget(panel)
        self.planned_body_layout.addStretch(1)
        planned_scroll.setWidget(planned_body)
        planned_layout.addWidget(planned_scroll, 1)
        self.splitter.addWidget(self.planned_container)

        self.splitter.setStretchFactor(0, 1)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setStretchFactor(2, 2)
        self.splitter.setSizes([270, 330, 510])
        for index in range(3):
            self.splitter.widget(index).setSizePolicy(
                QSizePolicy.Policy.Expanding,
                QSizePolicy.Policy.Expanding,
            )
        self.refresh()

    def closeEvent(self, event) -> None:
        self._inspection_closed = True
        self._inspection_timer.stop()
        self.thumbnail_cache.close()
        super().closeEvent(event)

    def _populate_online_image_list(
        self,
        site: SiteImagePlan,
        image_list: ImageCardList,
    ) -> None:
        image_list.clear()
        for index, image in enumerate(site.baseline, start=1):
            image_list.add_workspace_item(
                f"{index}. {_image_card_text(image)}",
                source=site.code,
                index=index - 1,
                thumbnail_url=image.image_url,
                thumbnail_cache=self.thumbnail_cache,
                title=_image_card_text(image),
                subtitle=f"imageId: {image.image_id or '—'}",
                badge="线上",
                badge_role="online",
            )

    def _refresh_remote_thumbnails(self, _url: str) -> None:
        for code, image_list in self.online_image_lists.items():
            self._populate_online_image_list(self.state.sites[code], image_list)
        for panel in self.site_panels.values():
            panel.refresh()

    def _open_online_item_detail(self, site: SiteImagePlan, item) -> None:
        metadata = item.data(Qt.ItemDataRole.UserRole) or {}
        index = int(metadata.get("index", -1))
        if 0 <= index < len(site.baseline):
            self.open_image_detail(site.baseline[index])

    def open_image_detail(
        self,
        image: WorkspaceImage,
    ) -> WorkspaceImageDetailDialog:
        dialog = WorkspaceImageDetailDialog(
            image,
            self.thumbnail_cache.icon(image.image_url),
            self,
        )
        self._detail_dialogs.append(dialog)
        dialog.finished.connect(
            lambda _result, target=dialog: self._detail_dialogs.remove(target)
            if target in self._detail_dialogs
            else None
        )
        dialog.show()
        return dialog

    def refresh(self) -> None:
        for panel in self.site_panels.values():
            panel.refresh()
        self.candidate_panel.refresh()
        modified = sum(
            1 for site in self.state.sites.values() if site.dirty
        )
        self.summary_label.setText(
            f"产品 {self.state.product_id} · {len(self.state.sites)} 个站点 · "
            f"{modified} 个已修改"
        )

    def _finish_edit(self) -> None:
        self.refresh()
        self.state_changed.emit(self.state.product_id)

    def set_editing_enabled(self, enabled: bool) -> None:
        self.editing_enabled = bool(enabled)
        self.candidate_panel.setEnabled(self.editing_enabled)
        self.planned_container.setEnabled(self.editing_enabled)

    def add_candidate_to_site(
        self,
        candidate_key: str,
        site_code: str,
        index: int | None = None,
    ) -> bool:
        if not self.editing_enabled:
            return False
        candidate = self.state.candidates.get(candidate_key)
        if (
            candidate is None
            or candidate.status != "uploaded"
            or candidate.uploaded is None
        ):
            return False
        self.history.perform(
            lambda: add_image_to_site(
                self.state,
                site_code,
                candidate.uploaded,
                index,
            )
        )
        self._finish_edit()
        return True

    def remove_candidates(self, candidate_keys: list[str]) -> int:
        if not self.editing_enabled:
            return 0
        removed = 0
        for key in dict.fromkeys(candidate_keys):
            candidate = self.state.candidates.get(key)
            if candidate is None or candidate.status in {"queued", "uploading"}:
                continue
            del self.state.candidates[key]
            removed += 1
        if removed:
            self.candidate_panel.refresh()
            self.state_changed.emit(self.state.product_id)
        return removed

    def handle_workspace_drop(
        self,
        payload_data: bytes,
        target_site_code: str,
        target_index: int,
    ) -> bool:
        if not self.editing_enabled:
            return False
        try:
            payload = decode_drag_payload(payload_data)
            if payload["productId"] != self.state.product_id:
                return False
            kind = str(payload["kind"])
            source = str(payload["source"])
            source_index = int(payload["index"])
            if kind == "candidate":
                return self.add_candidate_to_site(
                    source,
                    target_site_code,
                    target_index,
                )
            if kind == "online":
                source_site = self.state.sites.get(source)
                if (
                    source_site is None
                    or source_index < 0
                    or source_index >= len(source_site.baseline)
                ):
                    return False
                self.history.perform(
                    lambda: add_image_to_site(
                        self.state,
                        target_site_code,
                        source_site.baseline[source_index],
                        target_index,
                    )
                )
                self._finish_edit()
                return True
            if source not in self.state.sites or source_index < 0:
                return False
            source_images = self.state.sites[source].planned
            if source_index >= len(source_images):
                return False
            if source == target_site_code:
                self.move_site_image(
                    source,
                    source_index,
                    target_index,
                )
                return True
            image = source_images[source_index]
            self.history.perform(
                lambda: add_image_to_site(
                    self.state,
                    target_site_code,
                    image,
                    target_index,
                )
            )
            self._finish_edit()
            return True
        except (KeyError, TypeError, ValueError, IndexError):
            return False

    def enqueue_candidate_paths(
        self,
        paths: list[str | Path],
        inspector: Callable[[str | Path], LocalImageInspection] = inspect_local_image,
    ) -> None:
        queued: list[Path] = []
        for path in paths:
            normalized = Path(path).expanduser().resolve()
            key = str(normalized)
            if key in self.state.candidates or key in self._inspection_pending:
                continue
            self._inspection_pending.add(key)
            queued.append(normalized)
        if not queued:
            return

        def run() -> None:
            for candidate_path in queued:
                inspection = inspector(candidate_path)
                self._inspection_queue.put(inspection)

        threading.Thread(target=run, daemon=True).start()

    def _drain_inspection_queue(self) -> None:
        if self._inspection_closed:
            return
        changed = False
        while True:
            try:
                inspection = self._inspection_queue.get_nowait()
            except queue.Empty:
                break
            self._inspection_pending.discard(str(inspection.path.resolve()))
            try:
                add_candidate(self.state, inspection)
            except ValueError:
                continue
            changed = True
        if changed:
            self.candidate_panel.refresh()
            self.state_changed.emit(self.state.product_id)

    def move_site_image(
        self,
        site_code: str,
        old_index: int,
        new_index: int,
    ) -> None:
        if not self.editing_enabled:
            return
        self.history.perform(
            lambda: move_image_in_site(
                self.state,
                site_code,
                old_index,
                new_index,
            )
        )
        self._finish_edit()

    def remove_site_image(self, site_code: str, index: int) -> bool:
        if not self.editing_enabled:
            return False
        site = self.state.sites.get(site_code)
        if site is None or index < 0 or index >= len(site.planned):
            return False
        self.history.perform(
            lambda: remove_image_from_site(self.state, site_code, index)
        )
        self._finish_edit()
        return True

    def copy_site_to_other_sites(self, site_code: str) -> bool:
        targets = [
            code for code in self.state.sites if code != site_code
        ]
        return self.copy_site_to_sites(site_code, targets)

    def copy_site_to_sites(
        self,
        site_code: str,
        target_codes: list[str],
    ) -> bool:
        if not self.editing_enabled or site_code not in self.state.sites:
            return False
        targets = [
            code
            for code in dict.fromkeys(target_codes)
            if code in self.state.sites and code != site_code
        ]
        if not targets:
            return False
        self.history.perform(
            lambda: copy_site_plan(self.state, site_code, targets)
        )
        self._finish_edit()
        return True

    def choose_copy_targets(self, site_code: str) -> bool:
        if not self.editing_enabled or site_code not in self.state.sites:
            return False
        dialog = QDialog(self)
        dialog.setWindowTitle("选择要复制到的站点")
        layout = QVBoxLayout(dialog)
        layout.addWidget(QLabel("可多选目标站点：", dialog))
        site_list = QListWidget(dialog)
        site_list.setSelectionMode(
            QAbstractItemView.SelectionMode.ExtendedSelection
        )
        for code, site in self.state.sites.items():
            if code == site_code:
                continue
            site_list.addItem(f"{site.label} ({code})")
            item = site_list.item(site_list.count() - 1)
            item.setData(Qt.ItemDataRole.UserRole, code)
        layout.addWidget(site_list)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel,
            dialog,
        )
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return False
        targets = [
            str(item.data(Qt.ItemDataRole.UserRole))
            for item in site_list.selectedItems()
        ]
        return self.copy_site_to_sites(site_code, targets)

    def apply_site_to_all_sites(self, site_code: str) -> bool:
        targets = [
            code
            for code in self.state.sites
            if code != site_code
        ]
        return self.copy_site_to_sites(site_code, targets)

    def restore_site_plan(self, site_code: str) -> None:
        if not self.editing_enabled:
            return
        self.history.perform(lambda: restore_site(self.state, site_code))
        self._finish_edit()

    def restore_product_plan(self) -> None:
        if not self.editing_enabled:
            return
        self.history.perform(lambda: restore_product(self.state))
        self._finish_edit()

    def undo(self) -> bool:
        if not self.editing_enabled:
            return False
        changed = self.history.undo()
        if changed:
            self._finish_edit()
        return changed

    def redo(self) -> bool:
        if not self.editing_enabled:
            return False
        changed = self.history.redo()
        if changed:
            self._finish_edit()
        return changed


class ProductImageWorkspace(QWidget):
    write_started = pyqtSignal(str)
    write_finished = pyqtSignal(str)
    auth_refresh_requested = pyqtSignal()
    settings_changed = pyqtSignal()
    request_failed = pyqtSignal(str, int)

    def __init__(
        self,
        backend: ProductImageWorkspaceBackend,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.backend = backend
        self.product_order: list[str] = []
        self.product_states: dict[str, ProductImageEditorState] = {}
        self.product_panes: dict[str, ProductImageEditorPane] = {}
        self.failed_products: dict[str, str] = {}
        self.upload_coordinators: dict[str, ProductUploadCoordinator] = {}
        self.upload_threads: dict[str, threading.Thread] = {}
        self.save_thread: threading.Thread | None = None
        self.save_results: dict[str, str] = {}
        self.save_messages: dict[str, str] = {}
        self._event_queue: queue.Queue[tuple[str, str, object]] = queue.Queue()
        self._stop_event = threading.Event()
        self._closed = False
        self._theme_refreshing = False
        self._guide_dialog: ProductImageOperationGuideDialog | None = None
        self._status_base = "输入产品 ID 后读取当前图片配置"
        self._request_stats_text = ""

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(6)

        workflow_header = QFrame(self)
        workflow_header.setObjectName("productImageWorkflowHeader")
        workflow_header.setFrameShape(QFrame.Shape.StyledPanel)
        workflow_header_layout = QHBoxLayout(workflow_header)
        workflow_header_layout.setContentsMargins(14, 7, 14, 7)
        workflow_header_layout.setSpacing(20)
        workflow_copy = QVBoxLayout()
        workflow_copy.setSpacing(2)
        workflow_title = QLabel("产品图片工作台", workflow_header)
        workflow_title.setProperty("productImageWorkflowTitle", True)
        workflow_subtitle = QLabel(
            "按产品与语言站点核对线上图片，上传候选图并形成可回读验证的修改",
            workflow_header,
        )
        workflow_subtitle.setProperty("productImageWorkflowSubtitle", True)
        workflow_steps = QLabel(
            "读取 → 上传 → 编排 → 保存回读",
            workflow_header,
        )
        workflow_steps.setProperty("productImageWorkflowSteps", True)
        workflow_copy.addWidget(workflow_title)
        workflow_copy.addWidget(workflow_subtitle)
        workflow_copy.addWidget(workflow_steps)
        workflow_header_layout.addLayout(workflow_copy, 2)

        self.guide_btn = QPushButton("操作指南", workflow_header)
        self.guide_btn.setObjectName("productImageGuideAction")
        self.guide_btn.setProperty("productImageActionRole", "guide")
        self.guide_btn.setToolTip("查看选择、上传、拖入站点和保存回读的完整流程")
        self.guide_btn.clicked.connect(self.open_operation_guide)
        workflow_header_layout.addWidget(self.guide_btn)

        runtime_status = QVBoxLayout()
        runtime_status.setSpacing(3)
        runtime_caption = QLabel("实时状态", workflow_header)
        runtime_caption.setProperty("productImageStageHint", True)
        self.status_label = QLabel(
            self._status_base,
            workflow_header,
        )
        self.status_label.setObjectName("productImageRuntimeStatus")
        self.status_label.setWordWrap(True)
        self.status_label.setMinimumWidth(260)
        runtime_status.addWidget(runtime_caption)
        runtime_status.addWidget(self.status_label)
        workflow_header_layout.addLayout(runtime_status, 1)
        layout.addWidget(workflow_header)

        workflow_controls = QHBoxLayout()
        workflow_controls.setSpacing(6)

        read_stage = QFrame(self)
        read_stage.setObjectName("productImageReadStage")
        read_stage.setProperty("productImageStage", True)
        read_stage_layout = QVBoxLayout(read_stage)
        read_stage_layout.setContentsMargins(10, 7, 10, 7)
        read_stage_layout.setSpacing(5)
        read_heading = QHBoxLayout()
        read_number = QLabel("01", read_stage)
        read_number.setProperty("productImageStageNumber", True)
        read_title = QLabel("读取产品", read_stage)
        read_title.setProperty("productImageStageTitle", True)
        read_hint = QLabel("每行一个产品 ID，也可用逗号或空格分隔", read_stage)
        read_hint.setProperty("productImageStageHint", True)
        read_heading.addWidget(read_number)
        read_heading.addWidget(read_title)
        read_heading.addWidget(read_hint)
        read_heading.addStretch(1)
        read_stage_layout.addLayout(read_heading)

        self.product_ids_edit = QPlainTextEdit(read_stage)
        self.product_ids_edit.setObjectName("productImageProductIds")
        self.product_ids_edit.setPlaceholderText(
            "输入多个产品 ID，用逗号、空格或换行分隔"
        )
        self._fit_product_ids_to_rows()
        read_actions = QHBoxLayout()
        self.load_btn = QPushButton("读取产品图片", read_stage)
        self.load_btn.setObjectName("productImagePrimaryAction")
        self.load_btn.setProperty("productImageActionRole", "read")
        self.load_btn.clicked.connect(self._load_from_input)
        self.reread_btn = QPushButton("重新读取当前产品", read_stage)
        self.reread_btn.clicked.connect(self.reread_current_product)
        read_actions.addWidget(self.load_btn)
        read_actions.addWidget(self.reread_btn)
        read_actions.addStretch(1)
        read_stage_layout.addWidget(self.product_ids_edit)
        read_stage_layout.addLayout(read_actions)
        workflow_controls.addWidget(read_stage, 2)

        delivery_stage = QFrame(self)
        delivery_stage.setObjectName("productImageDeliveryStage")
        delivery_stage.setProperty("productImageStage", True)
        delivery_stage_layout = QVBoxLayout(delivery_stage)
        delivery_stage_layout.setContentsMargins(10, 7, 10, 7)
        delivery_stage_layout.setSpacing(5)
        delivery_heading = QHBoxLayout()
        delivery_number = QLabel("03", delivery_stage)
        delivery_number.setProperty("productImageStageNumber", True)
        delivery_title = QLabel("保存与验证", delivery_stage)
        delivery_title.setProperty("productImageStageTitle", True)
        delivery_heading.addWidget(delivery_number)
        delivery_heading.addWidget(delivery_title)
        delivery_heading.addStretch(1)
        delivery_stage_layout.addLayout(delivery_heading)
        delivery_hint = QLabel(
            "仅提交已修改产品；保存后自动逐站点回读图片成员与顺序",
            delivery_stage,
        )
        delivery_hint.setProperty("productImageStageHint", True)
        delivery_hint.setWordWrap(True)
        delivery_stage_layout.addWidget(delivery_hint)
        delivery_actions = QHBoxLayout()
        self.submit_current_btn = QPushButton("提交当前产品", delivery_stage)
        self.submit_all_btn = QPushButton("提交全部已修改产品", delivery_stage)
        self.submit_current_btn.setProperty(
            "productImageActionRole", "commit"
        )
        self.submit_all_btn.setProperty(
            "productImageActionRole", "commit"
        )
        self.submit_current_btn.clicked.connect(self._confirm_submit_current)
        self.submit_all_btn.clicked.connect(self._confirm_submit_all)
        self.submit_current_btn.setEnabled(False)
        self.submit_all_btn.setEnabled(False)
        delivery_actions.addWidget(self.submit_current_btn)
        delivery_actions.addWidget(self.submit_all_btn)
        delivery_stage_layout.addLayout(delivery_actions)
        delivery_stage_layout.addStretch(1)
        workflow_controls.addWidget(delivery_stage, 1)
        layout.addLayout(workflow_controls)

        results_stage = QFrame(self)
        results_stage.setObjectName("productImageResultsStage")
        results_stage.setProperty("productImageStage", True)
        results_stage_layout = QVBoxLayout(results_stage)
        results_stage_layout.setContentsMargins(7, 6, 7, 7)
        results_stage_layout.setSpacing(5)
        results_heading = QHBoxLayout()
        results_number = QLabel("02", results_stage)
        results_number.setProperty("productImageStageNumber", True)
        results_title = QLabel("上传与站点编排", results_stage)
        results_title.setProperty("productImageStageTitle", True)
        results_hint = QLabel(
            "线上基线只读；候选区上传成功后拖入待提交区，选择与修改规则保持不变",
            results_stage,
        )
        results_hint.setProperty("productImageStageHint", True)
        results_heading.addWidget(results_number)
        results_heading.addWidget(results_title)
        results_heading.addWidget(results_hint)
        results_heading.addStretch(1)
        results_stage_layout.addLayout(results_heading)
        self.tabs = QTabWidget(results_stage)
        self.tabs.setObjectName("productImageProductTabs")
        self.tabs.setDocumentMode(True)
        self.tabs.currentChanged.connect(
            lambda _index: self._refresh_submit_buttons()
        )
        results_stage_layout.addWidget(self.tabs, 1)
        layout.addWidget(results_stage, 1)

        self._event_timer = QTimer(self)
        self._event_timer.setInterval(20)
        self._event_timer.timeout.connect(self._drain_events)
        self._event_timer.start()
        self._apply_workspace_theme()

    def set_request_stats_text(self, text: str) -> None:
        self._request_stats_text = str(text or "").strip()
        self._render_status()

    def _fit_product_ids_to_rows(self, rows: int = 3) -> None:
        metrics = self.product_ids_edit.fontMetrics()
        margins = self.product_ids_edit.contentsMargins()
        height = (
            metrics.lineSpacing() * max(1, int(rows))
            + margins.top()
            + margins.bottom()
            + self.product_ids_edit.frameWidth() * 2
            + round(self.product_ids_edit.document().documentMargin() * 2)
        )
        self.product_ids_edit.setFixedHeight(height)

    def _set_status(self, text: str) -> None:
        self._status_base = str(text or "就绪")
        self._render_status()

    def _render_status(self) -> None:
        suffix = (
            f" | {self._request_stats_text}"
            if self._request_stats_text
            else ""
        )
        self.status_label.setText(f"{self._status_base}{suffix}")

    def open_operation_guide(self) -> ProductImageOperationGuideDialog:
        if self._guide_dialog is not None and self._guide_dialog.isVisible():
            self._guide_dialog.raise_()
            self._guide_dialog.activateWindow()
            return self._guide_dialog
        dialog = ProductImageOperationGuideDialog(self)
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self._guide_dialog = dialog
        dialog.destroyed.connect(
            lambda: setattr(self, "_guide_dialog", None)
        )
        dialog.show()
        return dialog

    def _apply_workspace_theme(self) -> None:
        if self._theme_refreshing:
            return
        self._theme_refreshing = True
        try:
            colors = semantic_colors(self.palette())
            disabled_background = colors["header"]
            self.setStyleSheet(
                f"""
                #productImageWorkflowHeader {{
                    background-color: {colors['header']};
                    border: 1px solid {colors['strong_border']};
                    border-radius: 10px;
                }}
                QFrame[productImageStage="true"],
                QFrame[productImageEditorColumn="true"] {{
                    background-color: {colors['card']};
                    border: 1px solid {colors['strong_border']};
                    border-radius: 10px;
                }}
                QFrame[columnRole="planned"] {{
                    border: 2px solid {colors['accent']};
                }}
                QFrame[toolbarRole="candidate"] {{
                    background-color: {colors['subcard']};
                    border: 0;
                    border-radius: 8px;
                }}
                QFrame[productImageSitePanel="true"] {{
                    background-color: {colors['subcard']};
                    border: 1px solid {colors['border']};
                    border-radius: 9px;
                }}
                QFrame[sitePlanState="changed"] {{
                    border: 2px solid {colors['link']};
                }}
                QLabel[productImageWorkflowTitle="true"] {{
                    color: {colors['text']};
                    font-size: 18px;
                    font-weight: 700;
                }}
                QLabel[productImageWorkflowSubtitle="true"],
                QLabel[productImageStageHint="true"] {{
                    color: {colors['muted']};
                    font-size: 11px;
                }}
                QLabel[productImageWorkflowSteps="true"],
                QLabel[productImageStageTitle="true"],
                QLabel[productImageColumnTitle="true"] {{
                    color: {colors['text']};
                    font-size: 13px;
                    font-weight: 700;
                }}
                QLabel[productImageColumnTitle="true"] {{
                    padding: 3px 2px;
                    font-size: 14px;
                }}
                QLabel[productImageSiteTitle="true"] {{
                    color: {colors['text']};
                    font-weight: 700;
                }}
                QLabel[productImageStageNumber="true"] {{
                    color: {colors['accent']};
                    font-size: 11px;
                    font-weight: 700;
                }}
                #productImageRuntimeStatus, #productImageProductSummary {{
                    color: {colors['link']};
                    font-weight: 600;
                }}
                #productImageProductIds, QListWidget {{
                    background-color: {colors['subcard']};
                    color: {colors['text']};
                    border: 1px solid {colors['border']};
                    border-radius: 8px;
                }}
                QListWidget[workspaceCardRole="candidate"] {{
                    background-color: {colors['card']};
                    border: 1px dashed {colors['accent']};
                }}
                QListWidget::item {{
                    background: transparent;
                    border: 0;
                }}
                QScrollArea {{
                    background-color: transparent;
                    border: 0;
                }}
                QSplitter::handle {{
                    background-color: {colors['border']};
                    border-radius: 2px;
                }}
                QSplitter::handle:horizontal {{
                    width: 5px;
                    margin: 14px 1px;
                }}
                QTabWidget#productImageProductTabs::pane {{
                    border: 1px solid {colors['border']};
                    border-radius: 8px;
                    background-color: {colors['base']};
                }}
                QTabWidget#productImageProductTabs QTabBar::tab {{
                    background-color: {colors['header']};
                    color: {colors['muted']};
                    border: 1px solid {colors['border']};
                    border-bottom: 0;
                    border-top-left-radius: 7px;
                    border-top-right-radius: 7px;
                    padding: 7px 12px;
                    margin-right: 3px;
                }}
                QTabWidget#productImageProductTabs QTabBar::tab:selected {{
                    background-color: {colors['base']};
                    color: {colors['text']};
                    font-weight: 700;
                }}
                QPushButton {{
                    background-color: {colors['header']};
                    color: {colors['text']};
                    border: 1px solid {colors['border']};
                    border-radius: 7px;
                    padding: 5px 9px;
                }}
                QPushButton:hover {{
                    border-color: {colors['accent']};
                    background-color: {colors['subcard']};
                }}
                QPushButton:focus {{
                    border: 2px solid {colors['accent']};
                }}
                QPushButton:disabled {{
                    color: {colors['muted']};
                }}
                #productImagePrimaryAction {{
                    background-color: {colors['accent']};
                    color: {colors['accent_text']};
                    font-weight: 600;
                }}
                QPushButton[productImageActionRole="guide"] {{
                    background-color: transparent;
                    color: {colors['link']};
                    border: 1px solid {colors['accent']};
                    font-weight: 600;
                }}
                QPushButton[productImageActionRole="choose"] {{
                    background-color: {colors['accent']};
                    color: {colors['accent_text']};
                    border-color: {colors['accent']};
                    font-weight: 600;
                }}
                QPushButton[productImageActionRole="choose"]:hover {{
                    background-color: {colors['selection']};
                    border-color: {colors['selection']};
                }}
                QPushButton[productImageActionRole="upload"] {{
                    background-color: {colors['accent']};
                    color: {colors['accent_text']};
                    border-color: {colors['accent']};
                    font-weight: 600;
                }}
                QPushButton[productImageActionRole="upload"]:hover {{
                    background-color: {colors['selection']};
                    border-color: {colors['selection']};
                }}
                QPushButton[productImageActionRole="commit"] {{
                    background-color: {colors['link']};
                    color: {colors['base']};
                    border-color: {colors['link']};
                    font-weight: 600;
                }}
                QPushButton[productImageActionRole="commit"]:hover {{
                    border-color: {colors['text']};
                }}
                QPushButton[productImageToolButton="true"] {{
                    padding: 3px 7px;
                    color: {colors['link']};
                    background-color: transparent;
                }}
                QPushButton[productImageActionRole="choose"]:disabled,
                QPushButton[productImageActionRole="upload"]:disabled,
                QPushButton[productImageActionRole="commit"]:disabled {{
                    background-color: {disabled_background};
                    color: {colors['muted']};
                    border-color: {colors['border']};
                }}
                """
            )
        finally:
            self._theme_refreshing = False

    def changeEvent(self, event: QEvent) -> None:
        super().changeEvent(event)
        if event.type() in {
            QEvent.Type.FontChange,
            QEvent.Type.PaletteChange,
            QEvent.Type.StyleChange,
        }:
            if hasattr(self, "product_ids_edit"):
                self._fit_product_ids_to_rows()
            self._apply_workspace_theme()

    def _load_from_input(self) -> None:
        text = self.product_ids_edit.toPlainText()
        product_ids = text.replace(",", " ").replace("\n", " ").split()
        self.load_products(product_ids)

    def load_products(self, product_ids: list[str]) -> None:
        if not self._closed:
            self._stop_event.clear()
        seen = set(self.product_order)
        for raw_id in product_ids:
            product_id = str(raw_id).strip()
            if not product_id or product_id in seen:
                continue
            seen.add(product_id)
            self.product_order.append(product_id)
            placeholder = QLabel(
                f"正在读取产品 {product_id} 的当前图片配置…",
                self.tabs,
            )
            placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
            index = self.tabs.addTab(placeholder, f"{product_id} · 读取中")
            self.tabs.tabBar().setTabData(index, product_id)
            self._start_load(product_id)
        if product_ids:
            self._set_status(
                f"正在读取 {len(self.product_order)} 个产品"
            )

    def _start_load(self, product_id: str) -> None:
        def run() -> None:
            try:
                result = self.backend.load_product(
                    product_id,
                    self._stop_event,
                )
                self._event_queue.put(("loaded", product_id, result))
            except Exception as exc:
                self._event_queue.put(("load_failed", product_id, str(exc)))

        threading.Thread(target=run, daemon=True).start()

    def _drain_events(self) -> None:
        if self._closed:
            return
        while True:
            try:
                kind, product_id, value = self._event_queue.get_nowait()
            except queue.Empty:
                break
            if kind == "loaded" and isinstance(value, LoadedProductImages):
                self._install_loaded_product(product_id, value)
            elif kind == "load_failed":
                self.request_failed.emit("image", 1)
                self._install_failed_product(product_id, str(value))
            elif kind.startswith("upload_"):
                if kind == "upload_failed":
                    self.request_failed.emit("image", 1)
                pane = self.product_panes.get(product_id)
                if pane is not None:
                    pane.refresh()
                    self._on_product_state_changed(product_id)
                if kind == "upload_batch_done":
                    self.upload_coordinators.pop(product_id, None)
                    self.upload_threads.pop(product_id, None)
                    self._set_status(
                        f"产品 {product_id} 图片上传完成：{value}"
                    )
            elif kind == "save_verified":
                self.save_results[product_id] = "verified"
                self._install_save_verified(product_id)
                pane = self.product_panes.get(product_id)
                if pane is not None:
                    pane.set_editing_enabled(True)
            elif kind == "save_verify_failed":
                self.save_results[product_id] = "verify_failed"
                pane = self.product_panes.get(product_id)
                if pane is not None:
                    pane.set_editing_enabled(True)
                errors = getattr(value, "site_errors", {})
                details = "；".join(
                    f"{site}：{message}"
                    for site, message in errors.items()
                )
                self.save_messages[product_id] = details
                self._set_status(
                    f"产品 {product_id} 保存后校验失败：{details}"
                )
            elif kind == "save_failed":
                self.request_failed.emit("image", 1)
                self.save_results[product_id] = "failed"
                self.save_messages[product_id] = str(value)
                pane = self.product_panes.get(product_id)
                if pane is not None:
                    pane.set_editing_enabled(True)
                self._set_status(
                    f"产品 {product_id} 提交失败：{value}"
                )
            elif kind == "save_batch_done":
                self.save_thread = None
                self.write_finished.emit("product_images")
                self._refresh_submit_buttons()
                counts = {
                    status: list(self.save_results.values()).count(status)
                    for status in ("verified", "verify_failed", "failed")
                }
                self._set_status(
                    "批量提交结束："
                    f"成功 {counts['verified']}，"
                    f"验证失败 {counts['verify_failed']}，"
                    f"提交失败 {counts['failed']}"
                    + (
                        "\n"
                        + "；".join(
                            f"产品 {pid}：{message}"
                            for pid, message in self.save_messages.items()
                        )
                        if self.save_messages
                        else ""
                    )
                )

    def _replace_product_tab(
        self,
        product_id: str,
        widget: QWidget,
        title: str,
    ) -> None:
        index = self.tab_index(product_id)
        current = self.tabs.currentIndex()
        if index >= 0:
            old_widget = self.tabs.widget(index)
            self.tabs.removeTab(index)
            old_widget.deleteLater()
            self.tabs.insertTab(index, widget, title)
        else:
            index = self.tabs.addTab(widget, title)
        self.tabs.tabBar().setTabData(index, product_id)
        if current == index or self.tabs.count() == 1:
            self.tabs.setCurrentIndex(index)

    def _install_loaded_product(
        self,
        product_id: str,
        loaded: LoadedProductImages,
    ) -> None:
        if product_id not in self.product_order:
            return
        state = make_product_editor_state(
            product_id,
            loaded.product_info,
            loaded.site_rows,
            currency_context=loaded.currency_context,
        )
        pane = ProductImageEditorPane(
            state,
            upload_candidates=lambda keys, pid=product_id: self.start_upload(
                pid, keys
            ),
            retry_failed=lambda pid=product_id: self.retry_failed_uploads(pid),
            cancel_uploads=lambda pid=product_id: self.cancel_uploads(pid),
            parent=self.tabs,
        )
        pane.state_changed.connect(self._on_product_state_changed)
        self.product_states[product_id] = state
        self.product_panes[product_id] = pane
        self.failed_products.pop(product_id, None)
        self._replace_product_tab(
            product_id,
            pane,
            f"{product_id} · 未修改",
        )
        self._set_status(
            f"已读取 {len(self.product_panes)} / {len(self.product_order)} 个产品"
        )

    def start_upload(self, product_id: str, candidate_keys: list[str]) -> bool:
        state = self.product_states.get(product_id)
        if (
            state is None
            or self.backend.upload_image is None
            or product_id in self.upload_threads
        ):
            return False
        coordinator = ProductUploadCoordinator(
            product_id,
            state,
            self.backend.upload_image,
            event_sink=lambda kind, pid, value: self._event_queue.put(
                (kind, pid, value)
            ),
        )
        thread = threading.Thread(
            target=lambda: coordinator.run(candidate_keys),
            daemon=True,
        )
        self.upload_coordinators[product_id] = coordinator
        self.upload_threads[product_id] = thread
        self._set_status(f"产品 {product_id} 正在上传图片…")
        thread.start()
        return True

    def retry_failed_uploads(self, product_id: str) -> bool:
        state = self.product_states.get(product_id)
        if state is None:
            return False
        keys = [
            key
            for key, candidate in state.candidates.items()
            if candidate.status == "failed"
        ]
        return bool(keys) and self.start_upload(product_id, keys)

    def cancel_uploads(self, product_id: str) -> bool:
        coordinator = self.upload_coordinators.get(product_id)
        if coordinator is None:
            return False
        coordinator.cancel()
        return True

    def _current_product_id(self) -> str:
        index = self.tabs.currentIndex()
        if index < 0:
            return ""
        return str(self.tabs.tabBar().tabData(index) or "")

    def _confirm_submit_current(self) -> None:
        product_id = self._current_product_id()
        if not product_id:
            return
        answer = QMessageBox.question(
            self,
            "确认提交图片配置",
            product_image_change_summary(self.product_states[product_id])
            + "\n\n保存后将自动回读校验，是否继续？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if answer == QMessageBox.StandardButton.Yes:
            self.start_save_products([product_id])

    def _confirm_submit_all(self) -> None:
        product_ids = [
            product_id
            for product_id in self.product_order
            if self.product_states.get(product_id)
            and self.product_states[product_id].dirty
        ]
        if not product_ids:
            return
        answer = QMessageBox.question(
            self,
            "确认批量提交图片配置",
            "以下产品将按顺序提交并逐一回读校验：\n\n"
            + "\n\n".join(
                product_image_change_summary(self.product_states[product_id])
                for product_id in product_ids
            )
            + "\n\n是否继续？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if answer == QMessageBox.StandardButton.Yes:
            self.start_save_products(product_ids)

    def start_save_products(self, product_ids: list[str]) -> bool:
        if (
            self._closed
            or self.backend.save_and_verify is None
            or (self.save_thread is not None and self.save_thread.is_alive())
        ):
            return False
        targets = [
            product_id
            for product_id in dict.fromkeys(product_ids)
            if self.product_states.get(product_id)
            and self.product_states[product_id].dirty
        ]
        if not targets:
            return False
        self._stop_event.clear()
        active_upload_products = [
            product_id
            for product_id in targets
            if product_id in self.upload_threads
            or any(
                candidate.status in {"queued", "uploading"}
                for candidate in self.product_states[product_id].candidates.values()
            )
        ]
        if active_upload_products:
            self._set_status(
                "以下产品仍有图片正在上传，暂不能提交："
                + "、".join(active_upload_products)
            )
            return False

        def run() -> None:
            for product_id in targets:
                if self._stop_event.is_set():
                    break
                state = self.product_states.get(product_id)
                if state is None:
                    continue
                self._event_queue.put(("save_started", product_id, None))
                try:
                    result = self.backend.save_and_verify(
                        state,
                        self._stop_event,
                    )
                except Exception as exc:
                    self._event_queue.put(
                        ("save_failed", product_id, str(exc))
                    )
                    continue
                kind = "save_verified" if getattr(result, "ok", False) else "save_verify_failed"
                self._event_queue.put((kind, product_id, result))
            self._event_queue.put(("save_batch_done", "", None))

        self.submit_current_btn.setEnabled(False)
        self.submit_all_btn.setEnabled(False)
        self._set_status(
            f"正在提交 {len(targets)} 个产品的图片配置…"
        )
        self.save_results = {}
        self.save_messages = {}
        for product_id in targets:
            self.product_panes[product_id].set_editing_enabled(False)
        self.save_thread = threading.Thread(target=run, daemon=True)
        self.write_started.emit("product_images")
        self.save_thread.start()
        return True

    def _install_save_verified(self, product_id: str) -> None:
        state = self.product_states.get(product_id)
        pane = self.product_panes.get(product_id)
        if state is None or pane is None:
            return
        for site in state.sites.values():
            site.baseline = list(site.planned)
        pane.history.clear()
        pane.refresh()
        index = self.tab_index(product_id)
        if index >= 0:
            self.tabs.setTabText(index, f"{product_id} · 已验证")
        self._set_status(
            f"产品 {product_id} 图片配置已保存并回读验证"
        )

    def _refresh_submit_buttons(self) -> None:
        current = self.product_states.get(self._current_product_id())
        self.submit_current_btn.setEnabled(
            bool(current and current.dirty and self.save_thread is None)
        )
        self.submit_all_btn.setEnabled(
            self.save_thread is None
            and any(state.dirty for state in self.product_states.values())
        )

    def _install_failed_product(
        self,
        product_id: str,
        message: str,
    ) -> None:
        if product_id not in self.product_order:
            return
        self.failed_products[product_id] = message
        panel = QWidget(self.tabs)
        layout = QVBoxLayout(panel)
        label = QLabel(f"读取失败：{message}", panel)
        label.setWordWrap(True)
        retry_btn = QPushButton("重试", panel)
        retry_btn.clicked.connect(
            lambda _checked=False, pid=product_id: self.retry_product(pid)
        )
        layout.addStretch(1)
        layout.addWidget(label)
        layout.addWidget(retry_btn)
        layout.addStretch(1)
        self._replace_product_tab(
            product_id,
            panel,
            f"{product_id} · 读取失败",
        )
        self._set_status(f"产品 {product_id} 读取失败")

    def retry_product(self, product_id: str) -> None:
        if product_id not in self.product_order:
            return
        self.failed_products.pop(product_id, None)
        placeholder = QLabel(
            f"正在重新读取产品 {product_id}…",
            self.tabs,
        )
        placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._replace_product_tab(
            product_id,
            placeholder,
            f"{product_id} · 重试中",
        )
        self._start_load(product_id)

    def reread_current_product(self) -> bool:
        return self.reread_product(self._current_product_id())

    def reread_product(
        self,
        product_id: str,
        answer: QMessageBox.StandardButton | None = None,
    ) -> bool:
        state = self.product_states.get(product_id)
        if not product_id or state is None:
            return False
        if state.dirty or state.candidates:
            if answer is None:
                answer = QMessageBox.question(
                    self,
                    "重新读取将放弃本地编排",
                    f"产品 {product_id} 存在未提交图片配置。\n"
                    "重新读取会放弃这些修改，是否继续？",
                    QMessageBox.StandardButton.Discard
                    | QMessageBox.StandardButton.Cancel,
                    QMessageBox.StandardButton.Cancel,
                )
            if answer != QMessageBox.StandardButton.Discard:
                return False
        placeholder = QLabel(
            f"正在重新读取产品 {product_id}…",
            self.tabs,
        )
        placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._replace_product_tab(
            product_id,
            placeholder,
            f"{product_id} · 重新读取中",
        )
        self._start_load(product_id)
        return True

    def tab_index(self, product_id: str) -> int:
        for index in range(self.tabs.count()):
            if str(self.tabs.tabBar().tabData(index) or "") == str(product_id):
                return index
        return -1

    def _on_product_state_changed(self, product_id: str) -> None:
        state = self.product_states.get(product_id)
        index = self.tab_index(product_id)
        if state is None or index < 0:
            return
        candidate_statuses = {
            candidate.status for candidate in state.candidates.values()
        }
        if candidate_statuses & {"queued", "uploading"}:
            status = "上传中"
        elif "failed" in candidate_statuses:
            status = "上传失败"
        elif candidate_statuses & {"local", "warning"}:
            status = "有待上传图片"
        elif state.dirty:
            status = "可提交"
        elif "uploaded" in candidate_statuses:
            status = "待编排"
        else:
            status = "未修改"
        self.tabs.setTabText(index, f"{product_id} · {status}")
        self._refresh_submit_buttons()

    def confirm_discard_dirty_products(
        self,
        product_ids: list[str],
        answer: QMessageBox.StandardButton | None = None,
    ) -> bool:
        if not product_ids:
            return True
        if answer is None:
            answer = QMessageBox.question(
                self,
                "存在未提交图片配置",
                "以下产品存在未提交修改：\n"
                + "、".join(product_ids)
                + "\n\n关闭后候选图片和本地编排将丢失，是否放弃？",
                QMessageBox.StandardButton.Discard
                | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel,
            )
        return answer == QMessageBox.StandardButton.Discard

    def unsaved_product_ids(self) -> list[str]:
        return [
            product_id
            for product_id in self.product_order
            if self.product_states.get(product_id)
            and (
                self.product_states[product_id].dirty
                or bool(self.product_states[product_id].candidates)
            )
        ]

    def has_unsaved_changes(self) -> bool:
        return bool(self.unsaved_product_ids())

    def is_running(self) -> bool:
        return bool(
            (self.save_thread is not None and self.save_thread.is_alive())
            or self.upload_threads
        )

    def stop(self) -> None:
        self._stop_event.set()
        for coordinator in self.upload_coordinators.values():
            coordinator.cancel()

    def dirty_product_ids(self) -> tuple[str, ...]:
        return tuple(self.unsaved_product_ids())

    def request_close(self, parent: QWidget | None = None) -> bool:
        unsaved_ids = self.unsaved_product_ids()
        if unsaved_ids and not self.confirm_discard_dirty_products(unsaved_ids):
            return False
        self.shutdown()
        return True

    def shutdown(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._stop_event.set()
        for coordinator in self.upload_coordinators.values():
            coordinator.cancel()
        if self._guide_dialog is not None:
            self._guide_dialog.close()
        self._event_timer.stop()

    def closeEvent(self, event) -> None:
        if self._closed:
            event.accept()
            return
        if self.request_close(self.parentWidget()):
            event.accept()
        else:
            event.ignore()

    def focus_product_input(self) -> None:
        self.product_ids_edit.setFocus(Qt.FocusReason.OtherFocusReason)

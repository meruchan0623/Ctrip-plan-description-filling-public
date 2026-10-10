# -*- coding: utf-8 -*-
"""Ctrip package introduction batch updater.

The GUI uses Python requests with the plaintext Ctrip login state refreshed
from a local Edge/Chrome browser. It edits draft package introductions through
Ctrip's draft APIs instead of driving textarea input.
"""

from __future__ import annotations

import copy
import csv
import datetime as dt
import difflib
import concurrent.futures
import argparse
import base64
import contextlib
import hashlib
import io
import json
import os
import platform
import queue
import re
import shutil
import socket
import ssl
import struct
import subprocess
import sys
import threading
import time
import traceback
import unicodedata
import urllib.parse
import urllib.request
import uuid
from collections import Counter
from dataclasses import asdict, dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Callable

try:
    from PyQt6.QtCore import QAbstractTableModel, QEvent, QModelIndex, Qt, QTimer
    from PyQt6.QtGui import QColor, QGuiApplication, QPixmap
    from PyQt6.QtWidgets import (
        QApplication,
        QAbstractItemView,
        QButtonGroup,
        QCheckBox,
        QComboBox,
        QDialog,
        QDialogButtonBox,
        QFileDialog,
        QFrame,
        QGridLayout,
        QHeaderView,
        QHBoxLayout,
        QLabel,
        QLineEdit,
        QMainWindow,
        QMessageBox,
        QPlainTextEdit,
        QPushButton,
        QRadioButton,
        QScrollArea,
        QSizePolicy,
        QSplitter,
        QTabWidget,
        QTableView,
        QTableWidget,
        QTableWidgetItem,
        QTextEdit,
        QVBoxLayout,
        QWidget,
    )
    QT_IMPORT_ERROR: Exception | None = None
except Exception as exc:  # pragma: no cover - surfaced by main()
    QT_IMPORT_ERROR = exc
    QAbstractTableModel = QEvent = QModelIndex = Qt = QTimer = QColor = QGuiApplication = QPixmap = QApplication = QAbstractItemView = QButtonGroup = QCheckBox = QComboBox = QDialog = QDialogButtonBox = QFileDialog = object
    QFrame = QGridLayout = QHeaderView = QHBoxLayout = QLabel = QLineEdit = QMainWindow = QMessageBox = object
    QPlainTextEdit = QPushButton = QRadioButton = QScrollArea = QSizePolicy = QSplitter = QTabWidget = QTableView = QTableWidget = QTableWidgetItem = QTextEdit = object
    QVBoxLayout = QWidget = object

if QT_IMPORT_ERROR is None:
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            from qfluentwidgets import BodyLabel, CheckBox, LineEdit, PlainTextEdit, PushButton, PrimaryPushButton, TableWidget, TextEdit
        QFLUENT_AVAILABLE = True
    except Exception:  # pragma: no cover - surfaced in GUI startup
        BodyLabel = QLabel
        CheckBox = QCheckBox
        LineEdit = QLineEdit
        PlainTextEdit = QPlainTextEdit
        PushButton = QPushButton
        PrimaryPushButton = QPushButton
        TableWidget = QTableWidget
        TextEdit = QTextEdit
        QFLUENT_AVAILABLE = False
else:
    BodyLabel = CheckBox = LineEdit = PlainTextEdit = PushButton = PrimaryPushButton = TableWidget = TextEdit = object
    QFLUENT_AVAILABLE = False

import requests

from ctrip_image_upload import upload_image as ctrip_upload_image, UploadResult as CtripUploadResult
from product_image_workspace_state import WorkspaceImage, workspace_image_key
from workflow_common import InMemoryApplicationWriteGate, WriteGateRequest

try:
    import openpyxl
except Exception:  # pragma: no cover - surfaced in GUI startup
    openpyxl = None

import translation_rules
if QT_IMPORT_ERROR is None:
    import ui_theme
    from docking_config import DockingConfigWidget
    from product_edit import ProductEditWidget
    from product_edit.catalog import FullFieldReadResult
else:  # keep the dependency-error startup path importable without PyQt6
    ui_theme = None
    DockingConfigWidget = object
    ProductEditWidget = object
    FullFieldReadResult = object


BROWSER_CDP_BASE = "http://localhost:9222"
BROWSER_CDP_TARGETS_URL = f"{BROWSER_CDP_BASE}/json/list"
EDGE_REMOTE_DEBUGGING_URL = "edge://inspect/#remote-debugging"
CHROME_REMOTE_DEBUGGING_URL = "chrome://inspect/#remote-debugging"
PRODUCT_URL = "https://vbooking.ctrip.com/activity-vbk/product-edit?productId={product_id}&source=PriceStock"
GET_PRODUCT_DRAFT_URL = "https://m.ctrip.com/restapi/soa2/16359/json/getProductDraft"
SAVE_PRODUCT_DRAFT_URL = "https://m.ctrip.com/restapi/soa2/16359/json/saveOrEffectProductDraft"
GET_RESOURCE_PRICE_AND_STOCK_URL = "https://m.ctrip.com/restapi/soa2/16359/json/getResourcePriceAndStock"
TRANSLATION_AVAILABLE_LOCALES_URL = "https://m.ctrip.com/restapi/soa2/16359/productTranslationAvailableLocales"
TRANSLATION_LIST_URL = "https://m.ctrip.com/restapi/soa2/16359/productTranslationList"
TRANSLATION_PUSH_URL = "https://m.ctrip.com/restapi/soa2/16359/productTranslationPush"
TRANSLATION_AI_REFERENCE_URL = "https://m.ctrip.com/restapi/soa2/16359/queryAiTranslationReference"
CTRIP_LOGIN_COOKIE_NAMES = frozenset({"vbkticket"})


def default_app_settings_file() -> Path:
    current_os = platform.system()
    if current_os == "Windows":
        config_dir = Path(os.environ.get("APPDATA", str(Path.home() / "AppData" / "Roaming"))) / "CtripPlanDescriptionFilling"
    elif current_os == "Darwin":
        config_dir = Path.home() / "Library" / "Preferences" / "CtripPlanDescriptionFilling"
    else:
        config_dir = Path.home() / ".config" / "CtripPlanDescriptionFilling"
    return config_dir / "app_settings.json"


def app_resource_path(*parts: str) -> Path:
    """Locate bundled read-only resources both from source and from a PyInstaller build."""
    base = Path(getattr(sys, "_MEIPASS", "") or Path(__file__).resolve().parent)
    return base.joinpath(*parts)


def translation_ops_manual_path() -> Path:
    return app_resource_path("docs", "translation_ops_manual.md")


def open_with_system_default(path: str) -> None:
    if platform.system() == "Windows":
        os.startfile(path)  # type: ignore[attr-defined]
    elif platform.system() == "Darwin":
        subprocess.Popen(["open", path])
    else:
        subprocess.Popen(["xdg-open", path])


def default_app_auth_dir() -> Path:
    return default_app_settings_file().parent / "auth"


def default_browser_cdp_user_data_dir(browser_key: str = "edge") -> Path:
    base = default_app_settings_file().parent
    if browser_key == "chrome":
        return base / "browser-cdp-profile-chrome"
    return base / "browser-cdp-profile"


def default_downloads_dir(create: bool = False) -> Path:
    downloads = Path.home() / "Downloads"
    if create:
        downloads.mkdir(parents=True, exist_ok=True)
        return downloads
    return downloads if downloads.exists() else Path.home()


def default_download_path(filename: str, create_dir: bool = False) -> str:
    return str(default_downloads_dir(create=create_dir) / filename)


def file_dialog_options_for_excel() -> Any:
    if QT_IMPORT_ERROR is not None:
        return None
    options = QFileDialog.Option(0)
    if platform.system() == "Darwin":
        options |= QFileDialog.Option.DontUseNativeDialog
    return options


def get_open_excel_file_name(parent: Any, title: str) -> tuple[str, str]:
    return QFileDialog.getOpenFileName(
        parent,
        title,
        str(default_downloads_dir()),
        "Excel 工作簿 (*.xlsx);;Excel 宏工作簿 (*.xlsm);;所有文件 (*)",
        options=file_dialog_options_for_excel(),
    )


def get_save_report_file_name(parent: Any, title: str, default: str, filters: str) -> tuple[str, str]:
    return QFileDialog.getSaveFileName(
        parent,
        title,
        default,
        filters,
        options=file_dialog_options_for_excel(),
    )


def translation_report_default_filename(task_template_path: str, stamp_provider: Callable[[], str] | None = None) -> str:
    stem = Path(task_template_path).stem if str(task_template_path or "").strip() else ""
    stamp_provider = stamp_provider or now_stamp
    return f"{stem}_result.xlsx" if stem else f"ctrip_translation_report_{stamp_provider()}.xlsx"


PLAIN_AUTH_DIR = default_app_auth_dir()
PLAIN_COOKIE_FILE = PLAIN_AUTH_DIR / "ctrip_cookie_header.txt"
PLAIN_AUTH_JSON = PLAIN_AUTH_DIR / "ctrip_auth_plain.json"
REQUIRED_COLUMNS = ("productId",)
TEMPLATE_COLUMNS = (
    "productId",
    "packageId",
    "packageName",
    "usedup_throttle",
    "reset_time_calc",
    "inst_adv",
    "target_cost_price",
    "target_vendor_package_id",
    "target_connection_code",
    "submit_audit",
    "remark",
    "enabled",
)
EDIT_TEMPLATE_SHEET = "修改模板"
INTRO_FILL_SHEET = "套餐说明填充"
INTRO_OPTIONS_SHEET = "套餐说明选项"
PRODUCT_EDIT_WIDE_HEADERS = (
    "productId",
    "productName",
    "packageId",
    "resourceId",
    "packageName",
    "PackageNameMark",
    "old_product_name",
    "target_product_name",
    "old_cost_price",
    "target_cost_price",
    "old_sale_status",
    "target_sale_status",
    "old_vendor_package_id",
    "target_vendor_package_id",
    "old_connection_code",
    "target_connection_code",
    "old_introduction",
    "target_introduction",
)
COST_PRICE_NOT_EDITABLE_MESSAGE = "请联系业务经理开放录入底价"
SALE_STATUS_OPTIONS = ("开", "关")
TRANSLATION_TEMPLATE_SHEET = "翻译回填"
TRANSLATION_OPTIONS_SHEET = "翻译字段说明"
MAX_INTRO_TEXT_LENGTH = 300
CTRIP_REQUEST_INTERVAL_SECONDS = 0.2
MIN_REQUEST_INTERVAL_SECONDS = 0.2
MAX_REQUEST_INTERVAL_SECONDS = 1.0
DEFAULT_PARALLEL_REQUESTS = 2
MAX_PARALLEL_REQUESTS = 5
MAX_PREVIEW_TABLE_ROWS = 2000
MAX_DETAIL_TEXT_CHARS = 20000
MAX_DIFF_TEXT_CHARS = 8000
TRANSLATION_TABLE_HISTORY_LIMIT = 20
QUEUE_POLL_MAX_EVENTS = 80
QUEUE_POLL_MAX_SECONDS = 0.03
RESULT_BATCH_SIZE = 100
TABLE_RENDER_BATCH_SIZE = 160
MAX_LOG_BLOCKS = 3000
ADAPTIVE_INITIAL_PARALLEL = 4
ADAPTIVE_MIN_PARALLEL = 1
ADAPTIVE_QUEUE_PRESSURE_THRESHOLD = 600
ADAPTIVE_AUDIT_PRESSURE_THRESHOLD = 200
ADAPTIVE_SUCCESS_GROWTH_STREAK = 8
WRITE_RUNS_DIR_NAME = "ctrip_product_edit_write_runs"
APP_SETTINGS_VERSION = 1

TRANSLATION_LOCALE_OPTIONS = (
    "en-US",
    "zh-HK",
    "zh-TW",
    "ja-JP",
    "ko-KR",
    "th-TH",
    "vi-VN",
    "id-ID",
    "ms-MY",
    "fr-FR",
    "de-DE",
    "es-ES",
    "ar-XX",
)

PRODUCT_IMAGE_RULE_LABELS = {
    "replace": "覆盖目标语言顶部图",
    "append": "追加到目标语言顶部图",
    "skip_existing": "已有图片时跳过",
}

LEGACY_TRANSLATION_FIELD_LABELS = {
    "productName": "产品名称",
    "productDesc": "产品描述",
    "productIntroduction": "产品介绍",
    "feeInclude": "费用包含",
    "feeExclude": "费用不含",
    "howToUse": "使用方法",
    "attention": "注意事项",
    "postBookingTravelReminder": "预订后旅行提醒",
    "operationAttention": "携程处理注意事项",
    "salesPropertyName": "销售属性名",
    "salesPropertyValueName": "销售属性值",
    "packageDesc": "套餐名称",
    "packageIntroduction": "套餐介绍",
    "resourceName": "套餐规格量词",
    "packageResourceName": "套餐规格量词",
}
LEGACY_TRANSLATION_FIELD_CODES = tuple(LEGACY_TRANSLATION_FIELD_LABELS.keys())

CTRIP_PACKAGE_TEMPLATE_DICT = {
    "combination_template": {
        "daily": "● {usedup_throttle}\n● {reset_time_calc}\n● {Day_calc}\n● {inst_adv}",
        "total": "● {usedup_throttle}\n● {Day_calc}\n● {inst_adv}",
    },
    "day_calc": "天数计算方式：每24小时为一日（例：3天套餐，10月1日10:00安装启用，则套餐于10月4日09:59结束）",
    "reset_time_calc": {
        "+7零点": "流量（套餐）刷新时间：GMT+7 每日00:00刷新",
        "+8零点": "流量（套餐）刷新时间：GMT+8 每日00:00刷新",
        "+9零点": "流量（套餐）刷新时间：GMT+9 每日00:00刷新",
        "激活后每24h": "流量自激活后每 24 小时自动刷新",
    },
    "install_instructions": {
        "可提前安装": "启用说明：可提前安装，进入方案覆盖地区连网即自动启用；若已位于覆盖范围，建议使用时再安装",
        "不可提前安装": "启用说明：为了确保您的使用天数完整，建议于「出发当天」或「抵达当地」再行安装",
    },
    "scripts": {
        "后降速": {
            "daily_generic": "高速流量{data_capacity}/天，用完后降速为128kbps",
            "daily_100gb": "100GB/天，高速流量1GB/天，后以10Mbps的网路速度持续使用",
            "daily_100gb_unlimited": "流量说明：每日100GB，不限速使用",
            "daily_20gb": "20GB/天，高速流量1GB/天，后以10Mbps的网路速度持续使用",
            "total": "高速流量总量{data_capacity}，用完后降速为128kbps",
        },
        "后停用": {
            "daily_generic": "高速流量{data_capacity}/天，用完后服务终止",
            "daily_100gb": "100GB/天，高速流量1GB/天，后以10Mbps的网路速度持续使用",
            "daily_100gb_unlimited": "流量说明：每日100GB，不限速使用",
            "daily_20gb": "20GB/天，高速流量1GB/天，后以10Mbps的网路速度持续使用",
            "total": "高速流量总量{data_capacity}，用完后服务终止",
        },
        "吃到饱_提前安装": {
            "daily_100gb": "100GB/天，高速流量1GB/天，后以10Mbps的网路速度持续使用",
            "daily_100gb_unlimited": "流量说明：每日100GB，不限速使用",
            "daily_20gb": "20GB/天，高速流量1GB/天，后以10Mbps的网路速度持续使用",
        },
        "总量停用每日降速": {
            "daily_generic": "高速流量{data_capacity}/天，用完后降速为128kbps",
            "daily_20gb": "20GB/天，高速流量1GB/天，后以10Mbps的网路速度持续使用",
            "total": "高速流量总量{data_capacity}，用完后服务终止",
        },
    },
}

USEDUP_THROTTLE_OPTIONS = ("后降速", "后停用", "吃到饱", "总量停用每日降速")
RESET_TIME_CALC_OPTIONS = ("+7零点", "+8零点", "+9零点", "激活后每24h")
INST_ADV_OPTIONS = ("可提前安装", "不可提前安装")

CDP_GUIDE_TEXT = f"""本工具通过 Edge/Chrome CDP 读取携程后台登录态。

直接点击“刷新登录态”时，工具会打开系统安装的 Edge/Chrome，并使用持久化的携程登录专用资料。首次使用请在该窗口完成登录；之后会复用该登录资料。

如需复用已经打开的日常浏览器，必须先在该浏览器中显式启用 remote debugging：

请在你平时登录 Ctrip 后台的浏览器地址栏打开：
Edge：{EDGE_REMOTE_DEBUGGING_URL}
Chrome：{CHROME_REMOTE_DEBUGGING_URL}

按页面提示启用 remote debugging。若页面提示需要重启浏览器，请重启后重新打开 Ctrip 后台。

然后在同一个 Edge/Chrome 中打开携程后台并确认已登录。工具不会再用固定产品权限判断登录是否成功。

完成后回到本工具重新点击“刷新登录态”。显式启用的 9222 会话可通过以下地址检查：
{BROWSER_CDP_TARGETS_URL}

温馨提示：部分站点对浏览器自动化操作检测严格，存在账号风控风险。工具只读取/保存套餐草稿，不提交审核。"""

LEGACY_RESET_RULE_MAP = {
    "activation_24h": "激活后每24h",
    "gmt+7": "+7零点",
    "gmt+8": "+8零点",
    "gmt+9": "+9零点",
}

TEMPLATE_MODE_LABELS = {
    "后降速": "每日/总量用完后降速；每日100GB/20GB使用规则模板专用模板",
    "后停用": "每日/总量用完后服务终止；每日100GB/20GB仍使用规则模板专用模板",
    "吃到饱": "仅处理每日100GB、每日100GB不限速、每日20GB；其他 SKU 预检显示 skipped",
    "总量停用每日降速": "总量用完后停用，每日用完后降速；每日20GB使用专用模板",
}

TEMPLATE_KEY_ALIASES = {
    "後降速": "后降速",
    "后降速": "后降速",
    "後停用": "后停用",
    "后停用": "后停用",
    "吃到饱": "吃到饱",
    "吃到饱_提前安装": "吃到饱",
    "總量停用每日降速": "总量停用每日降速",
    "总量停用每日降速": "总量停用每日降速",
    "daily_throttle": "后降速",
    "total_throttle": "后降速",
    "daily_100gb": "后降速",
    "daily_100gb_unlimited": "后降速",
    "daily_20gb": "吃到饱",
    "total_stop": "后停用",
    "total_stop_50gb": "后停用",
    "total_stop_100gb": "后停用",
    "total_stop_150gb": "后停用",
    "unlimited_preinstall": "吃到饱",
    "mixed_total_stop_daily_throttle": "总量停用每日降速",
}

TEMPLATE_KEY_OPTIONS = USEDUP_THROTTLE_OPTIONS

# Generic documentation row; fill business-specific APN and timing rules in local templates.
SOURCE_WORKBOOK_REQUIREMENTS = (
    ("示例Sheet", "自定义 APN", "自定义规格列", "后降速", "激活后每24h", "可提前安装", "示例规则，请按实际产品修改"),
)


@dataclass
class TemplateRow:
    row_number: int
    product_id: str
    package_id: str = ""
    package_name: str = ""
    usedup_throttle: str = ""
    reset_time_calc: str = ""
    inst_adv: str = ""
    target_cost_price: str = ""
    target_vendor_package_id: str = ""
    target_connection_code: str = ""
    submit_audit: bool = False
    remark: str = ""
    enabled: bool = True
    validation_error: str = ""


@dataclass
class SkuPlan:
    row: TemplateRow
    resource_index: int
    package_name: str
    old_introduction: str
    new_introduction_text: str
    new_introduction_html: str
    selected_template: str


@dataclass
class SkuWritePlan:
    row: TemplateRow
    resource_index: int
    package_id: str
    package_name: str
    resource_id: str
    old_cost_price: str = ""
    new_cost_price: str = ""
    old_vendor_package_id: str = ""
    new_vendor_package_id: str = ""
    old_connection_code: str = ""
    new_connection_code: str = ""
    planned_interfaces: list[str] | None = None
    payload_summary: str = ""


@dataclass
class ResultRow:
    product_id: str
    package_name: str
    status: str
    field_name: str = ""
    interface_name: str = ""
    old_value: str = ""
    new_value: str = ""
    old_introduction: str = ""
    new_introduction: str = ""
    message: str = ""
    row_number: int | str = ""
    usedup_throttle: str = ""
    reset_time_calc: str = ""
    inst_adv: str = ""
    package_id: str = ""
    resource_id: str = ""
    old_cost_price: str = ""
    new_cost_price: str = ""
    old_vendor_package_id: str = ""
    new_vendor_package_id: str = ""
    old_connection_code: str = ""
    new_connection_code: str = ""
    submit_audit: bool = False
    workbench: str = "package_connect"


@dataclass
class ProductWorkbenchUiState:
    workbench: str
    results: list[ResultRow] = field(default_factory=list)
    result_order: dict[str, int] = field(default_factory=dict)
    preloaded_products: dict[str, ProductSnapshot] = field(default_factory=dict)
    pending_diff_plans: list[DiffPlan] = field(default_factory=list)
    last_saved_products: set[str] = field(default_factory=set)
    submit_audit_candidate_product_ids: list[str] = field(default_factory=list)
    error_count: int = 0
    verify_failed_count: int = 0
    pressure_text: str = ""


@dataclass
class CurrencyRewriteContext:
    product_id: str = ""
    should_rewrite: bool = False
    paths: list[str] = field(default_factory=list)


@dataclass
class ProductDraft:
    product_id: str
    target_id: str
    package_info: dict[str, Any]
    package_resources: list[dict[str, Any]]
    product_version: Any = None
    draft_raw: dict[str, Any] | None = None


@dataclass
class SubmitAuditResult:
    response: dict[str, Any]
    request: dict[str, Any]
    confirmed_continue: bool = False
    initial_response: dict[str, Any] | None = None
    confirm_reason: str = ""
    confirm_reasons: list[str] = field(default_factory=list)
    intermediate_responses: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class PriceStockBundle:
    product_id: str
    package_id: str
    resource_id: str
    price_and_stock: dict[str, Any]


@dataclass
class SkuSnapshot:
    product_id: str
    package_id: str
    resource_id: str
    package_name: str
    vendor_package_id: str = ""
    connection_code: str = ""
    introduction: str = ""
    cost_price: str = ""
    cost_price_editable: bool = True
    sale_status: str = ""
    price_and_stock: dict[str, Any] | None = None
    price_error: str = ""
    resource_index: int = -1


@dataclass
class ProductSnapshot:
    product_id: str
    created_at: str
    draft: ProductDraft
    sku_snapshots: dict[str, SkuSnapshot]
    currency_context: CurrencyRewriteContext = field(default_factory=CurrencyRewriteContext)


@dataclass(frozen=True)
class ProductSnapshotNeeds:
    product_info: bool = True
    price_stock: bool = True
    currency_context: bool = True


class ProductWorkbench:
    PRICE_INVENTORY = "price_inventory"
    PRODUCT_INFO = "product_info"
    PACKAGE_CONNECT = "package_connect"
    AUDIT_REPORT = "audit_report"


@dataclass(frozen=True)
class ProductWorkbenchSpec:
    key: str
    title: str
    description: str
    allowed_field_names: tuple[str, ...]
    template_filename: str
    report_filename_prefix: str
    preload_button_text: str
    template_button_text: str
    apply_button_text: str


PRODUCT_WORKBENCH_SPECS: dict[str, ProductWorkbenchSpec] = {
    ProductWorkbench.PRICE_INVENTORY: ProductWorkbenchSpec(
        key=ProductWorkbench.PRICE_INVENTORY,
        title="价格修改",
        description="改套餐/资源底价；本阶段不开放库存数量写入。",
        allowed_field_names=("costPrice", "sale"),
        template_filename="ctrip_price_inventory_template",
        report_filename_prefix="ctrip_price_inventory_report",
        preload_button_text="输入产品ID并读取价格",
        template_button_text="导出调价模板",
        apply_button_text="传出价格修改",
    ),
    ProductWorkbench.PRODUCT_INFO: ProductWorkbenchSpec(
        key=ProductWorkbench.PRODUCT_INFO,
        title="产品信息接口修改",
        description="改产品名称、底价、开/关班状态、供应商套餐 ID、对接代码和套餐说明。",
        allowed_field_names=("costPrice", "sale", "productName", "vendorPackageId", "connectionCode", "introduction"),
        template_filename="ctrip_product_edit_template",
        report_filename_prefix="ctrip_product_edit_report",
        preload_button_text="输入产品ID并预载",
        template_button_text="导出修改模板",
        apply_button_text="传出修改",
    ),
    ProductWorkbench.PACKAGE_CONNECT: ProductWorkbenchSpec(
        key=ProductWorkbench.PACKAGE_CONNECT,
        title="套餐/API 对接修改",
        description="改套餐资源、供应商套餐 ID、对接代码和套餐说明。",
        allowed_field_names=("vendorPackageId", "connectionCode", "introduction"),
        template_filename="ctrip_package_connect_template",
        report_filename_prefix="ctrip_package_connect_report",
        preload_button_text="输入产品ID并读取套餐/API",
        template_button_text="导出套餐/API 模板",
        apply_button_text="传出套餐/API 修改",
    ),
    ProductWorkbench.AUDIT_REPORT: ProductWorkbenchSpec(
        key=ProductWorkbench.AUDIT_REPORT,
        title="审核与报告",
        description="提交审核、导出报告、查看写入审计。",
        allowed_field_names=(),
        template_filename="ctrip_audit_template",
        report_filename_prefix="ctrip_audit_report",
        preload_button_text="输入产品ID",
        template_button_text="生成审核清单",
        apply_button_text="提交审核",
    ),
}


PRODUCT_INFO_FIELD_SPECS: dict[str, dict[str, Any]] = {
    "productName": {
        "label": "产品名称",
        "path": "productBasicInfo.name",
    },
}


def product_workbench_spec(workbench: str) -> ProductWorkbenchSpec:
    try:
        return PRODUCT_WORKBENCH_SPECS[workbench]
    except KeyError as exc:
        raise RuntimeError(f"未知产品工作台：{workbench}") from exc


def product_snapshot_needs_for_workbench(workbench: str, rows: list["EditTemplateRow"]) -> ProductSnapshotNeeds:
    if workbench == ProductWorkbench.PRICE_INVENTORY:
        return ProductSnapshotNeeds(product_info=False, price_stock=True, currency_context=True)
    if workbench == ProductWorkbench.PRODUCT_INFO:
        if not rows:
            return ProductSnapshotNeeds(product_info=True, price_stock=True, currency_context=True)
        need_product_info = any(bool(row.target_product_name) for row in rows if not row.validation_error)
        need_price_stock = any(bool(row.target_cost_price or row.target_sale_status) for row in rows if not row.validation_error)
        return ProductSnapshotNeeds(
            product_info=need_product_info,
            price_stock=need_price_stock,
            currency_context=need_price_stock,
        )
    if workbench == ProductWorkbench.PACKAGE_CONNECT:
        return ProductSnapshotNeeds(product_info=False, price_stock=False, currency_context=False)
    if workbench == ProductWorkbench.AUDIT_REPORT:
        return ProductSnapshotNeeds(product_info=False, price_stock=False, currency_context=False)
    return product_snapshot_needs_for_workbench(product_workbench_spec(workbench).key, rows)


@dataclass
class EditTemplateRow:
    row_number: int
    product_id: str
    package_id: str
    resource_id: str
    package_name: str
    target_cost_price: str = ""
    target_sale_status: str = ""
    target_product_name: str = ""
    target_vendor_package_id: str = ""
    target_connection_code: str = ""
    target_introduction: str = ""
    usedup_throttle: str = ""
    reset_time_calc: str = ""
    inst_adv: str = ""
    validation_error: str = ""
    workbench: str = ProductWorkbench.PACKAGE_CONNECT


@dataclass
class DiffPlan:
    row: EditTemplateRow
    product_id: str
    package_id: str
    resource_id: str
    package_name: str
    field_name: str
    old_value: str
    new_value: str
    interface_name: str
    status: str = "pending"
    message: str = ""
    workbench: str = ProductWorkbench.PACKAGE_CONNECT


@dataclass
class TranslationFieldSnapshot:
    product_id: str
    locale: str
    module_code: str
    module_name: str
    field_code: str
    field_name: str
    value_key: str
    self_key: str
    path: str
    origin: str
    old_translation: str


@dataclass
class TranslationSnapshot:
    product_id: str
    created_at: str
    locales: list[str]
    raw_by_locale: dict[str, dict[str, Any]]
    fields: dict[str, TranslationFieldSnapshot]
    locale_options: dict[str, dict[str, Any]] | None = None


@dataclass
class TranslationTemplateRow:
    row_number: int
    product_id: str
    locale: str
    module_code: str
    field_code: str
    field_name: str
    value_key: str
    self_key: str
    origin: str
    old_translation: str
    target_translation: str = ""
    online: bool = True
    validation_error: str = ""


@dataclass
class TranslationDiffPlan:
    row: TranslationTemplateRow
    product_id: str
    locale: str
    module_code: str
    field_code: str
    field_name: str
    self_key: str
    old_value: str
    new_value: str
    online: bool
    status: str = "pending"
    message: str = ""
    baseline_source_locale: str = ""


@dataclass
class TranslationResultRow:
    product_id: str
    locale: str
    module_code: str
    field_code: str
    field_name: str
    self_key: str
    status: str
    old_value: str = ""
    new_value: str = ""
    online: bool = True
    interface_name: str = "productTranslationPush"
    message: str = ""
    row_number: int | str = ""


@dataclass
class TranslationOnlineContext:
    enabled: bool = False
    online: bool = False
    product_ids: list[str] = field(default_factory=list)
    selected_languages: list[str] = field(default_factory=list)
    locales_by_product: dict[str, list[str]] = field(default_factory=dict)


RENMINBI_CURRENCY_VALUES = {"人民币", "CNY", "RMB"}


def is_currency_definition_key(key: str) -> bool:
    normalized = str(key)
    lower = normalized.lower()
    return normalized in {"currency", "currencyCode"} or lower.endswith("currency") or lower.endswith("currencydb")


def is_renminbi_currency_value(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    stripped = value.strip()
    return stripped == "人民币" or stripped.upper() in {"CNY", "RMB"}


def collect_renminbi_currency_paths(value: Any, path: str = "") -> list[str]:
    paths: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}" if path else str(key)
            if is_currency_definition_key(str(key)) and is_renminbi_currency_value(child):
                paths.append(child_path)
            paths.extend(collect_renminbi_currency_paths(child, child_path))
    elif isinstance(value, list):
        for child in value:
            child_path = f"{path}[]" if path else "[]"
            paths.extend(collect_renminbi_currency_paths(child, child_path))
    return paths


def build_currency_rewrite_context(product_id: str, price_stock_draft: dict[str, Any] | None) -> CurrencyRewriteContext:
    paths = collect_renminbi_currency_paths(price_stock_draft or {})
    return CurrencyRewriteContext(product_id=str(product_id), should_rewrite=bool(paths), paths=paths)


def rewrite_renminbi_currencies_to_hkd(value: Any) -> tuple[Any, int]:
    rewritten = copy.deepcopy(value)
    count = 0

    def walk(current: Any) -> None:
        nonlocal count
        if isinstance(current, dict):
            for key, child in list(current.items()):
                if is_currency_definition_key(str(key)) and is_renminbi_currency_value(child):
                    current[key] = "港币" if str(key) == "currency" else "HKD"
                    count += 1
                else:
                    walk(child)
        elif isinstance(current, list):
            for child in current:
                walk(child)

    walk(rewritten)
    return rewritten, count


def apply_product_edit_currency_rewrite(payload: dict[str, Any], context: CurrencyRewriteContext | None) -> tuple[dict[str, Any], int]:
    if context is None or not context.should_rewrite:
        return payload, 0
    rewritten, count = rewrite_renminbi_currencies_to_hkd(payload)
    if not isinstance(rewritten, dict):
        raise RuntimeError("产品编辑请求币种转换后 payload 不是对象")
    return rewritten, count


def default_translation_execution_config() -> translation_rules.TranslationExecutionConfig:
    return translation_rules.TranslationExecutionConfig(
        selected_languages=translation_rules.DEFAULT_SELECTED_LANGUAGES.copy(),
        selected_modules=translation_rules.DEFAULT_SELECTED_MODULES.copy(),
        sales_attr_mode="strict",
        long_day_package_template_mode="none",
        package_special_rules=translation_rules.normalize_special_rule_config({}),
        online=True,
        include_unopened_locales=False,
    )


@dataclass
class TranslationRuleRuntime:
    task_path: str = ""
    detail_template_path: str = ""
    package_template_path: str = ""
    config: translation_rules.TranslationExecutionConfig = field(default_factory=default_translation_execution_config)
    online_context: TranslationOnlineContext = field(default_factory=TranslationOnlineContext)


@dataclass
class AppSettings:
    product_template_path: str = ""
    product_request_interval_seconds: float = CTRIP_REQUEST_INTERVAL_SECONDS
    product_parallel_requests: int = DEFAULT_PARALLEL_REQUESTS
    export_price: bool = True
    export_connection: bool = True
    export_intro: bool = False
    translation_task_path: str = ""
    translation_detail_template_path: str = ""
    translation_package_template_path: str = ""
    translation_request_interval_seconds: float = CTRIP_REQUEST_INTERVAL_SECONDS
    translation_parallel_requests: int = DEFAULT_PARALLEL_REQUESTS
    translation_execution_config: translation_rules.TranslationExecutionConfig = field(default_factory=default_translation_execution_config)
    product_image_request_interval_seconds: float = CTRIP_REQUEST_INTERVAL_SECONDS
    product_image_parallel_requests: int = DEFAULT_PARALLEL_REQUESTS


@dataclass(frozen=True)
class RuntimeRequestSnapshot:
    request_interval_seconds: float
    parallel_requests: int


class RuntimeRequestSettings:
    def __init__(
        self,
        request_interval_seconds: float = CTRIP_REQUEST_INTERVAL_SECONDS,
        parallel_requests: int = DEFAULT_PARALLEL_REQUESTS,
    ):
        self._lock = threading.Lock()
        self._request_interval_seconds = clamp_request_interval_seconds(request_interval_seconds)
        self._parallel_requests = clamp_parallel_requests_value(parallel_requests)

    def update(self, request_interval_seconds: float | None = None, parallel_requests: int | None = None) -> RuntimeRequestSnapshot:
        with self._lock:
            if request_interval_seconds is not None:
                self._request_interval_seconds = clamp_request_interval_seconds(request_interval_seconds)
            if parallel_requests is not None:
                self._parallel_requests = clamp_parallel_requests_value(parallel_requests)
            return RuntimeRequestSnapshot(self._request_interval_seconds, self._parallel_requests)

    def snapshot(self) -> RuntimeRequestSnapshot:
        with self._lock:
            return RuntimeRequestSnapshot(self._request_interval_seconds, self._parallel_requests)

    def request_interval_seconds(self) -> float:
        return self.snapshot().request_interval_seconds

    def parallel_requests(self) -> int:
        return self.snapshot().parallel_requests


REQUEST_STATS_AREAS = ("product", "image", "translation", "docking")


class RequestStatsStore:
    def __init__(self, path: Path | None = None, today_provider: Callable[[], str] | None = None):
        self.path = path or (default_app_settings_file().parent / "request_stats.json")
        self.today_provider = today_provider or (lambda: dt.date.today().isoformat())
        self._lock = threading.Lock()
        self.load_error = ""
        self.data = self._load()
        self.run_data = {area: {"total_requests": 0, "failed_requests": 0} for area in REQUEST_STATS_AREAS}

    def _empty_area(self) -> dict[str, Any]:
        return {"total_requests": 0, "failed_requests": 0, "daily": {}}

    def _empty_data(self) -> dict[str, Any]:
        return {"version": 1, "areas": {area: self._empty_area() for area in REQUEST_STATS_AREAS}}

    def _normalize_area(self, area_data: Any) -> dict[str, Any]:
        source = area_data if isinstance(area_data, dict) else {}
        normalized = self._empty_area()
        normalized["total_requests"] = int(source.get("total_requests") or 0)
        normalized["failed_requests"] = int(source.get("failed_requests") or 0)
        daily = source.get("daily") if isinstance(source.get("daily"), dict) else {}
        normalized_daily: dict[str, dict[str, int]] = {}
        for day, item in daily.items():
            if not isinstance(item, dict):
                continue
            normalized_daily[str(day)] = {
                "total_requests": int(item.get("total_requests") or 0),
                "failed_requests": int(item.get("failed_requests") or 0),
            }
        normalized["daily"] = normalized_daily
        return normalized

    def _load(self) -> dict[str, Any]:
        empty = self._empty_data()
        if not self.path.exists():
            return empty
        try:
            loaded = json.loads(self.path.read_text(encoding="utf-8"))
            areas = loaded.get("areas") if isinstance(loaded, dict) else {}
            return {
                "version": 1,
                "areas": {
                    area: self._normalize_area(areas.get(area) if isinstance(areas, dict) else {})
                    for area in REQUEST_STATS_AREAS
                },
            }
        except Exception as exc:
            self.load_error = f"请求统计文件读取失败，已从空统计启动：{exc}"
            return empty

    def _area_data(self, area: str) -> dict[str, Any]:
        if area not in REQUEST_STATS_AREAS:
            raise ValueError(f"未知请求统计模块：{area}")
        areas = self.data.setdefault("areas", {})
        if area not in areas:
            areas[area] = self._empty_area()
        return areas[area]

    def _today_data(self, area_data: dict[str, Any]) -> dict[str, int]:
        today = self.today_provider()
        daily = area_data.setdefault("daily", {})
        item = daily.setdefault(today, {"total_requests": 0, "failed_requests": 0})
        return item

    def _save_locked(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self.path.with_name(f"{self.path.name}.tmp")
        tmp_path.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp_path.replace(self.path)

    def record_request(self, area: str, count: int = 1) -> None:
        if count <= 0:
            return
        with self._lock:
            area_data = self._area_data(area)
            today_data = self._today_data(area_data)
            run_data = self.run_data[area]
            area_data["total_requests"] += count
            today_data["total_requests"] += count
            run_data["total_requests"] += count
            self._save_locked()

    def record_failure(self, area: str, count: int = 1) -> None:
        if count <= 0:
            return
        with self._lock:
            area_data = self._area_data(area)
            today_data = self._today_data(area_data)
            run_data = self.run_data[area]
            area_data["failed_requests"] += count
            today_data["failed_requests"] += count
            run_data["failed_requests"] += count
            self._save_locked()

    def summary_text(self, area: str) -> str:
        with self._lock:
            area_data = self._area_data(area)
            today_data = self._today_data(area_data)
            run_data = self.run_data[area]
            return (
                f"请求 累计 {area_data['total_requests']}/{area_data['failed_requests']} | "
                f"今日 {today_data['total_requests']}/{today_data['failed_requests']} | "
                f"本次 {run_data['total_requests']}/{run_data['failed_requests']}"
            )

    def snapshot(self, area: str) -> dict[str, Any]:
        with self._lock:
            area_data = self._area_data(area)
            today_data = self._today_data(area_data)
            run_data = self.run_data[area]
            return {
                "summary": (
                    f"请求 累计 {area_data['total_requests']}/{area_data['failed_requests']} | "
                    f"今日 {today_data['total_requests']}/{today_data['failed_requests']} | "
                    f"本次 {run_data['total_requests']}/{run_data['failed_requests']}"
                ),
                "total_requests": area_data["total_requests"],
                "failed_requests": area_data["failed_requests"],
                "today_requests": today_data["total_requests"],
                "today_failed_requests": today_data["failed_requests"],
                "run_requests": run_data["total_requests"],
                "run_failed_requests": run_data["failed_requests"],
            }


@dataclass(frozen=True)
class ProductRequestTarget:
    product_id: str

    def audit_dict(self) -> dict[str, str]:
        return {"productId": self.product_id}


@dataclass(frozen=True)
class TranslationRequestTarget:
    product_id: str
    locale: str

    def audit_dict(self) -> dict[str, str]:
        return {"productId": self.product_id, "locale": self.locale}


@dataclass
class CapturedRequestTemplate:
    product_id: str
    captured_at: str
    get_request: dict[str, Any] | None = None
    save_request: dict[str, Any] | None = None


def now_stamp() -> str:
    return dt.datetime.now().strftime("%Y%m%d_%H%M%S")


def now_iso() -> str:
    return dt.datetime.now().isoformat(timespec="seconds")


def normalize_cell(value: Any) -> str:
    if value is None:
        return ""
    return str(value).replace("\r\n", "\n").replace("\r", "\n").strip()


def parse_enabled(value: Any) -> bool:
    if value is None or value == "":
        return True
    text = str(value).strip().lower()
    return text not in {"0", "false", "no", "n", "否", "停用", "disabled", "skip"}


def parse_yes(value: Any) -> bool:
    if value is None or value == "":
        return False
    text = str(value).strip().lower()
    return text in {"1", "true", "yes", "y", "是", "提交", "提审", "submit", "enabled"}


def normalize_number_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return normalize_cell(value)
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        text = format(value, ".15g")
    else:
        text = normalize_cell(value)
        if re.fullmatch(r"[+-]?\d+\.\d{12,}", text):
            try:
                text = format(float(text), ".15g")
            except Exception:
                pass
    if not text:
        return ""
    try:
        number = Decimal(text)
    except (InvalidOperation, ValueError):
        return text
    if not number.is_finite():
        return text
    normalized = format(number.normalize(), "f")
    return "0" if normalized == "-0" else normalized


def clamp_parallel_requests_value(value: Any, default: int = DEFAULT_PARALLEL_REQUESTS) -> int:
    try:
        parsed = int(value)
    except Exception:
        parsed = default
    return max(1, min(MAX_PARALLEL_REQUESTS, parsed))


def clamp_request_interval_seconds(value: Any, default: float = CTRIP_REQUEST_INTERVAL_SECONDS) -> float:
    try:
        parsed = float(value)
    except Exception:
        parsed = default
    return max(MIN_REQUEST_INTERVAL_SECONDS, min(MAX_REQUEST_INTERVAL_SECONDS, parsed))


def interval_text(value: Any) -> str:
    normalized = f"{clamp_request_interval_seconds(value):.6f}".rstrip("0").rstrip(".")
    return normalized or "0"


def translation_execution_config_to_dict(config: translation_rules.TranslationExecutionConfig) -> dict[str, Any]:
    return {
        "selected_languages": list(config.selected_languages or []),
        "selected_modules": list(config.selected_modules or []),
        "sales_attr_mode": str(config.sales_attr_mode or "strict"),
        "long_day_package_template_mode": str(config.long_day_package_template_mode or "none"),
        "package_special_rules": translation_rules.normalize_special_rule_config(config.package_special_rules),
        "online": bool(config.online),
        "include_unopened_locales": bool(config.include_unopened_locales),
    }


def translation_execution_config_from_dict(data: Any) -> translation_rules.TranslationExecutionConfig:
    config = default_translation_execution_config()
    if not isinstance(data, dict):
        return config
    valid_languages = set(translation_rules.ALL_TEMPLATE_LANGUAGES)
    selected_languages = [
        str(item)
        for item in data.get("selected_languages", [])
        if str(item) in valid_languages
    ]
    if selected_languages:
        config.selected_languages = selected_languages
    valid_modules = set(translation_rules.MODULE_LABELS)
    selected_modules = [
        str(item)
        for item in data.get("selected_modules", [])
        if str(item) in valid_modules
    ]
    if selected_modules:
        config.selected_modules = selected_modules
    sales_mode = str(data.get("sales_attr_mode") or "")
    if sales_mode in {"strict", "fuzzy_prefix", "ai_translation"}:
        config.sales_attr_mode = sales_mode
    long_day_mode = str(data.get("long_day_package_template_mode") or "")
    if long_day_mode in {"none", "stop", "throttle"}:
        config.long_day_package_template_mode = long_day_mode
    config.package_special_rules = translation_rules.normalize_special_rule_config(
        data.get("package_special_rules") if isinstance(data.get("package_special_rules"), dict) else {}
    )
    if "online" in data:
        config.online = bool(data.get("online"))
    config.include_unopened_locales = bool(data.get("include_unopened_locales", False))
    return config


def app_settings_to_dict(settings: AppSettings) -> dict[str, Any]:
    return {
        "version": APP_SETTINGS_VERSION,
        "product": {
            "template_path": settings.product_template_path,
            "request_interval_seconds": clamp_request_interval_seconds(settings.product_request_interval_seconds),
            "parallel_requests": clamp_parallel_requests_value(settings.product_parallel_requests),
            "export_price": bool(settings.export_price),
            "export_connection": bool(settings.export_connection),
            "export_intro": bool(settings.export_intro),
        },
        "translation": {
            "task_path": settings.translation_task_path,
            "detail_template_path": settings.translation_detail_template_path,
            "package_template_path": settings.translation_package_template_path,
            "request_interval_seconds": clamp_request_interval_seconds(settings.translation_request_interval_seconds),
            "parallel_requests": clamp_parallel_requests_value(settings.translation_parallel_requests),
            "execution_config": translation_execution_config_to_dict(settings.translation_execution_config),
        },
        "product_image": {
            "request_interval_seconds": clamp_request_interval_seconds(settings.product_image_request_interval_seconds),
            "parallel_requests": clamp_parallel_requests_value(settings.product_image_parallel_requests),
        },
    }


def app_settings_from_dict(data: Any) -> AppSettings:
    if not isinstance(data, dict):
        return AppSettings()
    product = data.get("product") if isinstance(data.get("product"), dict) else {}
    translation = data.get("translation") if isinstance(data.get("translation"), dict) else {}
    product_image = data.get("product_image") if isinstance(data.get("product_image"), dict) else {}
    return AppSettings(
        product_template_path=str(product.get("template_path") or ""),
        product_request_interval_seconds=clamp_request_interval_seconds(product.get("request_interval_seconds")),
        product_parallel_requests=clamp_parallel_requests_value(product.get("parallel_requests")),
        export_price=bool(product.get("export_price", True)),
        export_connection=bool(product.get("export_connection", True)),
        export_intro=bool(product.get("export_intro", False)),
        translation_task_path=str(translation.get("task_path") or ""),
        translation_detail_template_path=str(translation.get("detail_template_path") or ""),
        translation_package_template_path=str(translation.get("package_template_path") or ""),
        translation_request_interval_seconds=clamp_request_interval_seconds(translation.get("request_interval_seconds")),
        translation_parallel_requests=clamp_parallel_requests_value(translation.get("parallel_requests")),
        translation_execution_config=translation_execution_config_from_dict(translation.get("execution_config")),
        product_image_request_interval_seconds=clamp_request_interval_seconds(product_image.get("request_interval_seconds")),
        product_image_parallel_requests=clamp_parallel_requests_value(product_image.get("parallel_requests")),
    )


def load_app_settings(path: Path | None = None) -> AppSettings:
    settings_path = path or default_app_settings_file()
    try:
        data = json.loads(settings_path.read_text(encoding="utf-8"))
    except Exception:
        return AppSettings()
    return app_settings_from_dict(data)


def save_app_settings(settings: AppSettings, path: Path | None = None) -> Path:
    settings_path = path or default_app_settings_file()
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = settings_path.with_name(f"{settings_path.name}.tmp")
    temp_path.write_text(json.dumps(app_settings_to_dict(settings), ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temp_path, settings_path)
    return settings_path




def product_image_locale_info(product_info: dict[str, Any]) -> dict[str, Any]:
    basic_info = product_info.get("productBasicInfo")
    if not isinstance(basic_info, dict):
        return {}
    value = basic_info.get("getImageLocaleInfo")
    return value if isinstance(value, dict) else {}


def product_image_basic_info(product_info: dict[str, Any]) -> dict[str, Any]:
    basic_info = product_info.get("productBasicInfo")
    return basic_info if isinstance(basic_info, dict) else {}


def product_image_language_rows(product_info: dict[str, Any]) -> list[dict[str, Any]]:
    locale_info = product_image_locale_info(product_info)
    images = locale_info.get("images")
    return images if isinstance(images, list) else []


def product_image_trip_image_rows(product_info: dict[str, Any]) -> list[dict[str, Any]]:
    trip_images = product_image_basic_info(product_info).get("tripImageList")
    if not isinstance(trip_images, list):
        return []
    grouped: dict[str, dict[str, Any]] = {}
    for image in trip_images:
        if not isinstance(image, dict):
            continue
        locale = normalize_cell(image.get("locale")) or normalize_cell(image.get("languageCode")) or "all"
        row = grouped.setdefault(
            locale,
            {
                "languageCode": locale,
                "languagelocale": locale,
                "imageList": [],
                "_imageRowSource": "productBasicInfo.tripImageList",
            },
        )
        row["imageList"].append(copy.deepcopy(image))
    return list(grouped.values())


def product_image_site_code(row: dict[str, Any]) -> str:
    return normalize_cell(row.get("languageCode")) or normalize_cell(row.get("languagelocale")) or "unknown"










def product_image_urls_from_rows(rows: list[dict[str, Any]], language_code: str = "") -> list[str]:
    urls: list[str] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        if language_code and str(row.get("languageCode") or "") != language_code:
            continue
        image_list = row.get("imageList")
        if not isinstance(image_list, list):
            continue
        for image in image_list:
            if not isinstance(image, dict):
                continue
            url = normalize_cell(image.get("imageUrl"))
            if url and url not in urls:
                urls.append(url)
    return urls


def product_image_effective_language_rows(product_info: dict[str, Any]) -> list[dict[str, Any]]:
    image_rows = product_image_language_rows(product_info)
    has_primary_images = any(
        isinstance(image, dict)
        and (
            normalize_cell(image.get("imageId"))
            or normalize_cell(image.get("imageUrl"))
        )
        for row in image_rows
        if isinstance(row, dict)
        for image in (
            row.get("imageList")
            if isinstance(row.get("imageList"), list)
            else []
        )
    )
    if has_primary_images:
        return image_rows
    trip_rows = product_image_trip_image_rows(product_info)
    if trip_rows:
        return trip_rows
    return image_rows








def workspace_image_to_api(image: WorkspaceImage) -> dict[str, Any]:
    value = copy.deepcopy(image.raw) if image.raw else {}
    image_name = image.image_name
    if not image_name and image.image_url:
        image_name = Path(urllib.parse.urlparse(image.image_url).path).name
    value.update(
        {
            "imageName": image_name,
            "imageUrl": image.image_url,
            "imageState": True,
            "fromTrip": True,
            "imageSource": image.image_source or "ttd",
            "imageEditModel": 1,
        }
    )
    value.setdefault("imageContentList", [])
    if image.image_id:
        value["imageId"] = (
            int(image.image_id)
            if image.image_id.isdigit()
            else image.image_id
        )
    return value


def build_product_info_workspace_image_payload(
    product_id: str,
    product_info: dict[str, Any],
    planned_by_site: dict[str, list[WorkspaceImage]],
    currency_context: CurrencyRewriteContext | None = None,
) -> dict[str, Any]:
    payload = {
        key: copy.deepcopy(product_info.get(key))
        for key in (
            "productBasicInfo",
            "productDescInfo",
            "productRecommendActivityInfo",
            "productAdditionSaleInfo",
            "productPriceStock",
            "productExtendInfo",
            "dsaInfo",
            "productVersion",
        )
        if key in product_info
    }
    payload["productId"] = (
        int(product_id) if str(product_id).isdigit() else product_id
    )
    payload["type"] = 2
    payload["draftTypes"] = ["ProductInfo"]
    payload["draftTypesRequired"] = ["ProductInfo"]

    basic_info = payload.setdefault("productBasicInfo", {})
    if not isinstance(basic_info, dict):
        raise RuntimeError("ProductInfo 中 productBasicInfo 不是对象")
    locale_info = basic_info.setdefault("getImageLocaleInfo", {})
    if not isinstance(locale_info, dict):
        raise RuntimeError("ProductInfo 中 getImageLocaleInfo 不是对象")

    effective_rows = product_image_effective_language_rows(product_info)
    effective_codes = {
        product_image_site_code(row)
        for row in effective_rows
        if isinstance(row, dict)
    }
    unknown_codes = sorted(set(planned_by_site) - effective_codes)
    if unknown_codes:
        raise RuntimeError(
            "接口当前未返回图片站点：" + ", ".join(unknown_codes)
        )

    raw_rows = product_image_language_rows(product_info)
    trip_fallback = (
        bool(product_image_trip_image_rows(product_info))
        and not product_image_urls_from_rows(raw_rows)
    )
    if trip_fallback:
        target_rows = copy.deepcopy(effective_rows)
        for row in target_rows:
            if isinstance(row, dict):
                row.pop("_imageRowSource", None)
        locale_info["images"] = target_rows
    else:
        target_rows = locale_info.setdefault("images", [])
    if not isinstance(target_rows, list):
        raise RuntimeError("ProductInfo 中 getImageLocaleInfo.images 不是数组")

    for row in target_rows:
        if not isinstance(row, dict):
            continue
        site_code = product_image_site_code(row)
        if site_code not in planned_by_site:
            continue
        row["imageList"] = [
            workspace_image_to_api(image)
            for image in planned_by_site[site_code]
        ]

    payload, _rewrite_count = apply_product_edit_currency_rewrite(
        payload,
        currency_context,
    )
    return payload


@dataclass(frozen=True)
class ProductImageVerification:
    ok: bool
    site_errors: dict[str, str]
    actual_by_site: dict[str, tuple[tuple[str, str], ...]]


def verify_product_image_workspace(
    expected_by_site: dict[str, list[WorkspaceImage]],
    actual_product_info: dict[str, Any],
) -> ProductImageVerification:
    actual_by_site: dict[str, tuple[tuple[str, str], ...]] = {}
    invalid_sites: dict[str, str] = {}
    for row in product_image_effective_language_rows(actual_product_info):
        if not isinstance(row, dict):
            continue
        site_code = product_image_site_code(row)
        image_list = row.get("imageList")
        if not isinstance(image_list, list):
            invalid_sites[site_code] = "回读 imageList 不是数组"
            continue
        keys: list[tuple[str, str]] = []
        try:
            for item in image_list:
                if not isinstance(item, dict):
                    raise ValueError("图片项不是对象")
                image_id = str(item.get("imageId") or "").strip()
                image_url = str(item.get("imageUrl") or "").strip()
                if not image_id and not image_url:
                    raise ValueError("图片缺少 imageId/imageUrl")
                keys.append(("id", image_id) if image_id else ("url", image_url))
        except ValueError as exc:
            invalid_sites[site_code] = str(exc)
            continue
        actual_by_site[site_code] = tuple(keys)

    site_errors = dict(invalid_sites)
    for site_code, expected_images in expected_by_site.items():
        expected_keys = tuple(
            workspace_image_key(image)
            for image in expected_images
        )
        actual_keys = actual_by_site.get(site_code)
        if actual_keys is None:
            site_errors[site_code] = "回读结果缺少该站点"
            continue
        if actual_keys == expected_keys:
            continue
        if len(actual_keys) == len(expected_keys) and Counter(actual_keys) == Counter(expected_keys):
            site_errors[site_code] = (
                f"图片顺序不一致：期望={expected_keys}，实际={actual_keys}"
            )
        else:
            site_errors[site_code] = (
                f"图片成员或数量不一致：期望={expected_keys}，实际={actual_keys}"
            )
    return ProductImageVerification(
        ok=not site_errors,
        site_errors=site_errors,
        actual_by_site=actual_by_site,
    )


def product_image_workspace_baseline_matches(
    expected_by_site: dict[str, list[WorkspaceImage]],
    current_product_info: dict[str, Any],
) -> ProductImageVerification:
    return verify_product_image_workspace(
        expected_by_site,
        current_product_info,
    )


def strict_product_image_save_response(response: dict[str, Any]) -> bool:
    if not isinstance(response, dict):
        return False
    response_status = response.get("ResponseStatus")
    response_base = response.get("responseBaseData")
    if not isinstance(response_status, dict) or not isinstance(response_base, dict):
        return False
    return (
        str(response_status.get("Ack") or "").lower() == "success"
        and not response_status.get("Errors")
        and response_base.get("success") is True
    )


def save_and_verify_product_image_workspace(
    client: Any,
    state: Any,
    stop_event: threading.Event,
) -> ProductImageVerification:
    current_product_info = client.load_product_info_draft(
        state.product_id,
        stop_event,
    )
    baseline_check = product_image_workspace_baseline_matches(
        state.baseline_by_site(),
        current_product_info,
    )
    if not baseline_check.ok:
        details = "；".join(
            f"{site}：{message}"
            for site, message in baseline_check.site_errors.items()
        )
        raise RuntimeError(
            f"线上图片已变化，请重新读取后再提交。{details}"
        )
    payload = build_product_info_workspace_image_payload(
        state.product_id,
        current_product_info,
        state.planned_by_site(),
        state.currency_context,
    )
    response = client.save_product_info_draft(
        state.product_id,
        payload,
        stop_event,
    )
    if not strict_product_image_save_response(response):
        raise RuntimeError(
            "保存接口返回失败："
            + response_message(response, "未提供失败原因")
        )
    verified_product_info = client.load_product_info_draft(
        state.product_id,
        stop_event,
    )
    return verify_product_image_workspace(
        state.planned_by_site(),
        verified_product_info,
    )


def make_product_image_workspace_backend(
    client: Any,
    open_advanced_config: Callable[[], None] | None = None,
    request_recorder: Callable[[str], None] | None = None,
) -> Any:
    from product_image_workspace import (
        LoadedProductImages,
        ProductImageWorkspaceBackend,
    )
    from product_image_workspace_state import workspace_image_from_api

    def load_product(
        product_id: str,
        stop_event: threading.Event,
    ) -> LoadedProductImages:
        product_info = client.load_product_info_draft(
            product_id,
            stop_event,
        )
        currency_context = client.load_product_currency_context(
            product_id,
            stop_event,
        )
        return LoadedProductImages(
            product_id=str(product_id),
            product_info=product_info,
            site_rows=product_image_effective_language_rows(product_info),
            currency_context=currency_context,
        )

    def upload_image(product_id: str, path: Path) -> WorkspaceImage:
        cookie_header = read_plain_cookie()
        if not cookie_header:
            raise RuntimeError("Cookie 为空，请先在主界面刷新登录态")
        try:
            result = ctrip_upload_image(path, product_id, cookie_header)
        finally:
            if request_recorder is not None:
                request_recorder("image")
        return workspace_image_from_api(
            {
                "imageId": result.image_id,
                "imageUrl": result.image_url,
                "imageName": result.image_name,
                "imageSource": "ttd",
            }
        )

    return ProductImageWorkspaceBackend(
        load_product=load_product,
        upload_image=upload_image,
        save_and_verify=lambda state, stop_event: (
            save_and_verify_product_image_workspace(
                client,
                state,
                stop_event,
            )
        ),
        open_advanced_config=open_advanced_config,
    )


class LazyCtripClientProxy:
    """Delay authenticated client construction until a workspace operation runs."""

    def __init__(self, factory: Callable[[], Any]):
        self._factory = factory
        self._client: Any = None
        self._lock = threading.Lock()

    def _get_client(self) -> Any:
        with self._lock:
            if self._client is None:
                self._client = self._factory()
            return self._client

    def __getattr__(self, name: str) -> Any:
        return getattr(self._get_client(), name)


def build_product_info_name_payload(
    product_id: str,
    product_info: dict[str, Any],
    new_name: str,
    currency_context: CurrencyRewriteContext | None = None,
) -> dict[str, Any]:
    payload = {
        key: copy.deepcopy(product_info.get(key))
        for key in (
            "productBasicInfo",
            "productDescInfo",
            "productRecommendActivityInfo",
            "productAdditionSaleInfo",
            "productPriceStock",
            "productExtendInfo",
            "dsaInfo",
            "productVersion",
        )
        if key in product_info
    }
    payload["productId"] = int(product_id) if str(product_id).isdigit() else product_id
    payload["type"] = 2
    payload["draftTypes"] = ["ProductInfo"]
    payload["draftTypesRequired"] = ["ProductInfo"]
    basic_info = payload.setdefault("productBasicInfo", {})
    if not isinstance(basic_info, dict):
        raise RuntimeError("ProductInfo 中 productBasicInfo 不是对象")
    basic_info["name"] = new_name
    payload, _rewrite_count = apply_product_edit_currency_rewrite(payload, currency_context)
    assert_product_payload_target(payload, ProductRequestTarget(target_product_id(product_id)), "product_info_name")
    return payload


class AdaptiveLoadController:
    def __init__(
        self,
        desired_parallel: int,
        request_interval_seconds: float,
        task_count: int = 0,
        min_parallel: int = ADAPTIVE_MIN_PARALLEL,
        initial_parallel: int | None = None,
    ):
        self.desired_parallel = max(1, min(MAX_PARALLEL_REQUESTS, int(desired_parallel)))
        self.request_interval_seconds = max(0.0, float(request_interval_seconds))
        self.task_count = max(0, int(task_count))
        self.min_parallel = min(self.desired_parallel, max(1, int(min_parallel)))
        start = initial_parallel if initial_parallel is not None else min(ADAPTIVE_INITIAL_PARALLEL, self.desired_parallel)
        self._current_parallel = min(self.desired_parallel, max(self.min_parallel, int(start)))
        self._success_streak = 0
        self._error_streak = 0
        self._pressure_reason = ""
        self._lock = threading.Lock()

    def current_parallel(self) -> int:
        with self._lock:
            return self._current_parallel

    def pressure_reason(self) -> str:
        with self._lock:
            return self._pressure_reason

    def update_limits(self, desired_parallel: int, request_interval_seconds: float) -> bool:
        desired = max(1, min(MAX_PARALLEL_REQUESTS, int(desired_parallel)))
        interval = max(0.0, float(request_interval_seconds))
        with self._lock:
            old_desired = self.desired_parallel
            changed = desired != self.desired_parallel or abs(interval - self.request_interval_seconds) > 1e-9
            self.desired_parallel = desired
            self.request_interval_seconds = interval
            self.min_parallel = min(self.desired_parallel, max(1, int(self.min_parallel)))
            self._current_parallel = max(self.min_parallel, min(self._current_parallel, self.desired_parallel))
            if desired > old_desired:
                self._current_parallel = min(
                    self.desired_parallel,
                    max(self._current_parallel, min(ADAPTIVE_INITIAL_PARALLEL, self.desired_parallel)),
                )
            if changed and self._current_parallel < self.desired_parallel:
                self._pressure_reason = ""
            return changed

    def _reduce_locked(self, reason: str) -> None:
        old_value = self._current_parallel
        self._current_parallel = max(self.min_parallel, max(1, old_value // 2))
        self._success_streak = 0
        self._pressure_reason = reason

    def on_pressure(self, queue_size: int = 0, audit_queue_size: int = 0, result_count: int = 0) -> int:
        with self._lock:
            reasons: list[str] = []
            if queue_size >= ADAPTIVE_QUEUE_PRESSURE_THRESHOLD:
                reasons.append(f"UI队列={queue_size}")
            if audit_queue_size >= ADAPTIVE_AUDIT_PRESSURE_THRESHOLD:
                reasons.append(f"审计队列={audit_queue_size}")
            if result_count >= 50000 and queue_size > ADAPTIVE_QUEUE_PRESSURE_THRESHOLD // 2:
                reasons.append(f"结果={result_count}")
            if reasons:
                self._reduce_locked("；".join(reasons))
            elif not self._pressure_reason:
                self._pressure_reason = ""
            return self._current_parallel

    def on_target_done(self, latency: float, status: str = "ok") -> int:
        with self._lock:
            error_status = str(status or "").lower() not in {"", "ok", "success", "preloaded", "saved"}
            slow = latency > max(30.0, self.request_interval_seconds * 12.0)
            if error_status or slow:
                self._error_streak += 1
                self._success_streak = 0
                if self._error_streak >= 2 or slow:
                    self._reduce_locked("请求错误/慢响应")
                return self._current_parallel

            self._error_streak = 0
            self._success_streak += 1
            if self._current_parallel < self.desired_parallel and self._success_streak >= ADAPTIVE_SUCCESS_GROWTH_STREAK:
                self._current_parallel += 1
                self._success_streak = 0
                self._pressure_reason = ""
            return self._current_parallel


class GlobalRequestLimiter:
    def __init__(self, interval_seconds: float = CTRIP_REQUEST_INTERVAL_SECONDS):
        self._lock = threading.Lock()
        self.interval_seconds = clamp_request_interval_seconds(interval_seconds)
        self.next_allowed_at = 0.0
        self.enabled = True

    def configure_for_workload(self, request_interval_seconds: float, desired_parallel: int) -> None:
        interval = clamp_request_interval_seconds(request_interval_seconds)
        with self._lock:
            self.interval_seconds = interval
            self.enabled = True

    def wait(self, stop_event: threading.Event) -> None:
        while True:
            if stop_event.is_set():
                raise RuntimeError("用户已停止")
            with self._lock:
                if not self.enabled:
                    return
                now = time.monotonic()
                wait_seconds = self.next_allowed_at - now
                if wait_seconds <= 0:
                    self.next_allowed_at = now + self.interval_seconds
                    return
            time.sleep(min(0.2, max(0.01, wait_seconds)))


class RequestWaitLogAggregator:
    def __init__(self, interval_seconds: float = 2.0):
        self.interval_seconds = interval_seconds
        self._lock = threading.Lock()
        self._count = 0
        self._total_wait = 0.0
        self._last_emit = time.monotonic()

    def record(self, log: Callable[[str], None], wait_seconds: float) -> None:
        should_emit = False
        with self._lock:
            self._count += 1
            self._total_wait += max(0.0, wait_seconds)
            now = time.monotonic()
            if now - self._last_emit >= self.interval_seconds:
                count = self._count
                total_wait = self._total_wait
                self._count = 0
                self._total_wait = 0.0
                self._last_emit = now
                should_emit = True
        if should_emit:
            log(f"请求间隔控制：近 {self.interval_seconds:.0f} 秒等待 {count} 次，累计 {total_wait:.1f} 秒")


GLOBAL_REQUEST_LIMITER = GlobalRequestLimiter()
REQUEST_WAIT_LOG_AGGREGATOR = RequestWaitLogAggregator()


@dataclass
class AdaptiveRunPressure:
    queue_size: int = 0
    audit_queue_size: int = 0
    result_count: int = 0


class AuditQueueWriter:
    def __init__(self):
        self._queue: queue.Queue[Any] = queue.Queue()
        self._errors: list[Exception] = []
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._closed = False
        self._thread.start()

    def qsize(self) -> int:
        return self._queue.qsize()

    def enqueue(
        self,
        run_dir: Path,
        product_id: str,
        kind: str,
        record: dict[str, Any],
        target: ProductRequestTarget | TranslationRequestTarget | None = None,
        transaction_id: str = "",
    ) -> None:
        if self._closed:
            raise RuntimeError("audit writer 已关闭")
        self._queue.put((run_dir, product_id, kind, record, target, transaction_id))

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            self._queue.put(None)
        self._thread.join()
        if self._errors:
            raise RuntimeError(f"audit 写入失败：{self._errors[0]}")

    def _run(self) -> None:
        while True:
            item = self._queue.get()
            try:
                if item is None:
                    return
                run_dir, product_id, kind, record, target, transaction_id = item
                write_audit_record(run_dir, product_id, kind, record, target=target, transaction_id=transaction_id)
            except Exception as exc:
                self._errors.append(exc)
            finally:
                self._queue.task_done()


def audit_write_or_enqueue(
    audit_writer: AuditQueueWriter | None,
    run_dir: Path,
    product_id: str,
    kind: str,
    record: dict[str, Any],
    target: ProductRequestTarget | TranslationRequestTarget | None = None,
    transaction_id: str = "",
) -> None:
    if audit_writer is None:
        write_audit_record(run_dir, product_id, kind, record, target=target, transaction_id=transaction_id)
    else:
        audit_writer.enqueue(run_dir, product_id, kind, record, target=target, transaction_id=transaction_id)


def run_adaptive_items(
    items: list[Any],
    handler: Callable[[int, Any], str | None],
    stop_event: threading.Event,
    controller: AdaptiveLoadController,
    pressure_provider: Callable[[], AdaptiveRunPressure] | None = None,
    pressure_callback: Callable[[AdaptiveLoadController], None] | None = None,
    runtime_settings_provider: Callable[[], RuntimeRequestSnapshot] | None = None,
) -> None:
    if not items:
        return
    if len(items) <= 1:
        for index, item in enumerate(items, start=1):
            if stop_event.is_set():
                break
            if runtime_settings_provider is not None:
                settings = runtime_settings_provider()
                controller.update_limits(settings.parallel_requests, settings.request_interval_seconds)
                GLOBAL_REQUEST_LIMITER.configure_for_workload(settings.request_interval_seconds, settings.parallel_requests)
            start = time.monotonic()
            status = handler(index, item) or "ok"
            controller.on_target_done(time.monotonic() - start, status)
        return

    indexed_items = list(enumerate(items, start=1))
    next_index = 0
    running: dict[concurrent.futures.Future, float] = {}

    def submit_available(executor: concurrent.futures.ThreadPoolExecutor) -> None:
        nonlocal next_index
        while not stop_event.is_set() and next_index < len(indexed_items) and len(running) < controller.current_parallel():
            item_index, item = indexed_items[next_index]
            next_index += 1
            future = executor.submit(handler, item_index, item)
            running[future] = time.monotonic()

    last_runtime_snapshot: RuntimeRequestSnapshot | None = None

    def refresh_runtime_limits() -> bool:
        nonlocal last_runtime_snapshot
        if runtime_settings_provider is None:
            return False
        settings = runtime_settings_provider()
        if settings == last_runtime_snapshot:
            return False
        last_runtime_snapshot = settings
        GLOBAL_REQUEST_LIMITER.configure_for_workload(settings.request_interval_seconds, settings.parallel_requests)
        return controller.update_limits(settings.parallel_requests, settings.request_interval_seconds)

    max_workers = min(MAX_PARALLEL_REQUESTS, max(1, len(indexed_items)))
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        refresh_runtime_limits()
        submit_available(executor)
        last_parallel = controller.current_parallel()
        if pressure_callback is not None:
            pressure_callback(controller)
        while running:
            limits_changed = refresh_runtime_limits()
            if pressure_provider is not None:
                pressure = pressure_provider()
                controller.on_pressure(
                    queue_size=pressure.queue_size,
                    audit_queue_size=pressure.audit_queue_size,
                    result_count=pressure.result_count,
                )
            current_parallel = controller.current_parallel()
            if pressure_callback is not None and (current_parallel != last_parallel or limits_changed):
                last_parallel = current_parallel
                pressure_callback(controller)
            done, _pending = concurrent.futures.wait(
                running.keys(),
                timeout=0.1,
                return_when=concurrent.futures.FIRST_COMPLETED,
            )
            if not done:
                if stop_event.is_set():
                    break
                submit_available(executor)
                continue
            for future in done:
                started_at = running.pop(future, time.monotonic())
                latency = time.monotonic() - started_at
                try:
                    status = future.result() or "ok"
                except Exception:
                    controller.on_target_done(latency, "error")
                    for pending in running:
                        pending.cancel()
                    raise
                controller.on_target_done(latency, status)
            submit_available(executor)
            if stop_event.is_set():
                break
        if stop_event.is_set():
            for pending in running:
                pending.cancel()


def template_row_has_intro_task(row: TemplateRow) -> bool:
    return bool(row.usedup_throttle or row.reset_time_calc or row.inst_adv)


def template_row_has_price_task(row: TemplateRow) -> bool:
    return bool(row.target_cost_price)


def template_row_has_connection_task(row: TemplateRow) -> bool:
    return bool(row.target_vendor_package_id or row.target_connection_code)


def template_row_needs_sku_locator(row: TemplateRow) -> bool:
    return template_row_has_price_task(row) or template_row_has_connection_task(row)


def text_to_ctrip_intro(text: str) -> str:
    lines = [line.rstrip() for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    while lines and not lines[-1]:
        lines.pop()
    return "<br/>\n".join(lines) + ("<br/>" if lines else "")


def plain_intro_payload_text(text: str) -> str:
    return str(text or "").replace("\r\n", "\n").replace("\r", "\n").strip()


def ctrip_intro_to_text(value: Any) -> str:
    text = "" if value is None else str(value)
    return text.replace("<br/>", "\n").replace("<br>", "\n").replace("\r\n", "\n").replace("\r", "\n").strip()


def text_length_for_limit(text: str) -> int:
    return len(text.replace("\n", ""))


def build_diff(old: str, new: str) -> str:
    old_lines = ctrip_intro_to_text(old).splitlines()
    new_lines = ctrip_intro_to_text(new).splitlines()
    return "\n".join(difflib.unified_diff(old_lines, new_lines, fromfile="当前", tofile="模板", lineterm=""))


def normalize_lookup_key(value: str) -> str:
    return normalize_cell(value).replace("－", "-").strip()


def normalize_capacity(value: Any) -> str:
    return str(value or "").replace(" ", "").replace("－", "-").upper()


def infer_package_info(package_name: str) -> dict[str, Any]:
    text = normalize_cell(package_name)
    normalized = normalize_capacity(text)
    capacity_match = re.search(r"(\d+(?:\.\d+)?\s*[Gg][Bb])", text)
    capacity = capacity_match.group(1).replace(" ", "").upper() if capacity_match else ""
    is_daily = "每日" in text or "每天" in text
    is_total = "总量" in text or "總量" in text
    is_unlimited_speed = "不限速" in text
    return {
        "capacity": capacity,
        "normalized_capacity": normalized,
        "is_daily": is_daily,
        "is_total": is_total,
        "is_unlimited_speed": is_unlimited_speed,
        "has_100gb": "100GB" in normalized,
        "has_150gb": "150GB" in normalized,
        "has_20gb": "20GB" in normalized,
    }


def build_package_name_mark(package_name: str) -> str:
    text = normalize_cell(package_name)
    day_match = re.search(r"(\d+)\s*天", text)
    capacity_match = re.search(r"(\d+(?:\.\d+)?\s*[Gg][Bb])", text)
    if not day_match or not capacity_match:
        return ""
    days = day_match.group(1)
    capacity = capacity_match.group(1).replace(" ", "").upper()
    prefix = "Daily" if ("每日" in text or "每天" in text) else ""
    suffix = text[capacity_match.end():]
    if suffix and not suffix.startswith("-"):
        suffix = ""
    return f"{days}-{prefix}{capacity}{suffix}"


def canonical_usedup_throttle(value: str) -> str:
    key = normalize_lookup_key(value)
    return TEMPLATE_KEY_ALIASES.get(key, key)


def migrate_old_reset_rule(value: str) -> tuple[str, str]:
    key = normalize_lookup_key(value).lower()
    if not key:
        return "", ""
    if key in LEGACY_RESET_RULE_MAP:
        return LEGACY_RESET_RULE_MAP[key], ""
    return "", f"旧字段 apnOrResetRule 只兼容 activation_24h/gmt+7/gmt+8/gmt+9，不再支持 APN：{value}"


def old_reset_fields_to_calc(reset_rule: str, reset_time: str) -> str:
    if reset_rule == "激活后每24h":
        return "激活后每24h"
    if reset_rule == "固定零点刷新":
        return reset_time
    return ""


def validate_placeholder_settings(usedup_throttle: str, reset_time_calc: str, inst_adv: str) -> str:
    if not usedup_throttle:
        return "usedup_throttle 不能为空"
    if usedup_throttle not in USEDUP_THROTTLE_OPTIONS:
        return f"未知 usedup_throttle：{usedup_throttle}"
    if reset_time_calc and reset_time_calc not in RESET_TIME_CALC_OPTIONS:
        return f"未知 reset_time_calc：{reset_time_calc}"
    if inst_adv and inst_adv not in INST_ADV_OPTIONS:
        return f"未知 inst_adv：{inst_adv}"
    return ""


def get_reset_line(reset_time_calc: str, is_daily: bool) -> tuple[str, str]:
    if not is_daily or not reset_time_calc:
        return "", ""
    line = CTRIP_PACKAGE_TEMPLATE_DICT["reset_time_calc"].get(reset_time_calc, "")
    if not line:
        return "", f"未知 reset_time_calc：{reset_time_calc}"
    return line, ""


def get_install_line(inst_adv: str) -> tuple[str, str]:
    effective = inst_adv or "可提前安装"
    line = CTRIP_PACKAGE_TEMPLATE_DICT["install_instructions"].get(effective, "")
    if not line:
        return "", f"未知 inst_adv：{inst_adv}"
    return line, ""


def script_key_for_usedup(usedup_throttle: str) -> str:
    return "吃到饱_提前安装" if usedup_throttle == "吃到饱" else usedup_throttle


def select_package_template_name(usedup_throttle: str, package_name: str) -> tuple[str | None, str]:
    package_info = infer_package_info(package_name)
    key = canonical_usedup_throttle(usedup_throttle)

    if not key:
        return "", "usedup_throttle 不能为空"
    if key not in USEDUP_THROTTLE_OPTIONS:
        return "", f"未知 usedup_throttle：{usedup_throttle}"

    if key == "吃到饱":
        if package_info["is_daily"] and package_info["has_100gb"] and package_info["is_unlimited_speed"]:
            return "daily_100gb_unlimited", ""
        if package_info["is_daily"] and package_info["has_100gb"]:
            return "daily_100gb", ""
        if package_info["is_daily"] and package_info["has_20gb"]:
            return "daily_20gb", ""
        return None, "吃到饱仅处理每日100GB/100GB不限速/20GB，当前 SKU 按兼容规则跳过"

    if key == "总量停用每日降速":
        if package_info["is_daily"] and package_info["has_20gb"]:
            return "daily_20gb", ""
        if package_info["is_daily"]:
            return "daily_generic", ""
        if package_info["is_total"]:
            return "total", ""
        return "", "无法从套餐名判断每日/总量"

    script_templates = CTRIP_PACKAGE_TEMPLATE_DICT["scripts"][script_key_for_usedup(key)]
    if package_info["is_daily"] and package_info["has_100gb"] and package_info["is_unlimited_speed"] and "daily_100gb_unlimited" in script_templates:
        return "daily_100gb_unlimited", ""
    if package_info["is_daily"] and package_info["has_100gb"] and "daily_100gb" in script_templates:
        return "daily_100gb", ""
    if package_info["is_daily"] and package_info["has_20gb"] and "daily_20gb" in script_templates:
        return "daily_20gb", ""
    if package_info["is_daily"] and "daily_generic" in script_templates:
        return "daily_generic", ""
    if package_info["is_total"] and "total" in script_templates:
        return "total", ""
    return "", "无法从套餐名判断每日/总量，或当前模式缺少对应模板"


def generate_intro_from_rule(usedup_throttle: str, reset_time_calc: str, inst_adv: str, package_name: str) -> tuple[str, str | None, str]:
    usedup_key = canonical_usedup_throttle(usedup_throttle)
    resolved_key, error = select_package_template_name(usedup_key, package_name)
    if error:
        return "", resolved_key, error
    if not resolved_key:
        return "", "", "未匹配到套餐模板"

    package_info = infer_package_info(package_name)
    capacity = package_info["capacity"]
    if not capacity:
        return "", resolved_key, f"无法从套餐名提取容量：{package_name}"

    script_key = script_key_for_usedup(usedup_key)
    script_templates = CTRIP_PACKAGE_TEMPLATE_DICT["scripts"].get(script_key, {})
    action_template = script_templates.get(resolved_key)
    if not action_template:
        return "", resolved_key, f"模板 {usedup_key}/{resolved_key} 缺少说明文本"

    reset_line, reset_error = get_reset_line(reset_time_calc, bool(package_info["is_daily"]))
    if reset_error:
        return "", resolved_key, reset_error
    install_line, install_error = get_install_line(inst_adv)
    if install_error:
        return "", resolved_key, install_error

    replacements = {
        "{usedup_throttle}": action_template.format(data_capacity=capacity),
        "{reset_time_calc}": reset_line,
        "{Day_calc}": CTRIP_PACKAGE_TEMPLATE_DICT["day_calc"],
        "{inst_adv}": install_line,
    }
    template_type = "daily" if package_info["is_daily"] else "total"
    result_text = CTRIP_PACKAGE_TEMPLATE_DICT["combination_template"][template_type]
    for placeholder, value in replacements.items():
        result_text = result_text.replace(placeholder, value)
    lines = [line.rstrip() for line in result_text.splitlines() if line.strip() and line.strip() != "●"]

    return "\n".join(lines), resolved_key, ""


def build_template_workbook(path: str) -> None:
    if openpyxl is None:
        raise RuntimeError("缺少 openpyxl，无法生成模板。请先运行：py -3 -m pip install -r requirements.txt")

    from openpyxl.styles import Font, PatternFill
    from openpyxl.worksheet.datavalidation import DataValidation

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "任务模板"
    ws.append(list(TEMPLATE_COLUMNS))

    examples = [
        ["100000001", "", "", "后降速", "+8零点", "", "", "", "", "否", "示例：自动处理该产品全部套餐 SKU 说明", "否"],
        ["100000002", "200000001", "QR code-1天-5G网络-每日-0.5GB", "", "", "", "1.00", "", "", "否", "示例：只改底价", "否"],
        ["100000002", "200000001", "QR code-1天-5G网络-每日-0.5GB", "", "", "", "", "EXAMPLE_VENDOR_PACKAGE_ID", "", "否", "示例：只改供应商套餐 ID/对接代码", "否"],
        ["100000002", "200000001", "QR code-1天-5G网络-每日-0.5GB", "", "", "", "1.00", "EXAMPLE_VENDOR_PACKAGE_ID", "", "是", "示例：改价格和对接配置后提交审核", "否"],
    ]
    for row in examples:
        ws.append(row)

    header_fill = PatternFill("solid", fgColor="D9EAF7")
    for cell in ws[1]:
        cell.font = Font(bold=True)
        cell.fill = header_fill
    widths = [16, 14, 38, 24, 18, 18, 18, 42, 42, 14, 46, 12]
    for idx, width in enumerate(widths, start=1):
        ws.column_dimensions[openpyxl.utils.get_column_letter(idx)].width = width
    ws.freeze_panes = "A2"

    rules = wb.create_sheet("规则说明")
    rules.append(["usedup_throttle", "说明"])
    for key in USEDUP_THROTTLE_OPTIONS:
        rules.append([key, TEMPLATE_MODE_LABELS.get(key, "")])
    start_reset_time_row = rules.max_row + 2
    rules.cell(start_reset_time_row, 1, "reset_time_calc")
    rules.cell(start_reset_time_row, 2, "说明")
    for value in RESET_TIME_CALC_OPTIONS:
        rules.append([value, CTRIP_PACKAGE_TEMPLATE_DICT["reset_time_calc"][value]])
    start_install_row = rules.max_row + 2
    rules.cell(start_install_row, 1, "inst_adv")
    rules.cell(start_install_row, 2, "说明")
    for value in INST_ADV_OPTIONS:
        rules.append([value, CTRIP_PACKAGE_TEMPLATE_DICT["install_instructions"][value]])
    for col in range(1, 3):
        rules.column_dimensions[openpyxl.utils.get_column_letter(col)].width = 36

    source_rules = wb.create_sheet("填充要求")
    source_rules.append(["来源Sheet", "原 APN/方案", "原表列名", "usedup_throttle", "reset_time_calc", "inst_adv", "备注"])
    for row in SOURCE_WORKBOOK_REQUIREMENTS:
        source_rules.append(list(row))
    source_rules.append([])
    source_rules.append(["字典项", "键", "内容", "", "", "", ""])
    for script_key, entries in CTRIP_PACKAGE_TEMPLATE_DICT["scripts"].items():
        for entry_key, text in entries.items():
            source_rules.append([script_key, entry_key, text, "", "", "", ""])
    source_rules.append(["fixed", "day_calc", CTRIP_PACKAGE_TEMPLATE_DICT["day_calc"], "", "", "", ""])
    for key, text in CTRIP_PACKAGE_TEMPLATE_DICT["reset_time_calc"].items():
        source_rules.append(["reset_time_calc", key, text, "", "", "", ""])
    for key, text in CTRIP_PACKAGE_TEMPLATE_DICT["install_instructions"].items():
        source_rules.append(["inst_adv", key, text, "", "", "", ""])
    for col, width in enumerate((18, 58, 24, 26, 22, 22, 58), start=1):
        source_rules.column_dimensions[openpyxl.utils.get_column_letter(col)].width = width
    for cell in source_rules[1]:
        cell.font = Font(bold=True)
        cell.fill = header_fill

    template_dv = DataValidation(type="list", formula1=f"'规则说明'!$A$2:$A${1 + len(USEDUP_THROTTLE_OPTIONS)}", allow_blank=True)
    reset_time_end = start_reset_time_row + len(RESET_TIME_CALC_OPTIONS)
    reset_time_dv = DataValidation(type="list", formula1=f"'规则说明'!$A${start_reset_time_row + 1}:$A${reset_time_end}", allow_blank=True)
    install_end = start_install_row + len(INST_ADV_OPTIONS)
    install_dv = DataValidation(type="list", formula1=f"'规则说明'!$A${start_install_row + 1}:$A${install_end}", allow_blank=True)
    enabled_dv = DataValidation(type="list", formula1='"是,否"', allow_blank=True)
    submit_dv = DataValidation(type="list", formula1='"是,否"', allow_blank=True)
    ws.add_data_validation(template_dv)
    ws.add_data_validation(reset_time_dv)
    ws.add_data_validation(install_dv)
    ws.add_data_validation(submit_dv)
    ws.add_data_validation(enabled_dv)
    template_dv.add("D2:D1000")
    reset_time_dv.add("E2:E1000")
    install_dv.add("F2:F1000")
    submit_dv.add("J2:J1000")
    enabled_dv.add("L2:L1000")

    wb.save(path)


def read_template(path: str) -> list[TemplateRow]:
    if openpyxl is None:
        raise RuntimeError("缺少 openpyxl，请先运行：py -3 -m pip install -r requirements.txt")

    wb = openpyxl.load_workbook(path, data_only=True)
    ws = wb.active
    headers: dict[str, int] = {}
    for idx, cell in enumerate(ws[1], start=1):
        name = normalize_cell(cell.value)
        if name:
            headers[name] = idx

    old_template_mode = "usedup_throttle" not in headers and "templateKey" in headers
    missing = [name for name in REQUIRED_COLUMNS if name not in headers]
    if missing:
        raise ValueError(f"Excel 缺少必填列：{', '.join(missing)}")

    def get_value(row_idx: int, column_name: str) -> str:
        column = headers.get(column_name)
        if not column:
            return ""
        return normalize_cell(ws.cell(row_idx, column).value)

    rows: list[TemplateRow] = []
    for row_idx in range(2, ws.max_row + 1):
        product_id = normalize_number_text(get_value(row_idx, "productId"))
        package_id = normalize_number_text(get_value(row_idx, "packageId"))
        package_name = get_value(row_idx, "packageName")
        usedup_throttle = get_value(row_idx, "usedup_throttle")
        reset_time_calc = get_value(row_idx, "reset_time_calc")
        inst_adv = get_value(row_idx, "inst_adv")
        target_cost_price = normalize_number_text(get_value(row_idx, "target_cost_price"))
        target_vendor_package_id = get_value(row_idx, "target_vendor_package_id")
        target_connection_code = get_value(row_idx, "target_connection_code")
        submit_audit = parse_yes(ws.cell(row_idx, headers["submit_audit"]).value) if "submit_audit" in headers else False
        old_template_error = ""
        if old_template_mode:
            usedup_throttle = get_value(row_idx, "templateKey")
            reset_rule = get_value(row_idx, "resetRule")
            reset_time = get_value(row_idx, "resetTime")
            reset_time_calc = old_reset_fields_to_calc(reset_rule, reset_time)
            inst_adv = get_value(row_idx, "installRule")
        if not reset_time_calc and "apnOrResetRule" in headers:
            reset_time_calc, old_template_error = migrate_old_reset_rule(get_value(row_idx, "apnOrResetRule"))
        remark = get_value(row_idx, "remark")
        enabled = parse_enabled(ws.cell(row_idx, headers["enabled"]).value) if "enabled" in headers else True

        if not any([product_id, package_id, package_name, usedup_throttle, reset_time_calc, target_cost_price, target_vendor_package_id, target_connection_code, submit_audit, remark]):
            continue

        validation_error = ""
        usedup_throttle = canonical_usedup_throttle(usedup_throttle)
        temp_row = TemplateRow(
            row_number=row_idx,
            product_id=product_id,
            package_id=package_id,
            package_name=package_name,
            usedup_throttle=usedup_throttle,
            reset_time_calc=reset_time_calc,
            inst_adv=inst_adv,
            target_cost_price=target_cost_price,
            target_vendor_package_id=target_vendor_package_id,
            target_connection_code=target_connection_code,
            submit_audit=submit_audit,
            remark=remark,
            enabled=enabled,
        )
        if old_template_error:
            validation_error = old_template_error
        elif not product_id:
            validation_error = "productId 不能为空"
        elif not any([template_row_has_intro_task(temp_row), template_row_has_price_task(temp_row), template_row_has_connection_task(temp_row), submit_audit]):
            validation_error = "没有任何修改目标"
        elif template_row_needs_sku_locator(temp_row) and not (package_id or package_name):
            validation_error = "价格/API 对接配置任务必须填写 packageId 或 packageName"
        elif target_cost_price:
            try:
                float(target_cost_price)
            except Exception:
                validation_error = f"target_cost_price 不是数字：{target_cost_price}"
        if not validation_error and template_row_has_intro_task(temp_row):
            validation_error = validate_placeholder_settings(usedup_throttle, reset_time_calc, inst_adv)

        temp_row.validation_error = validation_error
        rows.append(
            temp_row
        )
    return rows


class CdpWebSocket:
    def __init__(self, websocket_url: str, timeout: int = 60):
        self.websocket_url = websocket_url
        self.timeout = timeout
        self.sock: socket.socket | ssl.SSLSocket | None = None
        self.next_id = 0

    def __enter__(self) -> "CdpWebSocket":
        self.connect()
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        self.close()

    def connect(self) -> None:
        parsed = urllib.parse.urlparse(self.websocket_url)
        if parsed.scheme not in ("ws", "wss"):
            raise RuntimeError(f"不支持的 CDP WebSocket 地址：{self.websocket_url}")
        host = parsed.hostname or "localhost"
        port = parsed.port or (443 if parsed.scheme == "wss" else 80)
        path = parsed.path or "/"
        if parsed.query:
            path += "?" + parsed.query
        raw_sock = socket.create_connection((host, port), timeout=self.timeout)
        if parsed.scheme == "wss":
            self.sock = ssl.create_default_context().wrap_socket(raw_sock, server_hostname=host)
        else:
            self.sock = raw_sock
        self.sock.settimeout(self.timeout)
        key = base64.b64encode(os.urandom(16)).decode("ascii")
        request = (
            f"GET {path} HTTP/1.1\r\n"
            f"Host: {host}:{port}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n"
            "\r\n"
        ).encode("ascii")
        self.sock.sendall(request)
        response = self._read_http_response()
        if b" 101 " not in response.split(b"\r\n", 1)[0]:
            raise RuntimeError(f"CDP WebSocket 握手失败：{response[:200].decode('utf-8', errors='replace')}")
        accept = base64.b64encode(hashlib.sha1((key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode("ascii")).digest()).decode("ascii")
        headers: dict[str, str] = {}
        for line in response.decode("utf-8", errors="replace").split("\r\n")[1:]:
            if ":" in line:
                name, value = line.split(":", 1)
                headers[name.strip().lower()] = value.strip()
        if headers.get("sec-websocket-accept") != accept:
            raise RuntimeError("CDP WebSocket 握手校验失败")

    def _read_http_response(self) -> bytes:
        chunks: list[bytes] = []
        while True:
            chunk = self._recv_exact(1)
            chunks.append(chunk)
            data = b"".join(chunks)
            if b"\r\n\r\n" in data:
                return data

    def _recv_exact(self, size: int) -> bytes:
        if self.sock is None:
            raise RuntimeError("CDP WebSocket 未连接")
        data = b""
        while len(data) < size:
            chunk = self.sock.recv(size - len(data))
            if not chunk:
                raise RuntimeError("CDP WebSocket 已断开")
            data += chunk
        return data

    def _send_frame(self, payload: bytes, opcode: int = 1) -> None:
        if self.sock is None:
            raise RuntimeError("CDP WebSocket 未连接")
        header = bytearray([0x80 | opcode])
        length = len(payload)
        if length < 126:
            header.append(0x80 | length)
        elif length <= 0xFFFF:
            header.append(0x80 | 126)
            header.extend(struct.pack("!H", length))
        else:
            header.append(0x80 | 127)
            header.extend(struct.pack("!Q", length))
        mask = os.urandom(4)
        masked = bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))
        self.sock.sendall(bytes(header) + mask + masked)

    def _recv_frame(self) -> tuple[int, bytes]:
        first, second = self._recv_exact(2)
        opcode = first & 0x0F
        masked = bool(second & 0x80)
        length = second & 0x7F
        if length == 126:
            length = struct.unpack("!H", self._recv_exact(2))[0]
        elif length == 127:
            length = struct.unpack("!Q", self._recv_exact(8))[0]
        mask = self._recv_exact(4) if masked else b""
        payload = self._recv_exact(length) if length else b""
        if masked:
            payload = bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))
        return opcode, payload

    def send_command(self, method: str, params: dict[str, Any] | None = None) -> Any:
        self.next_id += 1
        command_id = self.next_id
        payload = json.dumps({"id": command_id, "method": method, "params": params or {}}, ensure_ascii=False).encode("utf-8")
        self._send_frame(payload)
        while True:
            opcode, frame_payload = self._recv_frame()
            if opcode == 8:
                raise RuntimeError("CDP WebSocket 被浏览器关闭")
            if opcode == 9:
                self._send_frame(frame_payload, opcode=10)
                continue
            if opcode not in (1, 2):
                continue
            message = json.loads(frame_payload.decode("utf-8"))
            if message.get("id") == command_id:
                if "error" in message:
                    raise RuntimeError(json.dumps(message["error"], ensure_ascii=False))
                return message.get("result")

    def close(self) -> None:
        if self.sock is None:
            return
        try:
            self._send_frame(b"", opcode=8)
        except Exception:
            pass
        try:
            self.sock.close()
        finally:
            self.sock = None


class CdpClient:
    def __init__(self, base_url: str = BROWSER_CDP_BASE):
        self.base_url = base_url.rstrip("/")

    def _browser_json(self, path: str, timeout: int = 30, method: str = "GET") -> Any:
        req = urllib.request.Request(self.base_url + path, method=method)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
        return json.loads(raw) if raw else None

    def targets(self) -> list[dict[str, Any]]:
        data = self._browser_json("/json/list", timeout=10)
        return data if isinstance(data, list) else []

    def _target(self, target_id: str) -> dict[str, Any]:
        for target in self.targets():
            if target.get("id") == target_id or target.get("targetId") == target_id:
                return target
        raise RuntimeError(f"找不到浏览器标签页：{target_id}")

    def open_product(self, product_id: str) -> str:
        return self.open_url(PRODUCT_URL.format(product_id=product_id))

    def open_blank_target(self) -> str:
        return self.open_url("about:blank")

    def open_url(self, url: str) -> str:
        encoded_url = urllib.parse.quote(url, safe="")
        try:
            data = self._browser_json(f"/json/new?{encoded_url}", timeout=90, method="PUT")
        except Exception:
            data = self._browser_json(f"/json/new?{encoded_url}", timeout=90)
        if isinstance(data, dict):
            target_id = data.get("id") or data.get("targetId")
            if target_id:
                return target_id
        raise RuntimeError(f"无法创建浏览器标签页：{data}")

    def close(self, target_id: str) -> None:
        try:
            self._browser_json(f"/json/close/{urllib.parse.quote(target_id)}", timeout=10)
        except Exception:
            pass

    def eval(self, target_id: str, script: str, timeout: int = 60) -> Any:
        target = self._target(target_id)
        websocket_url = target.get("webSocketDebuggerUrl")
        if not websocket_url:
            raise RuntimeError(f"浏览器标签页缺少 webSocketDebuggerUrl：{target_id}")
        with CdpWebSocket(websocket_url, timeout=timeout) as ws:
            result = ws.send_command(
                "Runtime.evaluate",
                {
                    "expression": script,
                    "awaitPromise": True,
                    "returnByValue": True,
                    "userGesture": True,
                },
            )
        if not isinstance(result, dict):
            return None
        if result.get("exceptionDetails"):
            details = result["exceptionDetails"]
            text = details.get("text") or details.get("exception", {}).get("description") or str(details)
            raise RuntimeError(text)
        remote = result.get("result") or {}
        if "value" in remote:
            return remote["value"]
        if "unserializableValue" in remote:
            return remote["unserializableValue"]
        return None

    def command(self, target_id: str, method: str, params: dict[str, Any] | None = None, timeout: int = 60) -> Any:
        target = self._target(target_id)
        websocket_url = target.get("webSocketDebuggerUrl")
        if not websocket_url:
            raise RuntimeError(f"浏览器标签页缺少 webSocketDebuggerUrl：{target_id}")
        with CdpWebSocket(websocket_url, timeout=timeout) as ws:
            return ws.send_command(method, params or {})

    def add_script_to_evaluate_on_new_document(self, target_id: str, script: str) -> None:
        self.command(
            target_id,
            "Page.addScriptToEvaluateOnNewDocument",
            {"source": script},
            timeout=20,
        )

    def navigate(self, target_id: str, url: str) -> None:
        self.command(target_id, "Page.navigate", {"url": url}, timeout=90)

    def get_cookies(self, target_id: str, urls: list[str]) -> list[dict[str, Any]]:
        self.command(target_id, "Network.enable", {}, timeout=20)
        data = self.command(target_id, "Network.getCookies", {"urls": urls}, timeout=20)
        cookies = data.get("cookies") if isinstance(data, dict) else None
        return cookies if isinstance(cookies, list) else []

    def close_browser(self) -> None:
        data = self._browser_json("/json/version", timeout=10)
        websocket_url = data.get("webSocketDebuggerUrl") if isinstance(data, dict) else ""
        if not websocket_url:
            raise RuntimeError("浏览器版本信息缺少 webSocketDebuggerUrl")
        try:
            with CdpWebSocket(websocket_url, timeout=10) as ws:
                ws.send_command("Browser.close", {})
        except RuntimeError as exc:
            text = str(exc)
            if "CDP WebSocket 被浏览器关闭" in text or "CDP WebSocket 已断开" in text:
                return
            raise


def browser_cdp_base_url(port: int) -> str:
    return f"http://127.0.0.1:{port}"


def is_browser_cdp_available(base_url: str = BROWSER_CDP_BASE) -> bool:
    try:
        with urllib.request.urlopen(f"{base_url.rstrip('/')}/json/version", timeout=2) as resp:
            return 200 <= resp.status < 300
    except Exception:
        return False


@dataclass(frozen=True)
class BrowserCdpLaunch:
    browser_name: str
    command: list[str]
    browser_key: str = ""
    port: int = 9222
    profile_dir: str = ""

    @property
    def base_url(self) -> str:
        return browser_cdp_base_url(self.port)


@dataclass
class BrowserCdpSession:
    started_by_tool: bool
    browser_name: str
    process: Any | None = None
    browser_key: str = ""
    port: int = 9222
    profile_dir: str = ""
    base_url: str = ""

    def __post_init__(self) -> None:
        if not self.base_url:
            self.base_url = browser_cdp_base_url(self.port)


def browser_executable_path(browser_key: str) -> str:
    current_os = platform.system()
    if current_os == "Windows":
        executable = "msedge.exe" if browser_key == "edge" else "chrome.exe"
        resolved = shutil.which(executable)
        if resolved:
            return resolved
        relative = Path("Microsoft/Edge/Application/msedge.exe") if browser_key == "edge" else Path("Google/Chrome/Application/chrome.exe")
        roots = [
            os.environ.get("PROGRAMFILES"),
            os.environ.get("PROGRAMFILES(X86)"),
            os.environ.get("LOCALAPPDATA"),
        ]
        for root in roots:
            candidate = Path(root) / relative if root else None
            if candidate and candidate.exists():
                return str(candidate)
        return ""
    commands = ("microsoft-edge",) if browser_key == "edge" else ("google-chrome", "chromium", "chromium-browser")
    return next((resolved for command in commands if (resolved := shutil.which(command))), "")


def browser_is_installed(browser_key: str) -> bool:
    if platform.system() == "Darwin":
        app_name = "Microsoft Edge.app" if browser_key == "edge" else "Google Chrome.app"
        return any((root / app_name).exists() for root in (Path("/Applications"), Path.home() / "Applications"))
    return bool(browser_executable_path(browser_key))


def allocate_browser_cdp_port(preferred_port: int, occupied_ports: set[int]) -> int:
    for port in [preferred_port, *range(9222, 9232)]:
        if port not in occupied_ports:
            occupied_ports.add(port)
            return port
    raise RuntimeError("没有可用的浏览器 CDP 端口（9222-9231）")


def browser_cdp_launches(
    url: str = "https://vbooking.ctrip.com/",
    occupied_ports: set[int] | None = None,
    excluded_browser_keys: set[str] | None = None,
) -> list[BrowserCdpLaunch]:
    occupied = set(occupied_ports or set())
    excluded = set(excluded_browser_keys or set())
    current_os = platform.system()
    installed = {browser_key: browser_is_installed(browser_key) for browser_key in ("edge", "chrome")}
    chrome_uses_legacy_profile = current_os == "Darwin" and installed["chrome"] and not installed["edge"]
    launches: list[BrowserCdpLaunch] = []
    for browser_key, browser_name, preferred_port in (
        ("edge", "Microsoft Edge", 9222),
        ("chrome", "Google Chrome", 9223),
    ):
        if browser_key in excluded or not installed[browser_key]:
            continue
        port = allocate_browser_cdp_port(preferred_port, occupied)
        profile_key = "edge" if browser_key == "edge" or chrome_uses_legacy_profile else "chrome"
        profile_dir = default_browser_cdp_user_data_dir(profile_key)
        profile_dir.mkdir(parents=True, exist_ok=True)
        common_args = [
            f"--remote-debugging-port={port}",
            f"--user-data-dir={profile_dir}",
            "--no-first-run",
            "--no-default-browser-check",
            url,
        ]
        if current_os == "Darwin":
            command = ["open", "-na", browser_name, "--args", *common_args]
        elif current_os == "Windows":
            executable = browser_executable_path(browser_key) or ("msedge.exe" if browser_key == "edge" else "chrome.exe")
            command = [executable, *common_args]
        else:
            executable = browser_executable_path(browser_key)
            command = [str(executable), *common_args]
        launches.append(
            BrowserCdpLaunch(
                browser_name,
                command,
                browser_key=browser_key,
                port=port,
                profile_dir=str(profile_dir),
            )
        )
    return launches


def launch_browser_with_cdp(launch: BrowserCdpLaunch) -> BrowserCdpSession:
    process = subprocess.Popen(launch.command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return BrowserCdpSession(
        started_by_tool=True,
        browser_name=launch.browser_name,
        process=process,
        browser_key=launch.browser_key,
        port=launch.port,
        profile_dir=launch.profile_dir,
        base_url=launch.base_url,
    )


def wait_for_browser_cdp_available(
    attempts: int = 20,
    wait_seconds: float = 0.5,
    base_url: str = BROWSER_CDP_BASE,
    stop_event: threading.Event | None = None,
) -> bool:
    for _index in range(max(1, attempts)):
        if stop_event is not None and stop_event.is_set():
            return False
        if is_browser_cdp_available(base_url):
            return True
        if wait_seconds > 0:
            if stop_event is not None:
                stop_event.wait(wait_seconds)
            else:
                time.sleep(wait_seconds)
    return is_browser_cdp_available(base_url)


def close_browser_cdp_session(session: BrowserCdpSession, cdp: CdpClient | None = None) -> None:
    if not session.started_by_tool:
        return
    try:
        (cdp or CdpClient(session.base_url)).close_browser()
        return
    except Exception:
        pass
    process = session.process
    if process is None:
        return
    try:
        if process.poll() is None:
            process.terminate()
    except Exception:
        pass


def browser_cdp_version(port: int) -> dict[str, Any] | None:
    try:
        with urllib.request.urlopen(f"{browser_cdp_base_url(port)}/json/version", timeout=0.2) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def browser_key_from_cdp_version(data: dict[str, Any]) -> str:
    identity = f"{data.get('Browser', '')} {data.get('User-Agent', '')}".lower()
    if "edg/" in identity or "microsoft edge" in identity:
        return "edge"
    if "chrome/" in identity or "chromium/" in identity:
        return "chrome"
    return ""


def discover_existing_browser_cdp_sessions(ports: range = range(9222, 9232)) -> list[BrowserCdpSession]:
    sessions: list[BrowserCdpSession] = []
    seen_keys: set[str] = set()
    for port in ports:
        version = browser_cdp_version(port)
        if not version:
            continue
        browser_key = browser_key_from_cdp_version(version)
        if browser_key not in {"edge", "chrome"} or browser_key in seen_keys:
            continue
        seen_keys.add(browser_key)
        browser_name = "Microsoft Edge" if browser_key == "edge" else "Google Chrome"
        sessions.append(
            BrowserCdpSession(
                started_by_tool=False,
                browser_name=browser_name,
                browser_key=browser_key,
                port=port,
                base_url=browser_cdp_base_url(port),
            )
        )
    return sessions


def tcp_port_is_available(port: int) -> bool:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("127.0.0.1", port))
        return True
    except OSError:
        return False


def browser_cookie_candidates(url: str = "https://vbooking.ctrip.com/") -> list[BrowserCdpSession | BrowserCdpLaunch]:
    existing = discover_existing_browser_cdp_sessions()
    occupied_ports = {port for port in range(9222, 9232) if not tcp_port_is_available(port)}
    represented = {session.browser_key for session in existing if session.browser_key in {"edge", "chrome"}}
    launches = browser_cdp_launches(
        url,
        occupied_ports=occupied_ports,
        excluded_browser_keys=represented,
    )
    return [*existing, *launches]


class CtripDraftClient:
    def __init__(self, cdp: CdpClient, log: Callable[[str], None]):
        self.cdp = cdp
        self.log = log

    def product_mix_request_capture_script(self) -> str:
        """Capture only an organically issued ProductMix request in this page."""
        return r"""
(() => {
  if (window.__ctripProductMixRequestCapture && window.__ctripProductMixRequestCapture.installed) {
    return {installed: true, reused: true};
  }
  const target = 'https://m.ctrip.com/restapi/soa2/16359/json/getProductMix';
  const capture = {installed: true, requests: []};
  const parseBody = (body) => {
    if (body == null) return {bodyText: '', bodyJson: null};
    const bodyText = typeof body === 'string' ? body : String(body);
    try {
      return {bodyText, bodyJson: JSON.parse(bodyText)};
    } catch (_error) {
      return {bodyText, bodyJson: null};
    }
  };
  const remember = (url, method, body) => {
    if (!String(url || '').includes(target)) return;
    capture.requests.push({source: 'frontend', url: String(url), method: method || 'GET', ...parseBody(body)});
    if (capture.requests.length > 20) capture.requests.shift();
  };
  const originalFetch = window.fetch;
  window.fetch = function(input, init = {}) {
    const url = typeof input === 'string' || input instanceof URL ? String(input) : String(input && input.url || '');
    const method = init.method || (input && input.method) || 'GET';
    const body = init.body === undefined && input ? input.body : init.body;
    remember(url, method, body);
    return originalFetch.apply(this, arguments);
  };
  const originalOpen = XMLHttpRequest.prototype.open;
  const originalSend = XMLHttpRequest.prototype.send;
  XMLHttpRequest.prototype.open = function(method, url) {
    this.__ctripProductMixRequestCapture = {method: method || 'GET', url: String(url || '')};
    return originalOpen.apply(this, arguments);
  };
  XMLHttpRequest.prototype.send = function(body) {
    const request = this.__ctripProductMixRequestCapture;
    if (request) remember(request.url, request.method, body);
    return originalSend.apply(this, arguments);
  };
  window.__ctripProductMixRequestCapture = capture;
  return {installed: true, reused: false};
})()
"""

    def get_captured_product_mix_request(self, target_id: str) -> dict[str, Any] | None:
        script = r"""
(() => {
  const capture = window.__ctripProductMixRequestCapture;
  const records = capture && Array.isArray(capture.requests) ? capture.requests : [];
  return records.length ? records[records.length - 1] : null;
})()
"""
        data = self.cdp.eval(target_id, script, timeout=20)
        return data if isinstance(data, dict) else None

    def fetch_captured_product_mix(self, target_id: str) -> dict[str, Any]:
        """Replay only the request that the current page already issued."""
        script = r"""
(async () => {
  const capture = window.__ctripProductMixRequestCapture;
  const records = capture && Array.isArray(capture.requests) ? capture.requests : [];
  const request = records.length ? records[records.length - 1] : null;
  if (!request || !request.bodyText) throw new Error('missing captured ProductMix request');
  const response = await fetch(request.url, {
    method: request.method || 'POST', credentials: 'include',
    headers: {'content-type': 'application/json'}, body: request.bodyText,
  });
  return await response.json();
})()
"""
        data = self.cdp.eval(target_id, script, timeout=60)
        if not isinstance(data, dict):
            raise RuntimeError("ProductMix 读取返回非 JSON 对象")
        return data

    def fetch_product_draft_group(
        self,
        target_id: str,
        product_id: str,
        draft_types: list[str],
        source: str,
    ) -> dict[str, Any]:
        product_id_json = json.dumps(str(product_id), ensure_ascii=False)
        draft_types_json = json.dumps(draft_types, ensure_ascii=False)
        source_json = json.dumps(source, ensure_ascii=False)
        script = f"""
(async () => {{
  const productId = {product_id_json};
  const numericProductId = /^\\d+$/.test(productId) ? Number(productId) : productId;
  const draftTypes = {draft_types_json};
  const source = {source_json};
  const resp = await fetch('https://m.ctrip.com/restapi/soa2/16359/json/getProductDraft', {{
    method: 'POST',
    credentials: 'include',
    headers: {{'content-type': 'application/json'}},
    body: JSON.stringify({{productId: numericProductId, draftTypes, source}})
  }});
  return await resp.json();
}})()
"""
        data = self.cdp.eval(target_id, script, timeout=60)
        if not isinstance(data, dict):
            raise RuntimeError("草稿读取返回非 JSON 对象")
        return data

    def load_full_field_catalog(self, product_id: str, stop_event: threading.Event) -> dict[str, dict[str, Any]]:
        """Read the verified full-field groups without issuing any write request."""
        groups = (
            ("ProductBasicInfo", ["ProductInfo", "ReserveMode", "ApplicablePeople", "PackageInfo", "BookingRule", "AdvancedSettings"]),
            ("PriceStock", ["PriceAndStock", "NegativeGrossProfit", "LowBrokerageRate"]),
        )
        result: dict[str, dict[str, Any]] = {
            source: {"raw": None, "error": None}
            for source, _draft_types in groups
        }
        result["ProductMix"] = {"raw": None, "error": None}
        target_id = self.cdp.open_blank_target()
        try:
            try:
                self.cdp.add_script_to_evaluate_on_new_document(target_id, self.product_mix_request_capture_script())
            except Exception:
                result["ProductMix"]["error"] = "前端请求捕获安装失败"
            self.cdp.navigate(target_id, PRODUCT_URL.format(product_id=product_id))
            self.wait_for_product_page(target_id, stop_event)
            for source, draft_types in groups:
                try:
                    result[source]["raw"] = self.fetch_product_draft_group(target_id, product_id, draft_types, source)
                except Exception:
                    result[source]["error"] = "草稿读取失败"
            if result["ProductMix"]["error"] is None:
                try:
                    captured = self.get_captured_product_mix_request(target_id)
                    if captured is None:
                        result["ProductMix"]["error"] = "未捕获到前端 ProductMix 请求"
                    else:
                        result["ProductMix"]["raw"] = self.fetch_captured_product_mix(target_id)
                except Exception:
                    result["ProductMix"]["error"] = "前端 ProductMix 请求读取失败"
            return result
        finally:
            self.cdp.close(target_id)

    def install_request_capture(self, target_id: str) -> None:
        script = r"""
(() => {
  if (window.__ctripPackageRequestCapture && window.__ctripPackageRequestCapture.installed) {
    return {installed: true, reused: true, count: window.__ctripPackageRequestCapture.requests.length};
  }
  const targetUrls = [
    'https://m.ctrip.com/restapi/soa2/16359/json/getProductDraft',
    'https://m.ctrip.com/restapi/soa2/16359/json/saveOrEffectProductDraft'
  ];
  const capture = {
    installed: true,
    installedAt: new Date().toISOString(),
    requests: []
  };
  const shouldCapture = (url) => targetUrls.some((target) => String(url || '').includes(target));
  const normalizeHeaders = (headers) => {
    const result = {};
    try {
      if (!headers) return result;
      if (headers instanceof Headers) {
        headers.forEach((value, key) => result[key] = value);
        return result;
      }
      if (Array.isArray(headers)) {
        for (const [key, value] of headers) result[String(key)] = String(value);
        return result;
      }
      if (typeof headers === 'object') {
        for (const [key, value] of Object.entries(headers)) result[String(key)] = String(value);
      }
    } catch (error) {
      result.__captureError = String(error && error.message || error);
    }
    return result;
  };
  const parseBody = (body) => {
    if (body == null) return {bodyText: '', bodyJson: null};
    const bodyText = typeof body === 'string' ? body : String(body);
    try {
      return {bodyText, bodyJson: JSON.parse(bodyText)};
    } catch (_error) {
      return {bodyText, bodyJson: null};
    }
  };
  const pushRecord = (record) => {
    capture.requests.push({...record, capturedAt: new Date().toISOString()});
    if (capture.requests.length > 100) capture.requests.shift();
  };
  const originalFetch = window.fetch;
  window.fetch = async function(input, init = {}) {
    let url = '';
    let method = 'GET';
    let headers = {};
    let bodyInfo = {bodyText: '', bodyJson: null};
    let credentials = 'same-origin';
    try {
      if (typeof input === 'string' || input instanceof URL) {
        url = String(input);
      } else if (input && input.url) {
        url = input.url;
        method = input.method || method;
        headers = normalizeHeaders(input.headers);
        credentials = input.credentials || credentials;
      }
      method = init.method || method;
      headers = {...headers, ...normalizeHeaders(init.headers)};
      credentials = init.credentials || credentials;
      bodyInfo = parseBody(init.body);
      if (shouldCapture(url)) {
        pushRecord({source: 'fetch', phase: 'before', url, method, headers, credentials, ...bodyInfo});
      }
    } catch (error) {
      pushRecord({source: 'fetch', phase: 'capture-error', url, method, error: String(error && error.message || error)});
    }
    const response = await originalFetch.apply(this, arguments);
    try {
      if (shouldCapture(url)) {
        pushRecord({source: 'fetch', phase: 'after', url, method, status: response.status, ok: response.ok});
      }
    } catch (_error) {}
    return response;
  };
  const originalOpen = XMLHttpRequest.prototype.open;
  const originalSetRequestHeader = XMLHttpRequest.prototype.setRequestHeader;
  const originalSend = XMLHttpRequest.prototype.send;
  XMLHttpRequest.prototype.open = function(method, url) {
    this.__ctripCapture = {source: 'xhr', method: method || 'GET', url: String(url || ''), headers: {}};
    return originalOpen.apply(this, arguments);
  };
  XMLHttpRequest.prototype.setRequestHeader = function(name, value) {
    if (this.__ctripCapture) this.__ctripCapture.headers[String(name)] = String(value);
    return originalSetRequestHeader.apply(this, arguments);
  };
  XMLHttpRequest.prototype.send = function(body) {
    try {
      const record = this.__ctripCapture || {source: 'xhr', method: 'GET', url: '', headers: {}};
      if (shouldCapture(record.url)) {
        pushRecord({...record, phase: 'before', credentials: 'browser-managed', ...parseBody(body)});
      }
    } catch (error) {
      pushRecord({source: 'xhr', phase: 'capture-error', error: String(error && error.message || error)});
    }
    return originalSend.apply(this, arguments);
  };
  window.__ctripPackageRequestCapture = capture;
  return {installed: true, reused: false, count: 0};
})()
"""
        self.cdp.eval(target_id, script, timeout=20)

    def wait_for_product_page(self, target_id: str, stop_event: threading.Event, timeout: int = 60) -> None:
        script = r"""
(() => ({
  href: location.href,
  readyState: document.readyState,
  title: document.title,
  body: (document.body && document.body.innerText || '').slice(0, 300)
}))()
"""
        deadline = time.time() + timeout
        last: Any = None
        while time.time() < deadline:
            if stop_event.is_set():
                raise RuntimeError("用户已停止")
            last = self.cdp.eval(target_id, script, timeout=10)
            href = str((last or {}).get("href") or "")
            ready_state = str((last or {}).get("readyState") or "")
            if "vbooking.ctrip.com/activity-vbk/product-edit" in href and ready_state in {"interactive", "complete"}:
                return
            time.sleep(0.5)
        body = (last or {}).get("body", "")
        raise RuntimeError(f"等待产品页加载超时。页面内容摘要：{body}")

    def get_captured_requests(self, target_id: str) -> list[dict[str, Any]]:
        script = r"""
(() => {
  const capture = window.__ctripPackageRequestCapture;
  if (!capture || !Array.isArray(capture.requests)) return [];
  return capture.requests;
})()
"""
        data = self.cdp.eval(target_id, script, timeout=20)
        return data if isinstance(data, list) else []

    def trigger_get_draft_capture(self, target_id: str, product_id: str) -> None:
        product_id_json = json.dumps(str(product_id), ensure_ascii=False)
        script = f"""
(async () => {{
  const productId = {product_id_json};
  const numericProductId = /^\\d+$/.test(productId) ? Number(productId) : productId;
  const resp = await fetch('https://m.ctrip.com/restapi/soa2/16359/json/getProductDraft', {{
    method: 'POST',
    credentials: 'include',
    headers: {{'content-type': 'application/json'}},
    body: JSON.stringify({{productId: numericProductId, draftTypes: ['PackageInfo'], source: 'PriceStock'}})
  }});
  return {{status: resp.status, ok: resp.ok}};
}})()
"""
        self.cdp.eval(target_id, script, timeout=30)

    def capture_request_template(self, product_id: str, stop_event: threading.Event, wait_seconds: int = 300) -> CapturedRequestTemplate:
        target_id = self.cdp.open_product(product_id)
        self.log(f"已打开产品 {product_id}，安装接口捕获监听...")
        try:
            self.wait_for_product_page(target_id, stop_event)
            self.install_request_capture(target_id)
            self.trigger_get_draft_capture(target_id, product_id)
            self.log("已捕获 getProductDraft。请在打开的产品页中进入【套餐内容】，把条目数调到 100，打开任意【编辑套餐信息】，核对【套餐说明】后手动点击保存。")
            self.log("工具只监听请求，不会自动点击保存；捕获到 saveOrEffectProductDraft 后会保存请求模板。")
            deadline = time.time() + wait_seconds
            last_get: dict[str, Any] | None = None
            last_save: dict[str, Any] | None = None
            while time.time() < deadline:
                if stop_event.is_set():
                    raise RuntimeError("用户已停止")
                requests = self.get_captured_requests(target_id)
                before_records = [item for item in requests if item.get("phase") == "before"]
                for item in before_records:
                    url = str(item.get("url") or "")
                    if "getProductDraft" in url:
                        last_get = item
                    elif "saveOrEffectProductDraft" in url:
                        last_save = item
                if last_save:
                    return CapturedRequestTemplate(product_id=product_id, captured_at=now_iso(), get_request=last_get, save_request=last_save)
                time.sleep(1)
            raise RuntimeError("等待保存请求超时：未捕获到 saveOrEffectProductDraft。请确认已在页面弹窗中点击保存。")
        finally:
            self.cdp.close(target_id)

    def load_product(self, product_id: str, stop_event: threading.Event) -> ProductDraft:
        target_id = self.cdp.open_product(product_id)
        self.log(f"已打开产品 {product_id}，等待草稿数据加载...")
        try:
            draft = self._wait_for_draft(target_id, product_id, stop_event)
            package_info = draft.get("productPackageInfo") or {}
            resources = package_info.get("packageResourceInfo") or []
            if not isinstance(resources, list) or not resources:
                raise RuntimeError("未读取到 productPackageInfo.packageResourceInfo，可能未登录或页面未加载完成")
            return ProductDraft(
                product_id=product_id,
                target_id=target_id,
                package_info=package_info,
                package_resources=resources,
                product_version=draft.get("productVersion"),
                draft_raw=draft,
            )
        except Exception:
            self.cdp.close(target_id)
            raise

    def _wait_for_draft(self, target_id: str, product_id: str, stop_event: threading.Event) -> dict[str, Any]:
        product_id_json = json.dumps(str(product_id), ensure_ascii=False)
        script = f"""
(async () => {{
  const productId = {product_id_json};
  const numericProductId = /^\\d+$/.test(productId) ? Number(productId) : productId;
  const pickDraft = (data) => {{
    if (!data || typeof data !== 'object') return null;
    if (data.productPackageInfo) return data;
    for (const key of ['data', 'result', 'productDraft', 'draft']) {{
      const value = data[key];
      if (value && typeof value === 'object' && value.productPackageInfo) return value;
    }}
    return null;
  }};
  const state = window.g_app && window.g_app._store && window.g_app._store.getState && window.g_app._store.getState();
  const draft = state && state.draft;
  const stateResources = draft && draft.productPackageInfo && draft.productPackageInfo.packageResourceInfo;
  if (Array.isArray(stateResources) && stateResources.length > 0) {{
    return {{
      ready: true,
      via: 'state',
      productId: draft.productId || (draft.productBasicInfo && draft.productBasicInfo.productId),
      draft,
      title: document.title,
      body:(document.body && document.body.innerText || '').slice(0,500)
    }};
  }}
  try {{
    const resp = await fetch('https://m.ctrip.com/restapi/soa2/16359/json/getProductDraft', {{
      method: 'POST',
      credentials: 'include',
      headers: {{'content-type': 'application/json'}},
      body: JSON.stringify({{productId: numericProductId, draftTypes: ['PackageInfo'], source: 'PriceStock'}})
    }});
    const data = await resp.json();
    const apiDraft = pickDraft(data);
    const apiResources = apiDraft && apiDraft.productPackageInfo && apiDraft.productPackageInfo.packageResourceInfo;
    return {{
      ready: Array.isArray(apiResources) && apiResources.length > 0,
      via: 'getProductDraft',
      productId: apiDraft && (apiDraft.productId || (apiDraft.productBasicInfo && apiDraft.productBasicInfo.productId)),
      draft: apiDraft,
      status: resp.status,
      title: document.title,
      body:(document.body && document.body.innerText || '').slice(0,500)
    }};
  }} catch (error) {{
    return {{
      ready:false,
      via:'getProductDraft',
      reason:String(error && error.message || error),
      title:document.title,
      body:(document.body && document.body.innerText || '').slice(0,500)
    }};
  }}
}})()
"""
        deadline = time.time() + 90
        last: Any = None
        while time.time() < deadline:
            if stop_event.is_set():
                raise RuntimeError("用户已停止")
            last = self.cdp.eval(target_id, script, timeout=20)
            if last and last.get("ready"):
                page_product_id = str(last.get("productId") or "")
                if page_product_id and page_product_id != str(product_id):
                    raise RuntimeError(f"页面产品 ID 不一致：期望 {product_id}，实际 {page_product_id}")
                return last["draft"]
            time.sleep(1)
        body = (last or {}).get("body", "")
        raise RuntimeError(f"等待草稿数据超时。页面内容摘要：{body}")

    def load_product_currency_context(
        self,
        target_id: str,
        product_id: str,
        stop_event: threading.Event,
    ) -> CurrencyRewriteContext:
        if stop_event.is_set():
            raise RuntimeError("用户已停止")
        product_id_json = json.dumps(str(product_id), ensure_ascii=False)
        script = f"""
(async () => {{
  const productId = {product_id_json};
  const numericProductId = /^\\d+$/.test(productId) ? Number(productId) : productId;
  const resp = await fetch('https://m.ctrip.com/restapi/soa2/16359/json/getProductDraft', {{
    method: 'POST',
    credentials: 'include',
    headers: {{'content-type': 'application/json'}},
    body: JSON.stringify({{productId: numericProductId, draftTypes: ['PriceAndStock'], source: 'PriceStock'}})
  }});
  return await resp.json();
}})()
"""
        data = self.cdp.eval(target_id, script, timeout=60)
        if not isinstance(data, dict):
            raise RuntimeError("getProductDraft PriceAndStock 返回非 JSON 对象")
        response_base = data.get("responseBaseData")
        if isinstance(response_base, dict) and response_base.get("success") is False:
            raise RuntimeError(response_base.get("message") or "getProductDraft PriceAndStock 返回失败")
        return build_currency_rewrite_context(product_id, data)

    def save_package_info(
        self,
        draft: ProductDraft,
        package_info: dict[str, Any],
        stop_event: threading.Event,
        currency_context: CurrencyRewriteContext | None = None,
    ) -> dict[str, Any]:
        if stop_event.is_set():
            raise RuntimeError("用户已停止")
        request_template = load_request_template(draft.product_id)
        payload = build_save_payload(draft.product_id, package_info, request_template, product_version=draft.product_version)
        context = currency_context or self.load_product_currency_context(draft.target_id, draft.product_id, stop_event)
        payload, rewrite_count = apply_product_edit_currency_rewrite(payload, context)
        if rewrite_count:
            self.log(f"产品 {draft.product_id} CDP 传出前已将人民币/CNY/RMB 币种字段改为 HKD：{rewrite_count} 处")
        assert_product_payload_target(payload, ProductRequestTarget(target_product_id(draft.product_id)), "cdp_save_package_info")
        request_meta = build_save_request_meta(request_template)
        payload_json = json.dumps(payload, ensure_ascii=False)
        request_meta_json = json.dumps(request_meta, ensure_ascii=False)
        script = f"""
(async () => {{
  const payload = {payload_json};
  const requestMeta = {request_meta_json};
  const resp = await fetch(requestMeta.url, {{
    method: requestMeta.method || 'POST',
    credentials: requestMeta.credentials || 'include',
    headers: requestMeta.headers || {{'content-type': 'application/json'}},
    body: JSON.stringify(payload)
  }});
  const text = await resp.text();
  try {{
    return JSON.parse(text);
  }} catch (error) {{
    return {{status: resp.status, rawText: text}};
  }}
}})()
"""
        return self.cdp.eval(draft.target_id, script, timeout=120) or {}

    def verify_product(self, target_id: str, product_id: str, expected: dict[int, str], stop_event: threading.Event) -> dict[int, bool]:
        draft = self._wait_for_draft(target_id, product_id, stop_event)
        resources = ((draft.get("productPackageInfo") or {}).get("packageResourceInfo")) or []
        return {
            index: index < len(resources) and str(resources[index].get("introduction") or "") == intro
            for index, intro in expected.items()
        }


def try_json(text: str) -> Any:
    try:
        return json.loads(text)
    except Exception:
        return None


def pick_draft(data: Any) -> dict[str, Any] | None:
    if not isinstance(data, dict):
        return None
    if isinstance(data.get("productPackageInfo"), dict):
        return data
    for key in ("data", "result", "productDraft", "draft"):
        value = data.get(key)
        if isinstance(value, dict) and isinstance(value.get("productPackageInfo"), dict):
            return value
    return None


def read_plain_cookie(
    cookie_path: Path = PLAIN_COOKIE_FILE,
) -> str:
    if cookie_path.exists():
        return cookie_path.read_text(encoding="utf-8").strip()
    return ""


def cookie_header_from_cdp_cookies(cookies: list[dict[str, Any]]) -> str:
    entries: list[tuple[str, str, str, str]] = []
    for cookie in cookies:
        if not isinstance(cookie, dict):
            continue
        name = str(cookie.get("name") or "").strip()
        value = cookie.get("value")
        domain = str(cookie.get("domain") or "").lower()
        path = str(cookie.get("path") or "/")
        if not name or value is None or "ctrip.com" not in domain:
            continue
        entries.append((name, domain, path, str(value)))
    entries.sort(key=lambda item: (item[0], item[1], item[2], item[3]))
    return "; ".join(f"{name}={value}" for name, _domain, _path, value in entries)


def has_ctrip_login_cookie(cookie_header: str) -> bool:
    for part in str(cookie_header or "").split(";"):
        name, separator, _value = part.partition("=")
        if separator and name.strip().lower() in CTRIP_LOGIN_COOKIE_NAMES:
            return True
    return False


def persist_plain_auth(
    cookie_header: str,
    source: str,
    loaded_cookie_count: int,
    cookie_path: Path = PLAIN_COOKIE_FILE,
    auth_json_path: Path = PLAIN_AUTH_JSON,
    extra: dict[str, Any] | None = None,
) -> Path:
    cookie_header = str(cookie_header or "").strip()
    if not cookie_header:
        raise RuntimeError("登录态 Cookie 为空")
    cookie_path.parent.mkdir(parents=True, exist_ok=True)
    cookie_path.write_text(cookie_header, encoding="utf-8")
    meta: dict[str, Any] = {
        "createdAt": now_iso(),
        "source": source,
        "loadedTripDetailCookies": loaded_cookie_count,
    }
    if extra:
        meta.update(extra)
    auth_json_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return cookie_path


def refresh_plain_auth_with_validation(
    cookie_header: str,
    source: str,
    loaded_cookie_count: int,
    validator: Callable[[str], None] | None,
    cookie_path: Path = PLAIN_COOKIE_FILE,
    auth_json_path: Path = PLAIN_AUTH_JSON,
    extra: dict[str, Any] | None = None,
) -> tuple[Path, int, str]:
    cookie_header = str(cookie_header or "").strip()
    if not cookie_header:
        raise RuntimeError("登录态 Cookie 为空")
    if validator is not None:
        validator(cookie_header)
    path = persist_plain_auth(cookie_header, source, loaded_cookie_count, cookie_path, auth_json_path, extra=extra)
    return path, loaded_cookie_count, source


def build_default_headers(product_id: str) -> dict[str, str]:
    return {
        "accept": "application/json, text/plain, */*",
        "content-type": "application/json",
        "origin": "https://vbooking.ctrip.com",
        "referer": PRODUCT_URL.format(product_id=product_id),
        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36",
    }


def request_json_with_cookie(url: str, product_id: str, body: dict[str, Any], cookie_header: str, timeout: int = 90) -> dict[str, Any]:
    session = requests.Session()
    headers = build_default_headers(product_id)
    headers["cookie"] = cookie_header
    request = requests.Request("POST", url, headers=headers, json=body)
    prepared = session.prepare_request(request)
    GLOBAL_REQUEST_LIMITER.wait(threading.Event())
    response = session.send(prepared, timeout=timeout)
    text = response.text
    data = try_json(text)
    if not response.ok:
        if isinstance(data, dict):
            raise RuntimeError(f"接口请求失败：HTTP {response.status_code}，{format_response_error(data, text[:1000])}")
        raise RuntimeError(f"接口请求失败：HTTP {response.status_code}，{text[:1000]}")
    if not isinstance(data, dict):
        raise RuntimeError(f"接口返回非 JSON：{text[:300]}")
    return data


def validate_plain_auth_cookie(cookie_header: str, product_id: str, area: str = "product") -> None:
    product_id = str(product_id or "").strip()
    if not product_id:
        return
    if area == "translation":
        body = {
            "productId": product_id,
            "requestBaseData": translation_request_base_data(),
        }
        data = request_json_with_cookie(TRANSLATION_AVAILABLE_LOCALES_URL, product_id, body, cookie_header)
        if not response_success(data):
            raise RuntimeError(f"登录态校验失败：{format_response_error(data)}")
        return
    body = {
        "productId": int(product_id) if product_id.isdigit() else product_id,
        "draftTypes": ["PackageInfo"],
        "source": "PriceStock",
    }
    data = request_json_with_cookie(GET_PRODUCT_DRAFT_URL, product_id, body, cookie_header)
    if not response_success(data):
        raise RuntimeError(f"登录态校验失败：{format_response_error(data)}")


@dataclass(frozen=True)
class AuthCheckResult:
    status: str
    message: str = ""
    cookie_digest: str = ""


def cookie_digest(cookie_header: str) -> str:
    value = str(cookie_header or "").strip()
    return hashlib.sha256(value.encode("utf-8")).hexdigest() if value else ""


def check_saved_plain_auth(
    cookie_path: Path = PLAIN_COOKIE_FILE,
    product_id: str = "",
    validator: Callable[[str, str, str], None] | None = None,
) -> AuthCheckResult:
    try:
        cookie_header = read_plain_cookie(cookie_path)
    except Exception as exc:
        return AuthCheckResult(status="error", message=str(exc))
    if not cookie_header:
        return AuthCheckResult(status="missing")
    digest = cookie_digest(cookie_header)
    if not has_ctrip_login_cookie(cookie_header):
        return AuthCheckResult(status="invalid", message="未检测到携程后台登录 Cookie", cookie_digest=digest)
    product_id = str(product_id or "").strip()
    if not product_id:
        return AuthCheckResult(status="valid", cookie_digest=digest)
    try:
        (validator or validate_plain_auth_cookie)(cookie_header, product_id, "product")
    except Exception as exc:
        message = str(exc)
        status = "invalid" if "LOGIN_ERROR" in message.upper() else "error"
        return AuthCheckResult(status=status, message=message, cookie_digest=digest)
    return AuthCheckResult(status="valid", cookie_digest=digest)


@dataclass(frozen=True)
class BrowserCookieResult:
    cookie_header: str
    cookie_count: int
    browser_key: str
    browser_name: str
    port: int
    profile_dir: str
    session: BrowserCdpSession | None = field(default=None, repr=False, compare=False)


def poll_browser_cookie(
    cdp: CdpClient,
    session: BrowserCdpSession,
    stop_event: threading.Event,
    wait_seconds: float,
    poll_seconds: float,
) -> BrowserCookieResult:
    target_id = ""
    succeeded = False
    try:
        target_id = cdp.open_url("https://vbooking.ctrip.com/")
        deadline = time.monotonic() + max(0.0, wait_seconds)
        last_cookie_count = 0
        while True:
            if stop_event.is_set():
                raise RuntimeError("已取消")
            cookies = cdp.get_cookies(target_id, ["https://vbooking.ctrip.com/", "https://m.ctrip.com/"])
            last_cookie_count = len(cookies)
            cookie_header = cookie_header_from_cdp_cookies(cookies)
            if has_ctrip_login_cookie(cookie_header):
                browser_name = "Edge" if session.browser_key == "edge" else "Chrome" if session.browser_key == "chrome" else session.browser_name
                result = BrowserCookieResult(
                    cookie_header,
                    len(cookies),
                    session.browser_key,
                    browser_name,
                    session.port,
                    session.profile_dir,
                    session=session,
                )
                succeeded = True
                return result
            if time.monotonic() >= deadline:
                break
            if poll_seconds > 0:
                stop_event.wait(min(poll_seconds, max(0.0, deadline - time.monotonic())))
            else:
                break
        raise RuntimeError(
            "未检测到携程后台登录 Cookie；"
            f"已读取原始 cookie 数={last_cookie_count}"
        )
    finally:
        if target_id:
            cdp.close(target_id)
        if not succeeded:
            close_browser_cdp_session(session, cdp)


def read_browser_cookie_candidate(
    candidate: BrowserCdpSession | BrowserCdpLaunch,
    stop_event: threading.Event,
    wait_seconds: float,
    poll_seconds: float,
) -> BrowserCookieResult:
    if isinstance(candidate, BrowserCdpLaunch):
        session = launch_browser_with_cdp(candidate)
        if not wait_for_browser_cdp_available(
            attempts=60,
            wait_seconds=0.5,
            base_url=session.base_url,
            stop_event=stop_event,
        ):
            close_browser_cdp_session(session)
            if stop_event.is_set():
                raise RuntimeError("已取消")
            raise RuntimeError(f"无法连接 {session.base_url}/json/version")
    else:
        session = candidate
    return poll_browser_cookie(
        CdpClient(session.base_url),
        session,
        stop_event,
        wait_seconds,
        poll_seconds,
    )


def read_browser_cookie_candidates(
    candidates: list[BrowserCdpSession | BrowserCdpLaunch],
    reader: Callable[[BrowserCdpSession | BrowserCdpLaunch, threading.Event, float, float], BrowserCookieResult] | None = None,
    wait_seconds: float = 180,
    poll_seconds: float = 2,
) -> BrowserCookieResult:
    if not candidates:
        raise RuntimeError("未找到已安装或已启用远程调试的 Edge/Chrome")
    candidate_reader = reader or read_browser_cookie_candidate
    stop_event = threading.Event()
    errors: dict[int, str] = {}
    winner: BrowserCookieResult | None = None
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(candidates)) as executor:
        future_map = {
            executor.submit(candidate_reader, candidate, stop_event, wait_seconds, poll_seconds): index
            for index, candidate in enumerate(candidates)
        }
        for future in concurrent.futures.as_completed(future_map):
            index = future_map[future]
            try:
                result = future.result()
            except Exception as exc:
                errors[index] = str(exc)
                continue
            if winner is None:
                winner = result
                stop_event.set()
            elif result.session is not None:
                close_browser_cdp_session(result.session)
    if winner is not None:
        return winner
    detail = "；".join(
        f"{candidate.browser_name}：{errors.get(index, '未能读取登录态')}"
        for index, candidate in enumerate(candidates)
    )
    raise RuntimeError(detail)


def extract_browser_cookie_result(
    cdp: CdpClient | None = None,
    wait_seconds: float = 180,
    poll_seconds: float = 2,
) -> BrowserCookieResult:
    if cdp is not None:
        session = BrowserCdpSession(
            started_by_tool=False,
            browser_name="provided",
            browser_key="provided",
            port=0,
            base_url=getattr(cdp, "base_url", BROWSER_CDP_BASE),
        )
        return poll_browser_cookie(cdp, session, threading.Event(), wait_seconds, poll_seconds)
    return read_browser_cookie_candidates(
        browser_cookie_candidates(),
        wait_seconds=wait_seconds,
        poll_seconds=poll_seconds,
    )


def extract_browser_cookie_header(
    cdp: CdpClient | None = None,
    wait_seconds: float = 180,
    poll_seconds: float = 2,
) -> tuple[str, int]:
    result = extract_browser_cookie_result(cdp, wait_seconds, poll_seconds)
    return result.cookie_header, result.cookie_count


def refresh_plain_auth(
    validation_product_id: str = "",
    area: str = "product",
    cdp: CdpClient | None = None,
    cookie_path: Path = PLAIN_COOKIE_FILE,
    auth_json_path: Path = PLAIN_AUTH_JSON,
) -> tuple[Path, int, str]:
    validation_product_id = str(validation_product_id or "").strip()

    validator: Callable[[str], None] | None = None
    if validation_product_id:
        validator = lambda cookie_header: validate_plain_auth_cookie(cookie_header, validation_product_id, area)

    try:
        browser_result = extract_browser_cookie_result(cdp)
        return refresh_plain_auth_with_validation(
            browser_result.cookie_header,
            browser_result.browser_name,
            browser_result.cookie_count,
            validator,
            cookie_path,
            auth_json_path,
            extra={
                "validationProductId": validation_product_id,
                "validationArea": area,
                "browser": browser_result.browser_key,
                "browserName": browser_result.browser_name,
                "cdpPort": browser_result.port,
                "profileDir": browser_result.profile_dir,
            },
        )
    except Exception as exc:
        raise RuntimeError(f"刷新登录态失败：{exc}") from exc


class CtripRequestsClient:
    def __init__(
        self,
        log: Callable[[str], None],
        request_interval_seconds: float = CTRIP_REQUEST_INTERVAL_SECONDS,
        request_interval_provider: Callable[[], float] | None = None,
        stats_area: str = "",
        stats_recorder: Callable[[str], None] | None = None,
    ):
        self.log = log
        self.request_interval_seconds = max(0.0, float(request_interval_seconds))
        self.request_interval_provider = request_interval_provider
        self.stats_area = stats_area
        self.stats_recorder = stats_recorder
        self.session = requests.Session()
        self.last_request_at = 0.0
        self.product_price_stock_cache: dict[str, dict[str, dict[str, Any]]] = {}
        self.product_price_stock_draft_cache: dict[str, dict[str, Any]] = {}
        self.product_currency_context_cache: dict[str, CurrencyRewriteContext] = {}
        self.cookie_header = read_plain_cookie()
        self.loaded_trip_cookies = 0
        self.auth_source = str(PLAIN_COOKIE_FILE) if self.cookie_header else ""
        if not self.cookie_header:
            raise RuntimeError(
                f"未找到可用 Ctrip 登录态。请先点击“刷新登录态”，从当前 Edge/Chrome 登录浏览器读取并校验 Cookie：{PLAIN_COOKIE_FILE}"
            )

    def _wait_for_request_slot(self, stop_event: threading.Event) -> None:
        request_interval_seconds = self.current_request_interval_seconds()
        elapsed = time.monotonic() - self.last_request_at
        remaining = request_interval_seconds - elapsed
        if remaining <= 0:
            return
        REQUEST_WAIT_LOG_AGGREGATOR.record(self.log, remaining)
        deadline = time.monotonic() + remaining
        while time.monotonic() < deadline:
            if stop_event.is_set():
                raise RuntimeError("用户已停止")
            time.sleep(max(0.01, min(0.2, deadline - time.monotonic())))

    def current_request_interval_seconds(self) -> float:
        if self.request_interval_provider is None:
            return self.request_interval_seconds
        try:
            value = float(self.request_interval_provider())
        except Exception:
            return self.request_interval_seconds
        self.request_interval_seconds = max(0.0, value)
        return self.request_interval_seconds

    def _request_json(self, url: str, product_id: str, body: dict[str, Any], stop_event: threading.Event, timeout: int = 90) -> dict[str, Any]:
        if stop_event.is_set():
            raise RuntimeError("用户已停止")
        self._wait_for_request_slot(stop_event)
        headers = build_default_headers(product_id)
        if self.cookie_header:
            headers["cookie"] = self.cookie_header
        request = requests.Request("POST", url, headers=headers, json=body)
        prepared = self.session.prepare_request(request)
        GLOBAL_REQUEST_LIMITER.wait(stop_event)
        try:
            response = self.session.send(prepared, timeout=timeout)
        finally:
            self.last_request_at = time.monotonic()
        if self.stats_area and self.stats_recorder is not None:
            self.stats_recorder(self.stats_area)
        text = response.text
        data = try_json(text)
        if not response.ok:
            if isinstance(data, dict):
                raise RuntimeError(f"接口请求失败：HTTP {response.status_code}，{format_response_error(data, text[:1000])}")
            raise RuntimeError(f"接口请求失败：HTTP {response.status_code}，{text[:1000]}")
        if not isinstance(data, dict):
            raise RuntimeError(f"接口返回非 JSON：{text[:300]}")
        return data

    def post_json(
        self,
        url: str,
        product_id: str,
        body: dict[str, Any],
        stop_event: threading.Event,
        *,
        timeout: int = 90,
    ) -> dict[str, Any]:
        """Public transport boundary shared by independent business workbenches."""
        return self._request_json(url, product_id, body, stop_event, timeout=timeout)

    def load_product(self, product_id: str, stop_event: threading.Event) -> ProductDraft:
        self.log(f"通过 Python requests 读取产品 {product_id} 的 getProductDraft...")
        body = {
            "productId": int(product_id) if str(product_id).isdigit() else product_id,
            "draftTypes": ["PackageInfo"],
            "source": "PriceStock",
        }
        data = self._request_json(GET_PRODUCT_DRAFT_URL, product_id, body, stop_event)
        response_base = data.get("responseBaseData")
        if isinstance(response_base, dict) and response_base.get("success") is False:
            raise RuntimeError(response_base.get("message") or "getProductDraft 返回失败")
        draft = pick_draft(data)
        if not draft:
            raise RuntimeError("getProductDraft 返回中未找到 productPackageInfo")
        page_product_id = str(draft.get("productId") or (draft.get("productBasicInfo") or {}).get("productId") or product_id)
        if page_product_id and page_product_id != str(product_id):
            raise RuntimeError(f"接口产品 ID 不一致：期望 {product_id}，实际 {page_product_id}")
        package_info = draft.get("productPackageInfo") or {}
        resources = package_info.get("packageResourceInfo") or []
        if not isinstance(resources, list) or not resources:
            raise RuntimeError("未读取到 productPackageInfo.packageResourceInfo，可能登录态失效或账号无权限")
        self.log(f"产品 {product_id} 已读取 {len(resources)} 个套餐 SKU")
        return ProductDraft(
            product_id=product_id,
            target_id="",
            package_info=package_info,
            package_resources=resources,
            product_version=draft.get("productVersion"),
            draft_raw=draft,
        )

    def load_product_info_draft(self, product_id: str, stop_event: threading.Event) -> dict[str, Any]:
        self.log(f"读取产品信息草稿：productId={product_id}（ProductInfo）")
        body = {
            "productId": int(product_id) if str(product_id).isdigit() else product_id,
            "draftTypes": ["ProductInfo"],
            "source": "ProductBasicInfo",
        }
        data = self._request_json(GET_PRODUCT_DRAFT_URL, product_id, body, stop_event)
        response_base = data.get("responseBaseData")
        if isinstance(response_base, dict) and response_base.get("success") is False:
            raise RuntimeError(response_base.get("message") or "getProductDraft ProductInfo 返回失败")
        draft = pick_draft(data) or data
        if not isinstance(draft.get("productBasicInfo"), dict):
            raise RuntimeError("getProductDraft ProductInfo 返回中未找到 productBasicInfo")
        page_product_id = str(draft.get("productId") or (draft.get("productBasicInfo") or {}).get("productId") or product_id)
        if page_product_id and page_product_id != str(product_id):
            raise RuntimeError(f"接口产品 ID 不一致：期望 {product_id}，实际 {page_product_id}")
        return draft

    def save_product_info_draft(
        self,
        product_id: str,
        product_info_payload: dict[str, Any],
        stop_event: threading.Event,
    ) -> dict[str, Any]:
        assert_product_payload_target(product_info_payload, ProductRequestTarget(target_product_id(product_id)), "save_product_info")
        self.log(f"保存产品资料草稿：productId={product_id}（ProductInfo）")
        return self._request_json(SAVE_PRODUCT_DRAFT_URL, product_id, product_info_payload, stop_event, timeout=120)

    def load_product_applicable_people_draft(self, product_id: str, stop_event: threading.Event) -> dict[str, Any]:
        self.log(f"读取适用人群草稿：productId={product_id}（ApplicablePeople）")
        body = {
            "productId": int(product_id) if str(product_id).isdigit() else product_id,
            "draftTypes": ["ApplicablePeople"],
            "source": "PriceStock",
        }
        data = self._request_json(GET_PRODUCT_DRAFT_URL, product_id, body, stop_event)
        response_base = data.get("responseBaseData")
        if isinstance(response_base, dict) and response_base.get("success") is False:
            raise RuntimeError(response_base.get("message") or "getProductDraft ApplicablePeople 返回失败")
        draft = pick_draft(data) or data
        if not isinstance(draft.get("productApplicablePeopleInfo"), dict):
            raise RuntimeError("getProductDraft ApplicablePeople 返回中未找到 productApplicablePeopleInfo")
        page_product_id = str(draft.get("productId") or product_id)
        if page_product_id and page_product_id != str(product_id):
            raise RuntimeError(f"接口产品 ID 不一致：期望 {product_id}，实际 {page_product_id}")
        return draft

    def load_product_price_stock_draft(self, product_id: str, stop_event: threading.Event, refresh: bool = False) -> dict[str, Any]:
        cache_key = str(product_id)
        if not refresh and cache_key in self.product_price_stock_draft_cache:
            return self.product_price_stock_draft_cache[cache_key]
        self.log(f"读取价格库存草稿：productId={product_id}（PriceAndStock）")
        body = {
            "productId": int(product_id) if str(product_id).isdigit() else product_id,
            "draftTypes": ["PriceAndStock"],
            "source": "PriceStock",
        }
        data = self._request_json(GET_PRODUCT_DRAFT_URL, product_id, body, stop_event)
        response_base = data.get("responseBaseData")
        if isinstance(response_base, dict) and response_base.get("success") is False:
            raise RuntimeError(response_base.get("message") or "getProductDraft PriceAndStock 返回失败")
        package_price_stock_list = data.get("packagePriceAndStockList")
        if not isinstance(package_price_stock_list, list):
            raise RuntimeError("getProductDraft PriceAndStock 返回中未找到 packagePriceAndStockList")
        self.product_price_stock_draft_cache[cache_key] = data
        self.product_currency_context_cache[cache_key] = build_currency_rewrite_context(product_id, data)
        self.product_price_stock_cache.pop(cache_key, None)
        return data

    def load_product_currency_context(
        self,
        product_id: str,
        stop_event: threading.Event,
        refresh: bool = False,
    ) -> CurrencyRewriteContext:
        cache_key = str(product_id)
        if not refresh and cache_key in self.product_currency_context_cache:
            return self.product_currency_context_cache[cache_key]
        price_stock_draft = self.load_product_price_stock_draft(product_id, stop_event, refresh=refresh)
        context = build_currency_rewrite_context(product_id, price_stock_draft)
        self.product_currency_context_cache[cache_key] = context
        return context

    def prepare_product_edit_payload(
        self,
        product_id: str,
        payload: dict[str, Any],
        stop_event: threading.Event,
        currency_context: CurrencyRewriteContext | None = None,
    ) -> tuple[dict[str, Any], int]:
        context = currency_context or self.load_product_currency_context(product_id, stop_event)
        prepared, rewrite_count = apply_product_edit_currency_rewrite(payload, context)
        if rewrite_count:
            self.log(f"产品 {product_id} 传出前已将人民币/CNY/RMB 币种字段改为 HKD：{rewrite_count} 处")
        return prepared, rewrite_count

    def load_product_price_stock(self, product_id: str, stop_event: threading.Event, refresh: bool = False) -> dict[str, dict[str, Any]]:
        cache_key = str(product_id)
        if not refresh and cache_key in self.product_price_stock_cache:
            return self.product_price_stock_cache[cache_key]
        data = self.load_product_price_stock_draft(product_id, stop_event, refresh=refresh)
        package_price_stock_list = data.get("packagePriceAndStockList")
        if not isinstance(package_price_stock_list, list):
            raise RuntimeError("getProductDraft PriceAndStock 返回中未找到 packagePriceAndStockList")
        result: dict[str, dict[str, Any]] = {}
        for item in package_price_stock_list:
            if not isinstance(item, dict):
                continue
            package_id = item.get("packageId")
            if package_id is None:
                continue
            result[str(package_id)] = item
        self.product_price_stock_cache[cache_key] = result
        self.log(f"产品 {product_id} 价格库存草稿已读取 {len(result)} 个套餐")
        return result

    def save_package_info(
        self,
        draft: ProductDraft,
        package_info: dict[str, Any],
        stop_event: threading.Event,
        currency_context: CurrencyRewriteContext | None = None,
    ) -> dict[str, Any]:
        payload = build_save_payload(draft.product_id, package_info, None, product_version=draft.product_version)
        payload, _rewrite_count = self.prepare_product_edit_payload(draft.product_id, payload, stop_event, currency_context)
        assert_product_payload_target(payload, ProductRequestTarget(target_product_id(draft.product_id)), "save_package_info")
        self.log(f"通过 Python requests 保存产品 {draft.product_id} 草稿...")
        return self._request_json(SAVE_PRODUCT_DRAFT_URL, draft.product_id, payload, stop_event, timeout=120)

    def get_resource_price_and_stock(self, product_id: str, package_id: str, resource_id: str, stop_event: threading.Event) -> PriceStockBundle:
        package_price_stock = self.load_product_price_stock(product_id, stop_event).get(str(package_id))
        if not isinstance(package_price_stock, dict):
            raise RuntimeError(f"PriceAndStock 草稿中未找到 packageId={package_id}")
        price_and_stock = package_price_stock_to_price_and_stock(package_price_stock)
        if not price_and_stock_has_resource(price_and_stock, resource_id):
            raise RuntimeError(f"PriceAndStock 草稿中未找到 resourceId={resource_id}")
        return PriceStockBundle(product_id=product_id, package_id=package_id, resource_id=resource_id, price_and_stock=price_and_stock)

    def get_resource_price_and_stock_direct(
        self,
        product_id: str,
        package_id: str,
        resource_id: str,
        stop_event: threading.Event,
    ) -> dict[str, Any]:
        body = {
            "productId": int(product_id) if str(product_id).isdigit() else product_id,
            "packageId": int(package_id) if str(package_id).isdigit() else package_id,
            "resourceId": int(resource_id) if str(resource_id).isdigit() else resource_id,
        }
        response = self._request_json(GET_RESOURCE_PRICE_AND_STOCK_URL, product_id, body, stop_event)
        return {"request": body, "response": response}

    def build_price_stock_save_payload(
        self,
        product_id: str,
        price_stock_draft: dict[str, Any],
        package_ids: set[str] | None = None,
        currency_context: CurrencyRewriteContext | None = None,
    ) -> dict[str, Any]:
        package_price_stock_list = price_stock_draft.get("packagePriceAndStockList")
        if not isinstance(package_price_stock_list, list):
            raise RuntimeError("PriceAndStock 草稿中未找到 packagePriceAndStockList")
        if package_ids is not None:
            package_price_stock_list = [
                item
                for item in package_price_stock_list
                if isinstance(item, dict) and str(item.get("packageId") or "") in package_ids
            ]
        payload = {
            "productId": int(product_id) if str(product_id).isdigit() else product_id,
            "draftTypes": ["PriceAndStock"],
            "packagePriceAndStockList": package_price_stock_list,
            "type": 2,
            "operator": 3,
        }
        for key in ("categoryId", "reserveMode", "productVersion"):
            if key in price_stock_draft:
                payload[key] = price_stock_draft.get(key)
        if "productPriceStock" in price_stock_draft:
            payload["productPriceStock"] = price_stock_draft.get("productPriceStock")
        payload["requestBaseData"] = {
            "extParameterList": [
                {"key": "page_version", "value": "5.3"},
                {"key": "needValidatePermission", "value": "true"},
            ]
        }
        assert_product_payload_target(payload, ProductRequestTarget(target_product_id(product_id)), "build_price_stock_save_payload")
        if currency_context is not None:
            payload, _rewrite_count = apply_product_edit_currency_rewrite(payload, currency_context)
        return payload

    def save_product_price_stock_draft(
        self,
        product_id: str,
        price_stock_draft: dict[str, Any],
        stop_event: threading.Event,
        package_ids: set[str] | None = None,
        currency_context: CurrencyRewriteContext | None = None,
    ) -> dict[str, Any]:
        context = currency_context or self.load_product_currency_context(product_id, stop_event)
        payload = self.build_price_stock_save_payload(product_id, price_stock_draft, package_ids)
        payload, rewrite_count = apply_product_edit_currency_rewrite(payload, context)
        if rewrite_count:
            self.log(f"产品 {product_id} 价格库存传出前已将人民币/CNY/RMB 币种字段改为 HKD：{rewrite_count} 处")
        self.log(f"保存价格库存草稿：productId={product_id}, packages={len(payload['packagePriceAndStockList'])}")
        response = self._request_json(SAVE_PRODUCT_DRAFT_URL, product_id, payload, stop_event, timeout=120)
        self.product_price_stock_cache.pop(str(product_id), None)
        self.product_price_stock_draft_cache.pop(str(product_id), None)
        self.product_currency_context_cache.pop(str(product_id), None)
        return response

    def submit_audit(
        self,
        draft: ProductDraft,
        stop_event: threading.Event,
        currency_context: CurrencyRewriteContext | None = None,
    ) -> dict[str, Any]:
        return self.submit_audit_with_payload(draft, stop_event, currency_context=currency_context).response

    def submit_audit_with_payload(
        self,
        draft: ProductDraft,
        stop_event: threading.Event,
        currency_context: CurrencyRewriteContext | None = None,
    ) -> SubmitAuditResult:
        applicable_people_draft = self.load_product_applicable_people_draft(draft.product_id, stop_event)
        payload = build_submit_audit_payload(draft, applicable_people_draft)
        payload, _rewrite_count = self.prepare_product_edit_payload(draft.product_id, payload, stop_event, currency_context)
        assert_product_payload_target(payload, ProductRequestTarget(target_product_id(draft.product_id)), "submit_audit")
        self.log(f"提交审核：productId={draft.product_id}")
        response = self._request_json(SAVE_PRODUCT_DRAFT_URL, draft.product_id, payload, stop_event, timeout=120)
        initial_response = response
        intermediate_responses: list[dict[str, Any]] = []
        confirm_reasons: list[str] = []
        current_payload = payload
        current_response = response
        while True:
            retry_payload, confirm_reason = build_submit_audit_confirm_retry_payload(current_payload, current_response)
            if retry_payload is None:
                break
            assert_product_payload_target(
                retry_payload,
                ProductRequestTarget(target_product_id(draft.product_id)),
                "submit_audit_confirm_retry",
            )
            removed_marks = sorted(set(current_payload.get("effectMarks") or []) - set(retry_payload.get("effectMarks") or []))
            self.log(
                f"提交审核返回需确认继续：{confirm_reason}；"
                f"移除 effectMarks={removed_marks} 后重试 productId={draft.product_id}"
            )
            confirm_reasons.append(confirm_reason)
            intermediate_responses.append(current_response)
            current_payload = retry_payload
            current_response = self._request_json(SAVE_PRODUCT_DRAFT_URL, draft.product_id, current_payload, stop_event, timeout=120)
        return SubmitAuditResult(
            response=current_response,
            request=current_payload,
            confirmed_continue=bool(confirm_reasons),
            initial_response=initial_response if confirm_reasons else None,
            confirm_reason="；".join(confirm_reasons),
            confirm_reasons=confirm_reasons,
            intermediate_responses=intermediate_responses,
        )

    def verify_product(self, product_id: str, expected: dict[int, str], stop_event: threading.Event) -> dict[int, bool]:
        draft = self.load_product(product_id, stop_event)
        resources = draft.package_resources
        return {
            index: index < len(resources) and str(resources[index].get("introduction") or "") == intro
            for index, intro in expected.items()
        }

    def load_translation_available_locales(self, product_id: str, stop_event: threading.Event) -> dict[str, Any]:
        self.log(f"读取翻译件可用语言：productId={product_id}")
        body = {
            "productId": str(product_id),
            "requestBaseData": translation_request_base_data(),
        }
        data = self._request_json(TRANSLATION_AVAILABLE_LOCALES_URL, product_id, body, stop_event)
        if not response_success(data):
            raise RuntimeError(f"读取翻译件可用语言失败：{format_response_error(data)}")
        return data

    def load_translation_list(self, product_id: str, locales: list[str], stop_event: threading.Event) -> dict[str, Any]:
        self.log(f"读取翻译件内容：productId={product_id}, locales={','.join(locales)}")
        body = {
            "productId": str(product_id),
            "requestBaseData": translation_request_base_data(),
            "needMeta": True,
            "locales": locales,
            "fromTranslationConfirm": False,
        }
        data = self._request_json(TRANSLATION_LIST_URL, product_id, body, stop_event, timeout=120)
        if not response_success(data):
            raise RuntimeError(f"读取翻译件内容失败：{format_response_error(data)}")
        return data

    def query_ai_translation_reference(
        self,
        product_id: str,
        target_locale: str,
        original_content: str,
        stop_event: threading.Event,
    ) -> str:
        self.log(f"读取机器翻译参考：productId={product_id}, locale={target_locale}")
        body = {
            "productId": str(product_id),
            "requestBaseData": translation_request_base_data(),
            "targetLocale": target_locale,
            "originalContent": original_content,
        }
        response = self._request_json(TRANSLATION_AI_REFERENCE_URL, product_id, body, stop_event, timeout=120)
        if not response_success(response):
            self.log(f"机器翻译参考接口返回失败：{response_message(response, 'unknown error')}")
            return ""
        content = str(response.get("aiTranslationContent") or "").strip()
        if not content:
            self.log("机器翻译参考接口未返回 aiTranslationContent")
        return content

    def build_translation_push_payload(
        self,
        product_id: str,
        locale: str,
        raw_translation: dict[str, Any],
        changed_plans: list[TranslationDiffPlan],
        online: bool,
    ) -> dict[str, Any]:
        translation_modules = copy.deepcopy(raw_translation.get("translationModules") or [])
        if not isinstance(translation_modules, list) or not translation_modules:
            raise RuntimeError(f"{locale} 未返回 translationModules")
        for plan in changed_plans:
            applied = apply_translation_to_modules(translation_modules, plan.self_key, plan.row.value_key, plan.new_value)
            if not applied:
                raise RuntimeError(f"未能在最新翻译树中定位 selfKey={plan.self_key}")
        normalize_translation_push_fields(translation_modules)
        payload: dict[str, Any] = {
            "productId": str(product_id),
            "requestBaseData": translation_request_base_data(),
            "online": bool(online),
            "locale": locale,
            "translationModules": translation_modules,
            "aiGen": False,
        }
        for key in ("tour", "clause"):
            if key in raw_translation:
                payload[key] = copy.deepcopy(raw_translation.get(key))
        assert_translation_payload_target(payload, TranslationRequestTarget(target_product_id(product_id), locale), "build_translation_push_payload")
        return payload

    def save_translation(
        self,
        product_id: str,
        locale: str,
        raw_translation: dict[str, Any],
        changed_plans: list[TranslationDiffPlan],
        online: bool,
        stop_event: threading.Event,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        payload = self.build_translation_push_payload(product_id, locale, raw_translation, changed_plans, online)
        self.log(f"写入翻译件：productId={product_id}, locale={locale}, fields={len(changed_plans)}, online={online}")
        response = self._request_json(TRANSLATION_PUSH_URL, product_id, payload, stop_event, timeout=120)
        return payload, response


def group_rows(rows: list[TemplateRow]) -> dict[str, list[TemplateRow]]:
    grouped: dict[str, list[TemplateRow]] = {}
    for row in rows:
        if row.enabled:
            grouped.setdefault(row.product_id, []).append(row)
    return grouped


def backup_package_info(product_id: str, package_info: dict[str, Any], backup_dir: Path) -> Path:
    backup_dir.mkdir(parents=True, exist_ok=True)
    path = backup_dir / f"package_resource_backup_{now_stamp()}.jsonl"
    record = {
        "createdAt": dt.datetime.now().isoformat(timespec="seconds"),
        "productId": product_id,
        "productPackageInfo": package_info,
    }
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
    return path


REQUEST_TEMPLATE_DIR = Path("request_templates")


def request_template_path(product_id: str, directory: Path = REQUEST_TEMPLATE_DIR) -> Path:
    safe_product_id = re.sub(r"[^0-9A-Za-z_-]+", "_", str(product_id)).strip("_") or "unknown"
    return directory / f"ctrip_request_template_{safe_product_id}.json"


def save_request_template(template: CapturedRequestTemplate, directory: Path = REQUEST_TEMPLATE_DIR) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = request_template_path(template.product_id, directory)
    data = {
        "productId": template.product_id,
        "capturedAt": template.captured_at,
        "getRequest": template.get_request,
        "saveRequest": template.save_request,
    }
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def load_request_template(product_id: str, directory: Path = REQUEST_TEMPLATE_DIR) -> CapturedRequestTemplate | None:
    path = request_template_path(product_id, directory)
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    return CapturedRequestTemplate(
        product_id=str(data.get("productId") or product_id),
        captured_at=str(data.get("capturedAt") or ""),
        get_request=data.get("getRequest") if isinstance(data.get("getRequest"), dict) else None,
        save_request=data.get("saveRequest") if isinstance(data.get("saveRequest"), dict) else None,
    )


def filter_fetch_headers(headers: Any) -> dict[str, str]:
    if not isinstance(headers, dict):
        return {"content-type": "application/json"}
    blocked = {
        "accept-encoding",
        "connection",
        "content-length",
        "cookie",
        "host",
        "origin",
        "referer",
        "sec-fetch-dest",
        "sec-fetch-mode",
        "sec-fetch-site",
        "sec-fetch-user",
        "te",
        "upgrade-insecure-requests",
        "user-agent",
    }
    result: dict[str, str] = {}
    for key, value in headers.items():
        name = str(key).strip()
        if not name:
            continue
        lower = name.lower()
        if lower in blocked or lower.startswith("proxy-") or lower.startswith("sec-"):
            continue
        if value is None:
            continue
        result[name] = str(value)
    result.setdefault("content-type", "application/json")
    return result


def build_save_payload(
    product_id: str,
    package_info: dict[str, Any],
    request_template: CapturedRequestTemplate | None = None,
    product_version: Any = None,
) -> dict[str, Any]:
    body_template: Any = None
    if request_template and request_template.save_request:
        body_template = request_template.save_request.get("bodyJson")
    if isinstance(body_template, dict):
        payload = copy.deepcopy(body_template)
        payload["productId"] = int(product_id) if str(product_id).isdigit() else product_id
        payload["productPackageInfo"] = package_info
        payload.setdefault("type", 2)
        payload.setdefault("draftTypes", ["PackageInfo"])
        payload.setdefault("draftTypesRequired", ["PackageInfo"])
        if product_version is not None:
            payload["productVersion"] = product_version
        return payload
    payload = {
        "productId": int(product_id) if str(product_id).isdigit() else product_id,
        "type": 2,
        "draftTypes": ["PackageInfo"],
        "draftTypesRequired": ["PackageInfo"],
        "productPackageInfo": package_info,
    }
    if product_version is not None:
        payload["productVersion"] = product_version
    return payload


def normalized_applicable_people_info(draft_data: dict[str, Any]) -> dict[str, Any]:
    info = copy.deepcopy(draft_data.get("productApplicablePeopleInfo") or {})
    if not isinstance(info, dict):
        info = {}
    info.setdefault("isApplicablePeople", False)
    info.setdefault("applicablePeopleRemark", "")
    info.setdefault("subResourceSettingList", [])
    info.setdefault("applicablePeopleRangeType", 0)
    return info


def build_submit_audit_payload(draft: ProductDraft, applicable_people_draft: dict[str, Any] | None = None) -> dict[str, Any]:
    if applicable_people_draft is not None:
        product_version = applicable_people_draft.get("productVersion", draft.product_version)
        payload = {
            "productId": int(draft.product_id) if str(draft.product_id).isdigit() else draft.product_id,
            "type": 3,
            "draftTypes": ["ApplicablePeople"],
            "checkWordMap": {"PriceStock.CrowdSetting.localCrowdRemark": ""},
            "productApplicablePeopleInfo": normalized_applicable_people_info(applicable_people_draft),
            "effectMarks": [1, 3, 4, 5, 6, 8, 9],
            "addDSAInfoLater": False,
        }
        if product_version is not None:
            payload["productVersion"] = product_version
        return payload
    payload = {
        "productId": int(draft.product_id) if str(draft.product_id).isdigit() else draft.product_id,
        "type": 3,
        "draftTypes": ["PackageInfo"],
        "draftTypesRequired": ["PackageInfo", "PriceAndStock", "NegativeGrossProfit", "LowBrokerageRate"],
        "effectMarks": [1, 3, 4, 5, 6, 8, 9],
        "addDSAInfoLater": False,
        "productPackageInfo": draft.package_info,
    }
    if draft.product_version is not None:
        payload["productVersion"] = draft.product_version
    return payload


SUBMIT_AUDIT_CONFIRM_RETRY_RULES: tuple[dict[str, Any], ...] = (
    {
        "error_codes": {"key.v.api.priceStock.check.fromNow.maintain"},
        "message_fragments": ("没有维护价格或库存数据",),
        "effect_mark": 1,
        "reason": "价格/库存缺失提示确认继续",
    },
    {
        "error_codes": {"key.v2.api.product.fill.in.number.limit.confirm"},
        "message_fragments": ("出行人", "填写人数"),
        "effect_mark": 3,
        "reason": "出行人填写人数提示确认继续",
    },
    {
        "error_codes": {"key.v.api.resource.currency.not.same"},
        "message_fragments": ("卖价币种与其他资源维护不一致",),
        "effect_mark": 4,
        "reason": "资源卖价币种不一致提示确认继续",
    },
    {
        "error_codes": {"key.v2.api.red.poi.audit.tip"},
        "message_fragments": ("POI",),
        "effect_mark": 5,
        "reason": "POI 审核提示确认继续",
    },
    {
        "error_codes": {"key.v2.api.product.sync.setting.is.false.result"},
        "message_fragments": ("同步",),
        "effect_mark": 6,
        "reason": "同步设置提示确认继续",
    },
    {
        "error_codes": {"key.v2.api.product.image.language_detect_filter_locales.headImage"},
        "message_fragments": ("headImage", "头图"),
        "effect_mark": 8,
        "reason": "头图语言检测提示确认继续",
    },
    {
        "error_codes": {"key.v2.api.product.image.language_detect_filter_locales.imageText"},
        "message_fragments": ("imageText", "图片文字"),
        "effect_mark": 9,
        "reason": "图片文字语言检测提示确认继续",
    },
)


def submit_audit_confirm_retry_rule(response: dict[str, Any]) -> dict[str, Any] | None:
    if response_success(response):
        return None
    response_text = json.dumps(response, ensure_ascii=False)
    response_base = response.get("responseBaseData")
    error_code = ""
    if isinstance(response_base, dict):
        error_code = str(response_base.get("errorCode") or response_base.get("code") or "")
    for rule in SUBMIT_AUDIT_CONFIRM_RETRY_RULES:
        if error_code and error_code in rule["error_codes"]:
            return rule
        if any(fragment in response_text for fragment in rule["message_fragments"]):
            return rule
    return None


def build_submit_audit_confirm_retry_payload(
    payload: dict[str, Any],
    response: dict[str, Any],
) -> tuple[dict[str, Any] | None, str]:
    rule = submit_audit_confirm_retry_rule(response)
    if rule is None:
        return None, ""
    effect_mark = rule["effect_mark"]
    effect_marks = payload.get("effectMarks")
    if not isinstance(effect_marks, list) or effect_mark not in effect_marks:
        return None, ""
    retry_payload = copy.deepcopy(payload)
    retry_payload["effectMarks"] = [mark for mark in effect_marks if mark != effect_mark]
    return retry_payload, str(rule["reason"])


def response_success(response: dict[str, Any]) -> bool:
    response_base = response.get("responseBaseData")
    if isinstance(response_base, dict):
        return bool(response_base.get("success", False))
    response_status = response.get("ResponseStatus")
    if isinstance(response_status, dict):
        ack = str(response_status.get("Ack") or "")
        if ack:
            return ack.lower() == "success" and not response_status.get("Errors")
    if "success" in response:
        return bool(response.get("success"))
    return "rawText" not in response


def compact_json_text(value: Any, limit: int = 1000) -> str:
    try:
        text = json.dumps(value, ensure_ascii=False)
    except Exception:
        text = str(value)
    text = text.replace("\n", "\\n")
    return text if len(text) <= limit else text[:limit] + "..."


def format_response_error(response: dict[str, Any], default: str = "接口返回失败") -> str:
    parts: list[str] = []
    response_base = response.get("responseBaseData")
    if isinstance(response_base, dict):
        for key in ("message", "errorCode", "code", "path"):
            value = response_base.get(key)
            if value not in (None, ""):
                parts.append(str(value))
    for key in ("message", "errorMessage", "errorCode", "rawText"):
        value = response.get(key)
        if value not in (None, ""):
            parts.append(str(value))
    response_status = response.get("ResponseStatus")
    if isinstance(response_status, dict):
        status_text = compact_json_text(response_status, limit=500)
        if status_text and status_text != "{}":
            parts.append(f"ResponseStatus={status_text}")
    if not parts:
        parts.append(default)
    summary = " | ".join(dict.fromkeys(parts))
    if summary == default and response:
        summary = f"{default} | response={compact_json_text(response)}"
    return summary[:1600]


def response_message(response: dict[str, Any], default: str = "接口返回失败") -> str:
    return format_response_error(response, default)


def product_version_from_save_response(response: dict[str, Any], default: Any = None) -> Any:
    draft = response.get("getProductDraft") if isinstance(response, dict) else None
    if isinstance(draft, dict) and draft.get("productVersion") is not None:
        return draft.get("productVersion")
    return default


def is_version_conflict(response: dict[str, Any]) -> bool:
    text = json.dumps(response, ensure_ascii=False)
    return "key.v2.api.product.version.not.match" in text or "version.not.match" in text


def resource_id_from_package_resource(item: dict[str, Any]) -> str:
    resources = item.get("resourceInfoList")
    if isinstance(resources, list) and resources:
        resource_id = resources[0].get("resourceId")
        return "" if resource_id is None else str(resource_id)
    return ""


def connection_code_from_package_resource(item: dict[str, Any]) -> str:
    resources = item.get("resourceInfoList")
    if not isinstance(resources, list) or not resources:
        return ""
    props = resources[0].get("connectionPropertyList")
    if isinstance(props, list):
        for prop in props:
            if isinstance(prop, dict) and str(prop.get("key")) == "4":
                return str(prop.get("value") or "")
    return str(resources[0].get("connectionSystemKey") or "")


def set_connection_code(item: dict[str, Any], connection_code: str) -> None:
    resources = item.get("resourceInfoList")
    if not isinstance(resources, list) or not resources:
        raise RuntimeError("目标套餐缺少 resourceInfoList，无法写入对接代码")
    resource = resources[0]
    resource["connectionSystemKey"] = connection_code
    props = resource.get("connectionPropertyList")
    if not isinstance(props, list):
        props = []
        resource["connectionPropertyList"] = props
    for prop in props:
        if isinstance(prop, dict) and str(prop.get("key")) == "4":
            prop["value"] = connection_code
            return
    props.append({"key": "4", "value": connection_code})


def package_price_stock_to_price_and_stock(package_price_stock: dict[str, Any]) -> dict[str, Any]:
    price = package_price_stock.get("price") if isinstance(package_price_stock.get("price"), dict) else {}
    stock = package_price_stock.get("stock") if isinstance(package_price_stock.get("stock"), dict) else {}
    price_basic = price.get("basicInfoList") if isinstance(price.get("basicInfoList"), list) else []
    stock_basic = stock.get("basicInfoList") if isinstance(stock.get("basicInfoList"), list) else []
    stock_by_resource = {str(item.get("resourceId")): item for item in stock_basic if isinstance(item, dict) and item.get("resourceId") is not None}
    basic_info_list: list[dict[str, Any]] = []
    seen_resource_ids: set[str] = set()
    for item in price_basic:
        if not isinstance(item, dict):
            continue
        resource_id = item.get("resourceId")
        key = str(resource_id)
        seen_resource_ids.add(key)
        merged = copy.deepcopy(item)
        stock_item = stock_by_resource.get(key)
        if isinstance(stock_item, dict):
            merged.update(copy.deepcopy(stock_item))
        basic_info_list.append(merged)
    for key, item in stock_by_resource.items():
        if key not in seen_resource_ids:
            basic_info_list.append(copy.deepcopy(item))
    result = {
        "basicInfoList": basic_info_list,
        "resourceShareStoreList": copy.deepcopy(stock.get("resourceShareStoreList") or []),
        "hasSpecialPrice": copy.deepcopy(price.get("hasSpecialPrice", False)),
        "specialPriceList": copy.deepcopy(price.get("specialPriceList") or []),
        "resourcePriceList": copy.deepcopy(price.get("resourcePriceList") or []),
        "resourcePriceDraftList": copy.deepcopy(price.get("resourcePriceDraftList") or []),
        "resourceStockList": copy.deepcopy(stock.get("resourceStockList") or []),
    }
    for optional_key in ("latestApplyProfitRule", "packageProfitInfo", "brokerageInfo", "packagePriceChangeRule", "packageStockChangeRules"):
        source = price if optional_key in price else stock
        if optional_key in source:
            result[optional_key] = copy.deepcopy(source.get(optional_key))
    return result


def price_and_stock_has_resource(price_and_stock: dict[str, Any], resource_id: str) -> bool:
    for key in ("basicInfoList", "resourcePriceList", "resourceStockList"):
        for item in price_and_stock.get(key) or []:
            if isinstance(item, dict) and str(item.get("resourceId") or "") == str(resource_id):
                return True
    return False


def find_package_resource(draft: ProductDraft, row: TemplateRow) -> tuple[int, dict[str, Any]]:
    if row.package_id:
        for index, item in enumerate(draft.package_resources):
            if str(item.get("packageId") or "") == row.package_id:
                return index, item
        raise RuntimeError(f"未找到 packageId={row.package_id}")
    matches = [
        (index, item)
        for index, item in enumerate(draft.package_resources)
        if str(item.get("packageName") or "").strip() == row.package_name.strip()
    ]
    if not matches:
        raise RuntimeError(f"未找到 packageName={row.package_name}")
    if len(matches) > 1:
        raise RuntimeError(f"packageName 命中多个 SKU，请改用 packageId：{row.package_name}")
    return matches[0]


def current_cost_price(price_and_stock: dict[str, Any], resource_id: str) -> str:
    for list_name in ("resourcePriceList", "resourcePriceDraftList"):
        for resource_price in price_and_stock.get(list_name) or []:
            if str(resource_price.get("resourceId") or "") != str(resource_id):
                continue
            for price in resource_price.get("priceList") or []:
                if "costPrice" in price:
                    return normalize_number_text(price.get("costPrice"))
    return ""


def vendor_can_edit_cost_price(price_and_stock: dict[str, Any], resource_id: str) -> bool:
    for basic_info in price_and_stock.get("basicInfoList") or []:
        if not isinstance(basic_info, dict) or str(basic_info.get("resourceId") or "") != str(resource_id):
            continue
        if "isAllowVendorEditCostPrice" in basic_info:
            return bool(basic_info.get("isAllowVendorEditCostPrice"))
    return True


def current_sale_status(price_and_stock: dict[str, Any], resource_id: str) -> str:
    resource_exists = False
    for list_name in ("resourcePriceDraftList", "resourcePriceList"):
        for resource_price in price_and_stock.get(list_name) or []:
            if not isinstance(resource_price, dict) or str(resource_price.get("resourceId") or "") != str(resource_id):
                continue
            resource_exists = True
            for price in resource_price.get("priceList") or []:
                if isinstance(price, dict) and "sale" in price:
                    return "开" if bool(price.get("sale")) else "关"
    return "关" if resource_exists else ""


def canonical_sale_status(value: Any) -> str:
    text = normalize_cell(value)
    if text in {"开", "打开", "已打开"}:
        return "开"
    if text in {"关", "关闭", "已关闭"}:
        return "关"
    return text


def set_package_sale_status_draft(package_price_stock: dict[str, Any], resource_id: str, sale_status: str) -> None:
    if sale_status not in SALE_STATUS_OPTIONS:
        raise ValueError(f"开/关班状态必须是：{', '.join(SALE_STATUS_OPTIONS)}")
    price = package_price_stock.get("price")
    if not isinstance(price, dict):
        raise RuntimeError("PriceAndStock 套餐草稿中未找到 price")
    resource_key = str(resource_id)
    draft_list = copy.deepcopy(price.get("resourcePriceDraftList") or [])
    source_list = price.get("resourcePriceList") or []
    target_resource = next(
        (item for item in draft_list if isinstance(item, dict) and str(item.get("resourceId") or "") == resource_key),
        None,
    )
    if target_resource is None:
        source_resource = next(
            (item for item in source_list if isinstance(item, dict) and str(item.get("resourceId") or "") == resource_key),
            None,
        )
        if source_resource is None:
            raise RuntimeError(f"价格库存中未找到 resourceId={resource_id} 的开/关班状态")
        target_resource = copy.deepcopy(source_resource)
        draft_list.append(target_resource)
    sale = sale_status == "开"
    price_list = target_resource.get("priceList") if isinstance(target_resource.get("priceList"), list) else []
    day_price = copy.deepcopy(price_list[0]) if price_list and isinstance(price_list[0], dict) else {
        "costPrice": 0,
        "salePrice": 0,
        "marketPrice": 0,
        "boxSalePrice": None,
        "boxCostPrice": None,
        "day": "00010101",
    }
    day_price["sale"] = sale
    day_price["isDraft"] = True
    target_resource["priceList"] = [day_price]
    price["resourcePriceDraftList"] = draft_list


def set_cost_price(price_and_stock: dict[str, Any], resource_id: str, cost_price: str) -> None:
    found = False
    numeric_price = float(cost_price)
    for resource_price in price_and_stock.get("resourcePriceList") or []:
        if str(resource_price.get("resourceId") or "") != str(resource_id):
            continue
        for price in resource_price.get("priceList") or []:
            price["costPrice"] = numeric_price
            found = True
    if not found:
        raise RuntimeError(f"价格库存中未找到 resourceId={resource_id} 的 costPrice")


def set_package_cost_price(package_price_stock: dict[str, Any], resource_id: str, cost_price: str) -> None:
    price = package_price_stock.get("price")
    if not isinstance(price, dict):
        raise RuntimeError("PriceAndStock 套餐草稿中未找到 price")
    resource_key = str(resource_id)
    package_id = str(package_price_stock.get("packageId") or "")
    numeric_price = float(cost_price)
    before_resource_prices = [
        copy.deepcopy(item)
        for item in price.get("resourcePriceList") or []
        if isinstance(item, dict) and str(item.get("resourceId") or "") == resource_key
    ]
    found = False
    for resource_price in price.get("resourcePriceList") or []:
        if str(resource_price.get("resourceId") or "") != resource_key:
            continue
        for day_price in resource_price.get("priceList") or []:
            old_cost = day_price.get("costPrice")
            old_sale = day_price.get("salePrice")
            if old_cost not in (None, "", 0) and old_sale not in (None, ""):
                try:
                    day_price["salePrice"] = round(float(old_sale) / float(old_cost) * numeric_price, 4)
                except Exception:
                    pass
            day_price["costPrice"] = numeric_price
            found = True
    if not found:
        raise RuntimeError(f"价格库存中未找到 resourceId={resource_id} 的 costPrice")
    if before_resource_prices:
        price["resourcePriceDraftList"] = before_resource_prices
    price["packagePriceChangeRule"] = {
        "changePriceType": "2",
        "dateDesc": "1010-1-",
        "date": ["00010101"],
        "effectDate": "00010101",
        "expireDate": "00010101",
        "resourcePriceChangeList": [
            {
                "resourceId": int(resource_id) if str(resource_id).isdigit() else resource_id,
                "costPrice": numeric_price,
                "packageId": package_id,
            }
        ],
    }
    stock = package_price_stock.get("stock")
    if isinstance(stock, dict):
        stock["resourceStockDraftList"] = copy.deepcopy(stock.get("resourceStockList") or [])
        stock["packageStockChangeRules"] = [
            {
                "dateDesc": "1010-1-",
                "date": ["00010101"],
                "effectDate": "00010101",
                "expireDate": "00010101",
                "changeStockType": "2",
                "resourceStockChangeList": [
                    {"resourceId": int(resource_id) if str(resource_id).isdigit() else resource_id}
                ],
            }
        ]


def set_package_cost_price_draft(package_price_stock: dict[str, Any], resource_id: str, cost_price: str) -> None:
    price = package_price_stock.get("price")
    if not isinstance(price, dict):
        raise RuntimeError("PriceAndStock 套餐草稿中未找到 price")
    resource_key = str(resource_id)
    package_id = str(package_price_stock.get("packageId") or "")
    numeric_price = float(cost_price)
    draft_list = copy.deepcopy(price.get("resourcePriceDraftList") or price.get("resourcePriceList") or [])
    found = False
    for resource_price in draft_list:
        if str(resource_price.get("resourceId") or "") != resource_key:
            continue
        price_list = resource_price.get("priceList")
        if not isinstance(price_list, list):
            price_list = []
            resource_price["priceList"] = price_list
        if not price_list:
            price_list.append(
                {
                    "day": "00010101",
                    "salePrice": 0.0,
                    "costPrice": 0,
                    "marketPrice": 0,
                    "sale": True,
                    "ruleId": 23087,
                }
            )
        for day_price in price_list:
            old_cost = day_price.get("costPrice")
            old_sale = day_price.get("salePrice")
            if old_cost not in (None, "", 0) and old_sale not in (None, ""):
                try:
                    day_price["salePrice"] = round(float(old_sale) / float(old_cost) * numeric_price, 4)
                except Exception:
                    pass
            day_price["costPrice"] = numeric_price
            found = True
    if not found:
        raise RuntimeError(f"价格库存草稿中未找到 resourceId={resource_id} 的 costPrice")
    price["resourcePriceDraftList"] = draft_list
    price["packagePriceChangeRule"] = {
        "changePriceType": "2",
        "dateDesc": "1010-1-",
        "date": ["00010101"],
        "effectDate": "00010101",
        "expireDate": "00010101",
        "resourcePriceChangeList": [
            {
                "resourceId": int(resource_id) if str(resource_id).isdigit() else resource_id,
                "costPrice": numeric_price,
                "packageId": package_id,
            }
        ],
    }
    stock = package_price_stock.get("stock")
    if isinstance(stock, dict):
        stock["resourceStockDraftList"] = copy.deepcopy(stock.get("resourceStockList") or [])
        stock["packageStockChangeRules"] = [
            {
                "dateDesc": "1010-1-",
                "date": ["00010101"],
                "effectDate": "00010101",
                "expireDate": "00010101",
                "changeStockType": "2",
                "resourceStockChangeList": [
                    {"resourceId": int(resource_id) if str(resource_id).isdigit() else resource_id}
                ],
            }
        ]


def ensure_price_stock_draft_lists(price_stock_draft: dict[str, Any]) -> None:
    for package_price_stock in price_stock_draft.get("packagePriceAndStockList") or []:
        if not isinstance(package_price_stock, dict):
            continue
        price = package_price_stock.get("price")
        if isinstance(price, dict) and price.get("resourcePriceList") and not price.get("resourcePriceDraftList"):
            price["resourcePriceDraftList"] = copy.deepcopy(price.get("resourcePriceList") or [])
        stock = package_price_stock.get("stock")
        if isinstance(stock, dict) and stock.get("resourceStockList") and not stock.get("resourceStockDraftList"):
            stock["resourceStockDraftList"] = copy.deepcopy(stock.get("resourceStockList") or [])


def build_price_effect_main_save_payload(
    product_id: str,
    package_info: dict[str, Any],
    price_stock_draft: dict[str, Any],
    product_version: Any,
    currency_context: CurrencyRewriteContext | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "productId": int(product_id) if str(product_id).isdigit() else product_id,
        "type": 0,
        "draftTypes": ["PackageInfo", "PriceAndStock"],
        "draftTypesRequired": ["PackageInfo", "PriceAndStock", "NegativeGrossProfit", "LowBrokerageRate"],
        "effectMarks": [3, 4],
        "productPackageInfo": package_info,
        "packagePriceAndStockList": price_stock_draft.get("packagePriceAndStockList") or [],
        "productPriceStock": price_stock_draft.get("productPriceStock"),
        "source": "PriceStock",
        "requestBaseData": {
            "extParameterList": [
                {"key": "page_version", "value": "5.3"},
                {"key": "needValidatePermission", "value": "true"},
            ]
        },
    }
    if product_version is not None:
        payload["productVersion"] = product_version
    for key in ("categoryId", "reserveMode"):
        if key in price_stock_draft:
            payload[key] = price_stock_draft.get(key)
    payload, _rewrite_count = apply_product_edit_currency_rewrite(payload, currency_context)
    return payload


AUDIT_WRITE_LOCK = threading.Lock()


def make_write_run_dir() -> Path:
    path = default_downloads_dir(create=True) / WRITE_RUNS_DIR_NAME / now_stamp()
    path.mkdir(parents=True, exist_ok=True)
    return path


def new_transaction_id() -> str:
    return uuid.uuid4().hex


def current_thread_id_text() -> str:
    return str(threading.get_ident())


def target_product_id(value: Any) -> str:
    return normalize_number_text(value)


def request_target_dict(target: ProductRequestTarget | TranslationRequestTarget | None, product_id: str = "") -> dict[str, str]:
    if isinstance(target, (ProductRequestTarget, TranslationRequestTarget)):
        return target.audit_dict()
    return {"productId": target_product_id(product_id)}


def payload_product_id(payload: dict[str, Any]) -> str:
    return target_product_id(payload.get("productId"))


def assert_product_payload_target(payload: dict[str, Any], target: ProductRequestTarget, context: str) -> None:
    actual = payload_product_id(payload)
    if actual != target.product_id:
        raise RuntimeError(f"{context} payload 产品 ID 不一致：期望 {target.product_id}，实际 {actual or '<empty>'}")


def assert_translation_payload_target(payload: dict[str, Any], target: TranslationRequestTarget, context: str) -> None:
    actual_product = payload_product_id(payload)
    actual_locale = str(payload.get("locale") or "")
    if actual_product != target.product_id or actual_locale != target.locale:
        raise RuntimeError(
            f"{context} payload 目标不一致：期望 {target.product_id}/{target.locale}，实际 {actual_product or '<empty>'}/{actual_locale or '<empty>'}"
        )


def validate_product_plan_targets(target: ProductRequestTarget, plans: list[DiffPlan]) -> None:
    for plan in plans:
        if target_product_id(plan.product_id) != target.product_id:
            raise RuntimeError(f"产品写入计划串线：当前目标 {target.product_id}，计划目标 {plan.product_id}")


def validate_translation_plan_targets(target: TranslationRequestTarget, plans: list[TranslationDiffPlan]) -> None:
    for plan in plans:
        plan_product_id = target_product_id(plan.product_id)
        if plan_product_id != target.product_id or str(plan.locale or "") != target.locale:
            raise RuntimeError(
                f"翻译写入计划串线：当前目标 {target.product_id}/{target.locale}，计划目标 {plan.product_id}/{plan.locale}"
            )


def write_audit_record(
    run_dir: Path,
    product_id: str,
    kind: str,
    record: dict[str, Any],
    target: ProductRequestTarget | TranslationRequestTarget | None = None,
    transaction_id: str = "",
) -> Path:
    safe_product_id = re.sub(r"[^0-9A-Za-z_-]+", "_", str(product_id)).strip("_") or "unknown"
    path = run_dir / f"{safe_product_id}_{kind}.jsonl"
    audit_record = dict(record)
    audit_record.setdefault("target", request_target_dict(target, product_id))
    audit_record.setdefault("transactionId", transaction_id or new_transaction_id())
    audit_record.setdefault("threadId", current_thread_id_text())
    with AUDIT_WRITE_LOCK:
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(audit_record, ensure_ascii=False) + "\n")
    return path


def parse_product_ids(text: str) -> list[str]:
    raw_items = [item.strip() for item in re.split(r"[\s,，;；]+", text or "") if item.strip()]
    result: list[str] = []
    seen: set[str] = set()
    for item in raw_items:
        normalized = normalize_number_text(item)
        if not normalized.isdigit():
            raise ValueError(f"产品ID必须是数字：{item}")
        if normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
    if not result:
        raise ValueError("请输入至少一个产品ID")
    return result


def parse_locale_codes(text: str) -> list[str]:
    if not normalize_cell(text) or normalize_cell(text).lower() in {"all", "全部", "所有"}:
        return []
    raw_items = [item.strip() for item in re.split(r"[\s,，;；]+", text or "") if item.strip()]
    result: list[str] = []
    seen: set[str] = set()
    for item in raw_items:
        if not re.fullmatch(r"[A-Za-z]{2,3}-[A-Za-z0-9]{2,4}", item):
            raise ValueError(f"语言代码格式无效：{item}，示例 en-US / ar-XX")
        language, region = item.split("-", 1)
        normalized = f"{language.lower()}-{region.upper()}"
        if normalized not in seen:
            seen.add(normalized)
            result.append(normalized)
    if not result:
        raise ValueError("请输入至少一个语言代码")
    return result


def product_order_map(product_ids: list[str]) -> dict[str, int]:
    result: dict[str, int] = {}
    for product_id in product_ids:
        key = str(product_id or "")
        if key and key not in result:
            result[key] = len(result)
    return result


def _sortable_row_number(value: int | str) -> tuple[int, str]:
    try:
        return int(value), ""
    except Exception:
        return 10**9, str(value or "")


def _product_order_key(product_id: str, product_order: dict[str, int] | None) -> tuple[int, str]:
    key = str(product_id or "")
    if not key:
        return 10**9 + 1, ""
    if product_order and key in product_order:
        return product_order[key], key
    return 10**9, key


def product_result_sort_key(item: ResultRow, product_order: dict[str, int] | None = None) -> tuple[Any, ...]:
    return (
        _product_order_key(item.product_id, product_order),
        _sortable_row_number(item.row_number),
        str(item.package_id or ""),
        str(item.resource_id or ""),
        str(item.field_name or ""),
        str(item.interface_name or ""),
        str(item.status or ""),
    )


def translation_result_sort_key(item: TranslationResultRow, product_order: dict[str, int] | None = None) -> tuple[Any, ...]:
    return (
        _product_order_key(item.product_id, product_order),
        str(item.locale or ""),
        _sortable_row_number(item.row_number),
        str(item.module_code or ""),
        str(item.field_code or ""),
        str(item.field_name or ""),
        str(item.self_key or ""),
        str(item.status or ""),
    )


def ordered_product_results(results: list[ResultRow], product_order: dict[str, int] | None = None) -> list[ResultRow]:
    return sorted(results, key=lambda item: product_result_sort_key(item, product_order))


def ordered_translation_results(results: list[TranslationResultRow], product_order: dict[str, int] | None = None) -> list[TranslationResultRow]:
    return sorted(results, key=lambda item: translation_result_sort_key(item, product_order))


def unique_product_ids(product_ids: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for product_id in product_ids:
        key = str(product_id or "").strip()
        if key and key not in seen:
            result.append(key)
            seen.add(key)
    return result


def successful_preload_audit_candidates(product_ids: list[str], successful_product_ids: set[str]) -> list[str]:
    successful = {str(product_id) for product_id in successful_product_ids}
    return [product_id for product_id in unique_product_ids(product_ids) if product_id in successful]


def select_submit_audit_product_ids(
    candidate_product_ids: list[str],
    last_saved_products: set[str],
    product_order: dict[str, int] | None = None,
) -> list[str]:
    candidates = unique_product_ids(candidate_product_ids)
    if candidates:
        return candidates
    return sorted((str(product_id) for product_id in last_saved_products), key=lambda product_id: _product_order_key(product_id, product_order))


def parse_online_flag(value: Any, default: bool = True) -> bool:
    if value is None or value == "":
        return default
    text = str(value).strip().lower()
    return text not in {"0", "false", "no", "n", "否", "不上线", "仅保存", "offline"}


def translation_request_base_data() -> dict[str, Any]:
    return {"extParameterList": [{"key": "page_version", "value": "4.0"}]}


def translation_field_key(product_id: str, locale: str, self_key: str) -> str:
    return f"{product_id}:{locale}:{self_key}"


def locale_code_from_item(item: Any) -> str:
    if isinstance(item, str):
        return item
    if isinstance(item, dict):
        return str(item.get("locale") or item.get("code") or item.get("value") or item.get("targetLocale") or "")
    return ""


def locale_codes_from_available(response: dict[str, Any], keys: list[str] | None = None) -> list[str]:
    result: list[str] = []
    for key in keys or ["allLocales", "availableLocales", "translatedLocales", "operableLocales"]:
        values = response.get(key)
        if not isinstance(values, list):
            continue
        for item in values:
            code = locale_code_from_item(item)
            if code and code not in result:
                result.append(code)
    return result


def locale_options_from_available(response: dict[str, Any]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for key in ("allLocales", "availableLocales", "translatedLocales", "operableLocales", "mainLocales", "aiLocales", "managedLocales"):
        for item in response.get(key) or []:
            code = locale_code_from_item(item)
            if not code:
                continue
            entry = result.setdefault(code, {"locale": code})
            entry[key] = True
            if isinstance(item, dict):
                for meta_key in ("name", "text", "label", "language", "status", "localeName"):
                    if meta_key in item and item.get(meta_key) not in (None, ""):
                        entry[meta_key] = item.get(meta_key)
    return result


def zh_sgmy_interface_locale(locale: str) -> bool:
    return translation_rules.get_lang_group(locale) == "zh-sgmy"


def ar_primary_interface_locale(locale: str) -> bool:
    return str(locale or "").strip().replace("_", "-").lower() == "ar-xx"


def ar_interface_locale(locale: str) -> bool:
    return translation_rules.get_lang_group(locale) == "ar"


def locale_allows_initial_online(locale: str, locale_option: dict[str, Any]) -> bool:
    if not ar_primary_interface_locale(locale):
        return False
    if not locale_option:
        return True
    return bool(locale_option.get("allLocales") or locale_option.get("availableLocales") or locale_option.get("operableLocales"))


def locale_is_unopened(locale_option: dict[str, Any]) -> bool:
    return bool(locale_option) and not locale_option.get("operableLocales") and not locale_translated(locale_option)


def locale_allowed_for_write(locale: str, locale_option: dict[str, Any], include_unopened: bool = False) -> bool:
    if not locale_option or locale_option.get("operableLocales") or locale_translated(locale_option):
        return True
    if locale_allows_initial_online(locale, locale_option):
        return True
    if include_unopened and (locale_option.get("allLocales") or locale_option.get("availableLocales")):
        return True
    return zh_sgmy_interface_locale(locale)


def locale_requires_baseline_fill(locale: str, locale_option: dict[str, Any]) -> bool:
    """空站点写入前需要先用同组完整译本补齐：中文(新马)沿用原有规则，其它语言仅在未开站时补齐。"""
    return zh_sgmy_interface_locale(locale) or locale_is_unopened(locale_option)


def locale_translated(locale_option: dict[str, Any]) -> bool:
    return bool(locale_option and locale_option.get("translatedLocales"))


def locale_status(locale_option: dict[str, Any]) -> int | None:
    value = (locale_option or {}).get("status")
    try:
        return int(value)
    except Exception:
        return None


def locale_already_online(locale_option: dict[str, Any]) -> bool:
    return locale_translated(locale_option) and locale_status(locale_option) == 1


def locale_can_submit_online(locale_option: dict[str, Any]) -> bool:
    return locale_translated(locale_option) and not locale_already_online(locale_option)


def locales_for_selected_language_groups(
    all_locales: list[str],
    selected_languages: set[str],
    locale_options: dict[str, dict[str, Any]] | None = None,
) -> list[str]:
    result: list[str] = []
    options = locale_options or {}
    has_ar_xx = any(ar_primary_interface_locale(locale) for locale in all_locales)
    for lang_group in selected_languages:
        for preferred_locale in translation_rules.interface_locales_for_lang_group(lang_group):
            for locale in all_locales:
                if locale.lower() == preferred_locale.lower() and locale not in result:
                    result.append(locale)
    for locale in all_locales:
        if translation_rules.get_lang_group(locale) not in selected_languages or locale in result:
            continue
        if has_ar_xx and ar_interface_locale(locale) and not ar_primary_interface_locale(locale):
            locale_option = options.get(locale, {})
            if not locale_option.get("operableLocales") and not locale_translated(locale_option):
                continue
        result.append(locale)
    return result


def translation_field_value(field: dict[str, Any]) -> tuple[str, str]:
    for key in ("translation", "targetValue", "target", "value", "content", "fieldValue", "translateValue"):
        if key in field:
            value = field.get(key)
            return key, "" if value is None else str(value)
    return "value", ""


def translation_field_origin(field: dict[str, Any]) -> str:
    for key in ("origin", "originValue", "sourceValue", "source", "original", "originalValue"):
        if key in field and field.get(key) is not None:
            return str(field.get(key))
    return ""


def translation_field_meta_map(response: dict[str, Any]) -> dict[str, str]:
    result: dict[str, str] = {}
    for list_name in ("activityFieldMetaList", "ticketFieldMetaList", "fieldMetaList"):
        values = response.get(list_name)
        if not isinstance(values, list):
            continue
        for item in values:
            if not isinstance(item, dict):
                continue
            code = str(item.get("fieldCode") or item.get("code") or "")
            name = str(item.get("fieldName") or item.get("name") or "")
            if code and name:
                result[code] = name
    for code, label in LEGACY_TRANSLATION_FIELD_LABELS.items():
        result.setdefault(code, label)
    return result


def translation_modules_from_locale(raw: dict[str, Any]) -> list[dict[str, Any]]:
    modules = raw.get("translationModules")
    return modules if isinstance(modules, list) else []


TRANSLATION_BASELINE_FIELD_CODES = {"productName", "feeInclude", "feeExclude", "productIntroduction"}
TRANSLATION_INITIAL_ONLINE_REQUIRED_FIELDS = {"productName", "feeInclude", "feeExclude", "productIntroduction"}


def iter_translation_fields(
    items: Any,
    module_code: str = "",
    module_name: str = "",
    path: str = "",
) -> Any:
    if isinstance(items, list):
        for index, item in enumerate(items):
            yield from iter_translation_fields(item, module_code, module_name, f"{path}/{index}" if path else str(index))
        return
    if not isinstance(items, dict):
        return

    current_module_code = str(items.get("moduleCode") or items.get("moduleType") or items.get("code") or module_code)
    current_module_name = str(items.get("moduleName") or items.get("name") or module_name)
    if items.get("fieldCode") and any(key in items for key in ("translation", "origin", "originLast", "ibuKey", "selfKey", "valueKey")):
        yield current_module_code, current_module_name, path, items

    for child_key in ("subItems", "children", "items", "translationModules"):
        children = items.get(child_key)
        if isinstance(children, list):
            yield from iter_translation_fields(children, current_module_code, current_module_name, f"{path}/{child_key}" if path else child_key)
    field_list = items.get("fields")
    if isinstance(field_list, list):
        yield from iter_translation_fields(field_list, current_module_code, current_module_name, f"{path}/fields" if path else "fields")


def translation_field_values_by_code(raw: dict[str, Any]) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for _module_code, _module_name, _path, field in iter_translation_fields(translation_modules_from_locale(raw)):
        field_code = str(field.get("fieldCode") or field.get("code") or "")
        if not field_code:
            continue
        _value_key, value = translation_field_value(field)
        result.setdefault(field_code, []).append(value)
    return result


def translation_missing_required_fields_after_plans(raw: dict[str, Any], plans: list[TranslationDiffPlan]) -> list[str]:
    by_self_key = {str(plan.self_key or ""): str(plan.new_value or "") for plan in plans}
    by_path = {str(plan.self_key)[5:]: str(plan.new_value or "") for plan in plans if str(plan.self_key).startswith("path:")}
    values_by_code: dict[str, list[str]] = {}
    for _module_code, _module_name, path, field in iter_translation_fields(translation_modules_from_locale(raw)):
        field_code = str(field.get("fieldCode") or field.get("code") or "")
        if field_code not in TRANSLATION_INITIAL_ONLINE_REQUIRED_FIELDS:
            continue
        self_key = str(field.get("selfKey") or field.get("key") or "")
        _value_key, value = translation_field_value(field)
        if self_key in by_self_key:
            value = by_self_key[self_key]
        elif path in by_path:
            value = by_path[path]
        values_by_code.setdefault(field_code, []).append(value)
    missing: list[str] = []
    for field_code in sorted(TRANSLATION_INITIAL_ONLINE_REQUIRED_FIELDS):
        values = values_by_code.get(field_code) or []
        if values and any(not str(value or "").strip() for value in values):
            missing.append(field_code)
    return missing


def translation_locale_needs_baseline(raw: dict[str, Any]) -> bool:
    values_by_code = translation_field_values_by_code(raw)
    if not values_by_code:
        return False
    for field_code in TRANSLATION_BASELINE_FIELD_CODES:
        values = values_by_code.get(field_code) or []
        if any(not str(value or "").strip() for value in values):
            return True
    return False


def translation_locale_has_baseline_content(raw: dict[str, Any]) -> bool:
    values_by_code = translation_field_values_by_code(raw)
    if not values_by_code:
        return False
    scored_values = [
        value
        for field_code in TRANSLATION_BASELINE_FIELD_CODES
        for value in values_by_code.get(field_code, [])
    ]
    return any(str(value or "").strip() for value in scored_values)


def translation_fields_for_locale(snapshot: TranslationSnapshot, locale: str) -> list[TranslationFieldSnapshot]:
    return [field for field in snapshot.fields.values() if field.locale == locale]


def translation_locale_needs_baseline_fields(fields: list[TranslationFieldSnapshot]) -> bool:
    values_by_code: dict[str, list[str]] = {}
    for field in fields:
        if field.field_code in TRANSLATION_BASELINE_FIELD_CODES:
            values_by_code.setdefault(field.field_code, []).append(field.old_translation)
    if not values_by_code:
        return False
    for field_code in TRANSLATION_BASELINE_FIELD_CODES:
        values = values_by_code.get(field_code) or []
        if any(not str(value or "").strip() for value in values):
            return True
    return False


def translation_locale_has_baseline_content_fields(fields: list[TranslationFieldSnapshot]) -> bool:
    scored_values = [
        field.old_translation
        for field in fields
        if field.field_code in TRANSLATION_BASELINE_FIELD_CODES
    ]
    return any(str(value or "").strip() for value in scored_values)


def translation_snapshot_locale_needs_baseline(snapshot: TranslationSnapshot, locale: str) -> bool:
    return translation_locale_needs_baseline_fields(translation_fields_for_locale(snapshot, locale))


def translation_baseline_source_locale(snapshot: TranslationSnapshot, target_locale: str) -> str:
    target_option = (snapshot.locale_options or {}).get(target_locale, {})
    if not locale_requires_baseline_fill(target_locale, target_option):
        return ""
    if not translation_snapshot_locale_needs_baseline(snapshot, target_locale):
        return ""
    target_lower = target_locale.lower()
    target_group = translation_rules.get_lang_group(target_locale)
    candidates: list[tuple[int, int, str]] = []
    for locale in snapshot.locales:
        if locale == target_locale or translation_rules.get_lang_group(locale) != target_group:
            continue
        if not translation_locale_has_baseline_content_fields(translation_fields_for_locale(snapshot, locale)):
            continue
        option = (snapshot.locale_options or {}).get(locale, {})
        translated_score = 1 if option.get("translatedLocales") else 0
        preferred_score = 1 if target_lower == "zh-sg" and locale.lower() == "zh-my" else 0
        candidates.append((translated_score, preferred_score, locale))
    if not candidates:
        return ""
    return sorted(candidates, reverse=True)[0][2]


def translation_fields_by_path(raw: dict[str, Any]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for _module_code, _module_name, path, field in iter_translation_fields(translation_modules_from_locale(raw)):
        if path:
            result[path] = field
    return result


def fill_translation_empty_values_from_baseline(target_raw: dict[str, Any], source_raw: dict[str, Any]) -> dict[str, Any]:
    merged = copy.deepcopy(target_raw)
    target_fields = translation_fields_by_path(merged)
    source_fields = translation_fields_by_path(source_raw)
    for path, target_field in target_fields.items():
        source_field = source_fields.get(path)
        if not isinstance(source_field, dict):
            continue
        target_value_key, target_value = translation_field_value(target_field)
        _source_value_key, source_value = translation_field_value(source_field)
        if str(target_value or "").strip() or not str(source_value or "").strip():
            continue
        target_field[target_value_key or "translation"] = source_value
        if "aiGen" in target_field:
            target_field["aiGen"] = False
    return merged


def build_translation_snapshot_from_response(
    product_id: str,
    locales: list[str],
    response: dict[str, Any],
    locale_options: dict[str, dict[str, Any]] | None = None,
    retain_raw: bool = False,
) -> TranslationSnapshot:
    meta = translation_field_meta_map(response)
    raw_sources_by_locale: dict[str, dict[str, Any]] = {}
    raw_by_locale: dict[str, dict[str, Any]] = {}
    translations = response.get("translations")
    if isinstance(translations, list):
        for item in translations:
            if not isinstance(item, dict):
                continue
            locale = str(item.get("targetLocale") or item.get("locale") or "")
            if locale:
                raw_sources_by_locale[locale] = item
                if retain_raw:
                    raw_by_locale[locale] = item
    elif translation_modules_from_locale(response):
        locale = locales[0] if locales else str(response.get("targetLocale") or response.get("locale") or "")
        if locale:
            raw_sources_by_locale[locale] = response
            if retain_raw:
                raw_by_locale[locale] = response

    snapshot_locales = [locale for locale in locales if locale in raw_sources_by_locale]
    for locale in raw_sources_by_locale:
        if locale not in snapshot_locales:
            snapshot_locales.append(locale)

    fields: dict[str, TranslationFieldSnapshot] = {}
    for locale in snapshot_locales:
        raw = raw_sources_by_locale.get(locale)
        if not isinstance(raw, dict):
            continue
        for module_code, module_name, path, field in iter_translation_fields(translation_modules_from_locale(raw)):
            field_code = str(field.get("fieldCode") or field.get("code") or "")
            if field_code not in LEGACY_TRANSLATION_FIELD_CODES:
                continue
            self_key = str(field.get("selfKey") or field.get("key") or "")
            if not self_key and path:
                self_key = f"path:{path}"
            if not self_key:
                continue
            value_key, old_translation = translation_field_value(field)
            field_name = str(field.get("fieldName") or field.get("name") or meta.get(field_code) or field_code)
            snapshot_field = TranslationFieldSnapshot(
                product_id=product_id,
                locale=locale,
                module_code=module_code,
                module_name=module_name,
                field_code=field_code,
                field_name=field_name,
                value_key=value_key,
                self_key=self_key,
                path=path,
                origin=translation_field_origin(field),
                old_translation=old_translation,
            )
            fields[translation_field_key(product_id, locale, self_key)] = snapshot_field
    return TranslationSnapshot(
        product_id=product_id,
        created_at=now_iso(),
        locales=snapshot_locales,
        raw_by_locale=raw_by_locale,
        fields=fields,
        locale_options=locale_options,
    )


def apply_translation_to_modules(items: Any, self_key: str, value_key: str, new_value: str) -> bool:
    if str(self_key).startswith("path:"):
        return apply_translation_by_path(items, str(self_key)[5:], value_key, new_value)
    changed = False
    if isinstance(items, list):
        for item in items:
            changed = apply_translation_to_modules(item, self_key, value_key, new_value) or changed
        return changed
    if not isinstance(items, dict):
        return False

    if str(items.get("selfKey") or items.get("key") or "") == self_key:
        items[value_key or "value"] = new_value
        if "aiGen" in items:
            items["aiGen"] = False
        changed = True

    field_list = items.get("fields")
    if isinstance(field_list, list):
        for field in field_list:
            if not isinstance(field, dict):
                continue
            if str(field.get("selfKey") or field.get("key") or "") == self_key:
                field[value_key or "value"] = new_value
                if "aiGen" in field:
                    field["aiGen"] = False
                changed = True
            for child_key in ("subItems", "children", "items"):
                changed = apply_translation_to_modules(field.get(child_key), self_key, value_key, new_value) or changed

    for child_key in ("subItems", "children", "items", "translationModules"):
        changed = apply_translation_to_modules(items.get(child_key), self_key, value_key, new_value) or changed
    return changed


def apply_translation_by_path(items: Any, path: str, value_key: str, new_value: str) -> bool:
    current = items
    if not path:
        return False
    for part in path.split("/"):
        if isinstance(current, list):
            if not part.isdigit():
                return False
            index = int(part)
            if index < 0 or index >= len(current):
                return False
            current = current[index]
            continue
        if isinstance(current, dict):
            current = current.get(part)
            continue
        return False
    if not isinstance(current, dict):
        return False
    current[value_key or "translation"] = new_value
    if "aiGen" in current:
        current["aiGen"] = False
    return True


def normalize_translation_push_fields(items: Any) -> None:
    if isinstance(items, list):
        for item in items:
            normalize_translation_push_fields(item)
        return
    if not isinstance(items, dict):
        return
    field_code = str(items.get("fieldCode") or items.get("code") or "")
    if field_code:
        _value_key, value = translation_field_value(items)
        if not str(value or "").strip():
            origin = translation_field_origin(items)
            if str(origin or "").strip():
                value = origin
        if "translation" not in items:
            items["translation"] = value
        elif not str(items.get("translation") or "").strip() and str(value or "").strip():
            items["translation"] = value
        if "ibuKey" not in items:
            items["ibuKey"] = field_code
    for child_key in ("fields", "subItems", "children", "items", "translationModules"):
        if child_key in items:
            normalize_translation_push_fields(items.get(child_key))


def build_translation_template_workbook(path: str, snapshots: dict[str, TranslationSnapshot]) -> None:
    if openpyxl is None:
        raise RuntimeError("缺少 openpyxl，无法生成模板。请先运行：py -3 -m pip install -r requirements.txt")
    if not snapshots:
        raise RuntimeError("请先预载翻译件")

    from openpyxl.styles import Font, PatternFill
    from openpyxl.worksheet.datavalidation import DataValidation

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = TRANSLATION_TEMPLATE_SHEET
    headers = [
        "productId",
        "locale",
        "operable",
        "translated",
        "mainLocale",
        "aiLocale",
        "moduleCode",
        "fieldCode",
        "fieldName",
        "valueKey",
        "selfKey",
        "origin",
        "old_translation",
        "target_translation",
        "online",
    ]
    ws.append(headers)
    readonly_fill = PatternFill("solid", fgColor="E7E6E6")
    target_fill = PatternFill("solid", fgColor="FFF2CC")
    for cell in ws[1]:
        cell.font = Font(bold=True)
        cell.fill = target_fill if cell.value in {"target_translation", "online"} else readonly_fill
    for snapshot in snapshots.values():
        for field in snapshot.fields.values():
            ws.append(
                [
                    field.product_id,
                    field.locale,
                    "是" if (snapshot.locale_options or {}).get(field.locale, {}).get("operableLocales") else "否",
                    "是" if (snapshot.locale_options or {}).get(field.locale, {}).get("translatedLocales") else "否",
                    "是" if (snapshot.locale_options or {}).get(field.locale, {}).get("mainLocales") else "否",
                    "是" if (snapshot.locale_options or {}).get(field.locale, {}).get("aiLocales") else "否",
                    field.module_code,
                    field.field_code,
                    field.field_name,
                    field.value_key,
                    field.self_key,
                    field.origin,
                    field.old_translation,
                    "",
                    "是",
                ]
            )
    widths = (16, 14, 10, 10, 12, 10, 18, 24, 24, 14, 46, 52, 52, 52, 12)
    for col_idx, width in enumerate(widths, start=1):
        ws.column_dimensions[openpyxl.utils.get_column_letter(col_idx)].width = width
    ws.freeze_panes = "A2"
    online_dv = DataValidation(type="list", formula1='"是,否"', allow_blank=True)
    ws.add_data_validation(online_dv)
    online_dv.add("O2:O10000")

    options = wb.create_sheet(TRANSLATION_OPTIONS_SHEET)
    options.append(["fieldCode", "fieldName"])
    for code, name in LEGACY_TRANSLATION_FIELD_LABELS.items():
        options.append([code, name])
    for col in range(1, 3):
        options.column_dimensions[openpyxl.utils.get_column_letter(col)].width = 28
    for cell in options[1]:
        cell.font = Font(bold=True)
        cell.fill = readonly_fill
    locale_ws = wb.create_sheet("语言列表")
    locale_ws.append(["productId", "locale", "operable", "translated", "available", "mainLocale", "aiLocale", "managed", "status", "name"])
    for snapshot in snapshots.values():
        for locale, option in sorted((snapshot.locale_options or {}).items()):
            locale_ws.append(
                [
                    snapshot.product_id,
                    locale,
                    "是" if option.get("operableLocales") else "否",
                    "是" if option.get("translatedLocales") else "否",
                    "是" if option.get("availableLocales") else "否",
                    "是" if option.get("mainLocales") else "否",
                    "是" if option.get("aiLocales") else "否",
                    "是" if option.get("managedLocales") else "否",
                    option.get("status", ""),
                    option.get("name") or option.get("label") or option.get("localeName") or "",
                ]
            )
    for col_idx, width in enumerate((16, 14, 10, 10, 10, 12, 10, 10, 12, 24), start=1):
        locale_ws.column_dimensions[openpyxl.utils.get_column_letter(col_idx)].width = width
    for cell in locale_ws[1]:
        cell.font = Font(bold=True)
        cell.fill = readonly_fill

    meta = wb.create_sheet("说明")
    meta.append(["说明", "值"])
    meta.append(["生成时间", now_iso()])
    meta.append(["写入方式", "通过 productTranslationPush 发送完整 locale translationModules"])
    meta.append(["语言来源", "语言代码填 ALL 或留空时，先读取 productTranslationAvailableLocales，再用 allLocales 拉取完整 translations"])
    meta.append(["可写语言", "operable=是 或 translated=是 的语言会被程序允许传出；非 operable/translated 语言可能因必填字段为空或源语言限制被接口拒绝"])
    meta.append(["空目标翻译", "target_translation 留空会跳过，不会清空线上翻译"])
    meta.append(["online", "默认 是，表示保存并上线；填 否 表示仅保存"])
    meta.append(["aiGen", "写入请求固定 aiGen=false，按人工翻译处理"])
    wb.save(path)


def read_translation_template(path: str) -> list[TranslationTemplateRow]:
    if openpyxl is None:
        raise RuntimeError("缺少 openpyxl，请先运行：py -3 -m pip install -r requirements.txt")
    wb = openpyxl.load_workbook(path, data_only=True)
    ws = wb[TRANSLATION_TEMPLATE_SHEET] if TRANSLATION_TEMPLATE_SHEET in wb.sheetnames else wb.active
    headers: dict[str, int] = {}
    for idx, cell in enumerate(ws[1], start=1):
        name = normalize_cell(cell.value)
        if name:
            headers[name] = idx
    required = ["productId", "locale", "fieldCode", "valueKey", "selfKey"]
    missing = [name for name in required if name not in headers]
    if missing:
        raise ValueError(f"翻译回填模板缺少必填列：{', '.join(missing)}")

    def get_value(row_idx: int, column_name: str) -> str:
        column = headers.get(column_name)
        if not column:
            return ""
        return normalize_cell(ws.cell(row_idx, column).value)

    rows: list[TranslationTemplateRow] = []
    for row_idx in range(2, ws.max_row + 1):
        target_translation = get_value(row_idx, "target_translation")
        if not target_translation:
            continue
        row = TranslationTemplateRow(
            row_number=row_idx,
            product_id=normalize_number_text(get_value(row_idx, "productId")),
            locale=get_value(row_idx, "locale"),
            module_code=get_value(row_idx, "moduleCode"),
            field_code=get_value(row_idx, "fieldCode"),
            field_name=get_value(row_idx, "fieldName"),
            value_key=get_value(row_idx, "valueKey"),
            self_key=get_value(row_idx, "selfKey"),
            origin=get_value(row_idx, "origin"),
            old_translation=get_value(row_idx, "old_translation"),
            target_translation=target_translation,
            online=parse_online_flag(ws.cell(row_idx, headers["online"]).value, default=True) if "online" in headers else True,
        )
        if not any([row.product_id, row.locale, row.field_code, row.self_key, target_translation]):
            continue
        errors: list[str] = []
        if not row.product_id:
            errors.append("productId 不能为空")
        if not row.locale:
            errors.append("locale 不能为空")
        if not row.field_code:
            errors.append("fieldCode 不能为空")
        if not row.self_key:
            errors.append("selfKey 不能为空")
        if row.field_code and row.field_code not in LEGACY_TRANSLATION_FIELD_CODES:
            errors.append(f"fieldCode 不属于翻译接口字段范围：{row.field_code}")
        row.validation_error = "；".join(errors)
        rows.append(row)
    return rows


def build_translation_diff_plans(
    snapshots: dict[str, TranslationSnapshot],
    rows: list[TranslationTemplateRow],
    include_unopened_locales: bool = False,
) -> list[TranslationDiffPlan]:
    plans: list[TranslationDiffPlan] = []
    for row in rows:
        if row.validation_error:
            status = "skipped" if "target_translation 为空" in row.validation_error else "invalid"
            plans.append(
                TranslationDiffPlan(
                    row,
                    row.product_id,
                    row.locale,
                    row.module_code,
                    row.field_code,
                    row.field_name,
                    row.self_key,
                    row.old_translation,
                    row.target_translation,
                    row.online,
                    status=status,
                    message=row.validation_error,
                )
            )
            continue
        snapshot = snapshots.get(row.product_id)
        if not snapshot:
            plans.append(TranslationDiffPlan(row, row.product_id, row.locale, row.module_code, row.field_code, row.field_name, row.self_key, "", row.target_translation, row.online, status="invalid", message="内存快照不存在，请重新预载翻译件"))
            continue
        locale_option = (snapshot.locale_options or {}).get(row.locale, {})
        if not locale_allowed_for_write(row.locale, locale_option, include_unopened_locales):
            plans.append(TranslationDiffPlan(row, row.product_id, row.locale, row.module_code, row.field_code, row.field_name, row.self_key, row.old_translation, row.target_translation, row.online, status="invalid", message="该语言未开站且不在 operableLocales，接口版默认跳过"))
            continue
        if row.online and not locale_translated(locale_option) and not locale_allows_initial_online(row.locale, locale_option):
            row.online = False
        baseline_source_locale = translation_baseline_source_locale(snapshot, row.locale)
        if locale_requires_baseline_fill(row.locale, locale_option) and translation_snapshot_locale_needs_baseline(snapshot, row.locale) and not baseline_source_locale:
            plans.append(TranslationDiffPlan(row, row.product_id, row.locale, row.module_code, row.field_code, row.field_name, row.self_key, row.old_translation, row.target_translation, row.online, status="invalid", message="目标翻译本为空，且未找到同组完整译本可补齐"))
            continue
        field = snapshot.fields.get(translation_field_key(row.product_id, row.locale, row.self_key))
        if not field:
            plans.append(TranslationDiffPlan(row, row.product_id, row.locale, row.module_code, row.field_code, row.field_name, row.self_key, "", row.target_translation, row.online, status="invalid", message="内存快照中未找到该翻译字段"))
            continue
        status = "unchanged" if row.target_translation == field.old_translation else "pending"
        message = "目标翻译与当前快照一致" if status == "unchanged" else ""
        if status == "pending" and baseline_source_locale:
            message = f"空站点将先用 {baseline_source_locale} 完整译本补齐再写入"
        if status == "pending" and not row.online and not locale_translated(locale_option):
            message = (message + "；" if message else "") + "该语言预载时未开站，本次仅保存不上线"
        if status == "pending" and row.online and locale_already_online(locale_option):
            message = (message + "；" if message else "") + "该语言预载时已上线，本次字段写入仍使用 online=true"
        plans.append(
            TranslationDiffPlan(
                row,
                row.product_id,
                row.locale,
                field.module_code,
                field.field_code,
                field.field_name,
                field.self_key,
                field.old_translation,
                row.target_translation,
                row.online,
                status=status,
                message=message,
                baseline_source_locale=baseline_source_locale,
            )
        )
    return plans


def natural_path_key(path: str) -> list[Any]:
    return [int(part) if part.isdigit() else part for part in re.split(r"(\d+)", str(path or ""))]


def make_translation_row_for_field(
    task: translation_rules.TranslationRuleTask,
    snapshot: TranslationSnapshot,
    field: TranslationFieldSnapshot,
    target: str,
    online: bool,
    message: str = "",
) -> TranslationTemplateRow:
    return TranslationTemplateRow(
        row_number=task.row_number,
        product_id=task.product_id,
        locale=field.locale,
        module_code=field.module_code,
        field_code=field.field_code,
        field_name=field.field_name,
        value_key=field.value_key,
        self_key=field.self_key,
        origin=field.origin,
        old_translation=field.old_translation,
        target_translation=target,
        online=online,
        validation_error=message,
    )


def make_translation_rule_invalid_plan(task: translation_rules.TranslationRuleTask, product_id: str, locale: str, module_key: str, message: str) -> TranslationDiffPlan:
    row = TranslationTemplateRow(
        row_number=task.row_number,
        product_id=product_id,
        locale=locale,
        module_code=module_key,
        field_code=module_key,
        field_name=translation_rules.MODULE_LABELS.get(module_key, module_key),
        value_key="",
        self_key="",
        origin="",
        old_translation="",
        target_translation="",
        online=True,
        validation_error=message,
    )
    return TranslationDiffPlan(row, product_id, locale, module_key, module_key, row.field_name, "", "", "", True, status="invalid", message=message)


def fields_for_locale(snapshot: TranslationSnapshot, locale: str) -> list[TranslationFieldSnapshot]:
    fields = [field for field in snapshot.fields.values() if field.locale == locale]
    return sorted(fields, key=lambda field: natural_path_key(field.path))


def first_field_by_code(fields: list[TranslationFieldSnapshot], field_code: str) -> TranslationFieldSnapshot | None:
    for field in fields:
        if field.field_code == field_code:
            return field
    return None


def package_desc_for_field(fields: list[TranslationFieldSnapshot], target_field: TranslationFieldSnapshot) -> str:
    target_index = fields.index(target_field) if target_field in fields else -1
    for field in reversed(fields[:target_index]):
        if field.field_code == "packageDesc":
            return field.origin or field.old_translation
    return target_field.origin


def _normalize_sales_property_origin(origin: str) -> str:
    text = str(origin or "").strip()
    text = re.sub(r"\s+", "", text)
    text = re.sub(r"[^\w\d\u4e00-\u9fff]+", "", text.lower())
    return text


_SALES_PROPERTY_NAME_ALIASES: dict[int, list[str]] = {
    0: [
        "取卡方式",
        "取卡方法",
        "取件方式",
        "领取方式",
        "收货方式",
        "收卡方式",
        "collectionmethod",
        "mottagningssätt",
    ],
    1: [
        "套餐天数",
        "套餐天數",
        "套餐日",
        "套餐天",
        "天数",
        "天數",
        "天",
        "日",
        "days",
        "day",
    ],
    2: [
        "套餐内容",
        "套餐內容",
        "套餐详情",
        "內容",
        "內容",
        "内容",
        "详情",
        "詳情",
        "plandetaljer",
        "plandetails",
        "detail",
    ],
}


def _match_sales_property_name_index(locale_sales_names: list[str], origin: str) -> int | None:
    normalized_origin = _normalize_sales_property_origin(origin)
    if not normalized_origin:
        return None

    for index, fixed_name in enumerate(locale_sales_names):
        if not fixed_name:
            continue
        normalized_name = _normalize_sales_property_origin(fixed_name)
        if normalized_name and (
            normalized_origin == normalized_name
            or normalized_origin.startswith(normalized_name)
            or normalized_name in normalized_origin
        ):
            return index

    for index, aliases in _SALES_PROPERTY_NAME_ALIASES.items():
        for alias in aliases:
            normalized_alias = _normalize_sales_property_origin(alias)
            if not normalized_alias:
                continue
            if (
                normalized_origin == normalized_alias
                or normalized_origin.startswith(normalized_alias)
                or normalized_alias in normalized_origin
            ):
                return index
    return None


def build_translation_rule_diff_plans(
    snapshots: dict[str, TranslationSnapshot],
    tasks: list[translation_rules.TranslationRuleTask],
    detail_template_path: str,
    package_template_path: str,
    config: translation_rules.TranslationExecutionConfig,
    client: CtripRequestsClient | None = None,
    client_factory: Callable[[], CtripRequestsClient] | None = None,
    stop_event: threading.Event | None = None,
    preload_errors: dict[str, str] | None = None,
) -> list[TranslationDiffPlan]:
    detail_store = translation_rules.DetailTemplateExcelStore()
    detail_store.load_template_from_path(detail_template_path)
    package_template: dict[str, Any] = {}
    needs_package = any(key in config.selected_modules for key in ("package_detail", "package_quantity"))
    if needs_package:
        if not package_template_path:
            package_template = {}
        else:
            package_template = translation_rules.load_package_template_xlsx(package_template_path)

    generated_rows: list[TranslationTemplateRow] = []
    direct_plans: list[TranslationDiffPlan] = []
    ai_reference_cache: dict[tuple[str, str, str], str] = {}
    selected_languages = set(config.selected_languages or [])
    preload_errors = preload_errors or {}
    for task in tasks:
        snapshot = snapshots.get(task.product_id)
        if not snapshot:
            message = preload_errors.get(task.product_id) or "内存翻译快照不存在，请先预载并生成Diff"
            direct_plans.append(make_translation_rule_invalid_plan(task, task.product_id, "", "translation_rule_preload", message))
            continue
        for locale in snapshot.locales:
            lang_group = translation_rules.get_lang_group(locale)
            if selected_languages and lang_group not in selected_languages:
                continue
            locale_option = (snapshot.locale_options or {}).get(locale, {})
            if not locale_allowed_for_write(locale, locale_option, config.include_unopened_locales):
                direct_plans.append(make_translation_rule_invalid_plan(task, task.product_id, locale, "locale", "该语言未开站且不在 operableLocales，接口版默认跳过"))
                continue
            baseline_source_locale = translation_baseline_source_locale(snapshot, locale)
            if locale_requires_baseline_fill(locale, locale_option) and translation_snapshot_locale_needs_baseline(snapshot, locale) and not baseline_source_locale:
                direct_plans.append(make_translation_rule_invalid_plan(task, task.product_id, locale, "locale", "目标翻译本为空，且未找到同组完整译本可补齐"))
                continue
            locale_fields = fields_for_locale(snapshot, locale)
            if (
                "post_booking_reminder" in config.selected_modules
                and translation_rules.detail_template_module_reuses_english(
                    detail_store,
                    locale,
                    "post_booking_reminder",
                )
            ):
                direct_plans.append(
                    make_translation_rule_invalid_plan(
                        task,
                        task.product_id,
                        locale,
                        "post_booking_reminder",
                        "当前语言的订后出行提醒与英文模板完全相同，已跳过该字段并保留线上现有翻译",
                    )
                )
            static_targets = translation_rules.generated_translation_static_targets(detail_store, locale, task.row_data, config.selected_modules)
            for field_code, target in static_targets.items():
                target_fields = [field for field in locale_fields if field.field_code == field_code]
                if not target_fields:
                    direct_plans.append(make_translation_rule_invalid_plan(task, task.product_id, locale, field_code, f"接口快照未找到字段 {field_code}"))
                    continue
                for field in target_fields:
                    generated_rows.append(make_translation_row_for_field(task, snapshot, field, target, config.online))

            if "sales_property" in config.selected_modules:
                fixed = translation_rules.FIXED_CONTENT.get(translation_rules.fixed_content_key(locale), {})
                sales_names = list(fixed.get("sales_property") or [])
                sales_name_fields = [field for field in locale_fields if field.field_code == "salesPropertyName"]
                used_sales_indexes: set[int] = set()
                sales_name_fields = sales_name_fields[: len(sales_names)]
                unmatched_sales_name_fields: list[TranslationFieldSnapshot] = []
                for field in sales_name_fields:
                    index = _match_sales_property_name_index(sales_names, field.origin)
                    if index is not None and index not in used_sales_indexes:
                        generated_rows.append(make_translation_row_for_field(task, snapshot, field, sales_names[index], config.online))
                        used_sales_indexes.add(index)
                    else:
                        unmatched_sales_name_fields.append(field)

                for field in unmatched_sales_name_fields:
                    for index in range(len(sales_names)):
                        if index in used_sales_indexes:
                            continue
                        generated_rows.append(make_translation_row_for_field(task, snapshot, field, sales_names[index], config.online))
                        used_sales_indexes.add(index)
                        break
                for field in [item for item in locale_fields if item.field_code == "salesPropertyValueName"]:
                    target = translation_rules.translate_sales_property_value(field.origin, locale, config.sales_attr_mode)
                    if not target and config.sales_attr_mode == "ai_translation" and field.origin and (client or client_factory) and stop_event:
                        cache_key = (task.product_id, locale, field.origin)
                        if cache_key not in ai_reference_cache:
                            query_client = client_factory() if client_factory is not None else client
                            if query_client is None:
                                ai_reference_cache[cache_key] = ""
                            else:
                                ai_reference_cache[cache_key] = query_client.query_ai_translation_reference(task.product_id, locale, field.origin, stop_event)
                        target = ai_reference_cache[cache_key]
                    if target:
                        generated_rows.append(make_translation_row_for_field(task, snapshot, field, target, config.online))

            if "package_detail" in config.selected_modules:
                if not package_template:
                    direct_plans.append(make_translation_rule_invalid_plan(task, task.product_id, locale, "package_detail", "未加载套餐规格模板，跳过套餐规格详情"))
                for field in [item for item in locale_fields if item.field_code == "packageIntroduction"]:
                    desc = package_desc_for_field(locale_fields, field)
                    days, data_type, data_capacity, capacity_descriptor = translation_rules.package_info_from_origin_with_descriptor(desc)
                    if not days:
                        continue
                    target = translation_rules.package_template_text(
                        package_template,
                        locale,
                        data_capacity,
                        data_type,
                        task.row_data,
                        config,
                        days,
                        capacity_descriptor=capacity_descriptor,
                    ) if package_template else ""
                    if target:
                        generated_rows.append(make_translation_row_for_field(task, snapshot, field, target, config.online))

            if "package_quantity" in config.selected_modules:
                quantity_fields = [field for field in locale_fields if field.field_code in {"resourceName", "packageResourceName"}]
                if not quantity_fields:
                    direct_plans.append(make_translation_rule_invalid_plan(task, task.product_id, locale, "package_quantity", "接口快照未找到套餐规格量词字段，已跳过"))
                quantity_word = translation_rules.QUANTITY_WORDS.get(lang_group, translation_rules.QUANTITY_WORDS["en"])
                for field in quantity_fields:
                    generated_rows.append(make_translation_row_for_field(task, snapshot, field, quantity_word, config.online))
    plans = build_translation_diff_plans(snapshots, generated_rows, config.include_unopened_locales)
    return direct_plans + plans


def translation_result_from_plan(plan: TranslationDiffPlan, status: str | None = None, message: str | None = None) -> TranslationResultRow:
    return TranslationResultRow(
        product_id=plan.product_id,
        locale=plan.locale,
        module_code=plan.module_code,
        field_code=plan.field_code,
        field_name=plan.field_name,
        self_key=plan.self_key,
        status=status or plan.status,
        old_value=plan.old_value,
        new_value=plan.new_value,
        online=plan.online,
        message=message if message is not None else plan.message,
        row_number=plan.row.row_number,
    )


def sku_key(product_id: str, package_id: str, resource_id: str) -> str:
    return f"{product_id}:{package_id}:{resource_id}"


def package_resource_is_active(item: dict[str, Any]) -> bool:
    resources = item.get("resourceInfoList")
    if not isinstance(resources, list) or not resources or not isinstance(resources[0], dict):
        return False
    return bool(resources[0].get("active"))


def sku_price_unavailable_reason(sku: SkuSnapshot) -> str:
    return "无效资源无价格库存" if sku.price_error == "inactive_resource" else ""


def build_product_snapshot(
    client: CtripRequestsClient,
    product_id: str,
    stop_event: threading.Event,
    needs: ProductSnapshotNeeds | None = None,
) -> ProductSnapshot:
    needs = needs or ProductSnapshotNeeds()
    draft = client.load_product(product_id, stop_event)
    if needs.product_info:
        product_info = client.load_product_info_draft(product_id, stop_event)
        product_basic_info = product_info.get("productBasicInfo") if isinstance(product_info, dict) else None
        if isinstance(product_basic_info, dict):
            draft_raw = dict(draft.draft_raw) if isinstance(draft.draft_raw, dict) else {}
            existing_basic_info = draft_raw.get("productBasicInfo")
            merged_basic_info = dict(existing_basic_info) if isinstance(existing_basic_info, dict) else {}
            merged_basic_info.update(product_basic_info)
            draft_raw["productBasicInfo"] = merged_basic_info
            draft.draft_raw = draft_raw
    currency_context = client.load_product_currency_context(product_id, stop_event) if needs.currency_context else CurrencyRewriteContext(product_id=str(product_id))
    sku_snapshots: dict[str, SkuSnapshot] = {}
    price_stock_by_package = client.load_product_price_stock(product_id, stop_event) if needs.price_stock else {}
    for index, item in enumerate(draft.package_resources):
        package_id = str(item.get("packageId") or "")
        package_name = str(item.get("packageName") or "")
        resource_id = resource_id_from_package_resource(item)
        if not package_id or not resource_id:
            continue
        price_and_stock: dict[str, Any] | None = None
        cost_price = ""
        cost_price_editable = True
        sale_status = ""
        price_error = ""
        if not needs.price_stock:
            price_error = "not_requested"
        elif not package_resource_is_active(item):
            price_error = "inactive_resource"
        else:
            try:
                package_price_stock = price_stock_by_package.get(package_id)
                if not isinstance(package_price_stock, dict):
                    raise RuntimeError(f"PriceAndStock 草稿中未找到 packageId={package_id}")
                price_and_stock = package_price_stock_to_price_and_stock(package_price_stock)
                if not price_and_stock_has_resource(price_and_stock, resource_id):
                    raise RuntimeError(f"PriceAndStock 草稿中未找到 resourceId={resource_id}")
                cost_price_editable = vendor_can_edit_cost_price(price_and_stock, resource_id)
                cost_price = current_cost_price(price_and_stock, resource_id) if cost_price_editable else COST_PRICE_NOT_EDITABLE_MESSAGE
                sale_status = current_sale_status(price_and_stock, resource_id)
            except Exception as exc:
                price_error = str(exc)
        sku = SkuSnapshot(
            product_id=product_id,
            package_id=package_id,
            resource_id=resource_id,
            package_name=package_name,
            vendor_package_id=str(item.get("vendorPackageId") or ""),
            connection_code=connection_code_from_package_resource(item),
            introduction=ctrip_intro_to_text(item.get("introduction")),
            cost_price=cost_price,
            cost_price_editable=cost_price_editable,
            sale_status=sale_status,
            price_and_stock=price_and_stock,
            price_error=price_error,
            resource_index=index,
        )
        sku_snapshots[sku_key(product_id, package_id, resource_id)] = sku
    return ProductSnapshot(
        product_id=product_id,
        created_at=now_iso(),
        draft=draft,
        sku_snapshots=sku_snapshots,
        currency_context=currency_context,
    )


def product_name_from_snapshot(snapshot: ProductSnapshot) -> str:
    draft_raw = snapshot.draft.draft_raw if isinstance(snapshot.draft.draft_raw, dict) else {}
    basic_info = draft_raw.get("productBasicInfo") if isinstance(draft_raw, dict) else None
    if not isinstance(basic_info, dict):
        basic_info = snapshot.draft.package_info.get("productBasicInfo") if isinstance(snapshot.draft.package_info, dict) else None
    if not isinstance(basic_info, dict):
        return ""
    return str(basic_info.get("name") or "").strip()


def build_edit_template_workbook(
    path: str,
    snapshots: dict[str, ProductSnapshot],
    include_price: bool,
    include_connection: bool,
    include_intro: bool,
    workbench: str = ProductWorkbench.PACKAGE_CONNECT,
) -> None:
    if openpyxl is None:
        raise RuntimeError("缺少 openpyxl，无法生成模板。请先运行：py -3 -m pip install -r requirements.txt")
    if not snapshots:
        raise RuntimeError("请先预载产品ID")
    spec = product_workbench_spec(workbench)

    from openpyxl.styles import Font, PatternFill
    from openpyxl.worksheet.datavalidation import DataValidation

    if workbench == ProductWorkbench.PRODUCT_INFO:
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = EDIT_TEMPLATE_SHEET
        headers = list(PRODUCT_EDIT_WIDE_HEADERS)
        ws.append(headers)
        readonly_fill = PatternFill("solid", fgColor="E7E6E6")
        target_fill = PatternFill("solid", fgColor="FFF2CC")
        for cell in ws[1]:
            cell.font = Font(bold=True)
            cell.fill = target_fill if str(cell.value).startswith("target_") else readonly_fill
        for snapshot in snapshots.values():
            product_name = product_name_from_snapshot(snapshot)
            if not snapshot.sku_snapshots:
                ws.append([snapshot.product_id, product_name, "", "", "", "", product_name, "", "", "", "", "", "", "", "", "", "", ""])
            for sku in snapshot.sku_snapshots.values():
                ws.append([
                    sku.product_id,
                    product_name,
                    sku.package_id,
                    sku.resource_id,
                    sku.package_name,
                    build_package_name_mark(sku.package_name),
                    product_name,
                    "",
                    sku.cost_price,
                    "",
                    sku.sale_status,
                    "",
                    sku.vendor_package_id,
                    "",
                    sku.connection_code,
                    "",
                    sku.introduction,
                    "",
                ])
        for col_idx, width in enumerate((16, 52, 16, 16, 42, 18, 52, 52, 18, 18, 18, 18, 36, 36, 36, 36, 52, 52), start=1):
            ws.column_dimensions[openpyxl.utils.get_column_letter(col_idx)].width = width
        ws.freeze_panes = "A2"

        sale_status_dv = DataValidation(type="list", formula1='"开,关"', allow_blank=True)
        ws.add_data_validation(sale_status_dv)
        sale_status_col = openpyxl.utils.get_column_letter(headers.index("target_sale_status") + 1)
        sale_status_dv.add(f"{sale_status_col}2:{sale_status_col}10000")

        meta = wb.create_sheet("说明")
        meta.append(["说明", "值"])
        meta.append(["工作台", spec.title])
        meta.append(["生成时间", now_iso()])
        meta.append(["只修改 target_* 列", "old_* 和定位列仅用于 diff 与防误写"])
        meta.append(["单入口产品编辑", "产品名称走 ProductInfo；底价及开/关班走 PriceAndStock；供应商套餐ID/对接代码/套餐说明走 PackageInfo"])
        wb.save(path)
        return
    if workbench == ProductWorkbench.PRICE_INVENTORY:
        include_price = True
        include_connection = False
        include_intro = False
    elif workbench == ProductWorkbench.PACKAGE_CONNECT:
        include_price = False
        include_connection = True
    elif workbench == ProductWorkbench.AUDIT_REPORT:
        raise RuntimeError("审核与报告工作台不导出字段修改模板")
    if not any([include_price, include_connection, include_intro]):
        raise RuntimeError("请至少勾选一个导出字段")

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = EDIT_TEMPLATE_SHEET
    headers = ["productId", "productName", "packageId", "resourceId", "packageName", "PackageNameMark"]
    if include_price:
        headers.extend(["old_cost_price", "target_cost_price", "old_sale_status", "target_sale_status"])
    if include_connection:
        headers.extend(["old_vendor_package_id", "target_vendor_package_id", "old_connection_code", "target_connection_code"])
    ws.append(headers)

    readonly_fill = PatternFill("solid", fgColor="E7E6E6")
    target_fill = PatternFill("solid", fgColor="FFF2CC")
    for cell in ws[1]:
        cell.font = Font(bold=True)
        cell.fill = target_fill if str(cell.value).startswith("target_") else readonly_fill

    for snapshot in snapshots.values():
        product_name = product_name_from_snapshot(snapshot)
        for sku in snapshot.sku_snapshots.values():
            row: list[Any] = [
                sku.product_id,
                product_name,
                sku.package_id,
                sku.resource_id,
                sku.package_name,
                build_package_name_mark(sku.package_name),
            ]
            if include_price:
                row.extend([sku.cost_price, "", sku.sale_status, ""])
            if include_connection:
                row.extend([sku.vendor_package_id, "", sku.connection_code, ""])
            ws.append(row)

    widths = {
        "A": 16,
        "B": 52,
        "C": 16,
        "D": 16,
        "E": 42,
        "F": 18,
    }
    for letter, width in widths.items():
        ws.column_dimensions[letter].width = width
    for col_idx in range(7, len(headers) + 1):
        ws.column_dimensions[openpyxl.utils.get_column_letter(col_idx)].width = 36
    ws.freeze_panes = "A2"

    if include_price:
        sale_status_dv = DataValidation(type="list", formula1='"开,关"', allow_blank=True)
        ws.add_data_validation(sale_status_dv)
        sale_status_col = openpyxl.utils.get_column_letter(headers.index("target_sale_status") + 1)
        sale_status_dv.add(f"{sale_status_col}2:{sale_status_col}10000")

    if include_intro:
        intro_ws = wb.create_sheet(INTRO_FILL_SHEET)
        intro_headers = [
            "productId",
            "productName",
            "packageId",
            "resourceId",
            "packageName",
            "PackageNameMark",
            "old_introduction",
            "usedup_throttle",
            "reset_time_calc",
            "inst_adv",
        ]
        intro_ws.append(intro_headers)
        for cell in intro_ws[1]:
            cell.font = Font(bold=True)
            cell.fill = target_fill if cell.value in {"usedup_throttle", "reset_time_calc", "inst_adv"} else readonly_fill
        for snapshot in snapshots.values():
            product_name = product_name_from_snapshot(snapshot)
            for sku in snapshot.sku_snapshots.values():
                intro_ws.append(
                    [
                        sku.product_id,
                        product_name,
                        sku.package_id,
                        sku.resource_id,
                        sku.package_name,
                        build_package_name_mark(sku.package_name),
                        sku.introduction,
                        "",
                        "",
                        "",
                    ]
                )
        for col_idx, width in enumerate((16, 52, 16, 16, 42, 18, 52, 24, 18, 18), start=1):
            intro_ws.column_dimensions[openpyxl.utils.get_column_letter(col_idx)].width = width
        intro_ws.freeze_panes = "A2"

        options = wb.create_sheet(INTRO_OPTIONS_SHEET)
        options.append(["usedup_throttle", "说明"])
        for key in USEDUP_THROTTLE_OPTIONS:
            options.append([key, TEMPLATE_MODE_LABELS.get(key, "")])
        start_reset_time_row = options.max_row + 2
        options.cell(start_reset_time_row, 1, "reset_time_calc")
        options.cell(start_reset_time_row, 2, "说明")
        for value in RESET_TIME_CALC_OPTIONS:
            options.append([value, CTRIP_PACKAGE_TEMPLATE_DICT["reset_time_calc"][value]])
        start_install_row = options.max_row + 2
        options.cell(start_install_row, 1, "inst_adv")
        options.cell(start_install_row, 2, "说明")
        for value in INST_ADV_OPTIONS:
            options.append([value, CTRIP_PACKAGE_TEMPLATE_DICT["install_instructions"][value]])
        for col in range(1, 3):
            options.column_dimensions[openpyxl.utils.get_column_letter(col)].width = 36
        for cell in options[1]:
            cell.font = Font(bold=True)
            cell.fill = readonly_fill

        usedup_dv = DataValidation(type="list", formula1=f"'{INTRO_OPTIONS_SHEET}'!$A$2:$A${1 + len(USEDUP_THROTTLE_OPTIONS)}", allow_blank=True)
        reset_time_end = start_reset_time_row + len(RESET_TIME_CALC_OPTIONS)
        reset_time_dv = DataValidation(type="list", formula1=f"'{INTRO_OPTIONS_SHEET}'!$A${start_reset_time_row + 1}:$A${reset_time_end}", allow_blank=True)
        install_end = start_install_row + len(INST_ADV_OPTIONS)
        install_dv = DataValidation(type="list", formula1=f"'{INTRO_OPTIONS_SHEET}'!$A${start_install_row + 1}:$A${install_end}", allow_blank=True)
        intro_ws.add_data_validation(usedup_dv)
        intro_ws.add_data_validation(reset_time_dv)
        intro_ws.add_data_validation(install_dv)
        usedup_dv.add("H2:H10000")
        reset_time_dv.add("I2:I10000")
        install_dv.add("J2:J10000")

    meta = wb.create_sheet("说明")
    meta.append(["说明", "值"])
    meta.append(["生成时间", now_iso()])
    meta.append(["只修改 target_* 列", "old_* 和定位列仅用于 diff 与防误写"])
    meta.append(["套餐说明填充", "在“套餐说明填充”分页通过 usedup_throttle / reset_time_calc / inst_adv 下拉选项生成说明；不要手写 target_introduction"])
    meta.append(["模板有效性", "读取模板时会按 productId 自动重新预载并生成 Diff"])
    wb.save(path)


def product_ids_from_edit_rows(rows: list[EditTemplateRow]) -> list[str]:
    product_ids: list[str] = []
    seen: set[str] = set()
    for row in rows:
        product_id = normalize_number_text(row.product_id)
        if not product_id or not product_id.isdigit() or product_id in seen:
            continue
        seen.add(product_id)
        product_ids.append(product_id)
    return product_ids


EDIT_TEMPLATE_TARGET_COLUMNS_BY_WORKBENCH: dict[str, tuple[str, ...]] = {
    ProductWorkbench.PRICE_INVENTORY: ("target_cost_price", "target_sale_status"),
    ProductWorkbench.PRODUCT_INFO: ("target_product_name", "target_cost_price", "target_sale_status", "target_vendor_package_id", "target_connection_code", "target_introduction"),
    ProductWorkbench.PACKAGE_CONNECT: ("target_vendor_package_id", "target_connection_code", "target_introduction"),
    ProductWorkbench.AUDIT_REPORT: (),
}


def disallowed_target_columns_for_workbench(headers: dict[str, int], workbench: str) -> list[str]:
    allowed = set(EDIT_TEMPLATE_TARGET_COLUMNS_BY_WORKBENCH.get(workbench, ()))
    present_targets = {name for name in headers if name.startswith("target_")}
    return sorted(present_targets - allowed)


def template_workbench_from_target_columns(disallowed_columns: list[str]) -> str:
    column_set = set(disallowed_columns)
    if column_set & {"target_cost_price", "target_sale_status"}:
        return ProductWorkbench.PRICE_INVENTORY
    if "target_product_name" in column_set:
        return ProductWorkbench.PRODUCT_INFO
    if column_set & {"target_vendor_package_id", "target_connection_code", "target_introduction"}:
        return ProductWorkbench.PACKAGE_CONNECT
    return ""


def wrong_template_message(current_workbench: str, source_workbench: str) -> str:
    current_title = product_workbench_spec(current_workbench).title
    source_title = product_workbench_spec(source_workbench).title if source_workbench else "其它"
    return f"当前是“{current_title}”，不能加载“{source_title}”模板。\n请到“{source_title}”入口加载该模板。"


def normalize_template_header_key(value: Any) -> str:
    text = unicodedata.normalize("NFKC", normalize_cell(value))
    return re.sub(r"[\s_\-:/：（）()]+", "", text).lower()


EDIT_TEMPLATE_HEADER_ALIASES = {
    "productid": "productId",
    "产品id": "productId",
    "产品编号": "productId",
    "productname": "productName",
    "产品名称": "productName",
    "packageid": "packageId",
    "套餐id": "packageId",
    "套餐编号": "packageId",
    "resourceid": "resourceId",
    "资源id": "resourceId",
    "资源编号": "resourceId",
    "packagename": "packageName",
    "套餐名称": "packageName",
    "packagenamemark": "PackageNameMark",
    "套餐标记": "PackageNameMark",
    "oldproductname": "old_product_name",
    "原产品名称": "old_product_name",
    "当前产品名称": "old_product_name",
    "targetproductname": "target_product_name",
    "目标产品名称": "target_product_name",
    "目标产品名": "target_product_name",
    "新产品名称": "target_product_name",
    "新产品名": "target_product_name",
    "oldcostprice": "old_cost_price",
    "原底价": "old_cost_price",
    "当前底价": "old_cost_price",
    "targetcostprice": "target_cost_price",
    "目标底价": "target_cost_price",
    "新底价": "target_cost_price",
    "oldsalestatus": "old_sale_status",
    "原开关班状态": "old_sale_status",
    "当前开关班状态": "old_sale_status",
    "开关班状态": "old_sale_status",
    "targetsalestatus": "target_sale_status",
    "目标开关班状态": "target_sale_status",
    "新开关班状态": "target_sale_status",
    "oldvendorpackageid": "old_vendor_package_id",
    "原供应商套餐id": "old_vendor_package_id",
    "当前供应商套餐id": "old_vendor_package_id",
    "targetvendorpackageid": "target_vendor_package_id",
    "目标供应商套餐id": "target_vendor_package_id",
    "新供应商套餐id": "target_vendor_package_id",
    "oldconnectioncode": "old_connection_code",
    "原对接代码": "old_connection_code",
    "当前对接代码": "old_connection_code",
    "targetconnectioncode": "target_connection_code",
    "目标对接代码": "target_connection_code",
    "新对接代码": "target_connection_code",
    "oldintroduction": "old_introduction",
    "原套餐说明": "old_introduction",
    "当前套餐说明": "old_introduction",
    "targetintroduction": "target_introduction",
    "目标套餐说明": "target_introduction",
    "新套餐说明": "target_introduction",
    "usedupthrottle": "usedup_throttle",
    "用完处理模板": "usedup_throttle",
    "resettimecalc": "reset_time_calc",
    "重置时间规则": "reset_time_calc",
    "instadv": "inst_adv",
    "安装说明模板": "inst_adv",
}


def canonical_edit_template_header(value: Any) -> str:
    raw = normalize_cell(value)
    if not raw:
        return ""
    return EDIT_TEMPLATE_HEADER_ALIASES.get(normalize_template_header_key(raw), raw)


def read_edit_template_headers(sheet: Any) -> dict[str, int]:
    result: dict[str, int] = {}
    for idx, cell in enumerate(sheet[1], start=1):
        name = canonical_edit_template_header(cell.value)
        if name:
            result[name] = idx
    return result


def append_validation_error(row: EditTemplateRow, message: str) -> None:
    if not message:
        return
    row.validation_error = "；".join(part for part in [row.validation_error, message] if part)


def mark_edit_template_conflicts(rows: list[EditTemplateRow]) -> None:
    product_names: dict[str, dict[str, list[int]]] = {}
    sku_targets: dict[tuple[str, str, str, str], dict[str, list[int]]] = {}
    for row in rows:
        product_id = normalize_number_text(row.product_id)
        if product_id and row.target_product_name:
            product_names.setdefault(product_id, {}).setdefault(row.target_product_name, []).append(row.row_number)
        for field_name, value in (
            ("target_cost_price", row.target_cost_price),
            ("target_sale_status", row.target_sale_status),
            ("target_vendor_package_id", row.target_vendor_package_id),
            ("target_connection_code", row.target_connection_code),
            ("target_introduction", row.target_introduction),
        ):
            if not value:
                continue
            key = (product_id, normalize_number_text(row.package_id), normalize_number_text(row.resource_id), field_name)
            sku_targets.setdefault(key, {}).setdefault(value, []).append(row.row_number)

    product_conflicts = {product_id for product_id, values in product_names.items() if len(values) > 1}
    sku_conflicts = {key for key, values in sku_targets.items() if len(values) > 1}
    for row in rows:
        product_id = normalize_number_text(row.product_id)
        if product_id in product_conflicts and row.target_product_name:
            append_validation_error(row, f"同一产品 {product_id} 存在多个目标产品名称")
        for field_name, value in (
            ("target_cost_price", row.target_cost_price),
            ("target_sale_status", row.target_sale_status),
            ("target_vendor_package_id", row.target_vendor_package_id),
            ("target_connection_code", row.target_connection_code),
            ("target_introduction", row.target_introduction),
        ):
            if not value:
                continue
            key = (product_id, normalize_number_text(row.package_id), normalize_number_text(row.resource_id), field_name)
            if key in sku_conflicts:
                append_validation_error(row, f"同一 SKU 同一字段存在多个目标值：{field_name}")


def product_snapshot_needs_from_edit_rows(rows: list[EditTemplateRow]) -> ProductSnapshotNeeds:
    need_price_stock = any(bool(row.target_cost_price or row.target_sale_status) for row in rows if not row.validation_error)
    return ProductSnapshotNeeds(
        product_info=any(bool(row.target_product_name) for row in rows if not row.validation_error),
        price_stock=need_price_stock,
        currency_context=need_price_stock,
    )


def edit_template_row_has_target(row: EditTemplateRow) -> bool:
    return any(
        [
            row.target_cost_price,
            row.target_sale_status,
            row.target_product_name,
            row.target_vendor_package_id,
            row.target_connection_code,
            row.target_introduction,
        ]
    )


def read_edit_template(path: str, workbench: str = ProductWorkbench.PACKAGE_CONNECT) -> list[EditTemplateRow]:
    if openpyxl is None:
        raise RuntimeError("缺少 openpyxl，请先运行：py -3 -m pip install -r requirements.txt")
    wb = openpyxl.load_workbook(path, data_only=True)
    ws = wb[EDIT_TEMPLATE_SHEET] if EDIT_TEMPLATE_SHEET in wb.sheetnames else wb.active

    headers = read_edit_template_headers(ws)
    product_workbench_spec(workbench)
    disallowed_columns = disallowed_target_columns_for_workbench(headers, workbench)
    if workbench != ProductWorkbench.PRODUCT_INFO and disallowed_columns:
        raise ValueError(wrong_template_message(workbench, template_workbench_from_target_columns(disallowed_columns)))

    def get_value(sheet: Any, sheet_headers: dict[str, int], row_idx: int, column_name: str) -> str:
        column = sheet_headers.get(column_name)
        if not column:
            return ""
        return normalize_cell(sheet.cell(row_idx, column).value)

    if workbench == ProductWorkbench.PRODUCT_INFO:
        if "productId" not in headers:
            raise ValueError("回填模板缺少必填列：productId")
        rows: list[EditTemplateRow] = []
        for row_idx in range(2, ws.max_row + 1):
            usedup_throttle = canonical_usedup_throttle(get_value(ws, headers, row_idx, "usedup_throttle"))
            reset_time_calc = get_value(ws, headers, row_idx, "reset_time_calc")
            inst_adv = get_value(ws, headers, row_idx, "inst_adv")
            rule_requested = bool(usedup_throttle or reset_time_calc or inst_adv)
            target_vendor_package_id = get_value(ws, headers, row_idx, "target_vendor_package_id")
            target_connection_code = get_value(ws, headers, row_idx, "target_connection_code")
            target_introduction = get_value(ws, headers, row_idx, "target_introduction")
            errors: list[str] = []
            if rule_requested and not target_introduction:
                validation_error = validate_placeholder_settings(usedup_throttle, reset_time_calc, inst_adv)
                if validation_error:
                    errors.append(validation_error)
                else:
                    package_name_for_rule = get_value(ws, headers, row_idx, "packageName")
                    new_text, _selected_template, generation_error = generate_intro_from_rule(
                        usedup_throttle,
                        reset_time_calc,
                        inst_adv,
                        package_name_for_rule,
                    )
                    if generation_error:
                        errors.append(generation_error)
                    elif text_length_for_limit(new_text) > MAX_INTRO_TEXT_LENGTH:
                        errors.append("套餐说明超过 300 字限制")
                    else:
                        target_introduction = new_text
            row = EditTemplateRow(
                row_number=row_idx,
                product_id=normalize_number_text(get_value(ws, headers, row_idx, "productId")),
                package_id=normalize_number_text(get_value(ws, headers, row_idx, "packageId")),
                resource_id=normalize_number_text(get_value(ws, headers, row_idx, "resourceId")),
                package_name=get_value(ws, headers, row_idx, "packageName"),
                target_cost_price=normalize_number_text(get_value(ws, headers, row_idx, "target_cost_price")),
                target_sale_status=canonical_sale_status(get_value(ws, headers, row_idx, "target_sale_status")),
                target_product_name=get_value(ws, headers, row_idx, "target_product_name"),
                target_vendor_package_id=target_vendor_package_id,
                target_connection_code=target_connection_code,
                target_introduction=target_introduction,
                usedup_throttle=usedup_throttle,
                reset_time_calc=reset_time_calc,
                inst_adv=inst_adv,
                workbench=workbench,
            )
            if not any(
                [
                    row.product_id,
                    row.package_id,
                    row.resource_id,
                    row.package_name,
                    row.target_cost_price,
                    row.target_sale_status,
                    row.target_product_name,
                    row.target_vendor_package_id,
                    row.target_connection_code,
                    row.target_introduction,
                    rule_requested,
                ]
            ):
                continue
            if not row.product_id:
                errors.append("productId 不能为空")
            elif not row.product_id.isdigit():
                errors.append(f"productId 必须是数字：{row.product_id}")
            has_sku_target = bool(row.target_cost_price or row.target_sale_status or target_vendor_package_id or target_connection_code or target_introduction or rule_requested)
            if has_sku_target:
                if not row.package_id:
                    errors.append("packageId 不能为空")
                if not row.resource_id:
                    errors.append("resourceId 不能为空")
            if row.target_cost_price:
                try:
                    float(row.target_cost_price)
                except Exception:
                    errors.append(f"target_cost_price 不是数字：{row.target_cost_price}")
            if row.target_sale_status and row.target_sale_status not in SALE_STATUS_OPTIONS:
                errors.append(f"target_sale_status 必须是：{', '.join(SALE_STATUS_OPTIONS)}")
            if not edit_template_row_has_target(row) and not errors:
                continue
            row.validation_error = "；".join(errors)
            rows.append(row)

        if INTRO_FILL_SHEET in wb.sheetnames:
            intro_ws = wb[INTRO_FILL_SHEET]
            intro_headers = read_edit_template_headers(intro_ws)
            intro_missing = [name for name in ("productId", "packageId", "resourceId", "packageName") if name not in intro_headers]
            if intro_missing:
                raise ValueError(f"{INTRO_FILL_SHEET} 缺少必填列：{', '.join(intro_missing)}")
            for row_idx in range(2, intro_ws.max_row + 1):
                usedup_throttle = canonical_usedup_throttle(get_value(intro_ws, intro_headers, row_idx, "usedup_throttle"))
                reset_time_calc = get_value(intro_ws, intro_headers, row_idx, "reset_time_calc")
                inst_adv = get_value(intro_ws, intro_headers, row_idx, "inst_adv")
                if not (usedup_throttle or reset_time_calc or inst_adv):
                    continue
                package_name = get_value(intro_ws, intro_headers, row_idx, "packageName")
                errors = []
                validation_error = validate_placeholder_settings(usedup_throttle, reset_time_calc, inst_adv)
                if validation_error:
                    errors.append(validation_error)
                    new_text = ""
                else:
                    new_text, _selected_template, generation_error = generate_intro_from_rule(usedup_throttle, reset_time_calc, inst_adv, package_name)
                    if generation_error:
                        errors.append(generation_error)
                    elif text_length_for_limit(new_text) > MAX_INTRO_TEXT_LENGTH:
                        errors.append("套餐说明超过 300 字限制")
                row = EditTemplateRow(
                    row_number=row_idx,
                    product_id=normalize_number_text(get_value(intro_ws, intro_headers, row_idx, "productId")),
                    package_id=normalize_number_text(get_value(intro_ws, intro_headers, row_idx, "packageId")),
                    resource_id=normalize_number_text(get_value(intro_ws, intro_headers, row_idx, "resourceId")),
                    package_name=package_name,
                    target_introduction="" if errors else new_text,
                    usedup_throttle=usedup_throttle,
                    reset_time_calc=reset_time_calc,
                    inst_adv=inst_adv,
                    validation_error="；".join(errors),
                    workbench=workbench,
                )
                if not row.product_id:
                    append_validation_error(row, "productId 不能为空")
                elif not row.product_id.isdigit():
                    append_validation_error(row, f"productId 必须是数字：{row.product_id}")
                if not row.package_id:
                    append_validation_error(row, "packageId 不能为空")
                if not row.resource_id:
                    append_validation_error(row, "resourceId 不能为空")
                rows.append(row)
        mark_edit_template_conflicts(rows)
        return rows
    required = ["productId", "packageId", "resourceId", "packageName"]
    missing = [name for name in required if name not in headers]
    if missing:
        raise ValueError(f"回填模板缺少必填列：{', '.join(missing)}")

    rows: list[EditTemplateRow] = []
    for row_idx in range(2, ws.max_row + 1):
        row = EditTemplateRow(
            row_number=row_idx,
            product_id=normalize_number_text(get_value(ws, headers, row_idx, "productId")),
            package_id=normalize_number_text(get_value(ws, headers, row_idx, "packageId")),
            resource_id=normalize_number_text(get_value(ws, headers, row_idx, "resourceId")),
            package_name=get_value(ws, headers, row_idx, "packageName"),
            target_cost_price=normalize_number_text(get_value(ws, headers, row_idx, "target_cost_price")),
            target_sale_status=canonical_sale_status(get_value(ws, headers, row_idx, "target_sale_status")),
            target_vendor_package_id=get_value(ws, headers, row_idx, "target_vendor_package_id"),
            target_connection_code=get_value(ws, headers, row_idx, "target_connection_code"),
            target_introduction=get_value(ws, headers, row_idx, "target_introduction"),
            workbench=workbench,
        )
        if not any([row.product_id, row.package_id, row.resource_id, row.package_name, row.target_cost_price, row.target_sale_status, row.target_vendor_package_id, row.target_connection_code, row.target_introduction]):
            continue
        errors: list[str] = []
        if not row.product_id:
            errors.append("productId 不能为空")
        elif not row.product_id.isdigit():
            errors.append(f"productId 必须是数字：{row.product_id}")
        if not row.package_id:
            errors.append("packageId 不能为空")
        if not row.resource_id:
            errors.append("resourceId 不能为空")
        if row.target_cost_price:
            try:
                float(row.target_cost_price)
            except Exception:
                errors.append(f"target_cost_price 不是数字：{row.target_cost_price}")
        if row.target_sale_status and row.target_sale_status not in SALE_STATUS_OPTIONS:
            errors.append(f"target_sale_status 必须是：{', '.join(SALE_STATUS_OPTIONS)}")
        if disallowed_columns:
            errors.append(f"{product_workbench_spec(workbench).title}工作台不接受字段：{', '.join(disallowed_columns)}")
        row.validation_error = "；".join(errors)
        rows.append(row)

    if INTRO_FILL_SHEET in wb.sheetnames:
        intro_ws = wb[INTRO_FILL_SHEET]
        intro_headers = read_edit_template_headers(intro_ws)
        intro_missing = [name for name in required if name not in intro_headers]
        if intro_missing:
            raise ValueError(f"{INTRO_FILL_SHEET} 缺少必填列：{', '.join(intro_missing)}")
        for row_idx in range(2, intro_ws.max_row + 1):
            usedup_throttle = canonical_usedup_throttle(get_value(intro_ws, intro_headers, row_idx, "usedup_throttle"))
            reset_time_calc = get_value(intro_ws, intro_headers, row_idx, "reset_time_calc")
            inst_adv = get_value(intro_ws, intro_headers, row_idx, "inst_adv")
            has_intro_task = bool(usedup_throttle or reset_time_calc or inst_adv)
            if not has_intro_task:
                continue
            package_name = get_value(intro_ws, intro_headers, row_idx, "packageName")
            errors = []
            validation_error = validate_placeholder_settings(usedup_throttle, reset_time_calc, inst_adv)
            if validation_error:
                errors.append(validation_error)
            new_text = ""
            if not errors:
                new_text, _selected_template, generation_error = generate_intro_from_rule(usedup_throttle, reset_time_calc, inst_adv, package_name)
                if generation_error:
                    errors.append(generation_error)
                elif text_length_for_limit(new_text) > MAX_INTRO_TEXT_LENGTH:
                    errors.append("套餐说明超过 300 字限制")
            row = EditTemplateRow(
                row_number=row_idx,
                product_id=normalize_number_text(get_value(intro_ws, intro_headers, row_idx, "productId")),
                package_id=normalize_number_text(get_value(intro_ws, intro_headers, row_idx, "packageId")),
                resource_id=normalize_number_text(get_value(intro_ws, intro_headers, row_idx, "resourceId")),
                package_name=package_name,
                target_introduction=new_text,
                usedup_throttle=usedup_throttle,
                reset_time_calc=reset_time_calc,
                inst_adv=inst_adv,
                validation_error="；".join(errors),
                workbench=workbench,
            )
            locator_errors: list[str] = []
            if not row.product_id:
                locator_errors.append("productId 不能为空")
            elif not row.product_id.isdigit():
                locator_errors.append(f"productId 必须是数字：{row.product_id}")
            if not row.package_id:
                locator_errors.append("packageId 不能为空")
            if not row.resource_id:
                locator_errors.append("resourceId 不能为空")
            if locator_errors:
                row.validation_error = "；".join(locator_errors + ([row.validation_error] if row.validation_error else []))
            rows.append(row)
    return rows


def build_diff_plans_from_rows(snapshots: dict[str, ProductSnapshot], rows: list[EditTemplateRow], workbench: str = ProductWorkbench.PACKAGE_CONNECT) -> list[DiffPlan]:
    plans: list[DiffPlan] = []
    for row in rows:
        def invalid_plan(message: str) -> DiffPlan:
            return DiffPlan(row, row.product_id, row.package_id, row.resource_id, row.package_name, "row", "", "", "none", status="invalid", message=message, workbench=workbench)

        if not edit_template_row_has_target(row):
            continue
        if row.validation_error:
            plans.append(invalid_plan(row.validation_error))
            continue
        snapshot = snapshots.get(row.product_id)
        if not snapshot:
            plans.append(invalid_plan("内存快照不存在，请重新预载产品ID"))
            continue
        if workbench == ProductWorkbench.PRODUCT_INFO and row.target_product_name:
            old_name = product_name_from_snapshot(snapshot)
            new_name = row.target_product_name
            status = "unchanged" if new_name == old_name else "pending"
            message = "产品名称与当前快照一致" if status == "unchanged" else ""
            plans.append(DiffPlan(row, row.product_id, "", "", "", "productName", old_name, new_name, "saveOrEffectProductDraft(ProductInfo)", status=status, message=message, workbench=workbench))
        if workbench == ProductWorkbench.PRODUCT_INFO and not (row.target_cost_price or row.target_sale_status or row.target_vendor_package_id or row.target_connection_code or row.target_introduction):
            continue
        sku = snapshot.sku_snapshots.get(sku_key(row.product_id, row.package_id, row.resource_id))
        if not sku:
            plans.append(invalid_plan("内存快照中未找到该 SKU"))
            continue
        if row.target_sale_status:
            if sku.price_and_stock is None or not sku.sale_status:
                reason = sku_price_unavailable_reason(sku) or sku.price_error or "开/关班状态快照缺失，请重新预载"
                plans.append(DiffPlan(row, row.product_id, row.package_id, row.resource_id, sku.package_name, "sale", sku.sale_status, row.target_sale_status, "saveOrEffectProductDraft(PriceAndStock)", status="invalid", message=reason, workbench=workbench))
            else:
                status = "unchanged" if row.target_sale_status == sku.sale_status else "pending"
                message = "目标开/关班状态与当前快照一致" if status == "unchanged" else ""
                plans.append(DiffPlan(row, row.product_id, row.package_id, row.resource_id, sku.package_name, "sale", sku.sale_status, row.target_sale_status, "saveOrEffectProductDraft(PriceAndStock)", status=status, message=message, workbench=workbench))
        if row.target_cost_price:
            if sku.price_and_stock is None:
                reason = sku_price_unavailable_reason(sku) or sku.price_error or "价格快照缺失，请重新预载"
                plans.append(DiffPlan(row, row.product_id, row.package_id, row.resource_id, sku.package_name, "costPrice", sku.cost_price, normalize_number_text(row.target_cost_price), "saveOrEffectProductDraft(PriceAndStock)", status="invalid", message=reason, workbench=workbench))
                continue
            if not sku.cost_price_editable:
                plans.append(DiffPlan(row, row.product_id, row.package_id, row.resource_id, sku.package_name, "costPrice", COST_PRICE_NOT_EDITABLE_MESSAGE, normalize_number_text(row.target_cost_price), "saveOrEffectProductDraft(PriceAndStock)", status="invalid", message=COST_PRICE_NOT_EDITABLE_MESSAGE, workbench=workbench))
                continue
            status = "unchanged" if normalize_number_text(row.target_cost_price) == normalize_number_text(sku.cost_price) else "pending"
            message = "目标底价与当前快照一致" if status == "unchanged" else ""
            plans.append(DiffPlan(row, row.product_id, row.package_id, row.resource_id, sku.package_name, "costPrice", sku.cost_price, normalize_number_text(row.target_cost_price), "saveOrEffectProductDraft(PriceAndStock)", status=status, message=message, workbench=workbench))
        if row.target_vendor_package_id:
            status = "unchanged" if row.target_vendor_package_id == sku.vendor_package_id else "pending"
            message = "供应商套餐ID与当前快照一致" if status == "unchanged" else ""
            plans.append(DiffPlan(row, row.product_id, row.package_id, row.resource_id, sku.package_name, "vendorPackageId", sku.vendor_package_id, row.target_vendor_package_id, "saveOrEffectProductDraft(type=2)", status=status, message=message, workbench=workbench))
        if row.target_connection_code:
            status = "unchanged" if row.target_connection_code == sku.connection_code else "pending"
            message = "对接代码与当前快照一致" if status == "unchanged" else ""
            plans.append(DiffPlan(row, row.product_id, row.package_id, row.resource_id, sku.package_name, "connectionCode", sku.connection_code, row.target_connection_code, "saveOrEffectProductDraft(type=2)", status=status, message=message, workbench=workbench))
        if row.target_introduction:
            status = "unchanged" if row.target_introduction == sku.introduction else "pending"
            message = "套餐说明与当前快照一致" if status == "unchanged" else ""
            plans.append(DiffPlan(row, row.product_id, row.package_id, row.resource_id, sku.package_name, "introduction", sku.introduction, row.target_introduction, "saveOrEffectProductDraft(type=2)", status=status, message=message, workbench=workbench))
    return plans


def build_save_request_meta(request_template: CapturedRequestTemplate | None = None) -> dict[str, Any]:
    request = request_template.save_request if request_template else None
    request = request if isinstance(request, dict) else {}
    return {
        "url": request.get("url") or "https://m.ctrip.com/restapi/soa2/16359/json/saveOrEffectProductDraft",
        "method": request.get("method") or "POST",
        "credentials": request.get("credentials") or "include",
        "headers": filter_fetch_headers(request.get("headers")),
        "source": request.get("source") or "default",
    }


def result_workbench_title(workbench: str) -> str:
    if not workbench:
        return ""
    try:
        return product_workbench_spec(workbench).title
    except RuntimeError:
        return str(workbench)


def report_headers(workbench: str = "") -> list[str]:
    return [
        "工作台",
        "产品ID",
        "套餐ID",
        "资源ID",
        "套餐名称",
        "修改字段",
        "修改前内容",
        "修改后内容",
        "调用接口",
        "用完处理模板",
        "重置时间规则",
        "安装说明模板",
        "原底价",
        "新底价",
        "原供应商套餐ID",
        "新供应商套餐ID",
        "原对接代码",
        "新对接代码",
        "是否提交审核",
        "处理状态",
        "原套餐说明",
        "新套餐说明",
        "结果说明",
        "模板行号",
    ]


def result_preview_rows(results: list[ResultRow]) -> tuple[list[str], list[list[Any]]]:
    return report_headers(), [result_row_values(item) for item in results]


def snapshot_preview_rows(snapshots: dict[str, ProductSnapshot]) -> tuple[list[str], list[list[Any]]]:
    headers = [
        "产品ID",
        "套餐ID",
        "资源ID",
        "套餐名称",
        "当前底价",
        "当前供应商套餐ID",
        "当前对接代码",
        "当前套餐说明",
        "价格读取状态",
        "快照时间",
    ]
    rows: list[list[Any]] = []
    for snapshot in snapshots.values():
        for sku in snapshot.sku_snapshots.values():
            rows.append(
                [
                    sku.product_id,
                    sku.package_id,
                    sku.resource_id,
                    sku.package_name,
                    sku.cost_price,
                    sku.vendor_package_id,
                    sku.connection_code,
                    sku.introduction,
                    sku.price_error,
                    snapshot.created_at,
                ]
            )
    return headers, rows


def write_report(path: str, results: list[ResultRow], product_order: dict[str, int] | None = None) -> None:
    headers = report_headers()
    ordered_results = ordered_product_results(results, product_order)
    if path.lower().endswith(".csv"):
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            writer.writerow(headers)
            for item in ordered_results:
                writer.writerow(result_row_values(item))
        return

    if openpyxl is None:
        raise RuntimeError("缺少 openpyxl，无法导出 xlsx")
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "结果"
    ws.append(headers)
    for item in ordered_results:
        ws.append(result_row_values(item))
    for col in range(1, len(headers) + 1):
        ws.column_dimensions[openpyxl.utils.get_column_letter(col)].width = 24 if col not in (16, 17, 18) else 52
    wb.save(path)


def result_row_values(item: ResultRow) -> list[Any]:
    return [
        result_workbench_title(item.workbench),
        item.product_id,
        item.package_id,
        item.resource_id,
        item.package_name,
        item.field_name,
        item.old_value,
        item.new_value,
        item.interface_name,
        item.usedup_throttle,
        item.reset_time_calc,
        item.inst_adv,
        item.old_cost_price,
        item.new_cost_price,
        item.old_vendor_package_id,
        item.new_vendor_package_id,
        item.old_connection_code,
        item.new_connection_code,
        "是" if item.submit_audit else "否",
        item.status,
        item.old_introduction,
        item.new_introduction,
        item.message,
        item.row_number,
    ]


def translation_report_headers() -> list[str]:
    return [
        "产品ID",
        "语言地区",
        "模块编码",
        "字段编码",
        "字段名称",
        "字段键",
        "修改前译文",
        "修改后译文",
        "是否上线",
        "调用接口",
        "处理状态",
        "结果说明",
        "模板行号",
    ]


def translation_result_row_values(item: TranslationResultRow) -> list[Any]:
    return [
        item.product_id,
        item.locale,
        item.module_code,
        item.field_code,
        item.field_name,
        item.self_key,
        item.old_value,
        item.new_value,
        "是" if item.online else "否",
        item.interface_name,
        item.status,
        item.message,
        item.row_number,
    ]


def translation_result_preview_rows(results: list[TranslationResultRow]) -> tuple[list[str], list[list[Any]]]:
    return translation_report_headers(), [translation_result_row_values(item) for item in results]


def build_translation_report_metadata(
    task_template_path: str = "",
    detail_template_path: str = "",
    package_template_path: str = "",
    execution_summary: str = "",
    results: list[TranslationResultRow] | None = None,
    request_stats: dict[str, Any] | None = None,
    generated_at: str | None = None,
) -> list[list[Any]]:
    results = results or []
    status_counts = Counter(item.status for item in results)
    stats = request_stats or {}
    rows: list[list[Any]] = [
        ["生成时间", generated_at or now_iso()],
        ["任务模板", task_template_path],
        ["详情模板", detail_template_path],
        ["规格模板", package_template_path],
        ["执行配置", execution_summary],
        ["结果总数", len(results)],
    ]
    for status, count in sorted(status_counts.items()):
        rows.append([f"状态 {status}", count])
    for label, key in [
        ("请求统计", "summary"),
        ("累计请求数", "total_requests"),
        ("累计错误数", "failed_requests"),
        ("今日请求数", "today_requests"),
        ("今日错误数", "today_failed_requests"),
        ("本次请求数", "run_requests"),
        ("本次错误数", "run_failed_requests"),
    ]:
        if key in stats:
            rows.append([label, stats.get(key)])
    return rows


def translation_snapshot_preview_rows(snapshots: dict[str, TranslationSnapshot]) -> tuple[list[str], list[list[Any]]]:
    headers = [
        "产品ID",
        "语言地区",
        "模块编码",
        "模块名称",
        "字段编码",
        "字段名称",
        "字段键",
        "原文内容",
        "当前译文",
        "快照时间",
    ]
    rows: list[list[Any]] = []
    for snapshot in snapshots.values():
        for field in snapshot.fields.values():
            rows.append(
                [
                    field.product_id,
                    field.locale,
                    field.module_code,
                    field.module_name,
                    field.field_code,
                    field.field_name,
                    field.self_key,
                    field.origin,
                    field.old_translation,
                    snapshot.created_at,
                ]
            )
    return headers, rows


def write_translation_report(
    path: str,
    results: list[TranslationResultRow],
    product_order: dict[str, int] | None = None,
    metadata: list[list[Any]] | None = None,
) -> None:
    headers = translation_report_headers()
    ordered_results = ordered_translation_results(results, product_order)
    if path.lower().endswith(".csv"):
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            writer.writerow(headers)
            for item in ordered_results:
                writer.writerow(translation_result_row_values(item))
        return

    if openpyxl is None:
        raise RuntimeError("缺少 openpyxl，无法导出 xlsx")
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "翻译结果"
    ws.append(headers)
    for item in ordered_results:
        ws.append(translation_result_row_values(item))
    for col in range(1, len(headers) + 1):
        ws.column_dimensions[openpyxl.utils.get_column_letter(col)].width = 52 if col in (7, 8, 12) else 22
    if metadata:
        meta_ws = wb.create_sheet("执行摘要")
        meta_ws.append(["项目", "值"])
        for row in metadata:
            meta_ws.append(row)
        meta_ws.column_dimensions["A"].width = 22
        meta_ws.column_dimensions["B"].width = 90
    wb.save(path)


class Worker:
    def __init__(
        self,
        rows: list[TemplateRow],
        out_queue: queue.Queue,
        stop_event: threading.Event,
        allow_submit_audit: bool = False,
        request_interval_seconds: float = CTRIP_REQUEST_INTERVAL_SECONDS,
    ):
        self.rows = rows
        self.out_queue = out_queue
        self.stop_event = stop_event
        self.allow_submit_audit = allow_submit_audit
        self.results: list[ResultRow] = []
        self.client = CtripRequestsClient(self.log, request_interval_seconds=request_interval_seconds)
        self.backup_dir = Path("backups")

    def log(self, message: str) -> None:
        self.out_queue.put(("log", message))

    def emit_result(self, result: ResultRow) -> None:
        self.results.append(result)
        self.out_queue.put(("result", result))

    def ordered_results(self) -> list[ResultRow]:
        return ordered_product_results(self.results, product_order_map([row.product_id for row in self.rows]))

    def emit_plan_result(self, plan: DiffPlan, status: str | None = None, message: str | None = None) -> None:
        if status is not None:
            plan.status = status
        if message is not None:
            plan.message = message
        self.emit_result(result_from_diff(plan, status=status, message=message))

    def result_for_row(self, row: TemplateRow, package_name: str, status: str, **kwargs: Any) -> ResultRow:
        return ResultRow(
            row.product_id,
            package_name,
            status,
            row_number=row.row_number,
            usedup_throttle=row.usedup_throttle,
            reset_time_calc=row.reset_time_calc,
            inst_adv=row.inst_adv,
            package_id=row.package_id,
            new_cost_price=row.target_cost_price,
            new_vendor_package_id=row.target_vendor_package_id,
            new_connection_code=row.target_connection_code or row.target_vendor_package_id,
            submit_audit=row.submit_audit,
            **kwargs,
        )

    def run_precheck(self) -> None:
        try:
            self._check_auth()
            grouped = group_rows(self.rows)
            self.log(f"开始预检：{len(grouped)} 个产品任务")
            for idx, (product_id, rows) in enumerate(grouped.items(), start=1):
                if self.stop_event.is_set():
                    break
                self.out_queue.put(("progress", f"预检 {idx}/{len(grouped)} 产品 {product_id}"))
                try:
                    draft = self.client.load_product(product_id, self.stop_event)
                    intro_rows = [row for row in rows if template_row_has_intro_task(row)]
                    if len(intro_rows) > 1:
                        for row in intro_rows:
                            self.emit_result(self.result_for_row(row, "", "conflict", message="同一 productId 最多只能有一条产品级套餐说明任务"))
                    elif intro_rows:
                        self._precheck_product(draft, intro_rows[0])
                    for row in rows:
                        self._precheck_write_row(draft, row)
                except Exception as exc:
                    msg = str(exc)
                    for row in rows:
                        self.emit_result(self.result_for_row(row, "", "error", message=msg))
            self.out_queue.put(("done", self.ordered_results()))
        except Exception as exc:
            self.out_queue.put(("fatal", f"{exc}\n{traceback.format_exc()}"))

    def run_refresh_auth(self) -> None:
        try:
            product_id = next((row.product_id for row in self.rows if row.enabled and row.product_id), "")
            path, loaded, source = refresh_plain_auth(validation_product_id=product_id, area="product")
            self.log(f"已刷新登录态：来源={source}，cookie={loaded} 个，写入 {path}")
            for row in self.rows:
                if row.enabled:
                    self.emit_result(self.result_for_row(row, "", "auth_refreshed", message=f"明文 Cookie 已写入：{path}"))
            self.out_queue.put(("done", self.ordered_results()))
        except Exception as exc:
            self.out_queue.put(("fatal", f"{exc}\n{traceback.format_exc()}"))

    def run_apply(self) -> None:
        try:
            self._check_auth()
            grouped = group_rows(self.rows)
            run_dir = make_write_run_dir()
            self.log(f"本次写入审计目录：{run_dir}")
            self.log(f"开始保存草稿：{len(grouped)} 个产品任务")
            for idx, (product_id, rows) in enumerate(grouped.items(), start=1):
                if self.stop_event.is_set():
                    break
                self.out_queue.put(("progress", f"保存 {idx}/{len(grouped)} 产品 {product_id}"))
                try:
                    draft = self.client.load_product(product_id, self.stop_event)
                    currency_context = self.client.load_product_currency_context(product_id, self.stop_event)
                    intro_rows = [row for row in rows if template_row_has_intro_task(row)]
                    if len(intro_rows) > 1:
                        for row in intro_rows:
                            self.emit_result(self.result_for_row(row, "", "conflict", message="同一 productId 最多只能有一条产品级套餐说明任务"))
                        continue
                    modifications = self._collect_sku_plans(draft, intro_rows[0]) if intro_rows else []
                    write_plans = [plan for row in rows for plan in self._collect_write_plans(draft, row, emit_unchanged=False, emit_update=False)]

                    new_package_info = copy.deepcopy(draft.package_info)
                    resources = new_package_info.get("packageResourceInfo") or []
                    intro_by_index = {plan.resource_index: plan.new_introduction_html for plan in modifications}
                    for resource_index, introduction_html in intro_by_index.items():
                        if resource_index < len(resources):
                            resources[resource_index]["introduction"] = introduction_html
                    connection_plans = [plan for plan in write_plans if plan.new_vendor_package_id or plan.new_connection_code]
                    for plan in connection_plans:
                        for item in resources:
                            if str(item.get("packageId") or "") == plan.package_id:
                                if plan.new_vendor_package_id:
                                    item["vendorPackageId"] = plan.new_vendor_package_id
                                set_connection_code(item, plan.new_connection_code or plan.new_vendor_package_id)
                                break

                    if modifications or connection_plans:
                        backup_package_info(product_id, draft.package_info, self.backup_dir)
                        payload = build_save_payload(draft.product_id, new_package_info, None, product_version=draft.product_version)
                        payload, _rewrite_count = apply_product_edit_currency_rewrite(payload, currency_context)
                        response = self.client.save_package_info(draft, new_package_info, self.stop_event, currency_context=currency_context)
                        write_audit_record(
                            run_dir,
                            product_id,
                            "package_info",
                            {
                                "createdAt": now_iso(),
                                "kind": "package_info",
                                "before": draft.package_info,
                                "request": payload,
                                "response": response,
                            },
                        )
                        if not response_success(response):
                            raise RuntimeError(response_message(response, "保存接口返回失败"))

                        verified_draft = self.client.load_product(product_id, self.stop_event)
                        verified_resources = verified_draft.package_resources
                        for plan in modifications:
                            ok = plan.resource_index < len(verified_resources) and str(verified_resources[plan.resource_index].get("introduction") or "") == plan.new_introduction_html
                            self.emit_result(
                                self.result_for_row(
                                    plan.row,
                                    plan.package_name,
                                    "saved" if ok else "verify_failed",
                                    old_introduction=ctrip_intro_to_text(plan.old_introduction),
                                    new_introduction=plan.new_introduction_text,
                                    package_id=str(verified_resources[plan.resource_index].get("packageId") or "") if plan.resource_index < len(verified_resources) else "",
                                    resource_id=resource_id_from_package_resource(verified_resources[plan.resource_index]) if plan.resource_index < len(verified_resources) else "",
                                    message=f"{'已保存并核对成功' if ok else '保存后核对未通过'} | 模板：{plan.selected_template}",
                                )
                            )
                        for plan in connection_plans:
                            verified_index, verified_item = find_package_resource(verified_draft, TemplateRow(row_number=plan.row.row_number, product_id=product_id, package_id=plan.package_id))
                            verified_vendor = str(verified_item.get("vendorPackageId") or "")
                            verified_code = connection_code_from_package_resource(verified_item)
                            ok = (not plan.new_vendor_package_id or verified_vendor == plan.new_vendor_package_id) and (not plan.new_connection_code or verified_code == plan.new_connection_code)
                            self.emit_result(
                                self.result_for_row(
                                    plan.row,
                                    plan.package_name,
                                    "saved" if ok else "verify_failed",
                                    package_id=plan.package_id,
                                    resource_id=plan.resource_id,
                                    old_vendor_package_id=plan.old_vendor_package_id,
                                    new_vendor_package_id=plan.new_vendor_package_id,
                                    old_connection_code=plan.old_connection_code,
                                    new_connection_code=plan.new_connection_code,
                                    message=f"{'API 对接配置已保存并核对成功' if ok else 'API 对接配置保存后核对未通过'} | index={verified_index}",
                                )
                            )

                    price_plans = [plan for plan in write_plans if plan.new_cost_price]
                    if price_plans:
                        price_stock_draft = self.client.load_product_price_stock_draft(product_id, self.stop_event, refresh=True)
                        ensure_price_stock_draft_lists(price_stock_draft)
                        package_price_stock_list = price_stock_draft.get("packagePriceAndStockList") or []
                        price_stock_by_package = {
                            str(item.get("packageId") or ""): item
                            for item in package_price_stock_list
                            if isinstance(item, dict)
                        }
                        before_price_by_plan: dict[int, dict[str, Any]] = {}
                        executable_price_plans: list[SkuWritePlan] = []
                        for plan in price_plans:
                            package_price_stock = price_stock_by_package.get(plan.package_id)
                            if not isinstance(package_price_stock, dict):
                                self.emit_result(self.result_for_row(plan.row, plan.package_name, "error", package_id=plan.package_id, resource_id=plan.resource_id, message="PriceAndStock 草稿中未找到目标套餐"))
                                continue
                            before_price_by_plan[id(plan)] = package_price_stock_to_price_and_stock(package_price_stock)
                            try:
                                set_package_cost_price_draft(package_price_stock, plan.resource_id, plan.new_cost_price)
                            except Exception as exc:
                                self.emit_result(self.result_for_row(plan.row, plan.package_name, "error", package_id=plan.package_id, resource_id=plan.resource_id, old_cost_price=plan.old_cost_price, new_cost_price=plan.new_cost_price, message=str(exc)))
                                continue
                            executable_price_plans.append(plan)
                        response = self.client.save_product_price_stock_draft(product_id, price_stock_draft, self.stop_event, None, currency_context=currency_context) if executable_price_plans else {}
                        main_response: dict[str, Any] = {}
                        if executable_price_plans and response_success(response):
                            latest_draft = self.client.load_product(product_id, self.stop_event)
                            latest_price_stock = self.client.load_product_price_stock_draft(product_id, self.stop_event, refresh=True)
                            currency_context = build_currency_rewrite_context(product_id, latest_price_stock)
                            main_payload = build_price_effect_main_save_payload(
                                product_id,
                                latest_draft.package_info,
                                latest_price_stock,
                                latest_draft.product_version,
                                currency_context,
                            )
                            main_response = self.client._request_json(SAVE_PRODUCT_DRAFT_URL, product_id, main_payload, self.stop_event, timeout=120)
                        write_audit_record(
                            run_dir,
                            product_id,
                            "price_stock",
                            {
                                "createdAt": now_iso(),
                                "kind": "price_stock",
                                "before": {plan.package_id: before_price_by_plan.get(id(plan)) for plan in executable_price_plans},
                                "request": self.client.build_price_stock_save_payload(product_id, price_stock_draft, None, currency_context=currency_context) if executable_price_plans else {},
                                "response": response,
                                "mainSaveRequest": main_payload if executable_price_plans and main_response else {},
                                "mainSaveResponse": main_response,
                                "plans": [asdict(plan) for plan in executable_price_plans],
                            },
                        )
                        if executable_price_plans and not response_success(response):
                            raise RuntimeError(response_message(response, "保存价格接口返回失败"))
                        if executable_price_plans and not response_success(main_response):
                            raise RuntimeError(response_message(main_response, "价格生效接口返回失败"))
                        for plan in executable_price_plans:
                            try:
                                verified_cost = formal_cost_price(self.client, product_id, plan.package_id, plan.resource_id, self.stop_event)
                                ok = verified_cost == normalize_number_text(plan.new_cost_price)
                            except Exception as exc:
                                verified_cost = ""
                                ok = False
                                verify_message = str(exc)
                            else:
                                verify_message = f"{'价格已保存并生效核对成功' if ok else '价格保存后正式核对未通过'} | old={plan.old_cost_price} new={plan.new_cost_price} verify={verified_cost}"
                            self.emit_result(
                                self.result_for_row(
                                    plan.row,
                                    plan.package_name,
                                    "saved" if ok else "verify_failed",
                                    package_id=plan.package_id,
                                    resource_id=plan.resource_id,
                                    old_cost_price=plan.old_cost_price,
                                    new_cost_price=plan.new_cost_price,
                                    message=verify_message,
                                )
                            )

                    if not modifications and not write_plans and not any(row.submit_audit for row in rows):
                        self.log(f"产品 {product_id} 没有可保存项，跳过")

                    if any(row.submit_audit for row in rows) and not self.allow_submit_audit:
                        for row in rows:
                            if row.submit_audit:
                                self.emit_result(self.result_for_row(row, row.package_name, "audit_skipped", message="已保存草稿；当前按钮不执行提交审核"))

                    if any(row.submit_audit for row in rows) and self.allow_submit_audit:
                        latest_draft = self.client.load_product(product_id, self.stop_event)
                        submit_result = self.client.submit_audit_with_payload(latest_draft, self.stop_event, currency_context=currency_context)
                        if not response_success(submit_result.response) and is_version_conflict(submit_result.response):
                            latest_draft = self.client.load_product(product_id, self.stop_event)
                            submit_result = self.client.submit_audit_with_payload(latest_draft, self.stop_event, currency_context=currency_context)
                        write_audit_record(
                            run_dir,
                            product_id,
                            "submit_audit",
                            {
                                "createdAt": now_iso(),
                                "kind": "submit_audit",
                                "request": submit_result.request,
                                "response": submit_result.response,
                                "confirmedContinue": submit_result.confirmed_continue,
                                "confirmReason": submit_result.confirm_reason,
                                "confirmReasons": submit_result.confirm_reasons,
                                "initialResponse": submit_result.initial_response,
                                "intermediateResponses": submit_result.intermediate_responses,
                            },
                        )
                        if not response_success(submit_result.response):
                            raise RuntimeError(response_message(submit_result.response, "提交审核接口返回失败"))
                        for row in rows:
                            if row.submit_audit:
                                message = "提交审核成功"
                                if submit_result.confirmed_continue:
                                    message += f"（已确认继续：{submit_result.confirm_reason}）"
                                self.emit_result(self.result_for_row(row, row.package_name, "audit_submitted", message=message))
                except Exception as exc:
                    msg = str(exc)
                    self.log(f"产品 {product_id} 保存失败：{msg}")
                    for row in rows:
                        if not any(r.product_id == product_id and r.row_number == row.row_number and r.status == "error" for r in self.results):
                            self.emit_result(self.result_for_row(row, "", "error", message=msg))
            self.out_queue.put(("done", self.ordered_results()))
        except Exception as exc:
            self.out_queue.put(("fatal", f"{exc}\n{traceback.format_exc()}"))

    def _check_auth(self) -> None:
        if read_plain_cookie():
            return
        raise RuntimeError("未找到 Ctrip 登录态。请先点击“刷新登录态”，从当前 Edge/Chrome 登录浏览器读取并校验 Cookie")

    def _precheck_write_row(self, draft: ProductDraft, row: TemplateRow) -> None:
        self._collect_write_plans(draft, row, emit_unchanged=True)
        if row.submit_audit and not (template_row_has_price_task(row) or template_row_has_connection_task(row)):
            self.emit_result(self.result_for_row(row, row.package_name, "will_submit_audit", message="该行启用 submit_audit=是，执行保存后会提交审核"))

    def _collect_write_plans(self, draft: ProductDraft, row: TemplateRow, emit_unchanged: bool, emit_update: bool = True) -> list[SkuWritePlan]:
        plans: list[SkuWritePlan] = []
        if row.validation_error:
            self.emit_result(self.result_for_row(row, row.package_name, "invalid", message=row.validation_error))
            return plans
        if not template_row_has_price_task(row) and not template_row_has_connection_task(row):
            return plans

        try:
            resource_index, item = find_package_resource(draft, row)
        except Exception as exc:
            self.emit_result(self.result_for_row(row, row.package_name, "error", message=str(exc)))
            return plans

        package_id = str(item.get("packageId") or row.package_id)
        package_name = str(item.get("packageName") or row.package_name)
        resource_id = resource_id_from_package_resource(item)
        if not resource_id:
            self.emit_result(self.result_for_row(row, package_name, "error", package_id=package_id, message="目标套餐缺少 resourceId"))
            return plans

        old_vendor = str(item.get("vendorPackageId") or "")
        new_vendor = row.target_vendor_package_id
        old_connection = connection_code_from_package_resource(item)
        new_connection = row.target_connection_code or row.target_vendor_package_id
        old_cost = ""
        interfaces: list[str] = []

        if template_row_has_price_task(row):
            bundle = self.client.get_resource_price_and_stock(draft.product_id, package_id, resource_id, self.stop_event)
            old_cost = current_cost_price(bundle.price_and_stock, resource_id)
            if old_cost != normalize_number_text(row.target_cost_price):
                interfaces.append("saveOrEffectProductDraft(PriceAndStock)")

        if template_row_has_connection_task(row):
            if (new_vendor and old_vendor != new_vendor) or (new_connection and old_connection != new_connection):
                interfaces.append("saveOrEffectProductDraft(type=2)")

        plan = SkuWritePlan(
            row=row,
            resource_index=resource_index,
            package_id=package_id,
            package_name=package_name,
            resource_id=resource_id,
            old_cost_price=old_cost,
            new_cost_price=normalize_number_text(row.target_cost_price),
            old_vendor_package_id=old_vendor,
            new_vendor_package_id=new_vendor,
            old_connection_code=old_connection,
            new_connection_code=new_connection,
            planned_interfaces=interfaces,
            payload_summary=json.dumps(
                {
                    "packageId": package_id,
                    "resourceId": resource_id,
                    "oldCostPrice": old_cost,
                    "newCostPrice": normalize_number_text(row.target_cost_price),
                    "oldVendorPackageId": old_vendor,
                    "newVendorPackageId": new_vendor,
                    "oldConnectionCode": old_connection,
                    "newConnectionCode": new_connection,
                    "interfaces": interfaces,
                    "submitAudit": row.submit_audit,
                },
                ensure_ascii=False,
            ),
        )
        if interfaces:
            plans.append(plan)
            if emit_update:
                self.emit_result(
                    self.result_for_row(
                        row,
                        package_name,
                        "will_update",
                        package_id=package_id,
                        resource_id=resource_id,
                        old_cost_price=old_cost,
                        new_cost_price=plan.new_cost_price,
                        old_vendor_package_id=old_vendor,
                        new_vendor_package_id=new_vendor,
                        old_connection_code=old_connection,
                        new_connection_code=new_connection,
                        message=plan.payload_summary,
                    )
                )
        elif emit_unchanged:
            self.emit_result(
                self.result_for_row(
                    row,
                    package_name,
                    "unchanged",
                    package_id=package_id,
                    resource_id=resource_id,
                    old_cost_price=old_cost,
                    new_cost_price=plan.new_cost_price,
                    old_vendor_package_id=old_vendor,
                    new_vendor_package_id=new_vendor,
                    old_connection_code=old_connection,
                    new_connection_code=new_connection,
                    message="价格/API 对接配置目标值与当前值一致，无需保存",
                )
            )
        return plans

    def _precheck_product(self, draft: ProductDraft, row: TemplateRow) -> None:
        modifications = self._collect_sku_plans(draft, row)
        for plan in modifications:
            diff = build_diff(plan.old_introduction, plan.new_introduction_html)
            self.emit_result(
                self.result_for_row(
                    row,
                    plan.package_name,
                    "will_update",
                    old_introduction=ctrip_intro_to_text(plan.old_introduction),
                    new_introduction=plan.new_introduction_text,
                    message=f"模板：{plan.selected_template}\n{diff or '内容相同'}",
                )
            )

    def _collect_sku_plans(self, draft: ProductDraft, row: TemplateRow) -> list[SkuPlan]:
        modifications: list[SkuPlan] = []
        if row.validation_error:
            self.emit_result(self.result_for_row(row, "", "invalid", message=row.validation_error))
            return modifications

        for resource_index, item in enumerate(draft.package_resources):
            package_name = str(item.get("packageName") or "").strip()
            if not package_name:
                self.emit_result(self.result_for_row(row, "", "invalid", message=f"接口第 {resource_index + 1} 个 SKU 缺少 packageName"))
                continue

            new_text, selected_template, error = generate_intro_from_rule(row.usedup_throttle, row.reset_time_calc, row.inst_adv, package_name)
            if error and selected_template is None:
                self.emit_result(self.result_for_row(row, package_name, "skipped", message=error))
                continue
            if error:
                self.emit_result(self.result_for_row(row, package_name, "invalid", message=error))
                continue
            if text_length_for_limit(new_text) > MAX_INTRO_TEXT_LENGTH:
                self.emit_result(self.result_for_row(row, package_name, "invalid", new_introduction=new_text, message="套餐说明超过 300 字限制"))
                continue

            new_html = text_to_ctrip_intro(new_text)
            old_intro = str(item.get("introduction") or "")
            if old_intro == new_html:
                self.emit_result(self.result_for_row(row, package_name, "unchanged", old_introduction=ctrip_intro_to_text(old_intro), new_introduction=new_text, message=f"内容相同，无需保存 | 模板：{selected_template}"))
                continue
            modifications.append(
                SkuPlan(
                    row=row,
                    resource_index=resource_index,
                    package_name=package_name,
                    old_introduction=old_intro,
                    new_introduction_text=new_text,
                    new_introduction_html=new_html,
                    selected_template=selected_template,
                )
            )
        return modifications


def result_from_diff(plan: DiffPlan, status: str | None = None, message: str | None = None) -> ResultRow:
    return ResultRow(
        product_id=plan.product_id,
        package_id=plan.package_id,
        resource_id=plan.resource_id,
        package_name=plan.package_name,
        status=status or plan.status,
        field_name=plan.field_name,
        interface_name=plan.interface_name,
        old_value=plan.old_value,
        new_value=plan.new_value,
        old_cost_price=plan.old_value if plan.field_name == "costPrice" else "",
        new_cost_price=plan.new_value if plan.field_name == "costPrice" else "",
        old_vendor_package_id=plan.old_value if plan.field_name == "vendorPackageId" else "",
        new_vendor_package_id=plan.new_value if plan.field_name == "vendorPackageId" else "",
        old_connection_code=plan.old_value if plan.field_name == "connectionCode" else "",
        new_connection_code=plan.new_value if plan.field_name == "connectionCode" else "",
        old_introduction=plan.old_value if plan.field_name == "introduction" else "",
        new_introduction=plan.new_value if plan.field_name == "introduction" else "",
        usedup_throttle=plan.row.usedup_throttle,
        reset_time_calc=plan.row.reset_time_calc,
        inst_adv=plan.row.inst_adv,
        row_number=plan.row.row_number,
        message=message if message is not None else f"{plan.field_name} | {plan.interface_name} | {plan.message}",
        workbench=plan.workbench,
    )


class ProductWorkflowWorker:
    def __init__(
        self,
        out_queue: queue.Queue,
        stop_event: threading.Event,
        preloaded_products: dict[str, ProductSnapshot],
        pending_diff_plans: list[DiffPlan],
        last_saved_products: set[str],
        request_interval_seconds: float = CTRIP_REQUEST_INTERVAL_SECONDS,
        parallel_requests: int = DEFAULT_PARALLEL_REQUESTS,
        client_factory: Callable[[], CtripRequestsClient] | None = None,
        runtime_settings: RuntimeRequestSettings | None = None,
        stats_recorder: Callable[[str], None] | None = None,
        workbench: str = ProductWorkbench.PACKAGE_CONNECT,
    ):
        self.out_queue = out_queue
        self.stop_event = stop_event
        self.preloaded_products = preloaded_products
        self.pending_diff_plans = pending_diff_plans
        self.last_saved_products = last_saved_products
        self.results: list[ResultRow] = []
        self.runtime_settings = runtime_settings or RuntimeRequestSettings(request_interval_seconds, parallel_requests)
        initial_settings = self.runtime_settings.snapshot()
        self.request_interval_seconds = initial_settings.request_interval_seconds
        self.parallel_requests = initial_settings.parallel_requests
        self.lock = threading.Lock()
        self.product_order: dict[str, int] = {}
        self._client_factory = client_factory
        self.stats_recorder = stats_recorder
        self.client: CtripRequestsClient | None = None
        self.workbench = product_workbench_spec(workbench).key

    def log(self, message: str) -> None:
        self.out_queue.put(("log", message))

    def new_client(self) -> CtripRequestsClient:
        if self._client_factory is not None:
            return self._client_factory()
        return CtripRequestsClient(
            self.log,
            request_interval_seconds=self.runtime_settings.request_interval_seconds(),
            request_interval_provider=self.runtime_settings.request_interval_seconds,
            stats_area="product",
            stats_recorder=self.stats_recorder,
        )

    def shared_client(self) -> CtripRequestsClient:
        if self.client is None:
            self.client = self.new_client()
        return self.client

    def emit_result(self, result: ResultRow) -> None:
        with self.lock:
            self.results.append(result)
        self.out_queue.put(("result", result))

    def emit_results(self, results: list[ResultRow]) -> None:
        if not results:
            return
        with self.lock:
            self.results.extend(results)
        for index in range(0, len(results), RESULT_BATCH_SIZE):
            self.out_queue.put(("result_batch", results[index:index + RESULT_BATCH_SIZE]))

    def set_product_order(self, product_ids: list[str]) -> None:
        self.product_order = product_order_map(product_ids)
        self.out_queue.put(("product_order", self.product_order))

    def ordered_results(self) -> list[ResultRow]:
        with self.lock:
            return ordered_product_results(self.results, self.product_order)

    def _run_items(
        self,
        items: list[Any],
        handler: Callable[[int, Any, CtripRequestsClient], str | None],
        audit_writer: AuditQueueWriter | None = None,
    ) -> None:
        settings = self.runtime_settings.snapshot()
        self.request_interval_seconds = settings.request_interval_seconds
        self.parallel_requests = settings.parallel_requests
        GLOBAL_REQUEST_LIMITER.configure_for_workload(settings.request_interval_seconds, settings.parallel_requests)
        controller = AdaptiveLoadController(settings.parallel_requests, settings.request_interval_seconds, task_count=len(items))
        self.log(f"并行上限={settings.parallel_requests}，初始实际并发={controller.current_parallel()}，任务数={len(items)}")

        def run_handler(index: int, item: Any) -> str | None:
            return handler(index, item, self.new_client())

        def pressure_provider() -> AdaptiveRunPressure:
            with self.lock:
                result_count = len(self.results)
            return AdaptiveRunPressure(
                queue_size=self.out_queue.qsize(),
                audit_queue_size=audit_writer.qsize() if audit_writer is not None else 0,
                result_count=result_count,
            )

        def pressure_callback(active_controller: AdaptiveLoadController) -> None:
            self.out_queue.put(
                (
                    "pressure",
                    {
                        "area": "product",
                        "parallel": active_controller.current_parallel(),
                        "desired": active_controller.desired_parallel,
                        "interval": active_controller.request_interval_seconds,
                        "reason": active_controller.pressure_reason(),
                    },
                )
            )

        run_adaptive_items(
            items,
            run_handler,
            self.stop_event,
            controller,
            pressure_provider=pressure_provider,
            pressure_callback=pressure_callback,
            runtime_settings_provider=self.runtime_settings.snapshot,
        )

    def emit_plan_result(self, plan: DiffPlan, status: str | None = None, message: str | None = None) -> None:
        if status is not None:
            plan.status = status
        if message is not None:
            plan.message = message
        self.emit_result(result_from_diff(plan, status=status, message=message))

    def run_preload(self, product_ids: list[str]) -> None:
        try:
            self.set_product_order(product_ids)
            self.log(f"开始预载：{len(product_ids)} 个产品，并行={self.parallel_requests}")
            successful_product_ids: set[str] = set()

            def handle_product(index: int, product_id: str, client: CtripRequestsClient) -> str:
                self.out_queue.put(("progress", f"预载 {index}/{len(product_ids)} 产品 {product_id}"))
                try:
                    snapshot = build_product_snapshot(
                        client,
                        product_id,
                        self.stop_event,
                        product_snapshot_needs_for_workbench(self.workbench, []),
                    )
                    with self.lock:
                        self.preloaded_products[product_id] = snapshot
                        self.last_saved_products.discard(product_id)
                        successful_product_ids.add(product_id)
                    price_success = sum(1 for sku in snapshot.sku_snapshots.values() if sku.price_and_stock is not None)
                    price_unavailable = sum(1 for sku in snapshot.sku_snapshots.values() if sku.price_and_stock is None and sku_price_unavailable_reason(sku))
                    price_failed = sum(1 for sku in snapshot.sku_snapshots.values() if sku.price_and_stock is None and not sku_price_unavailable_reason(sku))
                    product_name_status = "已读取" if product_name_from_snapshot(snapshot) else "为空"
                    self.emit_result(
                        ResultRow(
                            product_id=product_id,
                            package_name="",
                            status="preloaded",
                            message=(
                                f"SKU={len(snapshot.sku_snapshots)} | "
                                f"价格成功={price_success} 无价格库存={price_unavailable} 异常失败={price_failed} | "
                                f"productName={product_name_status} | "
                                f"币种转换={'HKD' if snapshot.currency_context.should_rewrite else '无需'}"
                            ),
                        )
                    )
                    return "preloaded"
                except Exception as exc:
                    self.emit_result(ResultRow(product_id=product_id, package_name="", status="error", message=str(exc)))
                    return "error"

            self._run_items(product_ids, handle_product)
            self.out_queue.put(("audit_candidates", successful_preload_audit_candidates(product_ids, successful_product_ids)))
            self.out_queue.put(("done", self.ordered_results()))
        except Exception as exc:
            self.out_queue.put(("fatal", f"{exc}\n{traceback.format_exc()}"))

    def run_preview_template(self, path: str) -> None:
        try:
            rows = read_edit_template(path, self.workbench)
            product_ids = product_ids_from_edit_rows(rows)
            snapshot_needs = product_snapshot_needs_for_workbench(self.workbench, rows)
            self.set_product_order(product_ids)
            with self.lock:
                self.preloaded_products.clear()
                self.pending_diff_plans.clear()
                self.last_saved_products.clear()
            successful_product_ids: set[str] = set()

            if product_ids:
                self.log(f"读取模板后自动预载：{len(product_ids)} 个产品，并行={self.parallel_requests}")

                def handle_product(index: int, product_id: str, client: CtripRequestsClient) -> str:
                    self.out_queue.put(("progress", f"模板预载 {index}/{len(product_ids)} 产品 {product_id}"))
                    try:
                        snapshot = build_product_snapshot(client, product_id, self.stop_event, snapshot_needs)
                        with self.lock:
                            self.preloaded_products[product_id] = snapshot
                            successful_product_ids.add(product_id)
                        return "preloaded"
                    except Exception as exc:
                        self.log(f"产品 {product_id} 模板预载失败：{exc}")
                        return "error"

                self._run_items(product_ids, handle_product)
            else:
                self.log("模板中没有可预载的有效 productId，仅生成行级校验结果")

            plans = build_diff_plans_from_rows(self.preloaded_products, rows, self.workbench)
            with self.lock:
                self.pending_diff_plans.clear()
                self.pending_diff_plans.extend(plans)
            self.emit_results([result_from_diff(plan) for plan in plans])
            self.out_queue.put(("audit_candidates", successful_preload_audit_candidates(product_ids, successful_product_ids)))
            self.out_queue.put(("done", self.ordered_results()))
        except Exception as exc:
            self.out_queue.put(("fatal", f"{exc}\n{traceback.format_exc()}"))

    def run_apply_pending(self) -> None:
        try:
            plans = [plan for plan in self.pending_diff_plans if plan.status == "pending"]
            wrong_workbench = [plan for plan in plans if plan.workbench != self.workbench]
            if wrong_workbench:
                for plan in wrong_workbench:
                    self.emit_plan_result(plan, status="error", message=f"当前工作台不能传出 {product_workbench_spec(plan.workbench).title} 的 Diff")
                plans = [plan for plan in plans if plan.workbench == self.workbench]
            if not plans:
                self.emit_result(ResultRow(product_id="", package_name="", status="skipped", message="没有 pending diff 可传出"))
                self.out_queue.put(("done", self.ordered_results()))
                return
            run_dir = make_write_run_dir()
            audit_writer = AuditQueueWriter()
            self.log(f"本次写入审计目录：{run_dir}")
            by_product: dict[str, list[DiffPlan]] = {}
            for plan in plans:
                by_product.setdefault(plan.product_id, []).append(plan)
            self.set_product_order([plan.product_id for plan in plans])
            items = list(by_product.items())

            def handle_product(index: int, item: tuple[str, list[DiffPlan]], client: CtripRequestsClient) -> str:
                product_id, product_plans = item
                target = ProductRequestTarget(target_product_id(product_id))
                self.out_queue.put(("progress", f"传出 {index}/{len(by_product)} 产品 {target.product_id}"))
                try:
                    saved_any = self._apply_product_plans(target.product_id, product_plans, run_dir, client, audit_writer=audit_writer)
                    if saved_any:
                        with self.lock:
                            self.last_saved_products.add(target.product_id)
                    return "saved" if saved_any else "ok"
                except Exception as exc:
                    self.log(f"产品 {target.product_id} 传出失败：{exc}")
                    for plan in product_plans:
                        self.emit_plan_result(plan, status="error", message=str(exc))
                    return "error"

            try:
                self._run_items(items, handle_product, audit_writer=audit_writer)
            finally:
                audit_writer.close()
            self.out_queue.put(("done", self.ordered_results()))
        except Exception as exc:
            self.out_queue.put(("fatal", f"{exc}\n{traceback.format_exc()}"))

    def run_submit_saved(self, product_ids: list[str]) -> None:
        try:
            if not product_ids:
                self.emit_result(ResultRow(product_id="", package_name="", status="skipped", message="没有当前预览/预载产品可提交审核"))
                self.out_queue.put(("done", self.ordered_results()))
                return
            self.set_product_order(product_ids)
            run_dir = make_write_run_dir()
            audit_writer = AuditQueueWriter()

            def handle_product(index: int, product_id: str, client: CtripRequestsClient) -> str:
                target = ProductRequestTarget(target_product_id(product_id))
                transaction_id = new_transaction_id()
                self.out_queue.put(("progress", f"提交审核 {index}/{len(product_ids)} 产品 {target.product_id}"))
                try:
                    latest_draft = client.load_product(target.product_id, self.stop_event)
                    currency_context = client.load_product_currency_context(target.product_id, self.stop_event, refresh=True)
                    submit_result = client.submit_audit_with_payload(latest_draft, self.stop_event, currency_context=currency_context)
                    if not response_success(submit_result.response) and is_version_conflict(submit_result.response):
                        latest_draft = client.load_product(target.product_id, self.stop_event)
                        submit_result = client.submit_audit_with_payload(latest_draft, self.stop_event, currency_context=currency_context)
                    assert_product_payload_target(submit_result.request, target, "submit_audit_audit_record")
                    audit_write_or_enqueue(
                        audit_writer,
                        run_dir,
                        target.product_id,
                        "submit_audit",
                        {
                            "createdAt": now_iso(),
                            "kind": "submit_audit",
                            "request": submit_result.request,
                            "response": submit_result.response,
                            "confirmedContinue": submit_result.confirmed_continue,
                            "confirmReason": submit_result.confirm_reason,
                            "confirmReasons": submit_result.confirm_reasons,
                            "initialResponse": submit_result.initial_response,
                            "intermediateResponses": submit_result.intermediate_responses,
                        },
                        target=target,
                        transaction_id=transaction_id,
                    )
                    if not response_success(submit_result.response):
                        raise RuntimeError(response_message(submit_result.response, "提交审核接口返回失败"))
                    message = "提交审核成功"
                    if submit_result.confirmed_continue:
                        message += f"（已确认继续：{submit_result.confirm_reason}）"
                    self.emit_result(ResultRow(
                        product_id=target.product_id,
                        package_name="",
                        status="audit_submitted",
                        field_name="submit_audit",
                        interface_name="saveOrEffectProductDraft(type=3)",
                        message=message,
                    ))
                    return "saved"
                except Exception as exc:
                    self.emit_result(ResultRow(
                        product_id=target.product_id,
                        package_name="",
                        status="error",
                        field_name="submit_audit",
                        interface_name="saveOrEffectProductDraft(type=3)",
                        message=str(exc),
                    ))
                    return "error"

            try:
                self._run_items(product_ids, handle_product, audit_writer=audit_writer)
            finally:
                audit_writer.close()
            self.out_queue.put(("done", self.ordered_results()))
        except Exception as exc:
            self.out_queue.put(("fatal", f"{exc}\n{traceback.format_exc()}"))

    def _apply_product_info_plans(
        self,
        product_id: str,
        plans: list[DiffPlan],
        run_dir: Path,
        client: CtripRequestsClient,
        audit_writer: AuditQueueWriter | None = None,
    ) -> bool:
        target = ProductRequestTarget(target_product_id(product_id))
        transaction_id = new_transaction_id()
        product_info = client.load_product_info_draft(target.product_id, self.stop_event)
        current_name = product_name_from_snapshot(
            ProductSnapshot(
                product_id=target.product_id,
                created_at=now_iso(),
                draft=ProductDraft(target.product_id, target.product_id, {}, [], draft_raw=product_info),
                sku_snapshots={},
            )
        )
        active_plans: list[DiffPlan] = []
        for plan in plans:
            if plan.field_name != "productName":
                self.emit_plan_result(plan, status="error", message=f"产品资料工作台不支持字段：{plan.field_name}")
                continue
            if current_name != plan.old_value:
                self.emit_plan_result(plan, status="stale", message="接口当前产品名称已不同于预载快照，请重新预载后再传出")
                continue
            active_plans.append(plan)
        if not active_plans:
            return False
        latest_plan = active_plans[-1]
        payload = build_product_info_name_payload(target.product_id, product_info, latest_plan.new_value)
        response = client.save_product_info_draft(target.product_id, payload, self.stop_event)
        audit_write_or_enqueue(
            audit_writer,
            run_dir,
            target.product_id,
            "product_info",
            {
                "createdAt": now_iso(),
                "kind": "product_info",
                "request": payload,
                "response": response,
                "plans": [asdict(plan) for plan in active_plans],
            },
            target=target,
            transaction_id=transaction_id,
        )
        if not response_success(response):
            raise RuntimeError(response_message(response, "保存产品资料接口返回失败"))
        verified = client.load_product_info_draft(target.product_id, self.stop_event)
        verified_name = product_name_from_snapshot(
            ProductSnapshot(
                product_id=target.product_id,
                created_at=now_iso(),
                draft=ProductDraft(target.product_id, target.product_id, {}, [], draft_raw=verified),
                sku_snapshots={},
            )
        )
        saved_any = False
        for plan in active_plans:
            ok = verified_name == plan.new_value
            self.emit_plan_result(plan, status="saved" if ok else "verify_failed", message=f"ProductInfo 回读产品名称={verified_name}")
            saved_any = saved_any or ok
        return saved_any

    def _apply_product_plans(
        self,
        product_id: str,
        plans: list[DiffPlan],
        run_dir: Path,
        client: CtripRequestsClient | None = None,
        audit_writer: AuditQueueWriter | None = None,
    ) -> bool:
        target = ProductRequestTarget(target_product_id(product_id))
        transaction_id = new_transaction_id()
        validate_product_plan_targets(target, plans)
        client = client or self.shared_client()
        saved_product_info = False
        if plans and all(plan.workbench == ProductWorkbench.PRODUCT_INFO for plan in plans):
            product_info_plans = [plan for plan in plans if plan.field_name == "productName"]
            package_info_plans = [plan for plan in plans if plan.field_name != "productName"]
            if product_info_plans:
                saved_product_info = self._apply_product_info_plans(product_id, product_info_plans, run_dir, client, audit_writer)
            if not package_info_plans:
                return saved_product_info
            plans = package_info_plans
        product_id = target.product_id
        snapshot = self.preloaded_products.get(product_id)
        if not snapshot:
            raise RuntimeError("内存快照不存在，请重新预载产品ID")
        if target_product_id(snapshot.product_id) != target.product_id:
            raise RuntimeError(f"产品快照目标不一致：期望 {target.product_id}，实际 {snapshot.product_id}")
        currency_context = snapshot.currency_context
        price_plans = [plan for plan in plans if plan.interface_name == "saveOrEffectProductDraft(PriceAndStock)"]
        latest_price_stock_for_plans: dict[str, Any] | None = None
        latest_price_stock_by_package: dict[str, dict[str, Any]] = {}
        if price_plans:
            latest_price_stock_for_plans = client.load_product_price_stock_draft(product_id, self.stop_event, refresh=True)
            ensure_price_stock_draft_lists(latest_price_stock_for_plans)
            latest_price_stock_by_package = {
                str(item.get("packageId") or ""): item
                for item in latest_price_stock_for_plans.get("packagePriceAndStockList") or []
                if isinstance(item, dict)
            }
            currency_context = build_currency_rewrite_context(product_id, latest_price_stock_for_plans)
        latest_draft = client.load_product(product_id, self.stop_event)
        if target_product_id(latest_draft.product_id) != target.product_id:
            raise RuntimeError(f"产品回读目标不一致：期望 {target.product_id}，实际 {latest_draft.product_id}")
        latest_by_key: dict[str, dict[str, Any]] = {}
        for item in latest_draft.package_resources:
            package_id = str(item.get("packageId") or "")
            resource_id = resource_id_from_package_resource(item)
            if package_id and resource_id:
                latest_by_key[sku_key(product_id, package_id, resource_id)] = item

        active_plans: list[DiffPlan] = []
        for plan in plans:
            if self._is_stale(plan, snapshot, latest_by_key, client, latest_price_stock_by_package):
                self.emit_plan_result(plan, status="stale", message="接口当前值已不同于预载快照，请重新预载后再传出")
            else:
                active_plans.append(plan)
        if not active_plans:
            return False

        package_plans = [plan for plan in active_plans if plan.interface_name.startswith("saveOrEffectProductDraft(type=2)")]
        price_plans = [plan for plan in active_plans if plan.interface_name == "saveOrEffectProductDraft(PriceAndStock)"]
        saved_any = saved_product_info
        current_draft = latest_draft
        if package_plans:
            new_package_info = copy.deepcopy(latest_draft.package_info)
            resources = new_package_info.get("packageResourceInfo") or []
            for plan in package_plans:
                target_item = None
                for item in resources:
                    if str(item.get("packageId") or "") == plan.package_id:
                        target_item = item
                        break
                if not target_item:
                    self.emit_plan_result(plan, status="error", message="最新草稿中未找到目标 SKU")
                    continue
                if plan.field_name == "vendorPackageId":
                    target_item["vendorPackageId"] = plan.new_value
                elif plan.field_name == "connectionCode":
                    set_connection_code(target_item, plan.new_value)
                elif plan.field_name == "introduction":
                    if plan.workbench == ProductWorkbench.PRODUCT_INFO:
                        target_item["introduction"] = plain_intro_payload_text(plan.new_value)
                    else:
                        target_item["introduction"] = text_to_ctrip_intro(plan.new_value)
            payload = build_save_payload(product_id, new_package_info, None, product_version=latest_draft.product_version)
            payload, _rewrite_count = apply_product_edit_currency_rewrite(payload, currency_context)
            assert_product_payload_target(payload, target, "package_info")
            response = client.save_package_info(latest_draft, new_package_info, self.stop_event, currency_context=currency_context)
            audit_write_or_enqueue(
                audit_writer,
                run_dir,
                product_id,
                "package_info",
                {
                    "createdAt": now_iso(),
                    "kind": "package_info",
                    "request": payload,
                    "response": response,
                    "plans": [asdict(plan) for plan in package_plans],
                },
                target=target,
                transaction_id=transaction_id,
            )
            if not response_success(response):
                raise RuntimeError(response_message(response, "保存草稿接口返回失败"))
            verify_draft = client.load_product(product_id, self.stop_event)
            if target_product_id(verify_draft.product_id) != target.product_id:
                raise RuntimeError(f"产品保存后回读目标不一致：期望 {target.product_id}，实际 {verify_draft.product_id}")
            current_draft = verify_draft
            verified_by_key: dict[str, dict[str, Any]] = {}
            for item in verify_draft.package_resources:
                package_id = str(item.get("packageId") or "")
                resource_id = resource_id_from_package_resource(item)
                if package_id and resource_id:
                    verified_by_key[sku_key(product_id, package_id, resource_id)] = item
            for plan in package_plans:
                ok = self._verify_package_plan(plan, verified_by_key)
                self.emit_plan_result(plan, status="saved" if ok else "verify_failed", message="保存并校验成功" if ok else "保存后校验未通过")
                saved_any = saved_any or ok

        if price_plans:
            price_stock_draft = latest_price_stock_for_plans
            if not isinstance(price_stock_draft, dict):
                price_stock_draft = client.load_product_price_stock_draft(product_id, self.stop_event, refresh=True)
                ensure_price_stock_draft_lists(price_stock_draft)
            package_price_stock_list = price_stock_draft.get("packagePriceAndStockList") or []
            price_stock_by_package = {
                str(item.get("packageId") or ""): item
                for item in package_price_stock_list
                if isinstance(item, dict)
            }
            executable_price_plans: list[DiffPlan] = []
            before_price_by_plan: dict[int, dict[str, Any]] = {}
            for plan in price_plans:
                sku = snapshot.sku_snapshots.get(sku_key(product_id, plan.package_id, plan.resource_id))
                if not sku or sku.price_and_stock is None:
                    self.emit_plan_result(plan, status="error", message=(sku_price_unavailable_reason(sku) if sku else "") or (sku.price_error if sku else "") or "价格快照缺失，请重新预载")
                    continue
                package_price_stock = price_stock_by_package.get(plan.package_id)
                if not isinstance(package_price_stock, dict):
                    self.emit_plan_result(plan, status="error", message="最新 PriceAndStock 草稿中未找到目标套餐")
                    continue
                before_price_by_plan[id(plan)] = package_price_stock_to_price_and_stock(package_price_stock)
                try:
                    if plan.field_name == "costPrice":
                        set_package_cost_price_draft(package_price_stock, plan.resource_id, plan.new_value)
                    elif plan.field_name == "sale":
                        set_package_sale_status_draft(package_price_stock, plan.resource_id, plan.new_value)
                    else:
                        raise RuntimeError(f"价格库存不支持字段：{plan.field_name}")
                except Exception as exc:
                    self.emit_plan_result(plan, status="error", message=str(exc))
                    continue
                executable_price_plans.append(plan)
            response = client.save_product_price_stock_draft(product_id, price_stock_draft, self.stop_event, None, currency_context=currency_context) if executable_price_plans else {}
            main_response: dict[str, Any] = {}
            main_intermediate_responses: list[dict[str, Any]] = []
            main_confirm_reasons: list[str] = []
            if executable_price_plans and response_success(response):
                product_version = product_version_from_save_response(response, current_draft.product_version)
                main_payload = build_price_effect_main_save_payload(
                    product_id,
                    current_draft.package_info,
                    price_stock_draft,
                    product_version,
                    currency_context,
                )
                main_response = client._request_json(SAVE_PRODUCT_DRAFT_URL, product_id, main_payload, self.stop_event, timeout=120)
                while True:
                    retry_payload, confirm_reason = build_submit_audit_confirm_retry_payload(main_payload, main_response)
                    if retry_payload is None:
                        break
                    removed_marks = sorted(set(main_payload.get("effectMarks") or []) - set(retry_payload.get("effectMarks") or []))
                    self.log(
                        f"价格生效返回需确认继续：{confirm_reason}；"
                        f"移除 effectMarks={removed_marks} 后重试 productId={product_id}"
                    )
                    main_confirm_reasons.append(confirm_reason)
                    main_intermediate_responses.append(main_response)
                    main_payload = retry_payload
                    main_response = client._request_json(SAVE_PRODUCT_DRAFT_URL, product_id, main_payload, self.stop_event, timeout=120)
            request_payload = client.build_price_stock_save_payload(product_id, price_stock_draft, None, currency_context=currency_context) if executable_price_plans else {}
            if request_payload:
                assert_product_payload_target(request_payload, target, "price_stock")
            audit_write_or_enqueue(
                audit_writer,
                run_dir,
                product_id,
                "price_stock",
                {
                    "createdAt": now_iso(),
                    "kind": "price_stock",
                    "before": {plan.package_id: before_price_by_plan.get(id(plan)) for plan in executable_price_plans},
                    "request": request_payload,
                    "response": response,
                    "mainSaveRequest": main_payload if executable_price_plans and main_response else {},
                    "mainSaveResponse": main_response,
                    "mainSaveConfirmedContinue": bool(main_confirm_reasons),
                    "mainSaveConfirmReasons": main_confirm_reasons,
                    "mainSaveIntermediateResponses": main_intermediate_responses,
                    "plans": [asdict(plan) for plan in executable_price_plans],
                },
                target=target,
                transaction_id=transaction_id,
            )
            if executable_price_plans and not response_success(response):
                raise RuntimeError(response_message(response, "保存价格接口返回失败"))
            if executable_price_plans and not response_success(main_response):
                raise RuntimeError(response_message(main_response, "价格生效接口返回失败"))
            for plan in executable_price_plans:
                try:
                    if plan.field_name == "costPrice":
                        verified_value = formal_cost_price(client, product_id, plan.package_id, plan.resource_id, self.stop_event)
                        ok = verified_value == normalize_number_text(plan.new_value)
                        message = f"正式价格校验值={verified_value}"
                    else:
                        verified_value = formal_sale_status(client, product_id, plan.package_id, plan.resource_id, self.stop_event)
                        ok = verified_value == plan.new_value
                        message = f"正式开/关班状态校验值={verified_value}"
                except Exception as exc:
                    ok = False
                    message = str(exc)
                self.emit_plan_result(plan, status="saved" if ok else "verify_failed", message=message)
                saved_any = saved_any or ok
        return saved_any

    def _is_stale(
        self,
        plan: DiffPlan,
        snapshot: ProductSnapshot,
        latest_by_key: dict[str, dict[str, Any]],
        client: CtripRequestsClient | None = None,
        latest_price_stock_by_package: dict[str, dict[str, Any]] | None = None,
    ) -> bool:
        client = client or self.shared_client()
        sku = snapshot.sku_snapshots.get(sku_key(plan.product_id, plan.package_id, plan.resource_id))
        latest = latest_by_key.get(sku_key(plan.product_id, plan.package_id, plan.resource_id))
        if not sku or not latest:
            return True
        if plan.field_name == "costPrice":
            try:
                package_price_stock = (latest_price_stock_by_package or {}).get(plan.package_id)
                if not isinstance(package_price_stock, dict):
                    bundle = client.get_resource_price_and_stock(plan.product_id, plan.package_id, plan.resource_id, self.stop_event)
                    price_and_stock = bundle.price_and_stock
                else:
                    price_and_stock = package_price_stock_to_price_and_stock(package_price_stock)
                return normalize_number_text(current_cost_price(price_and_stock, plan.resource_id)) != normalize_number_text(sku.cost_price)
            except Exception:
                return True
        if plan.field_name == "sale":
            try:
                package_price_stock = (latest_price_stock_by_package or {}).get(plan.package_id)
                if not isinstance(package_price_stock, dict):
                    bundle = client.get_resource_price_and_stock(plan.product_id, plan.package_id, plan.resource_id, self.stop_event)
                    price_and_stock = bundle.price_and_stock
                else:
                    price_and_stock = package_price_stock_to_price_and_stock(package_price_stock)
                return current_sale_status(price_and_stock, plan.resource_id) != sku.sale_status
            except Exception:
                return True
        if plan.field_name == "vendorPackageId":
            return str(latest.get("vendorPackageId") or "") != sku.vendor_package_id
        if plan.field_name == "connectionCode":
            return connection_code_from_package_resource(latest) != sku.connection_code
        if plan.field_name == "introduction":
            return ctrip_intro_to_text(latest.get("introduction")) != sku.introduction
        return True

    def _verify_package_plan(self, plan: DiffPlan, verified_by_key: dict[str, dict[str, Any]]) -> bool:
        item = verified_by_key.get(sku_key(plan.product_id, plan.package_id, plan.resource_id))
        if not item:
            return False
        if plan.field_name == "vendorPackageId":
            return str(item.get("vendorPackageId") or "") == plan.new_value
        if plan.field_name == "connectionCode":
            return connection_code_from_package_resource(item) == plan.new_value
        if plan.field_name == "introduction":
            return ctrip_intro_to_text(item.get("introduction")) == plan.new_value
        return False




class TranslationWorkflowWorker:
    def __init__(
        self,
        out_queue: queue.Queue,
        stop_event: threading.Event,
        translation_snapshots: dict[str, TranslationSnapshot],
        pending_translation_plans: list[TranslationDiffPlan],
        last_saved_translation_products: set[str],
        translation_online_context: TranslationOnlineContext | None = None,
        request_interval_seconds: float = CTRIP_REQUEST_INTERVAL_SECONDS,
        parallel_requests: int = DEFAULT_PARALLEL_REQUESTS,
        client_factory: Callable[[], CtripRequestsClient] | None = None,
        runtime_settings: RuntimeRequestSettings | None = None,
        stats_recorder: Callable[[str], None] | None = None,
    ):
        self.out_queue = out_queue
        self.stop_event = stop_event
        self.translation_snapshots = translation_snapshots
        self.pending_translation_plans = pending_translation_plans
        self.last_saved_translation_products = last_saved_translation_products
        self.translation_online_context = translation_online_context
        self.results: list[TranslationResultRow] = []
        self.runtime_settings = runtime_settings or RuntimeRequestSettings(request_interval_seconds, parallel_requests)
        initial_settings = self.runtime_settings.snapshot()
        self.request_interval_seconds = initial_settings.request_interval_seconds
        self.parallel_requests = initial_settings.parallel_requests
        self.lock = threading.Lock()
        self.product_order: dict[str, int] = {}
        self._client_factory = client_factory
        self.stats_recorder = stats_recorder
        self.client: CtripRequestsClient | None = None

    def log(self, message: str) -> None:
        self.out_queue.put(("log", message))

    def new_client(self) -> CtripRequestsClient:
        if self._client_factory is not None:
            return self._client_factory()
        return CtripRequestsClient(
            self.log,
            request_interval_seconds=self.runtime_settings.request_interval_seconds(),
            request_interval_provider=self.runtime_settings.request_interval_seconds,
            stats_area="translation",
            stats_recorder=self.stats_recorder,
        )

    def shared_client(self) -> CtripRequestsClient:
        if self.client is None:
            self.client = self.new_client()
        return self.client

    def emit_result(self, result: TranslationResultRow) -> None:
        with self.lock:
            self.results.append(result)
        self.out_queue.put(("result", result))

    def emit_results(self, results: list[TranslationResultRow]) -> None:
        if not results:
            return
        with self.lock:
            self.results.extend(results)
        for index in range(0, len(results), RESULT_BATCH_SIZE):
            self.out_queue.put(("result_batch", results[index:index + RESULT_BATCH_SIZE]))

    def set_product_order(self, product_ids: list[str]) -> None:
        self.product_order = product_order_map(product_ids)
        self.out_queue.put(("translation_product_order", self.product_order))

    def ordered_results(self) -> list[TranslationResultRow]:
        with self.lock:
            return ordered_translation_results(self.results, self.product_order)

    def _run_items(
        self,
        items: list[Any],
        handler: Callable[[int, Any, CtripRequestsClient], str | None],
        audit_writer: AuditQueueWriter | None = None,
    ) -> None:
        settings = self.runtime_settings.snapshot()
        self.request_interval_seconds = settings.request_interval_seconds
        self.parallel_requests = settings.parallel_requests
        GLOBAL_REQUEST_LIMITER.configure_for_workload(settings.request_interval_seconds, settings.parallel_requests)
        controller = AdaptiveLoadController(settings.parallel_requests, settings.request_interval_seconds, task_count=len(items))
        self.log(f"并行上限={settings.parallel_requests}，初始实际并发={controller.current_parallel()}，任务数={len(items)}")

        def run_handler(index: int, item: Any) -> str | None:
            return handler(index, item, self.new_client())

        def pressure_provider() -> AdaptiveRunPressure:
            with self.lock:
                result_count = len(self.results)
            return AdaptiveRunPressure(
                queue_size=self.out_queue.qsize(),
                audit_queue_size=audit_writer.qsize() if audit_writer is not None else 0,
                result_count=result_count,
            )

        def pressure_callback(active_controller: AdaptiveLoadController) -> None:
            self.out_queue.put(
                (
                    "pressure",
                    {
                        "area": "translation",
                        "parallel": active_controller.current_parallel(),
                        "desired": active_controller.desired_parallel,
                        "interval": active_controller.request_interval_seconds,
                        "reason": active_controller.pressure_reason(),
                    },
                )
            )

        run_adaptive_items(
            items,
            run_handler,
            self.stop_event,
            controller,
            pressure_provider=pressure_provider,
            pressure_callback=pressure_callback,
            runtime_settings_provider=self.runtime_settings.snapshot,
        )

    def emit_plan_result(self, plan: TranslationDiffPlan, status: str | None = None, message: str | None = None) -> None:
        if status is not None:
            plan.status = status
        if message is not None:
            plan.message = message
        self.emit_result(translation_result_from_plan(plan, status=status, message=message))

    def run_preload(self, product_ids: list[str], locales: list[str]) -> None:
        try:
            self.set_product_order(product_ids)
            if self.translation_online_context is not None:
                self.translation_online_context.enabled = False
                self.translation_online_context.product_ids = []
                self.translation_online_context.selected_languages = []
                self.translation_online_context.locales_by_product = {}
            locale_label = ",".join(locales) if locales else "ALL(allLocales)"
            self.log(f"开始预载翻译件：{len(product_ids)} 个产品，语言={locale_label}，并行={self.parallel_requests}")

            def handle_product(index: int, product_id: str, client: CtripRequestsClient) -> str:
                self.out_queue.put(("progress", f"预载翻译 {index}/{len(product_ids)} 产品 {product_id}"))
                try:
                    available = client.load_translation_available_locales(product_id, self.stop_event)
                    locale_options = locale_options_from_available(available)
                    target_locales = locales or locale_codes_from_available(available, ["allLocales"])
                    if not target_locales:
                        target_locales = locale_codes_from_available(available)
                    available_text = json.dumps(available, ensure_ascii=False)
                    missing = [locale for locale in target_locales if locale not in available_text]
                    if missing:
                        self.log(f"产品 {product_id} 可用语言响应中未直接出现：{', '.join(missing)}；仍按填写语言读取 translationList")
                    response = client.load_translation_list(product_id, target_locales, self.stop_event)
                    snapshot = build_translation_snapshot_from_response(product_id, target_locales, response, locale_options=locale_options)
                    with self.lock:
                        self.translation_snapshots[product_id] = snapshot
                        for locale in target_locales:
                            self.last_saved_translation_products.discard(f"{product_id}:{locale}")
                    loaded_locales = snapshot.locales or target_locales
                    operable_count = sum(1 for locale in loaded_locales if locale_options.get(locale, {}).get("operableLocales"))
                    self.emit_result(
                        TranslationResultRow(
                            product_id=product_id,
                            locale=",".join(loaded_locales),
                            module_code="",
                            field_code="",
	                            field_name="",
	                            self_key="",
	                            status="preloaded",
	                            message=f"字段={len(snapshot.fields)} | locale={len(snapshot.locales)} | operable={operable_count}",
	                        )
                    )
                    return "preloaded"
                except Exception as exc:
                    self.emit_result(TranslationResultRow(product_id=product_id, locale=locale_label, module_code="", field_code="", field_name="", self_key="", status="error", message=str(exc)))
                    return "error"

            self._run_items(product_ids, handle_product)
            self.out_queue.put(("done", self.ordered_results()))
        except Exception as exc:
            self.out_queue.put(("fatal", f"{exc}\n{traceback.format_exc()}"))

    def run_preview_template(self, path: str) -> None:
        try:
            if self.translation_online_context is not None:
                self.translation_online_context.enabled = False
            rows = read_translation_template(path)
            self.set_product_order([row.product_id for row in rows])
            plans = build_translation_diff_plans(self.translation_snapshots, rows)
            self.pending_translation_plans.clear()
            self.pending_translation_plans.extend(plans)
            self.emit_results([translation_result_from_plan(plan) for plan in plans])
            self.out_queue.put(("done", self.ordered_results()))
        except Exception as exc:
            self.out_queue.put(("fatal", f"{exc}\n{traceback.format_exc()}"))

    def run_translation_rule_preload_and_preview(
        self,
        task_path: str,
        detail_template_path: str,
        package_template_path: str,
        config: translation_rules.TranslationExecutionConfig,
    ) -> None:
        try:
            tasks = translation_rules.load_translation_rule_tasks(task_path)
            self.log(f"开始规则模板接口预载：任务={len(tasks)}，语言组={','.join(config.selected_languages)}")
            self.translation_snapshots.clear()
            self.pending_translation_plans.clear()
            self.last_saved_translation_products.clear()
            preload_errors: dict[str, str] = {}
            product_ids = list(dict.fromkeys(task.product_id for task in tasks))
            self.set_product_order(product_ids)
            if self.translation_online_context is not None:
                self.translation_online_context.enabled = True
                self.translation_online_context.online = bool(config.online)
                self.translation_online_context.product_ids = product_ids.copy()
                self.translation_online_context.selected_languages = list(config.selected_languages or [])
                self.translation_online_context.locales_by_product = {}

            def handle_product(index: int, product_id: str, client: CtripRequestsClient) -> str:
                self.out_queue.put(("progress", f"规则模板预载 {index}/{len(product_ids)} 产品 {product_id}"))
                try:
                    available = client.load_translation_available_locales(product_id, self.stop_event)
                    locale_options = locale_options_from_available(available)
                    all_locales = locale_codes_from_available(available, ["allLocales"]) or locale_codes_from_available(available)
                    selected_locales = locales_for_selected_language_groups(all_locales, set(config.selected_languages or []), locale_options)
                    if not selected_locales:
                        self.emit_result(TranslationResultRow(product_id=product_id, locale="", module_code="", field_code="", field_name="", self_key="", status="skipped", message="没有匹配执行配置的语言"))
                        return "ok"
                    response = client.load_translation_list(product_id, selected_locales, self.stop_event)
                    snapshot = build_translation_snapshot_from_response(product_id, selected_locales, response, locale_options=locale_options)
                    with self.lock:
                        self.translation_snapshots[product_id] = snapshot
                        if self.translation_online_context is not None:
                            self.translation_online_context.locales_by_product[product_id] = list(snapshot.locales or selected_locales)
                    loaded_locales = snapshot.locales or selected_locales
                    operable_count = sum(1 for locale in loaded_locales if locale_options.get(locale, {}).get("operableLocales"))
                    self.emit_result(
                        TranslationResultRow(
                            product_id=product_id,
                            locale=",".join(loaded_locales),
                            module_code="",
                            field_code="",
                            field_name="",
                            self_key="",
                            status="preloaded",
                            message=f"规则模板快照 | 字段={len(snapshot.fields)} | locale={len(snapshot.locales)} | operable={operable_count}",
                        )
                    )
                    return "preloaded"
                except Exception as exc:
                    with self.lock:
                        preload_errors[product_id] = str(exc)
                    self.emit_result(TranslationResultRow(product_id=product_id, locale="", module_code="", field_code="", field_name="", self_key="", status="error", message=str(exc)))
                    return "error"

            self._run_items(product_ids, handle_product)
            if not self.stop_event.is_set():
                self.out_queue.put(("progress", "规则模板生成 Diff"))
                plans = build_translation_rule_diff_plans(
                    self.translation_snapshots,
                    tasks,
                    detail_template_path,
                    package_template_path,
                    config,
                    client_factory=self.new_client,
                    stop_event=self.stop_event,
                    preload_errors=preload_errors,
                )
                self.pending_translation_plans.clear()
                self.pending_translation_plans.extend(plans)
                self.emit_results([translation_result_from_plan(plan) for plan in plans])
            self.out_queue.put(("done", self.ordered_results()))
        except Exception as exc:
            self.out_queue.put(("fatal", f"{exc}\n{traceback.format_exc()}"))

    def run_apply_pending(self) -> None:
        try:
            plans = [plan for plan in self.pending_translation_plans if plan.status == "pending"]
            unchanged_plans = [plan for plan in self.pending_translation_plans if plan.status == "unchanged"]
            if unchanged_plans:
                self.emit_results([translation_result_from_plan(plan) for plan in unchanged_plans])
            force_online_targets = self._translation_force_online_targets()
            if self.translation_online_context and self.translation_online_context.enabled and self.translation_online_context.online:
                selected_languages = set(self.translation_online_context.selected_languages or [])
                for plan in plans:
                    if not selected_languages or translation_rules.get_lang_group(plan.locale) in selected_languages:
                        snapshot = self.translation_snapshots.get(plan.product_id)
                        locale_option = (snapshot.locale_options or {}).get(plan.locale, {}) if snapshot else {}
                        if locale_translated(locale_option) or locale_allows_initial_online(plan.locale, locale_option):
                            plan.online = True
                        else:
                            plan.online = False
                            if not locale_translated(locale_option):
                                plan.message = (plan.message + "；" if plan.message else "") + "该语言预载时未开站，本次仅保存不上线"
            if not plans and not force_online_targets:
                if unchanged_plans:
                    self.set_product_order([plan.product_id for plan in unchanged_plans])
                else:
                    self.emit_result(TranslationResultRow(product_id="", locale="", module_code="", field_code="", field_name="", self_key="", status="skipped", message="没有 pending 翻译 diff 可传出"))
                self.out_queue.put(("done", self.ordered_results()))
                return
            run_dir = make_write_run_dir()
            audit_writer = AuditQueueWriter()
            self.log(f"本次翻译写入审计目录：{run_dir}")
            grouped: dict[tuple[str, str], list[TranslationDiffPlan]] = {}
            for plan in plans:
                grouped.setdefault((plan.product_id, plan.locale), []).append(plan)
            force_online_targets = [target for target in force_online_targets if target not in grouped]

            product_items: dict[str, tuple[dict[str, list[TranslationDiffPlan]], list[str]]] = {}
            for (product_id, locale), group_plans in grouped.items():
                locale_groups, force_locales = product_items.setdefault(product_id, ({}, []))
                locale_groups[locale] = group_plans
            for product_id, locale in force_online_targets:
                locale_groups, force_locales = product_items.setdefault(product_id, ({}, []))
                if locale not in force_locales:
                    force_locales.append(locale)
            apply_items = list(product_items.items())
            self.set_product_order(list(dict.fromkeys(
                [plan.product_id for plan in unchanged_plans] + [product_id for product_id, _item in apply_items]
            )))
            total_items = len(apply_items)

            def handle_item(index: int, item: tuple[str, tuple[dict[str, list[TranslationDiffPlan]], list[str]]], client: CtripRequestsClient) -> str:
                product_id, (locale_groups, force_locales) = item
                request_product_id = target_product_id(product_id)
                locale_count = len(locale_groups) + len(force_locales)
                self.out_queue.put(("progress", f"传出翻译 {index}/{total_items} 产品 {request_product_id} 语言数={locale_count}"))
                try:
                    saved_keys = self._apply_translation_product_groups(
                        request_product_id,
                        locale_groups,
                        force_locales,
                        run_dir,
                        client,
                        audit_writer=audit_writer,
                    )
                    if saved_keys:
                        with self.lock:
                            self.last_saved_translation_products.update(saved_keys)
                    return "saved" if saved_keys else "ok"
                except Exception as exc:
                    self.log(f"产品 {request_product_id} 翻译写入失败：{exc}")
                    for locale, plans_for_locale in locale_groups.items():
                        for plan in plans_for_locale:
                            self.emit_plan_result(plan, status="error", message=str(exc))
                    for locale in force_locales:
                        self.emit_result(
                            TranslationResultRow(
                                product_id=request_product_id,
                                locale=locale,
                                module_code="",
                                field_code="",
                                field_name="强制上线",
                                self_key="",
                                status="error",
                                old_value="",
                                new_value="",
                                online=True,
                                message=str(exc),
                            )
                        )
                    return "error"

            try:
                self._run_items(apply_items, handle_item, audit_writer=audit_writer)
            finally:
                audit_writer.close()
            self.out_queue.put(("done", self.ordered_results()))
        except Exception as exc:
            self.out_queue.put(("fatal", f"{exc}\n{traceback.format_exc()}"))

    def _apply_translation_product_groups(
        self,
        product_id: str,
        locale_groups: dict[str, list[TranslationDiffPlan]],
        force_online_locales: list[str],
        run_dir: Path,
        client: CtripRequestsClient | None = None,
        audit_writer: AuditQueueWriter | None = None,
    ) -> set[str]:
        client = client or self.shared_client()
        product_id = target_product_id(product_id)
        snapshot = self.translation_snapshots.get(product_id)
        if not snapshot:
            raise RuntimeError("内存翻译快照不存在，请重新预载翻译件")
        if target_product_id(snapshot.product_id) != product_id:
            raise RuntimeError(f"翻译快照目标不一致：期望 {product_id}，实际 {snapshot.product_id}")

        read_locales: list[str] = []
        for locale, plans in locale_groups.items():
            if locale not in read_locales:
                read_locales.append(locale)
            baseline = next((plan.baseline_source_locale for plan in plans if plan.baseline_source_locale), "")
            baseline = baseline or translation_baseline_source_locale(snapshot, locale)
            if baseline and baseline not in read_locales:
                read_locales.append(baseline)
        for locale in force_online_locales:
            if locale not in read_locales:
                read_locales.append(locale)
            baseline = translation_baseline_source_locale(snapshot, locale)
            if baseline and baseline not in read_locales:
                read_locales.append(baseline)
        if not read_locales:
            return set()

        latest_response = client.load_translation_list(product_id, read_locales, self.stop_event)
        latest_snapshot = build_translation_snapshot_from_response(product_id, read_locales, latest_response, retain_raw=True)
        pending_verify: dict[str, list[TranslationDiffPlan]] = {}
        saved_keys: set[str] = set()

        for locale, plans in locale_groups.items():
            active_plans: list[TranslationDiffPlan] = []
            try:
                target = TranslationRequestTarget(product_id, str(locale or ""))
                transaction_id = new_transaction_id()
                validate_translation_plan_targets(target, plans)
                baseline_source_locale = next((plan.baseline_source_locale for plan in plans if plan.baseline_source_locale), "")
                baseline_source_locale = baseline_source_locale or translation_baseline_source_locale(snapshot, locale)
                if locale not in latest_snapshot.locales:
                    raise RuntimeError(f"翻译回读目标缺失：期望 {product_id}/{locale}")
                raw_translation = latest_snapshot.raw_by_locale.get(locale)
                if not isinstance(raw_translation, dict):
                    raise RuntimeError(f"接口未返回 {locale} 翻译树")
                if baseline_source_locale:
                    source_raw = latest_snapshot.raw_by_locale.get(baseline_source_locale)
                    if isinstance(source_raw, dict):
                        raw_translation = fill_translation_empty_values_from_baseline(raw_translation, source_raw)
                    else:
                        self.log(f"产品 {product_id} 语言 {locale} 未能读取补齐来源 {baseline_source_locale}，将按目标翻译树直接写入")

                for plan in plans:
                    latest_field = latest_snapshot.fields.get(translation_field_key(product_id, locale, plan.self_key))
                    if not latest_field:
                        self.emit_plan_result(plan, status="stale", message="最新接口中未找到该 selfKey，请重新预载")
                        continue
                    snapshot_field = snapshot.fields.get(translation_field_key(product_id, locale, plan.self_key))
                    if not snapshot_field or latest_field.old_translation != plan.old_value:
                        self.emit_plan_result(plan, status="stale", message="接口当前值已不同于预载快照，请重新预载后再传出")
                        continue
                    active_plans.append(plan)
                if not active_plans:
                    continue

                online = any(plan.online for plan in active_plans)
                if online and not all(plan.online for plan in active_plans):
                    self.log(f"产品 {product_id} 语言 {locale} 同一批次混合 online=是/否；productTranslationPush 只能按语言整体提交，本次按 online=true 执行")
                for plan in active_plans:
                    plan.online = online
                locale_option = (snapshot.locale_options or {}).get(locale, {})
                if online and not locale_translated(locale_option):
                    if not locale_allows_initial_online(locale, locale_option):
                        raise RuntimeError("该语言预载时未开站，已禁止提交上线")
                    missing_required = translation_missing_required_fields_after_plans(raw_translation, active_plans)
                    if missing_required:
                        raise RuntimeError(f"阿语初次上线缺少必填翻译字段：{', '.join(missing_required)}")

                payload, response = client.save_translation(product_id, locale, raw_translation, active_plans, online, self.stop_event)
                assert_translation_payload_target(payload, target, "translation_push")
                audit_write_or_enqueue(
                    audit_writer,
                    run_dir,
                    product_id,
                    f"translation_{locale}",
                    {
                        "createdAt": now_iso(),
                        "kind": "translation_push",
                        "locale": locale,
                        "online": online,
                        "baselineSourceLocale": baseline_source_locale,
                        "request": payload,
                        "response": response,
                        "plans": [asdict(plan) for plan in active_plans],
                    },
                    target=target,
                    transaction_id=transaction_id,
                )
                if not response_success(response):
                    raise RuntimeError(response_message(response, "翻译保存接口返回失败"))
                pending_verify[locale] = active_plans
            except Exception as exc:
                message = str(exc)
                self.log(f"产品 {product_id} 语言 {locale} 翻译写入失败：{message}")
                for plan in active_plans or plans:
                    self.emit_plan_result(plan, status="error", message=message)

        for locale in force_online_locales:
            try:
                if self._force_online_product_locale(product_id, locale, run_dir, client, audit_writer=audit_writer):
                    saved_keys.add(f"{product_id}:{locale}")
            except Exception as exc:
                message = str(exc)
                self.log(f"产品 {product_id} 语言 {locale} 强制上线失败：{message}")
                self.emit_result(
                    TranslationResultRow(
                        product_id=product_id,
                        locale=locale,
                        module_code="",
                        field_code="",
                        field_name="强制上线",
                        self_key="",
                        status="error",
                        old_value="",
                        new_value="",
                        online=True,
                        message=message,
                    )
                )

        if pending_verify:
            verify_locales = list(pending_verify)
            try:
                verify_response = client.load_translation_list(product_id, verify_locales, self.stop_event)
                verify_snapshot = build_translation_snapshot_from_response(product_id, verify_locales, verify_response)
            except Exception as exc:
                message = f"保存后回读失败：{exc}"
                self.log(f"产品 {product_id} {message}")
                for active_plans in pending_verify.values():
                    for plan in active_plans:
                        self.emit_plan_result(plan, status="error", message=message)
                return saved_keys
            for locale, active_plans in pending_verify.items():
                try:
                    if locale not in verify_snapshot.locales:
                        raise RuntimeError(f"翻译保存后回读目标缺失：期望 {product_id}/{locale}")
                    locale_saved = False
                    for plan in active_plans:
                        verify_field = verify_snapshot.fields.get(translation_field_key(product_id, locale, plan.self_key))
                        verify_value = verify_field.old_translation if verify_field else ""
                        target_ok = bool(verify_field and target_product_id(verify_field.product_id) == product_id and verify_field.locale == locale)
                        ok = target_ok and verify_value == plan.new_value
                        self.emit_plan_result(
                            plan,
                            status="saved" if ok else "verify_failed",
                            message=("保存并上线校验成功" if plan.online else "保存校验成功") if ok else f"保存后校验未通过，回读={verify_value}",
                        )
                        locale_saved = locale_saved or ok
                    if locale_saved:
                        saved_keys.add(f"{product_id}:{locale}")
                except Exception as exc:
                    message = str(exc)
                    self.log(f"产品 {product_id} 语言 {locale} 保存后校验失败：{message}")
                    for plan in active_plans:
                        self.emit_plan_result(plan, status="error", message=message)
        return saved_keys

    def _translation_force_online_targets(self) -> list[tuple[str, str]]:
        context = self.translation_online_context
        if not context or not context.enabled or not context.online:
            return []
        selected_languages = set(context.selected_languages or [])
        targets: list[tuple[str, str]] = []
        product_ids = context.product_ids or list(self.translation_snapshots.keys())
        for product_id in product_ids:
            snapshot = self.translation_snapshots.get(product_id)
            locales = list((context.locales_by_product or {}).get(product_id) or (snapshot.locales if snapshot else []))
            for locale in locales:
                if selected_languages and translation_rules.get_lang_group(locale) not in selected_languages:
                    continue
                locale_option = (snapshot.locale_options or {}).get(locale, {}) if snapshot else {}
                if not locale_can_submit_online(locale_option):
                    continue
                target = (product_id, locale)
                if target not in targets:
                    targets.append(target)
        return targets

    def _force_online_product_locale(
        self,
        product_id: str,
        locale: str,
        run_dir: Path,
        client: CtripRequestsClient | None = None,
        audit_writer: AuditQueueWriter | None = None,
    ) -> bool:
        target = TranslationRequestTarget(target_product_id(product_id), str(locale or ""))
        transaction_id = new_transaction_id()
        client = client or self.shared_client()
        product_id = target.product_id
        locale = target.locale
        snapshot = self.translation_snapshots.get(product_id)
        if snapshot and target_product_id(snapshot.product_id) != target.product_id:
            raise RuntimeError(f"翻译快照目标不一致：期望 {target.product_id}，实际 {snapshot.product_id}")
        locale_option = (snapshot.locale_options or {}).get(locale, {}) if snapshot else {}
        if not locale_can_submit_online(locale_option):
            if not locale_translated(locale_option):
                raise RuntimeError("该语言预载时未开站，已禁止提交上线")
            if locale_already_online(locale_option):
                raise RuntimeError("该语言预载时已上线，已跳过重复提交上线")
            raise RuntimeError("该语言当前状态不允许提交上线")
        baseline_source_locale = translation_baseline_source_locale(snapshot, locale) if snapshot else ""
        read_locales = [locale]
        if baseline_source_locale and baseline_source_locale not in read_locales:
            read_locales.append(baseline_source_locale)
        latest_response = client.load_translation_list(product_id, read_locales, self.stop_event)
        latest_snapshot = build_translation_snapshot_from_response(product_id, read_locales, latest_response, retain_raw=True)
        if locale not in latest_snapshot.locales:
            raise RuntimeError(f"翻译回读目标缺失：期望 {product_id}/{locale}")
        raw_translation = latest_snapshot.raw_by_locale.get(locale)
        if not isinstance(raw_translation, dict):
            raise RuntimeError(f"接口未返回 {locale} 翻译树")
        if baseline_source_locale:
            source_raw = latest_snapshot.raw_by_locale.get(baseline_source_locale)
            if isinstance(source_raw, dict):
                raw_translation = fill_translation_empty_values_from_baseline(raw_translation, source_raw)
            else:
                self.log(f"产品 {product_id} 语言 {locale} 未能读取补齐来源 {baseline_source_locale}，将按目标翻译树直接强制上线")
        payload, response = client.save_translation(product_id, locale, raw_translation, [], True, self.stop_event)
        assert_translation_payload_target(payload, target, "translation_force_online")
        audit_write_or_enqueue(
            audit_writer,
            run_dir,
            product_id,
            f"translation_force_online_{locale}",
            {
                "createdAt": now_iso(),
                "kind": "translation_force_online",
                "locale": locale,
                "online": True,
                "baselineSourceLocale": baseline_source_locale,
                "request": payload,
                "response": response,
                "plans": [],
            },
            target=target,
            transaction_id=transaction_id,
        )
        if not response_success(response):
            raise RuntimeError(response_message(response, "翻译强制上线接口返回失败"))
        verify_response = client.load_translation_list(product_id, [locale], self.stop_event)
        verify_snapshot = build_translation_snapshot_from_response(product_id, [locale], verify_response)
        if locale not in verify_snapshot.locales:
            raise RuntimeError(f"翻译强制上线后回读目标缺失：期望 {product_id}/{locale}")
        self.emit_result(
            TranslationResultRow(
                product_id=product_id,
                locale=locale,
                module_code="",
                field_code="",
                field_name="强制上线",
                self_key="",
                status="saved",
                old_value="",
                new_value="",
                online=True,
                message="强制上线提交成功",
            )
        )
        return True

    def _apply_product_locale(
        self,
        product_id: str,
        locale: str,
        plans: list[TranslationDiffPlan],
        run_dir: Path,
        client: CtripRequestsClient | None = None,
        audit_writer: AuditQueueWriter | None = None,
        latest_snapshot: TranslationSnapshot | None = None,
        verify_snapshot: TranslationSnapshot | None = None,
    ) -> bool:
        target = TranslationRequestTarget(target_product_id(product_id), str(locale or ""))
        transaction_id = new_transaction_id()
        validate_translation_plan_targets(target, plans)
        client = client or self.shared_client()
        product_id = target.product_id
        locale = target.locale
        snapshot = self.translation_snapshots.get(product_id)
        if not snapshot:
            raise RuntimeError("内存翻译快照不存在，请重新预载翻译件")
        if target_product_id(snapshot.product_id) != target.product_id:
            raise RuntimeError(f"翻译快照目标不一致：期望 {target.product_id}，实际 {snapshot.product_id}")
        baseline_source_locale = next((plan.baseline_source_locale for plan in plans if plan.baseline_source_locale), "")
        if not baseline_source_locale:
            baseline_source_locale = translation_baseline_source_locale(snapshot, locale)
        read_locales = [locale]
        if baseline_source_locale and baseline_source_locale not in read_locales:
            read_locales.append(baseline_source_locale)
        if latest_snapshot is None:
            latest_response = client.load_translation_list(product_id, read_locales, self.stop_event)
            latest_snapshot = build_translation_snapshot_from_response(product_id, read_locales, latest_response, retain_raw=True)
        if locale not in latest_snapshot.locales:
            raise RuntimeError(f"翻译回读目标缺失：期望 {product_id}/{locale}")
        raw_translation = latest_snapshot.raw_by_locale.get(locale)
        if not isinstance(raw_translation, dict):
            raise RuntimeError(f"接口未返回 {locale} 翻译树")
        if baseline_source_locale:
            source_raw = latest_snapshot.raw_by_locale.get(baseline_source_locale)
            if isinstance(source_raw, dict):
                raw_translation = fill_translation_empty_values_from_baseline(raw_translation, source_raw)
            else:
                self.log(f"产品 {product_id} 语言 {locale} 未能读取补齐来源 {baseline_source_locale}，将按目标翻译树直接写入")

        active_plans: list[TranslationDiffPlan] = []
        for plan in plans:
            latest_field = latest_snapshot.fields.get(translation_field_key(product_id, locale, plan.self_key))
            if not latest_field:
                self.emit_plan_result(plan, status="stale", message="最新接口中未找到该 selfKey，请重新预载")
                continue
            snapshot_field = snapshot.fields.get(translation_field_key(product_id, locale, plan.self_key))
            if not snapshot_field or latest_field.old_translation != plan.old_value:
                self.emit_plan_result(plan, status="stale", message="接口当前值已不同于预载快照，请重新预载后再传出")
                continue
            active_plans.append(plan)
        if not active_plans:
            return False

        online = any(plan.online for plan in active_plans)
        if online and not all(plan.online for plan in active_plans):
            self.log(f"产品 {product_id} 语言 {locale} 同一批次混合 online=是/否；productTranslationPush 只能按语言整体提交，本次按 online=true 执行")
        for plan in active_plans:
            plan.online = online
        locale_option = (snapshot.locale_options or {}).get(locale, {})
        if online and not locale_translated(locale_option):
            if not locale_allows_initial_online(locale, locale_option):
                raise RuntimeError("该语言预载时未开站，已禁止提交上线")
            missing_required = translation_missing_required_fields_after_plans(raw_translation, active_plans)
            if missing_required:
                raise RuntimeError(f"阿语初次上线缺少必填翻译字段：{', '.join(missing_required)}")
        payload, response = client.save_translation(product_id, locale, raw_translation, active_plans, online, self.stop_event)
        assert_translation_payload_target(payload, target, "translation_push")
        audit_write_or_enqueue(
            audit_writer,
            run_dir,
            product_id,
            f"translation_{locale}",
            {
                "createdAt": now_iso(),
                "kind": "translation_push",
                "locale": locale,
                "online": online,
                "baselineSourceLocale": baseline_source_locale,
                "request": payload,
                "response": response,
                "plans": [asdict(plan) for plan in active_plans],
            },
            target=target,
            transaction_id=transaction_id,
        )
        if not response_success(response):
            raise RuntimeError(response_message(response, "翻译保存接口返回失败"))

        if verify_snapshot is None:
            verify_response = client.load_translation_list(product_id, [locale], self.stop_event)
            verify_snapshot = build_translation_snapshot_from_response(product_id, [locale], verify_response)
        if locale not in verify_snapshot.locales:
            raise RuntimeError(f"翻译保存后回读目标缺失：期望 {product_id}/{locale}")
        saved_any = False
        for plan in active_plans:
            verify_field = verify_snapshot.fields.get(translation_field_key(product_id, locale, plan.self_key))
            verify_value = verify_field.old_translation if verify_field else ""
            target_ok = bool(verify_field and target_product_id(verify_field.product_id) == target.product_id and verify_field.locale == target.locale)
            ok = target_ok and verify_value == plan.new_value
            self.emit_plan_result(
                plan,
                status="saved" if ok else "verify_failed",
                message=("保存并上线校验成功" if online else "保存校验成功") if ok else f"保存后校验未通过，回读={verify_value}",
            )
            saved_any = saved_any or ok
        return saved_any


def mix_qcolors(first: QColor, second: QColor, second_weight: float) -> QColor:
    return ui_theme.mix_colors(first, second, second_weight)


def translation_workbench_palette(widget: QWidget) -> dict[str, str]:
    return ui_theme.semantic_colors(widget.palette())


def table_is_dark(table: Any) -> bool:
    return table.palette().window().color().lightness() < 128


def table_text_color(table: Any) -> QColor:
    return table.palette().text().color()


PRODUCT_STATUS_LABEL_STYLE = "font-size: 13px; font-weight: 600;"


def create_readonly_table_item(table: QTableWidget, value: Any) -> QTableWidgetItem:
    item = QTableWidgetItem("" if value is None else str(value))
    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
    item.setForeground(table_text_color(table))
    return item


def apply_table_readable_style(table: Any) -> None:
    palette = table.palette()
    base_color = palette.base().color().name()
    alternate_color = palette.alternateBase().color().name()
    header_color = palette.button().color().name()
    grid_color = palette.mid().color().name()
    text_color = palette.text().color().name()
    selected_color = palette.highlight().color().name()
    selected_text_color = palette.highlightedText().color().name()
    hover_color = palette.light().color().name()
    border_color = palette.mid().color().name()
    table.setShowGrid(True)
    table.setGridStyle(Qt.PenStyle.SolidLine)
    table.verticalHeader().setDefaultSectionSize(34)
    table.horizontalHeader().setMinimumHeight(34)
    table.setStyleSheet(
        f"""
        QTableWidget, QTableView {{
            background-color: {base_color};
            alternate-background-color: {alternate_color};
            color: {text_color};
            gridline-color: {grid_color};
            border: 1px solid {border_color};
            selection-background-color: {selected_color};
            selection-color: {selected_text_color};
        }}
        QTableWidget::item, QTableView::item {{
            color: {text_color};
            border-bottom: 1px solid {grid_color};
            padding: 5px 8px;
        }}
        QTableWidget::item:hover, QTableView::item:hover {{
            background-color: {hover_color};
            color: {text_color};
        }}
        QTableWidget::item:selected, QTableView::item:selected {{
            background-color: {selected_color};
            color: {selected_text_color};
        }}
        QHeaderView::section {{
            background-color: {header_color};
            color: {text_color};
            border: 0;
            border-right: 1px solid {grid_color};
            border-bottom: 1px solid {border_color};
            padding: 6px 8px;
            font-weight: 600;
        }}
        QTableCornerButton::section {{
            background-color: {header_color};
            border: 0;
            border-right: 1px solid {grid_color};
            border-bottom: 1px solid {border_color};
        }}
        """
    )


def set_table_data(table: QTableWidget, headers: list[str], rows: list[list[Any]]) -> None:
    table.setColumnCount(len(headers))
    table.setHorizontalHeaderLabels(headers)
    table.setRowCount(len(rows))
    for row_index, row in enumerate(rows):
        for col_index, value in enumerate(row):
            item = create_readonly_table_item(table, value)
            table.setItem(row_index, col_index, item)
    table.setAlternatingRowColors(True)
    table.setWordWrap(False)
    table.setSortingEnabled(True)
    table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
    table.horizontalHeader().setStretchLastSection(False)
    table.verticalHeader().setVisible(False)
    apply_table_readable_style(table)


PRODUCT_RESULT_HEADERS = ["产品ID", "套餐ID", "资源ID", "套餐名称", "修改字段", "修改前内容", "修改后内容", "调用接口", "处理状态", "结果说明", "模板行号"]
TRANSLATION_RESULT_HEADERS = ["产品ID", "语言地区", "模块", "翻译字段", "修改前译文", "修改后译文", "是否上线", "调用接口", "处理状态", "结果说明", "模板行号"]


def product_table_values(result: ResultRow) -> list[Any]:
    return [
        result.product_id,
        result.package_id,
        result.resource_id,
        result.package_name,
        result.field_name,
        result.old_value,
        result.new_value,
        result.interface_name,
        result.status,
        result.message.replace("\n", " | ")[:240],
        result.row_number,
    ]


def translation_table_values(result: TranslationResultRow) -> list[Any]:
    return [
        result.product_id,
        result.locale,
        result.module_code,
        f"{result.field_code} {result.field_name}".strip(),
        result.old_value,
        result.new_value,
        "是" if result.online else "否",
        result.interface_name,
        result.status,
        result.message.replace("\n", " | ")[:240],
        result.row_number,
    ]


class ResultTableModel(QAbstractTableModel):
    def __init__(
        self,
        headers: list[str],
        value_getter: Callable[[Any], list[Any]],
        rows: list[Any] | None = None,
        parent: QWidget | None = None,
    ):
        if QT_IMPORT_ERROR is None:
            super().__init__(parent)
        else:
            super().__init__()
        self.headers = list(headers)
        self.value_getter = value_getter
        self.rows = rows if rows is not None else []

    def rowCount(self, parent: QModelIndex | None = None) -> int:
        return 0 if parent is not None and parent.isValid() else len(self.rows)

    def columnCount(self, parent: QModelIndex | None = None) -> int:
        return 0 if parent is not None and parent.isValid() else len(self.headers)

    def data(self, index: QModelIndex, role: Any = None) -> Any:
        display_role = Qt.ItemDataRole.DisplayRole if QT_IMPORT_ERROR is None else 0
        alignment_role = Qt.ItemDataRole.TextAlignmentRole if QT_IMPORT_ERROR is None else 7
        if not index.isValid():
            return None
        if role in (None, display_role):
            row = index.row()
            column = index.column()
            if row < 0 or row >= len(self.rows) or column < 0 or column >= len(self.headers):
                return None
            values = self.value_getter(self.rows[row])
            return "" if column >= len(values) or values[column] is None else str(values[column])
        if role == alignment_role and QT_IMPORT_ERROR is None:
            return Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft
        return None

    def headerData(self, section: int, orientation: Any, role: Any = None) -> Any:
        display_role = Qt.ItemDataRole.DisplayRole if QT_IMPORT_ERROR is None else 0
        horizontal = Qt.Orientation.Horizontal if QT_IMPORT_ERROR is None else 1
        if role in (None, display_role) and orientation == horizontal and 0 <= section < len(self.headers):
            return self.headers[section]
        return None

    def flags(self, index: QModelIndex) -> Any:
        if QT_IMPORT_ERROR is not None:
            return 0
        if not index.isValid():
            return Qt.ItemFlag.NoItemFlags
        return Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled

    def append_results(self, rows: list[Any]) -> None:
        if not rows:
            return
        start = len(self.rows)
        end = start + len(rows) - 1
        if QT_IMPORT_ERROR is None:
            self.beginInsertRows(QModelIndex(), start, end)
        self.rows.extend(rows)
        if QT_IMPORT_ERROR is None:
            self.endInsertRows()

    def set_results(self, rows: list[Any]) -> None:
        if QT_IMPORT_ERROR is None:
            self.beginResetModel()
        self.rows = rows
        if QT_IMPORT_ERROR is None:
            self.endResetModel()

    def resort(self, key: Callable[[Any], Any]) -> None:
        if QT_IMPORT_ERROR is None:
            self.layoutAboutToBeChanged.emit()
        self.rows.sort(key=key)
        if QT_IMPORT_ERROR is None:
            self.layoutChanged.emit()

    def result_at(self, row: int) -> Any | None:
        if row < 0 or row >= len(self.rows):
            return None
        return self.rows[row]


class ProductResultTableModel(ResultTableModel):
    def __init__(self, rows: list[ResultRow] | None = None, parent: QWidget | None = None):
        super().__init__(PRODUCT_RESULT_HEADERS, product_table_values, rows=rows, parent=parent)


class TranslationResultTableModel(ResultTableModel):
    def __init__(self, rows: list[TranslationResultRow] | None = None, parent: QWidget | None = None):
        super().__init__(TRANSLATION_RESULT_HEADERS, translation_table_values, rows=rows, parent=parent)


def drain_queue_limited(
    event_queue: queue.Queue,
    handler: Callable[[str, Any], None],
    max_events: int = QUEUE_POLL_MAX_EVENTS,
    max_seconds: float = QUEUE_POLL_MAX_SECONDS,
) -> int:
    processed = 0
    deadline = time.monotonic() + max(0.0, max_seconds)
    while processed < max_events and (processed == 0 or time.monotonic() < deadline):
        try:
            kind, payload = event_queue.get_nowait()
        except queue.Empty:
            break
        handler(kind, payload)
        processed += 1
    return processed


class ProductIdsDialog(QDialog):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("输入产品ID")
        self.resize(520, 320)
        self.setMinimumSize(420, 260)
        layout = QVBoxLayout(self)
        layout.addWidget(BodyLabel("请输入一个或多个产品ID，支持换行、逗号、空格分隔："))
        self.text_box = TextEdit(self)
        layout.addWidget(self.text_box, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, self)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def value(self) -> str:
        return self.text_box.toPlainText().strip()


class PreviewDialog(QDialog):
    def __init__(self, snapshots: dict[str, ProductSnapshot], results: list[ResultRow], parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("接口输出预览")
        self.resize(1280, 760)
        layout = QVBoxLayout(self)
        tabs = QTabWidget(self)
        if snapshots:
            headers, rows = snapshot_preview_rows(snapshots)
            tabs.addTab(self._table(headers, rows), "接口快照")
        if results:
            headers, rows = result_preview_rows(results)
            tabs.addTab(self._table(headers, rows), "结果报告")
        layout.addWidget(tabs)
        close_btn = PushButton("关闭", self)
        close_btn.clicked.connect(self.accept)
        button_row = QHBoxLayout()
        button_row.addStretch(1)
        button_row.addWidget(close_btn)
        layout.addLayout(button_row)

    def _table(self, headers: list[str], rows: list[list[Any]]) -> QTableWidget:
        table = TableWidget(self)
        display_rows = rows[:MAX_PREVIEW_TABLE_ROWS]
        set_table_data(table, headers, display_rows)
        if len(rows) > MAX_PREVIEW_TABLE_ROWS:
            table.setToolTip(f"预览仅加载前 {MAX_PREVIEW_TABLE_ROWS} 行，完整数据请导出报告查看。总行数：{len(rows)}")
        widths = {
            "套餐名称": 320,
            "原套餐说明": 520,
            "新套餐说明": 520,
            "当前套餐说明": 560,
            "结果说明": 420,
            "修改前内容": 300,
            "修改后内容": 300,
        }
        for index, header in enumerate(headers):
            table.setColumnWidth(index, widths.get(header, 150))
        return table


class TranslationPreviewDialog(QDialog):
    def __init__(self, snapshots: dict[str, TranslationSnapshot], results: list[TranslationResultRow], parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("翻译接口输出预览")
        self.resize(1280, 760)
        layout = QVBoxLayout(self)
        tabs = QTabWidget(self)
        if snapshots:
            headers, rows = translation_snapshot_preview_rows(snapshots)
            tabs.addTab(self._table(headers, rows), "翻译快照")
        if results:
            headers, rows = translation_result_preview_rows(results)
            tabs.addTab(self._table(headers, rows), "结果报告")
        layout.addWidget(tabs)
        close_btn = PushButton("关闭", self)
        close_btn.clicked.connect(self.accept)
        button_row = QHBoxLayout()
        button_row.addStretch(1)
        button_row.addWidget(close_btn)
        layout.addLayout(button_row)

    def _table(self, headers: list[str], rows: list[list[Any]]) -> QTableWidget:
        table = TableWidget(self)
        display_rows = rows[:MAX_PREVIEW_TABLE_ROWS]
        set_table_data(table, headers, display_rows)
        if len(rows) > MAX_PREVIEW_TABLE_ROWS:
            table.setToolTip(f"预览仅加载前 {MAX_PREVIEW_TABLE_ROWS} 行，完整数据请导出报告查看。总行数：{len(rows)}")
        widths = {
            "原文内容": 520,
            "当前译文": 520,
            "修改前译文": 520,
            "修改后译文": 520,
            "字段键": 360,
            "结果说明": 420,
        }
        for index, header in enumerate(headers):
            table.setColumnWidth(index, widths.get(header, 150))
        return table


# 产品图片预览的后台下载：信号量限制并发（避免切换站点时线程无上限堆积），
# 下载线程本身是 daemon，不阻止进程退出。
preview_image_download_semaphore = threading.BoundedSemaphore(4)




def translation_formatted_plain_text(value: Any) -> str:
    if isinstance(value, list):
        return "".join(str(item[0]) for item in value if isinstance(item, (list, tuple)) and item)
    return "" if value is None else str(value)


class TranslationDetailTemplateViewer(QDialog):
    def __init__(self, template_data: dict[str, dict[str, Any]], path: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("商品详情模板管理器（Excel只读）")
        self.resize(1080, 760)
        layout = QVBoxLayout(self)
        layout.addWidget(BodyLabel(f"只读预览：{os.path.basename(path) if path else '未指定'}"))
        tabs = QTabWidget(self)
        ordered_langs = [lang for lang in translation_rules.ALL_TEMPLATE_LANGUAGES if lang in template_data]
        ordered_langs.extend(sorted(lang for lang in template_data if lang not in ordered_langs))
        for lang in ordered_langs:
            text = QTextEdit(self)
            text.setReadOnly(True)
            parts: list[str] = []
            templates = template_data.get(lang, {})
            for column_name, key in translation_rules.DETAIL_COLUMNS:
                value = translation_formatted_plain_text(templates.get(key, [] if key in translation_rules.DETAIL_RICH_KEYS else ""))
                parts.append(f"{column_name}:\n{value}\n")
            text.setPlainText("\n".join(parts).strip())
            tabs.addTab(text, lang.upper())
        layout.addWidget(tabs, 1)
        close_btn = PushButton("关闭", self)
        close_btn.clicked.connect(self.accept)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(close_btn)
        layout.addLayout(row)


class TranslationPackageTemplateViewer(QDialog):
    def __init__(self, template_data: dict[str, Any], path: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("套餐模板管理器 - Trip.com规格填充工具（Excel只读）")
        self.resize(1180, 780)
        self.template_data = template_data or {}
        self.all_languages = translation_rules.ALL_TEMPLATE_LANGUAGES.copy()
        self._rendered_paths: set[tuple[str, ...]] = set()
        self._tab_path_by_widget: dict[QWidget, tuple[str, ...]] = {}
        self._frame_by_path: dict[tuple[str, ...], QWidget] = {}
        layout = QVBoxLayout(self)
        layout.addWidget(BodyLabel(f"只读预览：{os.path.basename(path) if path else '未指定'}"))
        self.notebook = QTabWidget(self)
        layout.addWidget(self.notebook, 1)
        self._create_template_tab_skeleton()
        close_btn = PushButton("关闭", self)
        close_btn.clicked.connect(self.accept)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(close_btn)
        layout.addLayout(row)
        QTimer.singleShot(0, lambda: self._ensure_selected_tab_rendered(self.notebook))

    def _create_template_tab_skeleton(self) -> None:
        if "scripts" in self.template_data:
            self._add_lazy_tab(self.notebook, ("scripts",), "容量模板 {usedup_throttle}")
        if "install_instructions" in self.template_data:
            self._add_lazy_tab(self.notebook, ("install_instructions",), "安装说明 {inst_adv}")
        if "day_calc" in self.template_data:
            self._add_lazy_tab(self.notebook, ("day_calc",), "天数计算 {Day_calc}")
        if "reset_time_calc" in self.template_data:
            self._add_lazy_tab(self.notebook, ("reset_time_calc",), "重置计时 {reset_time_calc}")
        if "combination_template" in self.template_data:
            self._add_lazy_tab(self.notebook, ("combination_template",), "组合模板")
        self.notebook.currentChanged.connect(lambda _index: self._ensure_selected_tab_rendered(self.notebook))

    def _add_lazy_tab(self, notebook: QTabWidget, path: tuple[str, ...], title: str) -> QWidget:
        frame = QWidget(self)
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.addWidget(BodyLabel("选择此页后加载只读内容..."))
        notebook.addTab(frame, title)
        self._tab_path_by_widget[frame] = tuple(path)
        self._frame_by_path[tuple(path)] = frame
        return frame

    def _ensure_selected_tab_rendered(self, notebook: QTabWidget) -> None:
        widget = notebook.currentWidget()
        if widget is None:
            return
        path = self._tab_path_by_widget.get(widget)
        if path:
            self._ensure_path_rendered(path)

    def _ensure_path_rendered(self, path: tuple[str, ...]) -> None:
        path = tuple(path)
        if path in self._rendered_paths:
            return
        frame = self._frame_by_path.get(path)
        if frame is None:
            return
        self._clear_layout(frame.layout())
        if path == ("combination_template",):
            self._create_combination_tab(frame)
        else:
            self._populate_language_fields(frame, self._get_data_at_path(path), list(path), lazy=True)
        self._rendered_paths.add(path)

    def _clear_layout(self, layout: Any) -> None:
        if layout is None:
            return
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            child_layout = item.layout()
            if widget is not None:
                widget.deleteLater()
            elif child_layout is not None:
                self._clear_layout(child_layout)

    def _get_data_at_path(self, path: tuple[str, ...]) -> Any:
        data: Any = self.template_data
        for key in path:
            data = data.get(key, {}) if isinstance(data, dict) else {}
        return data

    def _populate_language_fields(self, parent_frame: QWidget, data: Any, path: list[str], lazy: bool = False) -> None:
        data = data if isinstance(data, dict) else {}
        if data and all(isinstance(value, dict) for value in data.values() if value is not None):
            nested_notebook = QTabWidget(parent_frame)
            parent_frame.layout().addWidget(nested_notebook)
            for sub_key, sub_value in data.items():
                sub_path = tuple(path) + (str(sub_key),)
                title = self._get_tab_title(path, str(sub_key))
                if lazy:
                    self._add_lazy_tab(nested_notebook, sub_path, title)
                else:
                    sub_frame = QWidget(nested_notebook)
                    sub_frame.setLayout(QVBoxLayout())
                    nested_notebook.addTab(sub_frame, title)
                    self._populate_language_fields(sub_frame, sub_value, path + [str(sub_key)], lazy=False)
            if lazy:
                nested_notebook.currentChanged.connect(lambda _index, nb=nested_notebook: self._ensure_selected_tab_rendered(nb))
                QTimer.singleShot(0, lambda nb=nested_notebook: self._ensure_selected_tab_rendered(nb))
            return
        self._populate_language_leaf(parent_frame, data)

    def _populate_language_leaf(self, parent_frame: QWidget, data: Any) -> None:
        data = data if isinstance(data, dict) else {}
        scroll = QScrollArea(parent_frame)
        scroll.setWidgetResizable(True)
        inner = QWidget(scroll)
        inner_layout = QVBoxLayout(inner)
        inner_layout.setContentsMargins(8, 8, 8, 8)
        inner_layout.setSpacing(6)
        for lang in self.all_languages:
            row = QHBoxLayout()
            label = BodyLabel(f"{lang.upper()}:")
            label.setFixedWidth(82)
            row.addWidget(label)
            text = QTextEdit(inner)
            text.setReadOnly(True)
            value = str(data.get(lang, "") or "")
            text.setPlainText(value)
            text.setMinimumHeight(self._estimate_text_height(value, min_height=54, max_height=150))
            row.addWidget(text, 1)
            inner_layout.addLayout(row)
        inner_layout.addStretch(1)
        scroll.setWidget(inner)
        parent_frame.layout().addWidget(scroll)

    def _create_combination_tab(self, frame: QWidget) -> None:
        scroll = QScrollArea(frame)
        scroll.setWidgetResizable(True)
        inner = QWidget(scroll)
        layout = QVBoxLayout(inner)
        layout.setContentsMargins(8, 8, 8, 8)
        combo_data = self.template_data.get("combination_template", {})
        if isinstance(combo_data, str):
            combo_data = {"daily": combo_data, "total": combo_data}
        combo_data = combo_data if isinstance(combo_data, dict) else {}
        for title, key in (("每日套餐组合模板：", "daily"), ("总量套餐组合模板：", "total")):
            layout.addWidget(BodyLabel(title))
            text = QTextEdit(inner)
            text.setReadOnly(True)
            value = str(combo_data.get(key, "") or "")
            text.setPlainText(value)
            text.setMinimumHeight(self._estimate_text_height(value, min_height=130, max_height=240))
            layout.addWidget(text)
        layout.addStretch(1)
        scroll.setWidget(inner)
        frame.layout().addWidget(scroll)

    def _estimate_text_height(self, text: str, min_height: int = 72, max_height: int = 180, chars_per_line: int = 96) -> int:
        if not text:
            return min_height
        lines = 0
        for line in str(text).splitlines() or [""]:
            visual_width = sum(2 if ord(char) > 127 else 1 for char in line)
            lines += max(1, (visual_width // chars_per_line) + 1)
        return max(min_height, min(max_height, (lines + 1) * 22))

    def _get_tab_title(self, parent_path: list[str], sub_key: str) -> str:
        if tuple(parent_path) == ("scripts",):
            return {
                "后降速": "后降速",
                "后停用": "后停用",
                "吃到饱_提前安装": "吃到饱_提前安装",
                "总量停用每日降速": "总量停用每日降速",
            }.get(sub_key, sub_key)
        return {
            "daily_100gb": "每日-100GB {data_capacity}",
            "daily_100gb_unlimited": "每日-100GB-不限速 {data_capacity}",
            "daily_20gb": "每日20GB {data_capacity}",
            "daily_generic": "每日通用 {data_capacity}",
            "total": "总量 {data_capacity}",
            "pre_install_allowed": "允许提前安装",
            "pre_install_not_allowed": "不允许提前安装",
            "+7零点": "+7零点",
            "+8零点": "+8零点",
            "+9零点": "+9零点",
            "激活后每24h": "激活后每24h",
        }.get(sub_key, sub_key)


def apply_translation_config_dialog_theme(dialog: QDialog) -> None:
    colors = ui_theme.semantic_colors(dialog.palette())
    dialog.setStyleSheet(
        f"""
        QDialog#TranslationRuleConfigDialog {{ background-color: {colors['window']}; color: {colors['text']}; }}
        QDialog#TranslationRuleConfigDialog QWidget {{ color: {colors['text']}; }}
        QFrame#TranslationRuleConfigSection {{
            background-color: {colors['card']}; border: 1px solid {colors['border']}; border-radius: 8px;
        }}
        QFrame#TranslationRuleConfigSection QLabel,
        QFrame#TranslationRuleConfigSection QCheckBox,
        QFrame#TranslationRuleConfigSection QRadioButton {{ background: transparent; border: none; color: {colors['text']}; }}
        QFrame#TranslationRuleConfigSection QComboBox {{
            background-color: {colors['subcard']}; border: 1px solid {colors['border']};
            border-radius: 6px; color: {colors['text']}; padding: 4px 8px; min-height: 24px;
        }}
        QFrame#TranslationRuleConfigSection QComboBox QAbstractItemView {{
            background-color: {colors['subcard']}; color: {colors['text']};
            selection-background-color: {colors['selection']}; selection-color: {colors['selection_text']};
        }}
        QSplitter::handle {{ background-color: {colors['border']}; }}
        QDialog#TranslationRuleConfigDialog QPushButton {{
            background-color: {colors['header']}; border: 1px solid {colors['border']};
            border-radius: 6px; color: {colors['text']}; padding: 5px 14px;
        }}
        QDialog#TranslationRuleConfigDialog QPushButton:hover {{ background-color: {colors['card']}; }}
        QDialog#TranslationRuleConfigDialog QPushButton:disabled {{ color: {colors['muted']}; }}
        """
    )


class App(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Ctrip 产品信息接口修改工具")
        self.resize(1700, 900)
        self.setMinimumSize(980, 620)

        self.app_settings = load_app_settings()
        self.product_runtime_settings = RuntimeRequestSettings(
            self.app_settings.product_request_interval_seconds,
            self.app_settings.product_parallel_requests,
        )
        self.product_image_runtime_settings = RuntimeRequestSettings(
            self.app_settings.product_image_request_interval_seconds,
            self.app_settings.product_image_parallel_requests,
        )
        self.translation_runtime_settings = RuntimeRequestSettings(
            self.app_settings.translation_request_interval_seconds,
            self.app_settings.translation_parallel_requests,
        )
        self.request_stats = RequestStatsStore()
        self.write_gate = InMemoryApplicationWriteGate()
        self.rows: list[TemplateRow] = []
        self.results: list[ResultRow] = []
        self.product_result_order: dict[str, int] = {}
        self.preloaded_products: dict[str, ProductSnapshot] = {}
        self.pending_diff_plans: list[DiffPlan] = []
        self.last_saved_products: set[str] = set()
        self.submit_audit_candidate_product_ids: list[str] = []
        self.product_workbench_states: dict[str, ProductWorkbenchUiState] = {
            key: ProductWorkbenchUiState(workbench=key)
            for key in PRODUCT_WORKBENCH_SPECS
        }
        self.product_workbench_widgets: dict[str, dict[str, Any]] = {}
        product_info_state = self.product_workbench_states[ProductWorkbench.PRODUCT_INFO]
        product_info_state.results = self.results
        product_info_state.result_order = self.product_result_order
        product_info_state.preloaded_products = self.preloaded_products
        product_info_state.pending_diff_plans = self.pending_diff_plans
        product_info_state.last_saved_products = self.last_saved_products
        product_info_state.submit_audit_candidate_product_ids = self.submit_audit_candidate_product_ids
        self.active_product_workbench = ProductWorkbench.PRODUCT_INFO
        self.translation_results: list[TranslationResultRow] = []
        self.translation_product_order: dict[str, int] = {}
        self.translation_table_history: list[tuple[list[TranslationResultRow], dict[str, int]]] = []
        self.translation_table_history_index = -1
        self.translation_snapshots: dict[str, TranslationSnapshot] = {}
        self.pending_translation_plans: list[TranslationDiffPlan] = []
        self.last_saved_translation_products: set[str] = set()
        self.translation_rule_runtime = TranslationRuleRuntime()
        self.product_image_workspace = None
        self.docking_config_widget = None
        self.product_error_count = 0
        self.product_verify_failed_count = 0
        self.translation_error_count = 0
        self.translation_verify_failed_count = 0
        self.product_pressure_text = ""
        self.translation_pressure_text = ""
        self.active_worker_area = "translation"
        self.active_product_mode = ""
        self.worker_thread: threading.Thread | None = None
        self.catalog_thread: threading.Thread | None = None
        self.startup_auth_check_thread: threading.Thread | None = None
        self.last_validated_auth_digest = ""
        self.stop_event = threading.Event()
        self.catalog_stop_event = threading.Event()
        self.out_queue: queue.Queue = queue.Queue()
        self._product_render_generation = 0
        self._translation_render_generation = 0
        self._product_render_rows: list[ResultRow] = []
        self._translation_render_rows: list[TranslationResultRow] = []
        self._product_render_index = 0
        self._translation_render_index = 0

        self._build_ui()
        if self.request_stats.load_error:
            self._active_log(self.request_stats.load_error)
        self._apply_app_settings(self.app_settings)
        self._connect_runtime_settings_edits()
        self.product_scroll_timer = QTimer(self)
        self.product_scroll_timer.setSingleShot(True)
        self.product_scroll_timer.timeout.connect(self._scroll_product_table_to_bottom)
        self.translation_scroll_timer = QTimer(self)
        self.translation_scroll_timer.setSingleShot(True)
        self.translation_scroll_timer.timeout.connect(self._scroll_translation_table_to_bottom)
        self.product_detail_timer = QTimer(self)
        self.product_detail_timer.setSingleShot(True)
        self.product_detail_timer.timeout.connect(self.render_selected_detail)
        self.translation_detail_timer = QTimer(self)
        self.translation_detail_timer.setSingleShot(True)
        self.translation_detail_timer.timeout.connect(self.render_selected_translation_detail)
        self.poll_timer = QTimer(self)
        self.poll_timer.setInterval(50)
        self.poll_timer.timeout.connect(self._poll_queue)
        self.poll_timer.start()
        self._check_dependencies()

    def current_product_workbench_state(self, workbench: str | None = None) -> ProductWorkbenchUiState:
        key = workbench or self.active_product_workbench
        return self.product_workbench_states[product_workbench_spec(key).key]

    def _register_product_workbench_widgets(self, workbench: str, widgets: dict[str, Any]) -> None:
        self.product_workbench_widgets[product_workbench_spec(workbench).key] = widgets

    def _activate_product_workbench(self, workbench: str) -> None:
        key = product_workbench_spec(workbench).key
        self.active_product_workbench = key
        state = self.current_product_workbench_state(key)
        widgets = self.product_workbench_widgets.get(key)
        if not widgets:
            return
        self.results = state.results
        self.product_result_order = state.result_order
        self.preloaded_products = state.preloaded_products
        self.pending_diff_plans = state.pending_diff_plans
        self.last_saved_products = state.last_saved_products
        self.submit_audit_candidate_product_ids = state.submit_audit_candidate_product_ids
        self.product_error_count = state.error_count
        self.product_verify_failed_count = state.verify_failed_count
        self.product_pressure_text = state.pressure_text
        self.template_path = widgets["template_path"]
        self.preload_btn = widgets["preload_btn"]
        self.export_template_btn = widgets["export_template_btn"]
        self.apply_btn = widgets["apply_btn"]
        self.submit_audit_btn = widgets["submit_audit_btn"]
        self.export_btn = widgets["export_btn"]
        self.auth_btn = widgets["auth_btn"]
        self.stop_btn = widgets["stop_btn"]
        self.status_label = widgets["status_label"]
        self.export_price_check = widgets["export_price_check"]
        self.export_connection_check = widgets["export_connection_check"]
        self.export_intro_check = widgets["export_intro_check"]
        self.request_interval_edit = widgets["request_interval_edit"]
        self.parallel_requests_edit = widgets["parallel_requests_edit"]
        self.table = widgets["table"]
        self.product_result_model = widgets["product_result_model"]
        self.log_text = widgets["log_text"]
        self.detail_text = widgets["detail_text"]
        self.product_result_model.set_results(self.results)

    def _sync_active_product_workbench_state(self) -> None:
        state = self.current_product_workbench_state()
        state.results = self.results
        state.result_order = self.product_result_order
        state.preloaded_products = self.preloaded_products
        state.pending_diff_plans = self.pending_diff_plans
        state.last_saved_products = self.last_saved_products
        state.submit_audit_candidate_product_ids = self.submit_audit_candidate_product_ids
        state.error_count = self.product_error_count
        state.verify_failed_count = self.product_verify_failed_count
        state.pressure_text = self.product_pressure_text

    def _run_in_product_workbench(self, workbench: str, handler: Callable[[], None]) -> None:
        self._activate_product_workbench(workbench)
        handler()

    def _build_ui(self) -> None:
        root = QWidget(self)
        self.setCentralWidget(root)
        root_layout = QVBoxLayout(root)
        root_layout.setContentsMargins(10, 10, 10, 10)
        root_layout.setSpacing(8)

        tabs = QTabWidget(self)
        root_layout.addWidget(tabs, 1)

        product_tab = QWidget(self)
        product_tab.setObjectName("productEditTab")
        layout = QVBoxLayout(product_tab)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        workflow_header = QFrame(product_tab)
        workflow_header.setObjectName("productWorkflowHeader")
        workflow_header.setFrameShape(QFrame.Shape.StyledPanel)
        workflow_header_layout = QHBoxLayout(workflow_header)
        workflow_header_layout.setContentsMargins(18, 13, 18, 13)
        workflow_header_layout.setSpacing(20)
        workflow_copy = QVBoxLayout()
        workflow_copy.setSpacing(3)
        workflow_title = BodyLabel("产品修改工作台", workflow_header)
        workflow_title.setObjectName("productWorkflowTitle")
        workflow_title.setStyleSheet("font-size: 20px; font-weight: 700;")
        workflow_subtitle = BodyLabel("用一份统一模板管理产品名称、底价与套餐 API 信息", workflow_header)
        workflow_subtitle.setObjectName("productWorkflowSubtitle")
        workflow_subtitle.setStyleSheet("font-size: 12px;")
        workflow_steps = BodyLabel("预载数据  →  导出模板  →  回填预览  →  传出修改  →  提交审核", workflow_header)
        workflow_steps.setObjectName("productWorkflowSteps")
        workflow_steps.setStyleSheet("font-size: 12px; font-weight: 600;")
        workflow_copy.addWidget(workflow_title)
        workflow_copy.addWidget(workflow_subtitle)
        workflow_copy.addWidget(workflow_steps)
        workflow_header_layout.addLayout(workflow_copy, 1)

        auth_copy = QVBoxLayout()
        auth_copy.setSpacing(3)
        auth_caption = BodyLabel("第一步：登录态", workflow_header)
        auth_caption.setStyleSheet("font-size: 11px;")
        auth_row = QHBoxLayout()
        auth_row.setSpacing(8)
        self.auth_btn = PrimaryPushButton("刷新登录态", workflow_header)
        self.auth_btn.setToolTip("首次使用会打开携程登录专用 Edge/Chrome；请在该窗口完成登录，之后会复用登录资料。")
        self.auth_btn.clicked.connect(self.start_refresh_auth)
        self.product_auth_status_label = BodyLabel("登录态：检查中…", workflow_header)
        self.product_auth_status_label.setObjectName("productAuthStatusLabel")
        auth_row.addWidget(self.auth_btn)
        auth_row.addWidget(self.product_auth_status_label)
        auth_copy.addWidget(auth_caption)
        auth_copy.addLayout(auth_row)
        workflow_header_layout.addLayout(auth_copy)

        status_copy = QVBoxLayout()
        status_copy.setSpacing(2)
        status_caption = BodyLabel("当前运行状态", workflow_header)
        status_caption.setObjectName("productStatusCaption")
        status_caption.setStyleSheet("font-size: 11px;")
        self.status_label = BodyLabel(self._replace_request_stats("就绪", "product"), workflow_header)
        self.status_label.setObjectName("productStatusLabel")
        self.status_label.setStyleSheet(PRODUCT_STATUS_LABEL_STYLE)
        status_copy.addWidget(status_caption)
        status_copy.addWidget(self.status_label)
        workflow_header_layout.addLayout(status_copy)
        layout.addWidget(workflow_header)

        template_card = QFrame(product_tab)
        template_card.setObjectName("productTemplateCard")
        template_card.setFrameShape(QFrame.Shape.StyledPanel)
        template_layout = QVBoxLayout(template_card)
        template_layout.setContentsMargins(14, 10, 14, 12)
        template_layout.setSpacing(8)
        template_heading = QHBoxLayout()
        template_index = BodyLabel("01", template_card)
        template_index.setObjectName("productSectionIndex")
        template_index.setStyleSheet("font-size: 11px; font-weight: 700;")
        template_title = BodyLabel("准备数据与模板", template_card)
        template_title.setObjectName("productSectionTitle")
        template_title.setStyleSheet("font-size: 14px; font-weight: 700;")
        template_hint = BodyLabel("先获取最新产品数据，再导出、填写并加载统一模板", template_card)
        template_hint.setObjectName("productSectionHint")
        template_hint.setStyleSheet("font-size: 11px;")
        template_heading.addWidget(template_index)
        template_heading.addWidget(template_title)
        template_heading.addSpacing(6)
        template_heading.addWidget(template_hint)
        template_heading.addStretch(1)
        template_layout.addLayout(template_heading)

        template_actions = QHBoxLayout()
        template_actions.setSpacing(8)
        self.preload_btn = PrimaryPushButton("输入产品ID并预载", self)
        self.preload_btn.setObjectName("productPrimaryAction")
        self.export_template_btn = PushButton("导出修改模板", self)
        self.preload_btn.clicked.connect(self.start_preload_products)
        self.export_template_btn.clicked.connect(self.export_edit_template)
        template_actions.addWidget(self.preload_btn)
        template_actions.addWidget(self.export_template_btn)
        template_actions.addSpacing(12)
        template_file_label = BodyLabel("回填文件", template_card)
        template_file_label.setObjectName("productFieldLabel")
        template_actions.addWidget(template_file_label)
        self.template_path = LineEdit(self)
        self.template_path.setPlaceholderText("选择已回填的 .xlsx 修改模板")
        template_actions.addWidget(self.template_path, 1)
        choose_btn = PushButton("选择", self)
        choose_btn.clicked.connect(self.choose_template)
        template_actions.addWidget(choose_btn)
        load_btn = PushButton("加载回填并预览Diff", self)
        load_btn.clicked.connect(self.load_template)
        template_actions.addWidget(load_btn)
        template_layout.addLayout(template_actions)
        layout.addWidget(template_card)

        execution_card = QFrame(product_tab)
        execution_card.setObjectName("productExecutionCard")
        execution_card.setFrameShape(QFrame.Shape.StyledPanel)
        execution_layout = QHBoxLayout(execution_card)
        execution_layout.setContentsMargins(14, 10, 14, 10)
        execution_layout.setSpacing(8)
        execution_index = BodyLabel("02", execution_card)
        execution_index.setObjectName("productSectionIndex")
        execution_index.setStyleSheet("font-size: 11px; font-weight: 700;")
        execution_title = BodyLabel("校验与执行", execution_card)
        execution_title.setObjectName("productSectionTitle")
        execution_title.setStyleSheet("font-size: 14px; font-weight: 700;")
        execution_layout.addWidget(execution_index)
        execution_layout.addWidget(execution_title)
        execution_layout.addSpacing(8)
        self.apply_btn = PrimaryPushButton("传出修改", execution_card)
        self.apply_btn.setObjectName("productDangerAction")
        self.submit_audit_btn = PushButton("提交审核", self)
        self.export_btn = PushButton("导出结果报告", self)
        self.stop_btn = PushButton("停止", self)
        self.stop_btn.setObjectName("productStopAction")
        for button, handler in [
            (self.apply_btn, self.start_apply),
            (self.submit_audit_btn, self.start_submit_audit),
            (self.export_btn, self.export_report),
            (self.stop_btn, self.stop_work),
        ]:
            button.clicked.connect(handler)
            execution_layout.addWidget(button)
        execution_layout.addStretch(1)

        self.export_price_check = CheckBox("底价", self)
        self.export_price_check.setChecked(True)
        self.export_connection_check = CheckBox("供应商套餐ID/对接代码", self)
        self.export_connection_check.setChecked(True)
        self.export_intro_check = CheckBox("套餐说明", self)
        self.export_intro_check.setChecked(True)
        for checkbox in (self.export_price_check, self.export_connection_check, self.export_intro_check):
            checkbox.setVisible(False)
        request_interval_label = BodyLabel("请求间隔", execution_card)
        request_interval_label.setObjectName("productFieldLabel")
        execution_layout.addWidget(request_interval_label)
        self.request_interval_edit = LineEdit(self)
        self.request_interval_edit.setText(str(CTRIP_REQUEST_INTERVAL_SECONDS))
        self.request_interval_edit.setFixedWidth(66)
        self.request_interval_edit.setToolTip("两次接口请求之间的最短间隔，单位为秒。")
        execution_layout.addWidget(self.request_interval_edit)
        request_interval_unit = BodyLabel("秒", execution_card)
        request_interval_unit.setObjectName("productSectionHint")
        execution_layout.addWidget(request_interval_unit)
        execution_layout.addSpacing(4)
        parallel_label = BodyLabel("并行数", execution_card)
        parallel_label.setObjectName("productFieldLabel")
        execution_layout.addWidget(parallel_label)
        self.parallel_requests_edit = LineEdit(self)
        self.parallel_requests_edit.setText(str(DEFAULT_PARALLEL_REQUESTS))
        self.parallel_requests_edit.setFixedWidth(58)
        self.parallel_requests_edit.setToolTip(f"修改/读取接口并行请求数，范围 1-{MAX_PARALLEL_REQUESTS}。")
        execution_layout.addWidget(self.parallel_requests_edit)
        layout.addWidget(execution_card)

        results_card = QFrame(product_tab)
        results_card.setObjectName("productResultsCard")
        results_card.setFrameShape(QFrame.Shape.StyledPanel)
        results_layout = QVBoxLayout(results_card)
        results_layout.setContentsMargins(8, 8, 8, 8)
        results_layout.setSpacing(7)
        results_heading = QHBoxLayout()
        results_index = BodyLabel("03", results_card)
        results_index.setObjectName("productSectionIndex")
        results_index.setStyleSheet("font-size: 11px; font-weight: 700;")
        results_title = BodyLabel("修改预览", results_card)
        results_title.setObjectName("productSectionTitle")
        results_title.setStyleSheet("font-size: 14px; font-weight: 700;")
        results_hint = BodyLabel("单击行查看字段差异，双击打开完整预览", results_card)
        results_hint.setObjectName("productSectionHint")
        results_hint.setStyleSheet("font-size: 11px;")
        results_heading.addWidget(results_index)
        results_heading.addWidget(results_title)
        results_heading.addSpacing(6)
        results_heading.addWidget(results_hint)
        results_heading.addStretch(1)
        results_layout.addLayout(results_heading)

        splitter = QSplitter(Qt.Orientation.Vertical, self)
        results_layout.addWidget(splitter, 1)
        layout.addWidget(results_card, 1)

        self.table = QTableView(self)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._setup_result_table()
        self.table.selectionModel().selectionChanged.connect(lambda _selected, _deselected: self.show_selected_detail())
        self.table.doubleClicked.connect(lambda _index: self.open_preview())
        splitter.addWidget(self.table)

        bottom = QSplitter(Qt.Orientation.Horizontal, self)
        splitter.addWidget(bottom)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)

        log_panel = self._panel("运行日志")
        self.log_text = PlainTextEdit(self)
        self.log_text.setReadOnly(True)
        self.log_text.document().setMaximumBlockCount(MAX_LOG_BLOCKS)
        log_panel.layout().addWidget(self.log_text)
        bottom.addWidget(log_panel)

        detail_panel = self._panel("选中项详情 / Diff")
        self.detail_text = PlainTextEdit(self)
        self.detail_text.setReadOnly(True)
        detail_panel.layout().addWidget(self.detail_text)
        bottom.addWidget(detail_panel)
        bottom.setStretchFactor(0, 1)
        bottom.setStretchFactor(1, 1)
        self._register_product_workbench_widgets(
            ProductWorkbench.PRODUCT_INFO,
            {
                "template_path": self.template_path,
                "preload_btn": self.preload_btn,
                "export_template_btn": self.export_template_btn,
                "apply_btn": self.apply_btn,
                "submit_audit_btn": self.submit_audit_btn,
                "export_btn": self.export_btn,
                "auth_btn": self.auth_btn,
                "stop_btn": self.stop_btn,
                "status_label": self.status_label,
                "export_price_check": self.export_price_check,
                "export_connection_check": self.export_connection_check,
                "export_intro_check": self.export_intro_check,
                "request_interval_edit": self.request_interval_edit,
                "parallel_requests_edit": self.parallel_requests_edit,
                "table": self.table,
                "product_result_model": self.product_result_model,
                "log_text": self.log_text,
                "detail_text": self.detail_text,
            },
        )
        translation_tab = self._build_translation_tab()
        product_host = QWidget(self)
        product_host.setObjectName("productEditHost")
        product_host_layout = QVBoxLayout(product_host)
        product_host_layout.setContentsMargins(0, 0, 0, 0)
        product_pages = QTabWidget(product_host)
        product_pages.setObjectName("productEditPages")
        product_pages.addTab(product_tab, "批量修改")
        self.product_edit_component = ProductEditWidget(product_pages)
        self._connect_workbench_signals(self.product_edit_component)
        self.product_edit_component.read_requested.connect(self.start_full_field_catalog_read)
        self.product_edit_component.read_stopped.connect(self.stop_full_field_catalog_read)
        product_pages.addTab(self.product_edit_component, "全字段目录")
        product_host_layout.addWidget(product_pages)

        tabs.addTab(translation_tab, "翻译件管理")
        tabs.addTab(product_host, product_workbench_spec(ProductWorkbench.PRODUCT_INFO).title)
        tabs.addTab(self._build_product_image_tab(), "产品图片配置")
        tabs.addTab(self._build_docking_config_tab(), "产品对接单独配置")
        tabs.currentChanged.connect(lambda _index: self._activate_product_workbench_for_tab(tabs))
        self._activate_product_workbench(ProductWorkbench.PRODUCT_INFO)
        self._set_running(False)
        self._set_translation_running(False)

    def _activate_product_workbench_for_tab(self, tabs: QTabWidget) -> None:
        title = tabs.tabText(tabs.currentIndex())
        for key, spec in PRODUCT_WORKBENCH_SPECS.items():
            if title == spec.title and key != ProductWorkbench.AUDIT_REPORT:
                self._activate_product_workbench(key)
                return

    def _build_product_workbench_operational_tab(self, workbench: str) -> QWidget:
        spec = product_workbench_spec(workbench)
        state = self.current_product_workbench_state(workbench)
        tab = QWidget(self)
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(8)

        top = QHBoxLayout()
        top.addWidget(BodyLabel("回填模板"))
        template_path = LineEdit(self)
        top.addWidget(template_path, 1)
        choose_btn = PushButton("选择", self)
        choose_btn.clicked.connect(lambda _checked=False, key=workbench: self._run_in_product_workbench(key, self.choose_template))
        top.addWidget(choose_btn)
        load_btn = PushButton("加载回填并预览Diff", self)
        load_btn.clicked.connect(lambda _checked=False, key=workbench: self._run_in_product_workbench(key, self.load_template))
        top.addWidget(load_btn)
        layout.addLayout(top)

        actions = QHBoxLayout()
        preload_btn = PrimaryPushButton(spec.preload_button_text, self)
        export_template_btn = PushButton(spec.template_button_text, self)
        apply_btn = PushButton(spec.apply_button_text, self)
        submit_audit_btn = PushButton("提交审核", self)
        export_btn = PushButton(f"导出{spec.title}报告", self)
        auth_btn = PushButton("刷新登录态", self)
        stop_btn = PushButton("停止", self)
        for button, handler in [
            (preload_btn, self.start_preload_products),
            (export_template_btn, self.export_edit_template),
            (apply_btn, self.start_apply),
            (submit_audit_btn, self.start_submit_audit),
            (export_btn, self.export_report),
            (auth_btn, self.start_refresh_auth),
            (stop_btn, self.stop_work),
        ]:
            button.clicked.connect(lambda _checked=False, key=workbench, active_handler=handler: self._run_in_product_workbench(key, active_handler))
            actions.addWidget(button)
        status_label = BodyLabel(self._replace_request_stats("就绪", "product"))
        status_label.setStyleSheet(PRODUCT_STATUS_LABEL_STYLE)
        actions.addSpacing(8)
        actions.addWidget(status_label, 1)
        layout.addLayout(actions)

        fields = QHBoxLayout()
        fields.addWidget(BodyLabel("导出字段"))
        export_price_check = CheckBox("底价", self)
        export_price_check.setChecked(workbench == ProductWorkbench.PRICE_INVENTORY)
        export_connection_check = CheckBox("供应商套餐ID/对接代码", self)
        export_connection_check.setChecked(workbench == ProductWorkbench.PACKAGE_CONNECT)
        export_intro_check = CheckBox("套餐说明", self)
        export_intro_check.setChecked(False)
        export_price_check.setEnabled(workbench == ProductWorkbench.PRICE_INVENTORY)
        export_connection_check.setEnabled(workbench == ProductWorkbench.PACKAGE_CONNECT)
        export_intro_check.setEnabled(workbench == ProductWorkbench.PACKAGE_CONNECT)
        fields.addWidget(export_price_check)
        fields.addWidget(export_connection_check)
        fields.addWidget(export_intro_check)
        fields.addSpacing(18)
        fields.addWidget(BodyLabel("请求间隔秒"))
        request_interval_edit = LineEdit(self)
        request_interval_edit.setText(str(CTRIP_REQUEST_INTERVAL_SECONDS))
        request_interval_edit.setFixedWidth(88)
        fields.addWidget(request_interval_edit)
        fields.addSpacing(10)
        fields.addWidget(BodyLabel("并行请求数"))
        parallel_requests_edit = LineEdit(self)
        parallel_requests_edit.setText(str(DEFAULT_PARALLEL_REQUESTS))
        parallel_requests_edit.setFixedWidth(72)
        parallel_requests_edit.setToolTip(f"修改/读取接口并行请求数，范围 1-{MAX_PARALLEL_REQUESTS}。")
        fields.addWidget(parallel_requests_edit)
        fields.addStretch(1)
        layout.addLayout(fields)

        splitter = QSplitter(Qt.Orientation.Vertical, self)
        layout.addWidget(splitter, 1)
        table = QTableView(self)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        product_result_model = ProductResultTableModel(state.results, self)
        table.setModel(product_result_model)
        table.setAlternatingRowColors(True)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        table.verticalHeader().setVisible(False)
        apply_table_readable_style(table)
        splitter.addWidget(table)

        bottom = QSplitter(Qt.Orientation.Horizontal, self)
        splitter.addWidget(bottom)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        log_panel = self._panel("日志")
        log_text = PlainTextEdit(self)
        log_text.setReadOnly(True)
        log_text.document().setMaximumBlockCount(MAX_LOG_BLOCKS)
        log_panel.layout().addWidget(log_text)
        bottom.addWidget(log_panel)
        detail_panel = self._panel("详情 / Diff")
        detail_text = PlainTextEdit(self)
        detail_text.setReadOnly(True)
        detail_panel.layout().addWidget(detail_text)
        table.selectionModel().selectionChanged.connect(
            lambda _selected, _deselected, view=table, model=product_result_model, panel=detail_text: self.show_product_result_detail(view, model, panel)
        )
        table.doubleClicked.connect(
            lambda _index, view=table, model=product_result_model, key=workbench: self.open_product_result_preview(
                view,
                model,
                self.current_product_workbench_state(key).preloaded_products,
                model.rows,
            )
        )
        bottom.addWidget(detail_panel)
        bottom.setStretchFactor(0, 1)
        bottom.setStretchFactor(1, 1)

        self._register_product_workbench_widgets(
            workbench,
            {
                "template_path": template_path,
                "preload_btn": preload_btn,
                "export_template_btn": export_template_btn,
                "apply_btn": apply_btn,
                "submit_audit_btn": submit_audit_btn,
                "export_btn": export_btn,
                "auth_btn": auth_btn,
                "stop_btn": stop_btn,
                "status_label": status_label,
                "export_price_check": export_price_check,
                "export_connection_check": export_connection_check,
                "export_intro_check": export_intro_check,
                "request_interval_edit": request_interval_edit,
                "parallel_requests_edit": parallel_requests_edit,
                "table": table,
                "product_result_model": product_result_model,
                "log_text": log_text,
                "detail_text": detail_text,
            },
        )
        return tab

    def _panel(self, title: str) -> QFrame:
        panel = QFrame(self)
        panel.setFrameShape(QFrame.Shape.StyledPanel)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.addWidget(BodyLabel(title))
        return panel

    def _compact_panel(self, title: str) -> QFrame:
        panel = QFrame(self)
        panel.setFrameShape(QFrame.Shape.StyledPanel)
        layout = QVBoxLayout(panel)
        if title:
            layout.setContentsMargins(8, 6, 8, 6)
            layout.setSpacing(6)
            title_label = BodyLabel(title)
            title_label.setStyleSheet("font-weight: 600;")
            layout.addWidget(title_label)
        else:
            layout.setContentsMargins(6, 4, 6, 4)
            layout.setSpacing(3)
        return panel

    def _create_translation_sidebar_section(
        self,
        parent: QWidget,
        object_name: str,
        number: str,
        title: str,
        hint: str,
    ) -> tuple[QFrame, QVBoxLayout]:
        section = QFrame(parent)
        section.setObjectName(object_name)
        section.setProperty("translationSidebarSection", True)
        section.setFrameShape(QFrame.Shape.StyledPanel)
        section_layout = QVBoxLayout(section)
        section_layout.setContentsMargins(6, 3, 6, 3)
        section_layout.setSpacing(2)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(6)
        number_label = BodyLabel(number, section)
        number_label.setProperty("translationStageNumber", True)
        title_label = BodyLabel(title, section)
        title_label.setProperty("translationStageTitle", True)
        hint_label = BodyLabel(hint, section)
        hint_label.setProperty("translationStageHint", True)
        header.addWidget(number_label)
        header.addWidget(title_label)
        header.addWidget(hint_label)
        header.addStretch(1)
        section_layout.addLayout(header)
        return section, section_layout

    def _configure_translation_status_label(self, label: QLabel) -> None:
        label.setWordWrap(True)
        label.setMinimumWidth(0)
        label.setMaximumWidth(16777215)
        label.setMinimumHeight(label.fontMetrics().lineSpacing() + 2)
        label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        label.setToolTip(label.text())

    def _apply_global_theme(self) -> None:
        palette = self.palette()
        colors = ui_theme.semantic_colors(palette)
        tables: dict[int, Any] = {}
        text_edits: dict[int, Any] = {}
        labels: dict[int, Any] = {}
        for widgets in getattr(self, "product_workbench_widgets", {}).values():
            for key, collection in (
                ("table", tables),
                ("log_text", text_edits),
                ("detail_text", text_edits),
                ("status_label", labels),
            ):
                widget = widgets.get(key)
                if widget is not None:
                    collection[id(widget)] = widget

        for table in (
            getattr(self, "table", None),
            getattr(self, "translation_table", None),
        ):
            if table is not None:
                tables[id(table)] = table

        for text_edit in (
            getattr(self, "log_text", None),
            getattr(self, "detail_text", None),
            getattr(self, "translation_log_text", None),
            getattr(self, "translation_detail_text", None),
        ):
            if text_edit is not None:
                text_edits[id(text_edit)] = text_edit

        for label in (
            getattr(self, "status_label", None),
        ):
            if label is not None:
                labels[id(label)] = label

        for table in tables.values():
            table.setPalette(palette)
            apply_table_readable_style(table)
        for text_edit in text_edits.values():
            text_edit.setPalette(palette)
        for label in labels.values():
            label_palette = label.palette()
            label_palette.setColor(label.foregroundRole(), QColor(colors["link"]))
            label.setPalette(label_palette)

        self._apply_translation_workbench_theme()
        self._refresh_open_dialog_themes()

    def _refresh_open_dialog_themes(self) -> None:
        for widget in QApplication.topLevelWidgets():
            if isinstance(widget, QDialog) and widget.objectName() == "TranslationRuleConfigDialog":
                apply_translation_config_dialog_theme(widget)

    def _apply_translation_workbench_theme(self) -> None:
        tab = getattr(self, "translation_workbench_tab", None)
        if tab is None:
            return
        palette = tab.palette()
        colors = translation_workbench_palette(tab)
        tab.setStyleSheet(
            f"""
            #translationWorkflowHeader {{
                background-color: {colors['header']};
                border: 2px solid {colors['strong_border']};
                border-radius: 8px;
            }}
            QFrame[translationSidebarSection="true"], #translationResultsPane {{
                background-color: {colors['card']};
                border: 1px solid {colors['strong_border']};
                border-radius: 7px;
            }}
            #translationSidebar {{
                background-color: {colors['window']};
                border: 0;
            }}
            QLabel[translationStageNumber="true"] {{
                color: {colors['accent']};
            }}
            #translationLogText, #translationDetailText {{
                background-color: {colors['subcard']};
                color: {colors['text']};
                border: 1px solid {colors['border']};
            }}
            """
        )
        tab.setPalette(palette)
        button_hover = mix_qcolors(QColor(colors["header"]), QColor(colors["accent"]), 0.12).name()
        disabled_background = mix_qcolors(QColor(colors["header"]), QColor(colors["window"]), 0.44).name()
        primary_buttons = tuple(
            button
            for button in (
                getattr(self, "translation_rule_load_task_btn", None),
                getattr(self, "translation_rule_load_detail_btn", None),
                getattr(self, "translation_rule_load_package_btn", None),
                getattr(self, "translation_rule_generate_btn", None),
                getattr(self, "translation_rule_auth_btn", None),
            )
            if button is not None
        )
        for label in tab.findChildren(QLabel):
            label.setStyleSheet(f"color: {colors['text']};")
            if label.property("translationStageNumber") is True:
                label.setStyleSheet(f"color: {colors['accent']}; font-size: 11px; font-weight: 700;")
            elif label.property("translationStageTitle") is True or label.property("translationMaterialTitle") is True:
                label.setStyleSheet(f"color: {colors['text']}; font-size: 14px; font-weight: 700;")
            elif label.property("translationStageHint") is True:
                label.setStyleSheet(f"color: {colors['muted']}; font-size: 11px;")
            elif label.property("translationTemplateLoaded") is not None:
                status_color = colors["loaded"] if label.property("translationTemplateLoaded") else colors["muted"]
                label.setStyleSheet(f"color: {status_color};")
        for button in tab.findChildren(QPushButton):
            selector = button.metaObject().className()
            is_primary = button in primary_buttons
            background = colors["accent"] if is_primary else colors["header"]
            foreground = colors["accent_text"] if is_primary else colors["text"]
            hover = colors["accent"] if is_primary else button_hover
            button.setStyleSheet(
                f"""
                {selector} {{
                    background-color: {background};
                    color: {foreground};
                    border: 1px solid {colors['border']};
                    border-radius: 5px;
                    padding: 3px 8px;
                    font-weight: {600 if button is getattr(self, 'translation_rule_apply_btn', None) else 400};
                }}
                {selector}:hover {{
                    background-color: {hover};
                }}
                {selector}:disabled {{
                    background-color: {disabled_background};
                    color: {colors['muted']};
                    border-color: {colors['border']};
                }}
                """
            )
        for line_edit in (getattr(self, "translation_request_interval_edit", None), getattr(self, "translation_parallel_requests_edit", None)):
            if line_edit is not None:
                line_edit.setStyleSheet(
                    f"background-color: {colors['subcard']}; color: {colors['text']}; "
                    f"border: 1px solid {colors['border']}; border-radius: 5px; padding: 4px 7px;"
                )
        for widget_name in ("translation_table", "translation_log_text", "translation_detail_text"):
            widget = getattr(self, widget_name, None)
            if widget is not None:
                widget.setPalette(palette)
        for text_edit in (getattr(self, "translation_log_text", None), getattr(self, "translation_detail_text", None)):
            if text_edit is not None:
                text_edit.setStyleSheet(
                    f"background-color: {colors['subcard']}; color: {colors['text']}; "
                    f"border: 1px solid {colors['border']};"
                )
        if hasattr(self, "translation_table"):
            apply_table_readable_style(self.translation_table)
        for label_name in (
            "translation_rule_task_status_label",
            "translation_rule_detail_status_label",
            "translation_rule_package_status_label",
        ):
            label = getattr(self, label_name, None)
            if label is not None:
                label.setToolTip(label.text())

    def _flow_arrow_label(self, text: str) -> QLabel:
        arrow = BodyLabel(text)
        arrow.setAlignment(Qt.AlignmentFlag.AlignCenter)
        arrow.setStyleSheet("font-size: 22px; font-weight: 700;")
        arrow.setFixedWidth(34)
        arrow.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred)
        return arrow

    def _add_translation_template_row(
        self,
        layout: QVBoxLayout,
        label_text: str,
        load_button: QPushButton,
        manager_button: QPushButton,
        status_label: QLabel,
        download_button: QPushButton,
    ) -> None:
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        type_label = BodyLabel(label_text)
        type_label.setFixedWidth(58)
        for button in (load_button, manager_button):
            button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        status_label.setMinimumWidth(140)
        status_label.setMaximumWidth(360)
        status_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        download_button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        row.addWidget(type_label)
        row.addWidget(load_button)
        row.addWidget(manager_button)
        row.addWidget(status_label, 1)
        row.addWidget(download_button)
        layout.addLayout(row)

    def _create_translation_template_section(
        self,
        label_text: str,
        load_button: QPushButton,
        manager_button: QPushButton,
        status_label: QLabel,
        download_button: QPushButton,
    ) -> QWidget:
        section = QWidget(self)
        section_layout = QVBoxLayout(section)
        section_layout.setContentsMargins(0, 0, 0, 0)
        section_layout.setSpacing(4)

        top_row = QHBoxLayout()
        top_row.setContentsMargins(0, 0, 0, 0)
        top_row.setSpacing(8)
        type_label = BodyLabel(label_text)
        type_label.setFixedWidth(58)
        load_button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        manager_button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        download_button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        top_row.addWidget(type_label)
        top_row.addWidget(load_button)
        top_row.addWidget(manager_button)
        top_row.addStretch(1)
        top_row.addWidget(download_button)
        section_layout.addLayout(top_row)

        status_label.setMinimumWidth(0)
        status_label.setMaximumWidth(300)
        status_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        section_layout.addWidget(status_label)
        return section

    def _set_translation_rule_summary_text(self) -> None:
        summary = self.translation_rule_config_summary()
        self.translation_rule_summary_label.setText(summary)
        self.translation_rule_summary_label.setToolTip(summary)
        if hasattr(self, "translation_runtime_summary_label"):
            self.translation_runtime_summary_label.setText(summary)
            self.translation_runtime_summary_label.setToolTip(summary)

    def _setup_result_table(self) -> None:
        self.product_result_model = ProductResultTableModel(self.results, self)
        self.table.setModel(self.product_result_model)
        self.table.setSortingEnabled(False)
        widths = [120, 120, 120, 280, 130, 240, 240, 220, 120, 420, 80]
        for index, width in enumerate(widths):
            self.table.setColumnWidth(index, width)
        self.table.setAlternatingRowColors(True)
        self.table.setWordWrap(False)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.table.horizontalHeader().setStretchLastSection(False)
        self.table.verticalHeader().setVisible(False)
        apply_table_readable_style(self.table)

    def _build_product_image_tab(self) -> QWidget:
        from product_image_workspace import ProductImageWorkspace

        tab = QWidget(self)
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Keep the persisted request controls as non-visual adapters for the
        # existing settings format.  The embedded workspace owns its UI.
        self.product_image_request_interval_edit = LineEdit(self)
        self.product_image_request_interval_edit.setText(str(CTRIP_REQUEST_INTERVAL_SECONDS))
        self.product_image_request_interval_edit.hide()
        self.product_image_parallel_requests_edit = LineEdit(self)
        self.product_image_parallel_requests_edit.setText(str(DEFAULT_PARALLEL_REQUESTS))
        self.product_image_parallel_requests_edit.hide()

        lazy_client = LazyCtripClientProxy(
            lambda: CtripRequestsClient(
                self.product_image_log,
                request_interval_seconds=self.product_image_runtime_settings.request_interval_seconds(),
                request_interval_provider=self.product_image_runtime_settings.request_interval_seconds,
                stats_area="image",
                stats_recorder=self._queue_request_stat,
            )
        )
        backend = make_product_image_workspace_backend(
            lazy_client,
            request_recorder=self._queue_request_stat,
        )
        self.product_image_workspace = ProductImageWorkspace(backend, tab)
        self._connect_workbench_signals(self.product_image_workspace)
        self.product_image_workspace.set_request_stats_text(
            self.request_stats.summary_text("image")
        )
        layout.addWidget(self.product_image_workspace, 1)
        return tab

    def _build_docking_config_tab(self) -> QWidget:
        tab = QWidget(self)
        tab.setObjectName("dockingConfigTab")
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        lazy_client = LazyCtripClientProxy(
            lambda: CtripRequestsClient(
                lambda message: self.docking_config_widget.enqueue_log(message),
                request_interval_seconds=0,
                stats_area="docking",
                stats_recorder=self._queue_request_stat,
            )
        )
        self.docking_config_widget = DockingConfigWidget(lambda: lazy_client, tab)
        self._connect_workbench_signals(self.docking_config_widget)
        self.docking_config_widget.set_request_stats_text(
            self.request_stats.summary_text("docking")
        )
        layout.addWidget(self.docking_config_widget, 1)
        return tab

    def _connect_workbench_signals(self, component: QWidget) -> None:
        component.write_started.connect(self._on_workbench_write_started)
        component.write_finished.connect(self._on_workbench_write_finished)
        component.auth_refresh_requested.connect(self.start_refresh_auth)
        component.settings_changed.connect(self.persist_app_settings)
        if hasattr(component, "request_failed"):
            component.request_failed.connect(self._record_failure_stat)

    def start_full_field_catalog_read(self, product_ids: tuple[str, ...]) -> None:
        if self.catalog_thread and self.catalog_thread.is_alive():
            QMessageBox.warning(self, "提示", "全字段目录正在读取")
            return
        self.catalog_stop_event.clear()
        self.catalog_thread = threading.Thread(
            target=self._run_full_field_catalog_read,
            args=(tuple(product_ids),),
            daemon=True,
        )
        self.catalog_thread.start()

    def stop_full_field_catalog_read(self) -> None:
        self.catalog_stop_event.set()

    def _run_full_field_catalog_read(self, product_ids: tuple[str, ...]) -> None:
        client = CtripDraftClient(CdpClient(), lambda _message: None)
        total = len(product_ids)
        for completed, product_id in enumerate(product_ids, start=1):
            if self.catalog_stop_event.is_set():
                break
            try:
                sources = client.load_full_field_catalog(product_id, self.catalog_stop_event)
                payloads = {
                    source: (RuntimeError(str(item.get("error"))) if item.get("error") else item.get("raw"))
                    for source, item in sources.items()
                }
                result = FullFieldReadResult.from_payloads((product_id,), payloads)
            except Exception:
                result = FullFieldReadResult.from_payloads(
                    (product_id,), {"catalog": RuntimeError("完整字段读取失败")}
                )
            self.out_queue.put(("catalog_result", result))
            self.out_queue.put(("catalog_progress", (completed, total, f"已读取 {completed}/{total} 个商品")))
        self.out_queue.put(("catalog_done", self.catalog_stop_event.is_set()))

    def _on_workbench_write_started(self, area: str) -> None:
        request = WriteGateRequest(area=area, operation="write")
        if self.write_gate.acquire(request):
            return
        component = {
            "product_edit": getattr(self, "product_edit_component", None),
            "product_images": getattr(self, "product_image_workspace", None),
            "docking_config": getattr(self, "docking_config_widget", None),
        }.get(area)
        if component is not None:
            component.stop()
        QMessageBox.warning(self, "写入任务冲突", "另一个业务组件正在执行写入，请等待其完成后重试。")

    def _on_workbench_write_finished(self, area: str) -> None:
        self.write_gate.release(area)


    def _build_translation_tab(self) -> QWidget:
        tab = QWidget(self)
        tab.setObjectName("translationWorkbenchTab")
        self.translation_workbench_tab = tab
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(6)

        workflow_header = QFrame(tab)
        workflow_header.setObjectName("translationWorkflowHeader")
        workflow_header.setFrameShape(QFrame.Shape.StyledPanel)
        workflow_header_layout = QHBoxLayout(workflow_header)
        workflow_header_layout.setContentsMargins(14, 5, 14, 5)
        workflow_header_layout.setSpacing(20)
        workflow_copy = QVBoxLayout()
        workflow_copy.setSpacing(2)
        workflow_title = BodyLabel("翻译件工作台", workflow_header)
        workflow_title.setStyleSheet("font-size: 18px; font-weight: 700;")
        workflow_subtitle = BodyLabel("集中管理任务清单、翻译模板、Diff 生成与接口写入", workflow_header)
        workflow_subtitle.setStyleSheet("font-size: 12px;")
        workflow_steps = BodyLabel("准备素材  →  生成 Diff  →  确认传出  →  导出报告", workflow_header)
        workflow_steps.setStyleSheet("font-size: 12px; font-weight: 600;")
        workflow_copy.addWidget(workflow_title)
        workflow_copy.addWidget(workflow_subtitle)
        workflow_copy.addWidget(workflow_steps)
        workflow_header_layout.addLayout(workflow_copy, 1)

        auth_status = QVBoxLayout()
        auth_status.setSpacing(3)
        auth_caption = BodyLabel("第一步：登录态", workflow_header)
        auth_caption.setStyleSheet("font-size: 11px;")
        auth_row = QHBoxLayout()
        auth_row.setSpacing(8)
        self.translation_rule_auth_btn = PrimaryPushButton("刷新登录态", workflow_header)
        self.translation_rule_auth_btn.setToolTip("首次使用会打开携程登录专用 Edge/Chrome；请在该窗口完成登录，之后会复用登录资料。")
        self.translation_rule_auth_btn.clicked.connect(self.start_translation_refresh_auth)
        self.translation_auth_status_label = BodyLabel("登录态：检查中…", workflow_header)
        self.translation_auth_status_label.setObjectName("translationAuthStatusLabel")
        auth_row.addWidget(self.translation_rule_auth_btn)
        auth_row.addWidget(self.translation_auth_status_label)
        auth_status.addWidget(auth_caption)
        auth_status.addLayout(auth_row)
        workflow_header_layout.addLayout(auth_status)

        runtime_status = QGridLayout()
        runtime_status.setHorizontalSpacing(8)
        runtime_status.setVerticalSpacing(2)
        self.translation_runtime_summary_label = BodyLabel("", workflow_header)
        self.translation_runtime_summary_label.setWordWrap(True)
        self.translation_runtime_summary_label.setMinimumWidth(0)
        self.translation_runtime_summary_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.translation_runtime_status_label = BodyLabel(self._replace_request_stats("就绪", "translation"), workflow_header)
        self.translation_runtime_status_label.setObjectName("translationStatusLabel")
        self.translation_runtime_status_label.setWordWrap(True)
        self.translation_runtime_status_label.setMinimumWidth(0)
        self.translation_runtime_status_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        runtime_status.addWidget(BodyLabel("当前执行配置", workflow_header), 0, 0)
        runtime_status.addWidget(self.translation_runtime_summary_label, 0, 1)
        runtime_status.addWidget(BodyLabel("实时状态", workflow_header), 1, 0)
        runtime_status.addWidget(self.translation_runtime_status_label, 1, 1)
        workflow_header_layout.addLayout(runtime_status, 2)
        layout.addWidget(workflow_header)

        main_splitter = QSplitter(Qt.Orientation.Horizontal, tab)
        main_splitter.setObjectName("translationMainSplitter")
        main_splitter.setChildrenCollapsible(False)
        layout.addWidget(main_splitter, 1)

        sidebar = QWidget(main_splitter)
        sidebar.setObjectName("translationSidebar")
        sidebar.setMinimumWidth(340)
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(0, 0, 0, 0)
        sidebar_layout.setSpacing(4)
        main_splitter.addWidget(sidebar)

        task_section, task_layout = self._create_translation_sidebar_section(
            sidebar,
            "translationTaskSection",
            "01",
            "任务模板",
            "载入产品与语言任务",
        )
        self.translation_rule_load_task_btn = PrimaryPushButton("加载任务模板", self)
        self.translation_rule_load_task_btn.setToolTip("选择包含产品、语言和待处理任务的 Excel 任务模板。")
        self.translation_rule_load_task_btn.clicked.connect(self.choose_translation_rule_task)
        self.translation_rule_download_task_btn = PushButton("下载任务模板", self)
        self.translation_rule_download_task_btn.setToolTip("下载空白任务模板，用于填写产品和语言任务。")
        self.translation_rule_download_task_btn.clicked.connect(self.download_translation_rule_task_template)
        self.translation_rule_edit_task_btn = PushButton("编辑任务模板", self)
        self.translation_rule_edit_task_btn.setToolTip("打开当前任务模板进行编辑。")
        self.translation_rule_edit_task_btn.clicked.connect(self.edit_translation_rule_task_template)
        self.translation_rule_reload_task_btn = PushButton("重新加载任务", self)
        self.translation_rule_reload_task_btn.setToolTip("重新读取当前任务模板文件，刷新任务内容。")
        self.translation_rule_reload_task_btn.clicked.connect(self.reload_translation_rule_task)
        task_buttons = QGridLayout()
        task_buttons.setContentsMargins(0, 0, 0, 0)
        task_buttons.setHorizontalSpacing(6)
        task_buttons.setVerticalSpacing(4)
        task_buttons.addWidget(self.translation_rule_load_task_btn, 0, 0)
        task_buttons.addWidget(self.translation_rule_download_task_btn, 0, 1)
        task_buttons.addWidget(self.translation_rule_edit_task_btn, 1, 0)
        task_buttons.addWidget(self.translation_rule_reload_task_btn, 1, 1)
        for button in [
            self.translation_rule_load_task_btn,
            self.translation_rule_download_task_btn,
            self.translation_rule_edit_task_btn,
            self.translation_rule_reload_task_btn,
        ]:
            button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        task_layout.addLayout(task_buttons)
        self.translation_rule_task_status_label = BodyLabel("未加载任务模板")
        self._configure_translation_status_label(self.translation_rule_task_status_label)
        task_layout.addWidget(self.translation_rule_task_status_label)

        detail_section, detail_layout = self._create_translation_sidebar_section(
            sidebar,
            "translationDetailSection",
            "01",
            "详情模板",
            "维护详情字段翻译文本",
        )
        self.translation_rule_load_detail_btn = PrimaryPushButton("加载详情", self)
        self.translation_rule_load_detail_btn.setToolTip("选择详情字段的翻译文本模板。")
        self.translation_rule_load_detail_btn.clicked.connect(self.choose_translation_rule_detail_template)
        self.translation_rule_detail_manager_btn = PushButton("管理详情", self)
        self.translation_rule_detail_manager_btn.setToolTip("打开详情模板管理窗口，维护详情字段模板。")
        self.translation_rule_detail_manager_btn.clicked.connect(self.open_translation_rule_detail_template_manager)
        self.translation_rule_detail_status_label = BodyLabel("未加载详情模板")
        self.translation_rule_download_detail_btn = PushButton("下载详情", self)
        self.translation_rule_download_detail_btn.setToolTip("下载空白详情模板。")
        self.translation_rule_download_detail_btn.clicked.connect(self.download_translation_rule_detail_template)
        detail_actions = QHBoxLayout()
        detail_actions.setSpacing(6)
        detail_actions.addWidget(self.translation_rule_load_detail_btn)
        detail_actions.addWidget(self.translation_rule_detail_manager_btn)
        self.translation_rule_manual_link = BodyLabel(self)
        self.translation_rule_manual_link.setObjectName("translationManualLink")
        self.translation_rule_manual_link.setTextFormat(Qt.TextFormat.RichText)
        self.translation_rule_manual_link.setText('<a href="translation-manual">操作手册</a>')
        self.translation_rule_manual_link.setCursor(Qt.CursorShape.PointingHandCursor)
        self.translation_rule_manual_link.setToolTip("用系统默认程序打开翻译件管理操作手册（含详情模板富文本格式写法）。")
        self.translation_rule_manual_link.linkActivated.connect(lambda _href: self.open_translation_ops_manual())
        detail_actions.addWidget(self.translation_rule_manual_link)
        detail_actions.addStretch(1)
        detail_actions.addWidget(self.translation_rule_download_detail_btn)
        detail_layout.addLayout(detail_actions)
        self._configure_translation_status_label(self.translation_rule_detail_status_label)
        detail_layout.addWidget(self.translation_rule_detail_status_label)

        package_section, package_layout = self._create_translation_sidebar_section(
            sidebar,
            "translationPackageSection",
            "01",
            "规格模板",
            "维护规格字段翻译文本",
        )
        self.translation_rule_load_package_btn = PrimaryPushButton("加载规格", self)
        self.translation_rule_load_package_btn.setToolTip("选择规格字段的翻译文本模板。")
        self.translation_rule_load_package_btn.clicked.connect(self.choose_translation_rule_package_template)
        self.translation_rule_package_manager_btn = PushButton("管理规格", self)
        self.translation_rule_package_manager_btn.setToolTip("打开规格模板管理窗口，维护规格字段模板。")
        self.translation_rule_package_manager_btn.clicked.connect(self.open_translation_rule_package_template_manager)
        self.translation_rule_package_status_label = BodyLabel("未加载规格模板")
        self.translation_rule_download_package_btn = PushButton("下载规格", self)
        self.translation_rule_download_package_btn.setToolTip("下载空白规格模板。")
        self.translation_rule_download_package_btn.clicked.connect(self.download_translation_rule_package_template)
        package_actions = QHBoxLayout()
        package_actions.setSpacing(6)
        package_actions.addWidget(self.translation_rule_load_package_btn)
        package_actions.addWidget(self.translation_rule_package_manager_btn)
        package_actions.addStretch(1)
        package_actions.addWidget(self.translation_rule_download_package_btn)
        package_layout.addLayout(package_actions)
        self._configure_translation_status_label(self.translation_rule_package_status_label)
        package_layout.addWidget(self.translation_rule_package_status_label)
        sidebar_layout.addWidget(task_section)
        sidebar_layout.addWidget(detail_section)
        sidebar_layout.addWidget(package_section)

        preview_section, preview_layout = self._create_translation_sidebar_section(
            sidebar,
            "translationPreviewSection",
            "02",
            "生成并校验 Diff",
            "读取接口并生成修改预览",
        )
        self.translation_rule_config_btn = PushButton("执行配置", self)
        self.translation_rule_config_btn.setToolTip("选择语言、模块、销售属性策略和上线写入策略。")
        self.translation_rule_config_btn.clicked.connect(self.open_translation_rule_config_dialog)
        self.translation_rule_generate_btn = PrimaryPushButton("生成Diff", self)
        self.translation_rule_generate_btn.setObjectName("translationPrimaryAction")
        self.translation_rule_generate_btn.setToolTip("读取翻译件接口内容，并按模板生成待确认的 Diff。")
        self.translation_rule_generate_btn.clicked.connect(self.start_translation_rule_preview)
        preview_actions = QHBoxLayout()
        preview_actions.addWidget(self.translation_rule_config_btn)
        preview_actions.addWidget(self.translation_rule_generate_btn)
        preview_layout.addLayout(preview_actions)
        runtime_inputs = QHBoxLayout()
        runtime_inputs.addWidget(BodyLabel("请求间隔"))
        self.translation_request_interval_edit = LineEdit(self)
        self.translation_request_interval_edit.setText(str(CTRIP_REQUEST_INTERVAL_SECONDS))
        self.translation_request_interval_edit.setFixedWidth(60)
        self.translation_request_interval_edit.setToolTip("每次翻译件接口请求之间等待的秒数。")
        runtime_inputs.addWidget(self.translation_request_interval_edit)
        runtime_inputs.addWidget(BodyLabel("秒"))
        runtime_inputs.addWidget(BodyLabel("并行数"))
        self.translation_parallel_requests_edit = LineEdit(self)
        self.translation_parallel_requests_edit.setText(str(DEFAULT_PARALLEL_REQUESTS))
        self.translation_parallel_requests_edit.setFixedWidth(54)
        self.translation_parallel_requests_edit.setToolTip(f"翻译读取/写入接口并行请求数，范围 1-{MAX_PARALLEL_REQUESTS}。")
        runtime_inputs.addWidget(self.translation_parallel_requests_edit)
        runtime_inputs.addStretch(1)
        preview_layout.addLayout(runtime_inputs)

        delivery_section, delivery_layout = self._create_translation_sidebar_section(
            sidebar,
            "translationDeliverySection",
            "03",
            "写入与交付",
            "确认后传出并保留报告入口",
        )
        self.translation_table_prev_btn = PushButton("前一表格", self)
        self.translation_table_prev_btn.setToolTip("回到上一份翻译结果表格。")
        self.translation_table_prev_btn.clicked.connect(lambda: self.restore_translation_table_history(-1))
        self.translation_table_next_btn = PushButton("后一表格", self)
        self.translation_table_next_btn.setToolTip("前进到后一份翻译结果表格。")
        self.translation_table_next_btn.clicked.connect(lambda: self.restore_translation_table_history(1))
        self.translation_rule_apply_btn = PushButton("确认传出", self)
        self.translation_rule_apply_btn.setObjectName("translationApplyAction")
        self.translation_rule_apply_btn.setStyleSheet("font-weight: 600;")
        self.translation_rule_apply_btn.setToolTip("将当前 pending Diff 写入翻译件接口。")
        self.translation_rule_apply_btn.clicked.connect(self.start_apply_translations)
        self.translation_rule_export_btn = PushButton("导出翻译报告", self)
        self.translation_rule_export_btn.setToolTip("导出当前 Diff、写入结果和错误信息报告。")
        self.translation_rule_export_btn.clicked.connect(self.export_translation_report)
        self.translation_rule_stop_btn = PushButton("停止", self)
        self.translation_rule_stop_btn.setToolTip("请求当前翻译任务在安全边界停止。")
        self.translation_rule_stop_btn.clicked.connect(self.stop_translation_work)
        self.translation_reset_btn = PushButton("重置程序", self)
        self.translation_reset_btn.setToolTip("清空翻译件管理页的模板、表格、日志和状态。")
        self.translation_reset_btn.clicked.connect(self.reset_translation_workspace)
        self.translation_status_label = BodyLabel("就绪")
        self.translation_status_label.setMinimumWidth(80)
        self.translation_status_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        for button in [
            self.translation_table_prev_btn,
            self.translation_table_next_btn,
            self.translation_rule_apply_btn,
            self.translation_rule_export_btn,
            self.translation_rule_stop_btn,
            self.translation_reset_btn,
        ]:
            button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.translation_status_label.setVisible(False)
        delivery_grid = QGridLayout()
        delivery_grid.setContentsMargins(0, 0, 0, 0)
        delivery_grid.setHorizontalSpacing(6)
        delivery_grid.setVerticalSpacing(4)
        delivery_grid.addWidget(self.translation_rule_apply_btn, 0, 0)
        delivery_grid.addWidget(self.translation_rule_export_btn, 0, 1)
        delivery_grid.addWidget(self.translation_rule_stop_btn, 0, 2)
        delivery_layout.addLayout(delivery_grid)
        sidebar_layout.addWidget(preview_section)
        sidebar_layout.addWidget(delivery_section)
        sidebar_layout.addStretch(1)
        for button in sidebar.findChildren(QPushButton):
            button.setFixedHeight(24)

        self.translation_rule_summary_label = BodyLabel("")
        self.translation_rule_summary_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.translation_rule_summary_label.setVisible(False)
        self._set_translation_rule_summary_text()
        self.refresh_translation_rule_template_statuses()

        self.translation_table = QTableView(self)
        self.translation_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.translation_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._setup_translation_table()
        self.translation_table.selectionModel().selectionChanged.connect(
            lambda _selected, _deselected: self.show_translation_result_detail(
                self.translation_table,
                self.translation_result_model,
                self.translation_detail_text,
            )
        )
        self.translation_table.doubleClicked.connect(
            lambda _index: self.open_translation_result_preview(
                self.translation_table,
                self.translation_result_model,
                self.translation_snapshots,
                self.translation_result_model.rows,
            )
        )
        log_panel = self._panel("运行日志")
        self.translation_log_text = PlainTextEdit(self)
        self.translation_log_text.setObjectName("translationLogText")
        self.translation_log_text.setReadOnly(True)
        self.translation_log_text.document().setMaximumBlockCount(MAX_LOG_BLOCKS)
        log_panel.layout().addWidget(self.translation_log_text)

        detail_panel = self._panel("选中项翻译详情 / Diff")
        self.translation_detail_text = PlainTextEdit(self)
        self.translation_detail_text.setObjectName("translationDetailText")
        self.translation_detail_text.setReadOnly(True)
        detail_panel.layout().addWidget(self.translation_detail_text)

        results_pane = QFrame(main_splitter)
        results_pane.setObjectName("translationResultsPane")
        results_pane.setFrameShape(QFrame.Shape.StyledPanel)
        results_layout = QVBoxLayout(results_pane)
        results_layout.setContentsMargins(6, 6, 6, 6)
        results_layout.setSpacing(5)

        results_header = QHBoxLayout()
        results_header.addWidget(BodyLabel("04", results_pane))
        results_header.addWidget(BodyLabel("翻译结果预览", results_pane))
        results_header.addWidget(BodyLabel("单击查看译文差异，双击打开完整翻译预览", results_pane))
        results_header.addStretch(1)
        results_header.addWidget(self.translation_table_prev_btn)
        results_header.addWidget(self.translation_table_next_btn)
        results_header.addWidget(self.translation_reset_btn)
        results_layout.addLayout(results_header)

        results_splitter = QSplitter(Qt.Orientation.Vertical, results_pane)
        results_splitter.setObjectName("translationResultsSplitter")
        results_layout.addWidget(results_splitter, 1)
        results_splitter.addWidget(self.translation_table)

        log_detail_splitter = QSplitter(Qt.Orientation.Horizontal, results_pane)
        log_detail_splitter.setObjectName("translationLogDetailSplitter")
        results_splitter.addWidget(log_detail_splitter)
        log_detail_splitter.addWidget(log_panel)
        log_detail_splitter.addWidget(detail_panel)
        log_detail_splitter.setStretchFactor(0, 1)
        log_detail_splitter.setStretchFactor(1, 1)
        results_splitter.setStretchFactor(0, 3)
        results_splitter.setStretchFactor(1, 1)
        results_splitter.setSizes([600, 180])

        main_splitter.addWidget(results_pane)
        results_pane.setMinimumWidth(480)
        main_splitter.setStretchFactor(0, 0)
        main_splitter.setStretchFactor(1, 1)
        main_splitter.setSizes([390, 1000])
        self._apply_translation_workbench_theme()
        return tab

    def _setup_translation_table(self) -> None:
        self.translation_result_model = TranslationResultTableModel(self.translation_results, self)
        self.translation_table.setModel(self.translation_result_model)
        self.translation_table.setSortingEnabled(False)
        widths = [120, 100, 150, 170, 260, 260, 70, 180, 120, 420, 80]
        for index, width in enumerate(widths):
            self.translation_table.setColumnWidth(index, width)
        self.translation_table.setAlternatingRowColors(True)
        self.translation_table.setWordWrap(False)
        self.translation_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.translation_table.horizontalHeader().setStretchLastSection(False)
        self.translation_table.verticalHeader().setVisible(False)
        apply_table_readable_style(self.translation_table)

    def _check_dependencies(self) -> None:
        if openpyxl is None:
            self.log("缺少 openpyxl。请运行：python3 -m pip install -r requirements.txt")
        if not QFLUENT_AVAILABLE:
            self.log("缺少 PyQt-Fluent-Widgets，当前使用 PyQt6 原生组件降级显示。请运行：python3 -m pip install -r requirements.txt")

    def _apply_app_settings(self, settings: AppSettings) -> None:
        self.template_path.setText(settings.product_template_path)
        self.request_interval_edit.setText(interval_text(settings.product_request_interval_seconds))
        self.parallel_requests_edit.setText(str(clamp_parallel_requests_value(settings.product_parallel_requests)))
        self.product_runtime_settings.update(settings.product_request_interval_seconds, settings.product_parallel_requests)
        self.export_price_check.setChecked(bool(settings.export_price))
        self.export_connection_check.setChecked(bool(settings.export_connection))
        self.export_intro_check.setChecked(bool(settings.export_intro))

        self.product_image_request_interval_edit.setText(interval_text(settings.product_image_request_interval_seconds))
        self.product_image_parallel_requests_edit.setText(str(clamp_parallel_requests_value(settings.product_image_parallel_requests)))
        self.product_image_runtime_settings.update(settings.product_image_request_interval_seconds, settings.product_image_parallel_requests)

        self.translation_rule_runtime.task_path = settings.translation_task_path
        self.translation_rule_runtime.detail_template_path = settings.translation_detail_template_path
        self.translation_rule_runtime.package_template_path = settings.translation_package_template_path
        self.translation_rule_runtime.config = translation_execution_config_from_dict(
            translation_execution_config_to_dict(settings.translation_execution_config)
        )
        self.translation_request_interval_edit.setText(interval_text(settings.translation_request_interval_seconds))
        self.translation_parallel_requests_edit.setText(str(clamp_parallel_requests_value(settings.translation_parallel_requests)))
        self.translation_runtime_settings.update(settings.translation_request_interval_seconds, settings.translation_parallel_requests)
        self._set_translation_rule_summary_text()
        self.refresh_translation_rule_template_statuses()

    def _collect_app_settings(self) -> AppSettings:
        return AppSettings(
            product_template_path=self.template_path.text().strip(),
            product_request_interval_seconds=clamp_request_interval_seconds(self.request_interval_edit.text().strip()),
            product_parallel_requests=clamp_parallel_requests_value(self.parallel_requests_edit.text().strip()),
            export_price=self.export_price_check.isChecked(),
            export_connection=self.export_connection_check.isChecked(),
            export_intro=self.export_intro_check.isChecked(),
            translation_task_path=self.translation_rule_runtime.task_path,
            translation_detail_template_path=self.translation_rule_runtime.detail_template_path,
            translation_package_template_path=self.translation_rule_runtime.package_template_path,
            translation_request_interval_seconds=clamp_request_interval_seconds(self.translation_request_interval_edit.text().strip()),
            translation_parallel_requests=clamp_parallel_requests_value(self.translation_parallel_requests_edit.text().strip()),
            translation_execution_config=translation_execution_config_from_dict(
                translation_execution_config_to_dict(self.translation_rule_runtime.config)
            ),
            product_image_request_interval_seconds=clamp_request_interval_seconds(self.product_image_request_interval_edit.text().strip()),
            product_image_parallel_requests=clamp_parallel_requests_value(self.product_image_parallel_requests_edit.text().strip()),
        )

    def persist_app_settings(self) -> None:
        try:
            self.app_settings = self._collect_app_settings()
            save_app_settings(self.app_settings)
        except Exception as exc:
            self._active_log(f"保存设置失败：{exc}")

    def _connect_runtime_settings_edits(self) -> None:
        self.request_interval_edit.editingFinished.connect(lambda: self._apply_runtime_request_settings("product"))
        self.parallel_requests_edit.editingFinished.connect(lambda: self._apply_runtime_request_settings("product"))
        self.product_image_request_interval_edit.editingFinished.connect(lambda: self._apply_runtime_request_settings("image"))
        self.product_image_parallel_requests_edit.editingFinished.connect(lambda: self._apply_runtime_request_settings("image"))
        self.translation_request_interval_edit.editingFinished.connect(lambda: self._apply_runtime_request_settings("translation"))
        self.translation_parallel_requests_edit.editingFinished.connect(lambda: self._apply_runtime_request_settings("translation"))

    def _runtime_request_controls(self, area: str) -> tuple[QLineEdit, QLineEdit, RuntimeRequestSettings, Callable[[str], None], str]:
        if area == "translation":
            return (
                self.translation_request_interval_edit,
                self.translation_parallel_requests_edit,
                self.translation_runtime_settings,
                self.translation_log,
                "翻译",
            )
        if area == "image":
            return (
                self.product_image_request_interval_edit,
                self.product_image_parallel_requests_edit,
                self.product_image_runtime_settings,
                self.product_image_log,
                "产品图片",
            )
        return (
            self.request_interval_edit,
            self.parallel_requests_edit,
            self.product_runtime_settings,
            self.log,
            "产品",
        )

    def _apply_runtime_request_settings(self, area: str, quiet: bool = False) -> bool:
        interval_edit, parallel_edit, runtime_settings, log_func, label = self._runtime_request_controls(area)
        request_interval = self._request_interval_from_edit_or_warn(interval_edit)
        if request_interval is None:
            return False
        parallel_requests = self._parallel_requests_or_warn(parallel_edit)
        if parallel_requests is None:
            return False
        before = runtime_settings.snapshot()
        after = runtime_settings.update(request_interval, parallel_requests)
        self.persist_app_settings()
        if not quiet and before != after:
            log_func(f"{label}运行参数已更新：请求间隔={interval_text(after.request_interval_seconds)} 秒，并行请求数={after.parallel_requests}")
        return True

    def closeEvent(self, event: Any) -> None:
        components = (
            getattr(self, "product_image_workspace", None),
            getattr(self, "product_edit_component", None),
            getattr(self, "docking_config_widget", None),
        )
        for component in components:
            if component is not None and not component.request_close(self):
                event.ignore()
                return
        for component in components:
            if component is not None:
                component.shutdown()
        for area in ("translation", "product_edit", "product_images", "docking_config"):
            self.write_gate.release(area)
        self.persist_app_settings()
        super().closeEvent(event)

    def changeEvent(self, event: Any) -> None:
        super().changeEvent(event)
        if QT_IMPORT_ERROR is None and event.type() == QEvent.Type.PaletteChange:
            coordinator = getattr(self, "_theme_coordinator", None)
            if coordinator is None:
                QTimer.singleShot(0, self._apply_global_theme)
            elif not coordinator.is_self_applied_palette():
                coordinator.schedule_refresh()

    def choose_template(self) -> None:
        path, _selected = get_open_excel_file_name(self, "选择回填模板")
        if path:
            self.template_path.setText(path)
            self.persist_app_settings()
            self.load_template()

    def export_edit_template(self) -> None:
        if not self.preloaded_products:
            QMessageBox.warning(self, "提示", "请先输入产品ID并预载")
            return
        spec = product_workbench_spec(self.active_product_workbench)
        default = default_download_path(f"{spec.template_filename}_{now_stamp()}.xlsx")
        path, _selected = get_save_report_file_name(self, "导出修改模板", default, "Excel (*.xlsx)")
        if not path:
            return
        if not path.lower().endswith(".xlsx"):
            path += ".xlsx"
        try:
            build_edit_template_workbook(
                path,
                self.preloaded_products,
                include_price=self.export_price_check.isChecked(),
                include_connection=self.export_connection_check.isChecked(),
                include_intro=self.export_intro_check.isChecked(),
                workbench=self.active_product_workbench,
            )
            self.log(f"已导出修改模板：{path}")
            QMessageBox.information(self, "完成", f"已导出修改模板：{path}")
        except Exception as exc:
            QMessageBox.critical(self, "导出失败", str(exc))
            self.log(f"导出修改模板失败：{exc}")

    def load_template(self) -> None:
        path = self.template_path.text().strip()
        if not path:
            QMessageBox.warning(self, "提示", "请选择回填模板")
            return
        self.persist_app_settings()
        self.submit_audit_candidate_product_ids = []
        self._start_product_worker("preview", template_path=path)

    def start_preload_products(self) -> None:
        text = self.ask_product_ids_text()
        if text is None:
            return
        try:
            product_ids = parse_product_ids(text)
        except Exception as exc:
            QMessageBox.critical(self, "产品ID无效", str(exc))
            return
        self.preloaded_products.clear()
        self.pending_diff_plans.clear()
        self.last_saved_products.clear()
        self.submit_audit_candidate_product_ids = []
        self._sync_active_product_workbench_state()
        self._start_product_worker("preload", product_ids=product_ids)

    def ask_product_ids_text(self) -> str | None:
        dialog = ProductIdsDialog(self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return None
        return dialog.value()

    def start_refresh_auth(self) -> None:
        if self.worker_thread and self.worker_thread.is_alive():
            QMessageBox.warning(self, "提示", "任务正在运行")
            return
        self._set_auth_status_text("登录态：等待 Edge/Chrome 登录…")
        self.results = []
        self.product_result_order = {}
        self.product_error_count = 0
        self.product_verify_failed_count = 0
        self.product_pressure_text = ""
        self._sync_active_product_workbench_state()
        self._clear_table()
        self.detail_text.clear()
        self.stop_event.clear()
        self.active_worker_area = "product"
        self.worker_thread = threading.Thread(target=self._run_refresh_auth, daemon=True)
        self._set_running(True)
        self.worker_thread.start()

    def _run_refresh_auth(self) -> None:
        try:
            path, loaded, source = self._refresh_auth_for_area("product")
            result = ResultRow(product_id="", package_name="", status="auth_refreshed", message=f"已刷新登录态：来源={source}，cookie={loaded} 个，写入 {path}")
            auth_status = f"登录态：{source} 登录态有效" if source in {"Edge", "Chrome"} else "登录态：有效"
            self.out_queue.put(("auth_status", auth_status))
            self.out_queue.put(("result", result))
            self.out_queue.put(("done", [result]))
        except Exception as exc:
            self.out_queue.put(("auth_status", "登录态：刷新失败"))
            self.out_queue.put(("fatal", str(exc)))

    def start_apply(self) -> None:
        pending_count = sum(1 for plan in self.pending_diff_plans if plan.status == "pending")
        if pending_count <= 0:
            QMessageBox.warning(self, "提示", "没有 pending diff 可传出，请先加载回填模板并预览Diff")
            return
        product_count = len({plan.product_id for plan in self.pending_diff_plans if plan.status == "pending"})
        answer = QMessageBox.question(
            self,
            "确认传出修改",
            f"将传出 {pending_count} 个字段 diff，涉及 {product_count} 个产品。\n传出前会重新读取接口并拒绝 stale 项。是否继续？",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self._start_product_worker("apply")

    def start_submit_audit(self) -> None:
        product_ids = select_submit_audit_product_ids(
            self.submit_audit_candidate_product_ids,
            self.last_saved_products,
            self.product_result_order,
        )
        if not product_ids:
            QMessageBox.warning(self, "提示", "没有当前预览/预载产品可提交审核")
            return
        if self.submit_audit_candidate_product_ids:
            message = (
                f"将强行提交审核当前预览/预载的 {len(product_ids)} 个产品，"
                "无论是否发生修改或是否本轮传出成功：\n"
                f"{', '.join(product_ids)}\n是否继续？"
            )
        else:
            message = f"将提交审核 {len(product_ids)} 个本轮传出成功的产品：\n{', '.join(product_ids)}\n是否继续？"
        answer = QMessageBox.question(self, "确认提交审核", message)
        if answer != QMessageBox.StandardButton.Yes:
            return
        self._start_product_worker("submit", product_ids=product_ids)

    def _start_product_worker(self, mode: str, product_ids: list[str] | None = None, template_path: str = "") -> None:
        if self.worker_thread and self.worker_thread.is_alive():
            QMessageBox.warning(self, "提示", "任务正在运行")
            return
        self.active_worker_area = "product"
        self._activate_product_workbench(self.active_product_workbench)
        if not self._ensure_auth_ready(self._auth_validation_product_id("product", product_ids), "product"):
            return
        request_interval = self._request_interval_seconds_or_warn()
        if request_interval is None:
            return
        parallel_requests = self._parallel_requests_or_warn(self.parallel_requests_edit)
        if parallel_requests is None:
            return
        if not self._apply_runtime_request_settings("product", quiet=True):
            return
        self.persist_app_settings()
        self.active_product_mode = mode
        if mode != "submit":
            self.results = []
        if mode in {"preload", "preview"}:
            self.submit_audit_candidate_product_ids = []
        if mode == "preload":
            self.product_result_order = product_order_map(product_ids or [])
        elif mode != "submit":
            self.product_result_order = {}
        self.product_pressure_text = ""
        self._sync_active_product_workbench_state()
        if mode != "submit":
            self._clear_table()
            self.detail_text.clear()
        self.stop_event.clear()
        worker = ProductWorkflowWorker(
            self.out_queue,
            self.stop_event,
            self.preloaded_products,
            self.pending_diff_plans,
            self.last_saved_products,
            request_interval_seconds=request_interval,
            parallel_requests=parallel_requests,
            runtime_settings=self.product_runtime_settings,
            stats_recorder=self._queue_request_stat,
            workbench=self.active_product_workbench,
        )
        if mode == "preload":
            target = lambda: worker.run_preload(product_ids or [])
        elif mode == "preview":
            self.pending_diff_plans.clear()
            target = lambda: worker.run_preview_template(template_path)
        elif mode == "apply":
            target = worker.run_apply_pending
        elif mode == "submit":
            target = lambda: worker.run_submit_saved(product_ids or [])
        else:
            raise RuntimeError(f"未知任务模式：{mode}")
        self.worker_thread = threading.Thread(target=target, daemon=True)
        self._set_running(True)
        self.worker_thread.start()

    def _request_interval_seconds_or_warn(self) -> float | None:
        return self._request_interval_from_edit_or_warn(self.request_interval_edit)

    def _translation_request_interval_seconds_or_warn(self) -> float | None:
        return self._request_interval_from_edit_or_warn(self.translation_request_interval_edit)

    def _parallel_requests_or_warn(self, edit: QLineEdit) -> int | None:
        text = edit.text().strip()
        try:
            value = int(text)
        except Exception:
            QMessageBox.warning(self, "并行请求数无效", f"并行请求数必须是 1-{MAX_PARALLEL_REQUESTS} 的整数")
            return None
        if value < 1 or value > MAX_PARALLEL_REQUESTS:
            QMessageBox.warning(self, "并行请求数无效", f"并行请求数必须在 1-{MAX_PARALLEL_REQUESTS} 之间")
            return None
        edit.setText(str(value))
        return value

    def _request_interval_from_edit_or_warn(self, edit: QLineEdit) -> float | None:
        text = edit.text().strip()
        try:
            value = float(text)
        except Exception:
            QMessageBox.warning(self, "请求间隔无效", "请求间隔秒必须是数字，例如 1 或 0.5")
            return None
        if value < MIN_REQUEST_INTERVAL_SECONDS or value > MAX_REQUEST_INTERVAL_SECONDS:
            QMessageBox.warning(
                self,
                "请求间隔无效",
                f"请求间隔秒必须在 {MIN_REQUEST_INTERVAL_SECONDS:g}-{MAX_REQUEST_INTERVAL_SECONDS:g} 之间",
            )
            return None
        normalized = str(value).rstrip("0").rstrip(".")
        edit.setText(normalized or "0")
        return value

    def _auth_validation_product_id(self, area: str, product_ids: list[str] | None = None) -> str:
        if product_ids:
            return str(product_ids[0])
        if area == "translation":
            if self.pending_translation_plans:
                return str(self.pending_translation_plans[0].product_id)
            if self.translation_snapshots:
                return next(iter(self.translation_snapshots.keys()))
            task_path = self.translation_rule_runtime.task_path
            if task_path:
                try:
                    tasks = translation_rules.load_translation_rule_tasks(task_path)
                    if tasks:
                        return tasks[0].product_id
                except Exception:
                    return ""
            return ""
        if self.pending_diff_plans:
            return str(self.pending_diff_plans[0].product_id)
        if self.preloaded_products:
            return next(iter(self.preloaded_products.keys()))
        for row in self.results:
            if row.product_id:
                return str(row.product_id)
        return ""

    def _set_auth_status_text(self, text: str) -> None:
        for label_name in ("product_auth_status_label", "translation_auth_status_label"):
            label = getattr(self, label_name, None)
            if label is not None:
                label.setText(text)
        docking_widget = getattr(self, "docking_config_widget", None)
        docking_label = getattr(docking_widget, "product_auth_status_label", None)
        if docking_label is not None:
            docking_label.setText(text)

    def _refresh_auth_for_area(self, area: str, product_id: str = "") -> tuple[Path, int, str]:
        validation_product_id = product_id or self._auth_validation_product_id(area)
        auth_area = "translation" if area == "translation" and validation_product_id else "product"
        result = refresh_plain_auth(
            validation_product_id=validation_product_id,
            area=auth_area,
        )
        self.last_validated_auth_digest = cookie_digest(read_plain_cookie())
        return result

    def _ensure_auth_ready(self, product_id: str = "", area: str = "product") -> bool:
        product_id = str(product_id or "").strip()
        auth_area = "translation" if area == "translation" and product_id else "product"
        existing_cookie = read_plain_cookie()
        if existing_cookie:
            try:
                if not has_ctrip_login_cookie(existing_cookie):
                    raise RuntimeError("未检测到携程后台登录 Cookie")
                if product_id:
                    validate_plain_auth_cookie(existing_cookie, product_id, auth_area)
                self._set_auth_status_text("登录态：有效")
                return True
            except Exception as exc:
                self._active_log(f"当前登录态校验失败：{exc}")
        message = (
            "未找到可用 Ctrip 登录态。\n\n"
            "请先在 Edge/Chrome 登录 Ctrip，然后点击“刷新登录态”。\n"
            f"登录态将保存到：{PLAIN_COOKIE_FILE}"
        )
        if self.active_worker_area == "translation":
            self._set_translation_runtime_status_text("等待登录态")
        else:
            self.status_label.setText(self._replace_request_stats("等待登录态", "product"))
        self._set_auth_status_text("登录态：需要刷新")
        self._active_log(message)
        QMessageBox.warning(self, "需要登录态", message)
        return False

    def start_startup_auth_check(self) -> None:
        if self.startup_auth_check_thread and self.startup_auth_check_thread.is_alive():
            return

        def run_check() -> None:
            self.out_queue.put(("startup_auth_check", check_saved_plain_auth()))

        self.startup_auth_check_thread = threading.Thread(target=run_check, daemon=True)
        self.startup_auth_check_thread.start()

    def _handle_startup_auth_result(self, result: AuthCheckResult) -> None:
        try:
            current_digest = cookie_digest(read_plain_cookie())
        except Exception:
            current_digest = ""
        if current_digest != result.cookie_digest:
            return
        if current_digest and current_digest == self.last_validated_auth_digest:
            return
        if result.status == "valid":
            self.last_validated_auth_digest = current_digest
            self._set_auth_status_text("登录态：有效")
            return
        if result.status == "missing":
            title = "需要登录态"
            self._set_auth_status_text("登录态：未刷新")
            message = (
                "未找到 Ctrip 登录态。\n\n"
                "请先在 Edge/Chrome 登录 Ctrip，然后点击“刷新登录态”。\n"
                f"登录态将保存到：{PLAIN_COOKIE_FILE}"
            )
        elif result.status == "invalid":
            title = "登录态已失效"
            self._set_auth_status_text("登录态：已失效")
            message = (
                "当前保存的 Ctrip 登录态已失效。\n\n"
                "请重新登录 Edge/Chrome，然后点击“刷新登录态”。\n"
                f"登录态文件：{PLAIN_COOKIE_FILE}"
            )
        else:
            title = "暂时无法校验登录态"
            self._set_auth_status_text("登录态：校验失败")
            message = (
                "程序启动时暂时无法校验 Ctrip 登录态，请检查网络后重试。\n\n"
                f"校验信息：{result.message or '未知错误'}"
            )
        self._active_log(message)
        QMessageBox.warning(self, title, message)

    def show_cdp_guide(self) -> None:
        clipboard_text = f"Edge：{EDGE_REMOTE_DEBUGGING_URL}\nChrome：{CHROME_REMOTE_DEBUGGING_URL}"
        QGuiApplication.clipboard().setText(clipboard_text)
        self.log(CDP_GUIDE_TEXT)
        QMessageBox.information(self, "Edge/Chrome CDP 设置", CDP_GUIDE_TEXT + "\n\n已把 Edge 与 Chrome 的远程调试地址复制到剪贴板，请将对应地址粘贴到相应浏览器打开。")

    def stop_work(self) -> None:
        self.stop_event.set()
        self.status_label.setText(self._replace_request_stats("正在停止...", "product"))
        self.log("已请求停止，当前产品处理完后退出")

    def stop_translation_work(self) -> None:
        self.stop_event.set()
        self._set_translation_runtime_status_text("正在停止...")
        self.translation_log("已请求停止，当前翻译语言处理完后退出")

    def export_report(self) -> None:
        if not self.results:
            QMessageBox.warning(self, "提示", "没有可导出的结果")
            return
        spec = product_workbench_spec(self.active_product_workbench)
        default = default_download_path(f"{spec.report_filename_prefix}_{now_stamp()}.xlsx")
        path, selected = get_save_report_file_name(self, "导出结果报告", default, "Excel (*.xlsx);;CSV (*.csv)")
        if not path:
            return
        if selected.startswith("CSV") and not path.lower().endswith(".csv"):
            path += ".csv"
        elif not path.lower().endswith((".xlsx", ".csv")):
            path += ".xlsx"
        try:
            write_report(path, self.results, self.product_result_order)
            self.log(f"已导出报告：{path}")
            QMessageBox.information(self, "完成", f"已导出报告：{path}")
        except Exception as exc:
            QMessageBox.critical(self, "导出失败", str(exc))












    def choose_translation_rule_task(self) -> None:
        path, _selected = get_open_excel_file_name(self, "选择任务模板")
        if path:
            self.load_translation_rule_task_path(path)

    def choose_translation_rule_detail_template(self) -> None:
        path, _selected = get_open_excel_file_name(self, "选择详情模板")
        if path:
            self.load_translation_rule_detail_path(path)

    def choose_translation_rule_package_template(self) -> None:
        path, _selected = get_open_excel_file_name(self, "选择套餐规格模板")
        if path:
            self.load_translation_rule_package_path(path)

    def set_translation_rule_status_label(self, label: QLabel, path: str, loaded_text: str, missing_text: str) -> None:
        colors = translation_workbench_palette(label)
        if path:
            text = f"{loaded_text}: {os.path.basename(path)}"
            label.setText(text)
            label.setToolTip(text)
            label.setProperty("translationTemplateLoaded", True)
            label.setStyleSheet(f"color: {colors['loaded']};")
        else:
            label.setText(missing_text)
            label.setToolTip("")
            label.setProperty("translationTemplateLoaded", False)
            label.setStyleSheet(f"color: {colors['muted']};")

    def refresh_translation_rule_template_statuses(self) -> None:
        runtime = self.translation_rule_runtime
        if not hasattr(self, "translation_rule_task_status_label"):
            return
        self.set_translation_rule_status_label(self.translation_rule_task_status_label, runtime.task_path, "已加载", "未加载任务模板")
        self.set_translation_rule_status_label(self.translation_rule_detail_status_label, runtime.detail_template_path, "已加载", "未加载详情模板")
        self.set_translation_rule_status_label(self.translation_rule_package_status_label, runtime.package_template_path, "已加载", "未加载规格模板")
        for label in (
            self.translation_rule_task_status_label,
            self.translation_rule_detail_status_label,
            self.translation_rule_package_status_label,
        ):
            label.setToolTip(label.text())

    def load_translation_rule_task_path(self, path: str) -> None:
        try:
            tasks = translation_rules.load_translation_rule_tasks(path)
        except Exception as exc:
            self.translation_rule_runtime.task_path = ""
            self.refresh_translation_rule_template_statuses()
            self.persist_app_settings()
            QMessageBox.critical(self, "任务模板加载失败", str(exc))
            self.translation_log(f"任务模板加载失败：{exc}")
            return
        self.translation_rule_runtime.task_path = path
        self.refresh_translation_rule_template_statuses()
        self.persist_app_settings()
        self.translation_log(f"任务模板已加载：{path} | 任务={len(tasks)}")
        self.translation_detail_text.setPlainText(f"任务模板\n路径: {path}\n任务数: {len(tasks)}")

    def load_translation_rule_detail_path(self, path: str) -> None:
        try:
            data = translation_rules.load_detail_template_xlsx(path)
        except Exception as exc:
            self.translation_rule_runtime.detail_template_path = ""
            self.refresh_translation_rule_template_statuses()
            self.persist_app_settings()
            QMessageBox.critical(self, "详情模板加载失败", str(exc))
            self.translation_log(f"详情模板加载失败：{exc}")
            return
        self.translation_rule_runtime.detail_template_path = path
        self.refresh_translation_rule_template_statuses()
        self.persist_app_settings()
        self.translation_log(f"详情模板已加载：{path} | 语言={len(data)}")
        self.translation_detail_text.setPlainText(f"详情模板\n路径: {path}\n语言数: {len(data)}")

    def load_translation_rule_package_path(self, path: str) -> None:
        try:
            data = translation_rules.load_package_template_xlsx(path)
        except Exception as exc:
            self.translation_rule_runtime.package_template_path = ""
            self.refresh_translation_rule_template_statuses()
            self.persist_app_settings()
            QMessageBox.critical(self, "规格模板加载失败", str(exc))
            self.translation_log(f"规格模板加载失败：{exc}")
            return
        self.translation_rule_runtime.package_template_path = path
        self.refresh_translation_rule_template_statuses()
        self.persist_app_settings()
        script_count = len(data.get("scripts") or {})
        self.translation_log(f"规格模板已加载：{path} | 脚本={script_count}")
        self.translation_detail_text.setPlainText(f"规格模板\n路径: {path}\n脚本数: {script_count}")

    def save_translation_rule_template_file(self, title: str, default_name: str, writer: Callable[[str], None]) -> str:
        path, _selected = get_save_report_file_name(self, title, default_download_path(default_name), "Excel (*.xlsx)")
        if not path:
            return ""
        if not path.lower().endswith(".xlsx"):
            path += ".xlsx"
        try:
            writer(path)
        except Exception as exc:
            QMessageBox.critical(self, "下载失败", str(exc))
            self.translation_log(f"下载模板失败：{exc}")
            return ""
        self.translation_log(f"已下载模板：{path}")
        QMessageBox.information(self, "下载完成", f"模板已保存到：\n{path}")
        return path

    def download_translation_rule_task_template(self) -> None:
        path = self.save_translation_rule_template_file("下载任务模板Excel", "translation_rule_task_template.xlsx", translation_rules.create_translation_task_template_xlsx)
        if path:
            self.load_translation_rule_task_path(path)

    def download_translation_rule_detail_template(self) -> None:
        path = self.save_translation_rule_template_file("下载详情模板Excel", "detail_templates.xlsx", lambda target: translation_rules.create_detail_template_xlsx(target, translation_rules.ALL_TEMPLATE_LANGUAGES))
        if path:
            self.load_translation_rule_detail_path(path)

    def download_translation_rule_package_template(self) -> None:
        path = self.save_translation_rule_template_file("下载规格模板Excel", "package_templates.xlsx", translation_rules.create_package_template_xlsx)
        if path:
            self.load_translation_rule_package_path(path)

    def edit_translation_rule_task_template(self) -> None:
        path = self.translation_rule_runtime.task_path
        if not path or not os.path.exists(path):
            QMessageBox.warning(self, "提示", "请先加载任务模板文件")
            return
        try:
            open_with_system_default(path)
            self.translation_log(f"已打开任务模板：{path}")
        except Exception as exc:
            QMessageBox.critical(self, "打开失败", str(exc))

    def open_translation_ops_manual(self) -> None:
        path = translation_ops_manual_path()
        if not path.exists():
            QMessageBox.warning(self, "提示", f"未找到操作手册：{path}")
            return
        try:
            open_with_system_default(str(path))
            self.translation_log(f"已打开操作手册：{path}")
        except Exception as exc:
            QMessageBox.critical(self, "打开失败", str(exc))

    def reload_translation_rule_task(self) -> None:
        path = self.translation_rule_runtime.task_path
        if not path:
            QMessageBox.warning(self, "提示", "请先加载任务模板文件")
            return
        self.load_translation_rule_task_path(path)

    def ensure_translation_rule_detail_template_path(self) -> str:
        path = self.translation_rule_runtime.detail_template_path
        if path and os.path.exists(path):
            return path
        answer = QMessageBox.question(self, "选择详情模板Excel", "当前未加载可用的详情模板Excel。\n\n点击 Yes 新建空白详情模板Excel；点击 No 选择已有 XLSX。")
        if answer == QMessageBox.StandardButton.Yes:
            path = self.save_translation_rule_template_file("新建详情模板Excel", "detail_templates.xlsx", lambda target: translation_rules.create_detail_template_xlsx(target, translation_rules.ALL_TEMPLATE_LANGUAGES))
            return path
        self.choose_translation_rule_detail_template()
        return self.translation_rule_runtime.detail_template_path

    def ensure_translation_rule_package_template_path(self) -> str:
        path = self.translation_rule_runtime.package_template_path
        if path and os.path.exists(path):
            return path
        answer = QMessageBox.question(self, "选择规格模板Excel", "当前未加载可用的规格模板Excel。\n\n点击 Yes 新建默认规格模板Excel；点击 No 选择已有 XLSX。")
        if answer == QMessageBox.StandardButton.Yes:
            path = self.save_translation_rule_template_file("新建规格模板Excel", "package_templates.xlsx", translation_rules.create_package_template_xlsx)
            return path
        self.choose_translation_rule_package_template()
        return self.translation_rule_runtime.package_template_path

    def open_translation_rule_detail_template_manager(self) -> None:
        path = self.ensure_translation_rule_detail_template_path()
        if not path:
            return
        try:
            data = translation_rules.load_detail_template_xlsx(path)
        except Exception as exc:
            QMessageBox.critical(self, "详情模板管理", str(exc))
            return
        self.translation_detail_template_viewer = TranslationDetailTemplateViewer(data, path, self)
        self.translation_detail_template_viewer.exec()

    def open_translation_rule_package_template_manager(self) -> None:
        path = self.ensure_translation_rule_package_template_path()
        if not path:
            return
        try:
            data = translation_rules.load_package_template_xlsx(path)
        except Exception as exc:
            QMessageBox.critical(self, "规格模板管理", str(exc))
            return
        self.translation_package_template_viewer = TranslationPackageTemplateViewer(data, path, self)
        self.translation_package_template_viewer.exec()

    def translation_rule_config_summary(self) -> str:
        config = self.translation_rule_runtime.config
        modules = [translation_rules.MODULE_LABELS.get(key, key) for key in config.selected_modules]
        mode = "保存并上线" if config.online else "仅保存不上线"
        if config.include_unopened_locales:
            mode += " | 含未开站语言"
        return f"语言 {len(config.selected_languages)} | 模块 {len(modules)} | 销售属性 {config.sales_attr_mode} | {mode}"

    def open_translation_rule_config_dialog(self) -> None:
        config = self.translation_rule_runtime.config
        dialog = QDialog(self)
        dialog.setObjectName("TranslationRuleConfigDialog")
        dialog.setWindowTitle("执行配置中心")
        dialog.resize(1280, 820)
        dialog.setMinimumSize(1120, 740)
        layout = QVBoxLayout(dialog)
        apply_translation_config_dialog_theme(dialog)
        title_label = BodyLabel("执行配置中心")
        title_label.setStyleSheet("font-weight: 600;")
        layout.addWidget(title_label)

        def wrap_tooltip(*lines: str) -> str:
            return "\n".join(line.strip() for line in lines if line.strip())

        def make_section(title: str, description: str = "") -> tuple[QFrame, QVBoxLayout]:
            section = QFrame(dialog)
            section.setObjectName("TranslationRuleConfigSection")
            section.setFrameShape(QFrame.Shape.StyledPanel)
            if description:
                section.setToolTip(description)
            section_layout = QVBoxLayout(section)
            section_layout.setContentsMargins(14, 12, 14, 12)
            section_layout.setSpacing(7)
            section_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
            title_widget = BodyLabel(title)
            title_widget.setStyleSheet("font-weight: 600; border: none; background: transparent;")
            if description:
                title_widget.setToolTip(description)
            section_layout.addWidget(title_widget)
            return section, section_layout

        def set_all_checks(checks: dict[str, QCheckBox], checked: bool) -> None:
            for cb in checks.values():
                cb.setChecked(checked)

        def style_choice_widget(widget: QWidget) -> None:
            widget.setStyleSheet("border: none; background: transparent;")

        splitter = QSplitter(Qt.Orientation.Horizontal, dialog)
        layout.addWidget(splitter, 1)

        left_pane = QWidget(splitter)
        left_pane.setObjectName("TranslationRuleConfigLeftPane")
        left_column = QVBoxLayout(left_pane)
        left_column.setContentsMargins(0, 0, 8, 0)
        left_column.setSpacing(12)

        right_pane = QWidget(splitter)
        right_pane.setObjectName("TranslationRuleConfigRightPane")
        right_column = QVBoxLayout(right_pane)
        right_column.setContentsMargins(8, 0, 0, 0)
        right_column.setSpacing(12)
        splitter.addWidget(left_pane)
        splitter.addWidget(right_pane)
        splitter.setStretchFactor(0, 5)
        splitter.setStretchFactor(1, 4)
        splitter.setSizes([720, 520])

        lang_tooltip = wrap_tooltip(
            "只处理勾选的语言站点。",
            "先请求 productTranslationAvailableLocales，映射语言组到 locale。",
            "随后请求 productTranslationList 读取翻译树。",
            "普通语言默认限制 operableLocales；勾选“同时传出未开站语言”后，空站点会先用同组完整译本补齐再仅保存。",
        )
        lang_section, lang_outer = make_section("执行语言", lang_tooltip)
        lang_button_bar = QHBoxLayout()
        lang_outer.addLayout(lang_button_bar)
        lang_checks: dict[str, QCheckBox] = {}
        select_all_lang_btn = PushButton("全选", dialog)
        deselect_all_lang_btn = PushButton("全不选", dialog)
        lang_button_bar.addWidget(select_all_lang_btn)
        lang_button_bar.addWidget(deselect_all_lang_btn)
        lang_button_bar.addStretch(1)
        lang_grid_widget = QWidget(dialog)
        lang_grid_widget.setObjectName("TranslationRuleConfigGridWidget")
        lang_outer.addWidget(lang_grid_widget)
        lang_grid = QGridLayout(lang_grid_widget)
        lang_grid.setContentsMargins(0, 0, 0, 0)
        lang_grid.setHorizontalSpacing(18)
        lang_grid.setVerticalSpacing(4)
        for index, lang_code in enumerate(translation_rules.ALL_TEMPLATE_LANGUAGES):
            cb = CheckBox(f"{lang_code.upper()} {translation_rules.LANGUAGE_LABELS.get(lang_code, '')}".strip(), dialog)
            style_choice_widget(cb)
            cb.setChecked(lang_code in config.selected_languages)
            cb.setToolTip(
                wrap_tooltip(
                    f"{lang_code.upper()} 语言组",
                    "映射到 productTranslationAvailableLocales 返回的 locale。",
                    "普通语言只处理可写站点；中文(新马)会匹配 zh-SG / zh-MY。",
                )
            )
            lang_checks[lang_code] = cb
            lang_grid.addWidget(cb, index // 4, index % 4)
        select_all_lang_btn.clicked.connect(lambda _checked=False: set_all_checks(lang_checks, True))
        deselect_all_lang_btn.clicked.connect(lambda _checked=False: set_all_checks(lang_checks, False))
        left_column.addWidget(lang_section, 3)

        module_tooltip = wrap_tooltip(
            "只执行勾选的字段和套餐动作。",
            "接口版不会操作网页表单。",
            "本地按模板生成目标文本 Diff。",
            "最终通过 productTranslationPush 提交完整 translationModules。",
        )
        module_section, module_outer = make_section("执行模块", module_tooltip)
        module_button_bar = QHBoxLayout()
        module_outer.addLayout(module_button_bar)
        select_all_module_btn = PushButton("全选", dialog)
        deselect_all_module_btn = PushButton("全不选", dialog)
        module_button_bar.addWidget(select_all_module_btn)
        module_button_bar.addWidget(deselect_all_module_btn)
        module_button_bar.addStretch(1)
        module_checks: dict[str, QCheckBox] = {}
        module_grid_widget = QWidget(dialog)
        module_grid_widget.setObjectName("TranslationRuleConfigGridWidget")
        module_outer.addWidget(module_grid_widget)
        module_grid = QGridLayout(module_grid_widget)
        module_grid.setContentsMargins(0, 0, 0, 0)
        module_grid.setHorizontalSpacing(18)
        module_grid.setVerticalSpacing(6)
        module_definitions = {
            "product_name": "产品名称",
            "mm_detail": "商品图文详情",
            "fee_include": "费用包含",
            "fee_exclude": "费用不包含",
            "usage": "使用方法",
            "description": "产品说明",
            "notice": "注意事项",
            "post_booking_reminder": "订后出行提醒",
            "operation_attention": "携程处理注意事项",
            "sales_property": "销售属性（大项）",
            "package_detail": "套餐规格详情",
            "package_quantity": "套餐规格量词",
        }
        module_tooltips = {
            "product_name": wrap_tooltip("生成产品名称目标文本。", "对应 productName。", "最终随完整 translationModules 写入。"),
            "mm_detail": wrap_tooltip("生成商品图文详情目标文本。", "对应 productDesc。", "接口版只写翻译树，不操作网页富文本编辑器。"),
            "fee_include": wrap_tooltip("使用固定/模板费用包含文案。", "对应 feeInclude。", "最终随 productTranslationPush 写入。"),
            "fee_exclude": wrap_tooltip("使用固定/模板费用不包含文案。", "对应 feeExclude。", "最终随 productTranslationPush 写入。"),
            "usage": wrap_tooltip("使用详情模板生成使用方法。", "对应 howToUse。", "最终随 productTranslationPush 写入。"),
            "description": wrap_tooltip("使用详情模板富文本生成产品介绍。", "对应 productIntroduction。", "写入 HTML 化后的翻译内容。"),
            "notice": wrap_tooltip("使用详情模板富文本生成注意事项。", "对应 attention。", "最终随 productTranslationPush 写入。"),
            "post_booking_reminder": wrap_tooltip("使用详情模板生成订后出行提醒。", "对应 postBookingTravelReminder。", "最终随 productTranslationPush 写入。"),
            "operation_attention": wrap_tooltip(
                "使用详情模板生成携程处理注意事项。",
                "对应 operationAttentionInfo 子项 operationAttention。",
                "按纯文本随完整 translationModules 写入。",
            ),
            "sales_property": wrap_tooltip("生成销售属性名和销售属性值。", "对应 salesPropertyName / salesPropertyValueName。", "受右侧“销售属性”模式影响。"),
            "package_detail": wrap_tooltip("生成套餐规格详情。", "对应 packageIntroduction。", "受 90/180 天模板和特殊规则影响。"),
            "package_quantity": wrap_tooltip("生成套餐规格量词。", "对应 resourceName / packageResourceName。", "需要接口快照里存在对应字段。"),
        }
        for index, (module_key, label) in enumerate(module_definitions.items()):
            cb = CheckBox(label, dialog)
            style_choice_widget(cb)
            cb.setChecked(module_key in config.selected_modules)
            cb.setToolTip(module_tooltips.get(module_key, module_tooltip))
            module_checks[module_key] = cb
            module_grid.addWidget(cb, index // 2, index % 2)
        select_all_module_btn.clicked.connect(lambda _checked=False: set_all_checks(module_checks, True))
        deselect_all_module_btn.clicked.connect(lambda _checked=False: set_all_checks(module_checks, False))
        left_column.addWidget(module_section, 2)

        sales_section, sales_layout = make_section(
            "销售属性",
            wrap_tooltip(
                "仅在勾选“销售属性（大项）”模块时生效。",
                "接口版先按本地规则生成目标文本。",
                "请求机器翻译模式会读取 queryAiTranslationReference 参考译文。",
                "最终写入仍统一走 productTranslationPush。",
            ),
        )
        sales_mode_options = {
            "strict": "仅标准格式",
            "fuzzy_prefix": "模糊前缀匹配",
            "ai_translation": "请求机器翻译",
        }
        sales_mode_tooltips = {
            "strict": wrap_tooltip(
                "只匹配标准销售属性格式。",
                "例如 每日-xxGB、总量-xxGB、每日100GB特殊表。",
                "不匹配则不生成 Diff。",
            ),
            "fuzzy_prefix": wrap_tooltip(
                "匹配销售属性前缀并翻译。",
                "后缀原样保留。",
                "适合标准前缀后面带额外说明的值。",
            ),
            "ai_translation": wrap_tooltip(
                "先走本地销售属性规则。",
                "本地规则无法生成时调用 queryAiTranslationReference。",
                "该接口只返回参考文本。",
                "最终仍由 productTranslationPush 写入翻译件。",
            ),
        }
        sales_radios: dict[str, QRadioButton] = {}
        sales_group = QButtonGroup(dialog)
        current_sales_mode = config.sales_attr_mode if config.sales_attr_mode in sales_mode_options else "strict"
        for mode_value, mode_text in sales_mode_options.items():
            rb = QRadioButton(mode_text, dialog)
            style_choice_widget(rb)
            rb.setChecked(mode_value == current_sales_mode)
            rb.setToolTip(sales_mode_tooltips.get(mode_value, mode_text))
            sales_group.addButton(rb)
            sales_radios[mode_value] = rb
            sales_layout.addWidget(rb)
        right_column.addWidget(sales_section, 2)

        long_section, long_layout = make_section(
            "90/180天套餐模板",
            wrap_tooltip(
                "仅在勾选“套餐规格详情”模块时生效。",
                "它不是接口请求模式。",
                "只决定 packageIntroduction 的本地模板分支。",
                "最终随完整 translationModules 写入。",
            ),
        )
        long_day_mode_map = {
            "不套用": "none",
            "套用后停用模板": "stop",
            "套用后降速模板": "throttle",
        }
        long_day_reverse = {value: label for label, value in long_day_mode_map.items()}
        self._translation_rule_long_day_combo = QComboBox(dialog)
        self._translation_rule_long_day_combo.addItems(list(long_day_mode_map.keys()))
        self._translation_rule_long_day_combo.setCurrentText(long_day_reverse.get(config.long_day_package_template_mode, "不套用"))
        self._translation_rule_long_day_combo.setToolTip(
            wrap_tooltip(
                "不套用：按任务行/规格模板原规则选模板。",
                "套用后停用模板：90/180 天套餐强制使用后停用脚本。",
                "套用后降速模板：90/180 天套餐强制使用后降速脚本。",
            )
        )
        long_layout.addWidget(self._translation_rule_long_day_combo)

        rules_section, rules_layout = make_section(
            "套餐特殊填充规则",
            wrap_tooltip(
                "仅在勾选“套餐规格详情”模块时生效。",
                "控制本地 packageIntroduction 模板分支。",
                "不会发起独立请求。",
                "最终随完整 translationModules 写入。",
            ),
        )
        rule_checks: dict[str, QCheckBox] = {}
        current_rules = translation_rules.normalize_special_rule_config(config.package_special_rules)
        for rule_key, label in translation_rules.SPECIAL_RULE_LABELS.items():
            cb = CheckBox(label, dialog)
            style_choice_widget(cb)
            cb.setChecked(current_rules.get(rule_key, True))
            rule_desc = translation_rules.SPECIAL_RULE_DESCRIPTIONS.get(rule_key, "")
            cb.setToolTip(
                wrap_tooltip(
                    rule_desc,
                    "接口版含义：只影响套餐规格详情目标文本生成。",
                    "不是独立接口动作。",
                )
            )
            rule_checks[rule_key] = cb
            rules_layout.addWidget(cb)
        right_column.addWidget(rules_section, 3)

        bottom_option_row = QHBoxLayout()
        bottom_option_row.setSpacing(12)
        bottom_option_row.addWidget(long_section, 1)

        write_section, write_layout = make_section(
            "写入方式",
            wrap_tooltip(
                "直接影响 productTranslationPush 的 online 参数。",
                "接口版按产品+语言整体提交完整 translationModules。",
                "同一语言同批次不能真正混合保存/上线。",
            ),
        )
        self._translation_rule_online_check = CheckBox("保存并上线 online=true", dialog)
        style_choice_widget(self._translation_rule_online_check)
        self._translation_rule_online_check.setChecked(config.online)
        self._translation_rule_online_check.setToolTip(
            wrap_tooltip(
                "勾选：productTranslationPush 携带 online=true，保存并上线。",
                "不勾选：携带 online=false，仅保存草稿。",
                "这是右侧配置中唯一直接改变接口请求参数的选项。",
            )
        )
        write_layout.addWidget(self._translation_rule_online_check)
        self._translation_rule_unopened_check = CheckBox("同时传出未开站语言（仅保存草稿）", dialog)
        style_choice_widget(self._translation_rule_unopened_check)
        self._translation_rule_unopened_check.setChecked(config.include_unopened_locales)
        self._translation_rule_unopened_check.setToolTip(
            wrap_tooltip(
                "勾选：不在 operableLocales 的语言站点也生成 Diff 并写入。",
                "空站点会先用同一语言组的完整译本补齐其余字段，再以 online=false 仅保存草稿。",
                "同组没有完整译本的站点（如新马简中无来源）仍会跳过。",
            )
        )
        write_layout.addWidget(self._translation_rule_unopened_check)
        write_layout.addStretch(1)
        bottom_option_row.addWidget(write_section, 1)
        right_column.addLayout(bottom_option_row, 2)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, dialog)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        try:
            if dialog.exec() != QDialog.DialogCode.Accepted:
                return
            selected_languages = [lang for lang, cb in lang_checks.items() if cb.isChecked()]
            selected_modules = [key for key, cb in module_checks.items() if cb.isChecked()]
            if not selected_languages:
                QMessageBox.warning(self, "提示", "至少选择一个语言")
                return
            if not selected_modules:
                QMessageBox.warning(self, "提示", "至少选择一个模块")
                return
            config.selected_languages = selected_languages
            config.selected_modules = selected_modules
            config.sales_attr_mode = next((key for key, rb in sales_radios.items() if rb.isChecked()), "strict")
            config.long_day_package_template_mode = long_day_mode_map.get(self._translation_rule_long_day_combo.currentText(), "none")
            config.online = self._translation_rule_online_check.isChecked()
            config.include_unopened_locales = self._translation_rule_unopened_check.isChecked()
            config.package_special_rules = translation_rules.normalize_special_rule_config({key: cb.isChecked() for key, cb in rule_checks.items()})
            self._set_translation_rule_summary_text()
            self.persist_app_settings()
            enabled_rules = sum(1 for enabled in config.package_special_rules.values() if enabled)
            self.translation_log(f"规则模板执行配置已更新。语言={config.selected_languages}")
            self.translation_log(f"规则模板执行模块={[module_definitions[key] for key in config.selected_modules if key in module_definitions]}")
            self.translation_log(f"90/180天套餐模板={self._translation_rule_long_day_combo.currentText()} | 套餐特殊规则={enabled_rules}/{len(config.package_special_rules)}")
        finally:
            for attribute in ("_translation_rule_long_day_combo", "_translation_rule_online_check", "_translation_rule_unopened_check"):
                if hasattr(self, attribute):
                    delattr(self, attribute)
            dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
            dialog.deleteLater()
            QApplication.sendPostedEvents(dialog, QEvent.Type.DeferredDelete)

    def start_translation_rule_preview(self) -> None:
        task_path = self.translation_rule_runtime.task_path
        detail_path = self.translation_rule_runtime.detail_template_path
        package_path = self.translation_rule_runtime.package_template_path
        if not task_path:
            QMessageBox.warning(self, "提示", "请选择任务模板")
            return
        if not detail_path:
            QMessageBox.warning(self, "提示", "请选择详情模板")
            return
        needs_package = any(key in self.translation_rule_runtime.config.selected_modules for key in ("package_detail", "package_quantity"))
        if needs_package and not package_path:
            QMessageBox.warning(self, "提示", "已选择套餐模块，请选择套餐规格模板；不需要套餐时可在执行配置里取消套餐模块")
            return
        self.translation_rule_runtime.task_path = task_path
        self.translation_rule_runtime.detail_template_path = detail_path
        self.translation_rule_runtime.package_template_path = package_path
        self.persist_app_settings()
        self._start_translation_worker("translation_rule_preview")

    def start_apply_translations(self) -> None:
        self.translation_rule_runtime.online_context.online = bool(self.translation_rule_runtime.config.online)
        self.translation_rule_runtime.online_context.selected_languages = list(self.translation_rule_runtime.config.selected_languages or [])
        pending_plans = [plan for plan in self.pending_translation_plans if plan.status == "pending"]
        groups = {(plan.product_id, plan.locale) for plan in pending_plans}
        translation_force_groups = self.translation_force_online_groups(groups)
        if not pending_plans and not translation_force_groups:
            QMessageBox.warning(self, "提示", "没有 pending 翻译 diff 可传出，请先通过规则模板预载并生成Diff")
            return
        online_groups = {
            (plan.product_id, plan.locale)
            for plan in pending_plans
            if plan.online and locale_translated((self.translation_snapshots.get(plan.product_id).locale_options or {}).get(plan.locale, {}) if self.translation_snapshots.get(plan.product_id) else {})
        }
        if self.translation_rule_runtime.online_context.enabled and self.translation_rule_runtime.online_context.online:
            online_groups = online_groups | groups | set(translation_force_groups)
        answer = QMessageBox.question(
            self,
            "确认传出并上线",
            (
                f"将传出 {len(pending_plans)} 个翻译字段 diff，涉及 {len(groups)} 个产品语言。\n"
                f"其中 {len(online_groups)} 个产品语言会 online=true 保存并上线。\n"
                f"另外 {len(translation_force_groups)} 个规则模板选中产品语言没有 Diff，将强制提交当前翻译树上线。\n"
                "传出前会重新读取接口并拒绝 stale 项。是否继续？"
            ),
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self._start_translation_worker("apply")

    def translation_force_online_groups(self, exclude_groups: set[tuple[str, str]] | None = None) -> list[tuple[str, str]]:
        context = self.translation_rule_runtime.online_context
        if not context.enabled or not context.online:
            return []
        selected_languages = set(context.selected_languages or [])
        exclude_groups = exclude_groups or set()
        targets: list[tuple[str, str]] = []
        product_ids = context.product_ids or list(self.translation_snapshots.keys())
        for product_id in product_ids:
            snapshot = self.translation_snapshots.get(product_id)
            locales = list((context.locales_by_product or {}).get(product_id) or (snapshot.locales if snapshot else []))
            for locale in locales:
                if selected_languages and translation_rules.get_lang_group(locale) not in selected_languages:
                    continue
                locale_option = (snapshot.locale_options or {}).get(locale, {}) if snapshot else {}
                if not locale_can_submit_online(locale_option):
                    continue
                target = (product_id, locale)
                if target in exclude_groups or target in targets:
                    continue
                targets.append(target)
        return targets

    def export_translation_report(self) -> None:
        if not self.translation_results:
            QMessageBox.warning(self, "提示", "没有可导出的翻译结果")
            return
        default = default_download_path(translation_report_default_filename(self.translation_rule_runtime.task_path))
        path, selected = get_save_report_file_name(self, "导出翻译报告", default, "Excel (*.xlsx);;CSV (*.csv)")
        if not path:
            return
        if selected.startswith("CSV") and not path.lower().endswith(".csv"):
            path += ".csv"
        elif not path.lower().endswith((".xlsx", ".csv")):
            path += ".xlsx"
        try:
            metadata = build_translation_report_metadata(
                task_template_path=self.translation_rule_runtime.task_path,
                detail_template_path=self.translation_rule_runtime.detail_template_path,
                package_template_path=self.translation_rule_runtime.package_template_path,
                execution_summary=self.translation_rule_config_summary(),
                results=self.translation_results,
                request_stats=self.request_stats.snapshot("translation"),
            )
            write_translation_report(path, self.translation_results, self.translation_product_order, metadata=metadata)
            self.translation_log(f"已导出翻译报告：{path}")
            QMessageBox.information(self, "完成", f"已导出翻译报告：{path}")
        except Exception as exc:
            QMessageBox.critical(self, "导出失败", str(exc))

    def start_translation_refresh_auth(self) -> None:
        if self.worker_thread and self.worker_thread.is_alive():
            QMessageBox.warning(self, "提示", "任务正在运行")
            return
        self._set_auth_status_text("登录态：等待 Edge/Chrome 登录…")
        self.capture_translation_table_history()
        self.translation_results = []
        self.translation_product_order = {}
        self.translation_error_count = 0
        self.translation_verify_failed_count = 0
        self.translation_pressure_text = ""
        self._clear_translation_table()
        self.translation_detail_text.clear()
        self.stop_event.clear()
        self.active_worker_area = "translation"
        self.worker_thread = threading.Thread(target=self._run_translation_refresh_auth, daemon=True)
        self._set_translation_running(True)
        self.worker_thread.start()

    def _run_translation_refresh_auth(self) -> None:
        try:
            path, loaded, source = self._refresh_auth_for_area("translation")
            result = TranslationResultRow(product_id="", locale="", module_code="", field_code="", field_name="", self_key="", status="auth_refreshed", message=f"已刷新登录态：来源={source}，cookie={loaded} 个，写入 {path}")
            auth_status = f"登录态：{source} 登录态有效" if source in {"Edge", "Chrome"} else "登录态：有效"
            self.out_queue.put(("auth_status", auth_status))
            self.out_queue.put(("result", result))
            self.out_queue.put(("done", [result]))
        except Exception as exc:
            self.out_queue.put(("auth_status", "登录态：刷新失败"))
            self.out_queue.put(("fatal", str(exc)))

    def _start_translation_worker(
        self,
        mode: str,
    ) -> None:
        if self.worker_thread and self.worker_thread.is_alive():
            QMessageBox.warning(self, "提示", "任务正在运行")
            return
        self.active_worker_area = "translation"
        if not self._ensure_auth_ready(self._auth_validation_product_id("translation"), "translation"):
            return
        request_interval = self._translation_request_interval_seconds_or_warn()
        if request_interval is None:
            return
        parallel_requests = self._parallel_requests_or_warn(self.translation_parallel_requests_edit)
        if parallel_requests is None:
            return
        if not self._apply_runtime_request_settings("translation", quiet=True):
            return
        self.persist_app_settings()
        self.capture_translation_table_history()
        self.translation_results = []
        self.translation_product_order = {}
        self.translation_pressure_text = ""
        self._clear_translation_table()
        self.translation_detail_text.clear()
        self.stop_event.clear()
        worker = TranslationWorkflowWorker(
            self.out_queue,
            self.stop_event,
            self.translation_snapshots,
            self.pending_translation_plans,
            self.last_saved_translation_products,
            self.translation_rule_runtime.online_context,
            request_interval_seconds=request_interval,
            parallel_requests=parallel_requests,
            runtime_settings=self.translation_runtime_settings,
            stats_recorder=self._queue_request_stat,
        )
        if mode == "translation_rule_preview":
            self.pending_translation_plans.clear()
            runtime = self.translation_rule_runtime
            target = lambda: worker.run_translation_rule_preload_and_preview(
                runtime.task_path,
                runtime.detail_template_path,
                runtime.package_template_path,
                runtime.config,
            )
        elif mode == "apply":
            target = worker.run_apply_pending
        else:
            raise RuntimeError(f"未知翻译任务模式：{mode}")
        self.worker_thread = threading.Thread(target=target, daemon=True)
        self._set_translation_running(True)
        self.worker_thread.start()

    def open_preview(self) -> None:
        self.open_product_result_preview(self.table, self.product_result_model, self.preloaded_products, self.results)

    def open_translation_preview(self) -> None:
        self.open_translation_result_preview(
            self.translation_table,
            self.translation_result_model,
            self.translation_snapshots,
            self.translation_results,
        )


    def _poll_queue(self) -> None:
        drain_queue_limited(self.out_queue, self._handle_queue_event)
        if not self.out_queue.empty():
            QTimer.singleShot(0, self._poll_queue)

    def _queue_request_stat(self, area: str) -> None:
        self.out_queue.put(("request_stat", area))

    def _handle_queue_event(self, kind: str, payload: Any) -> None:
        if kind == "catalog_result":
            self.product_edit_component.show_catalog_read_result(payload)
        elif kind == "catalog_progress":
            completed, total, message = payload
            self.product_edit_component.set_catalog_progress(completed, total, message)
        elif kind == "catalog_done":
            self.product_edit_component.finish_catalog_read(bool(payload))
        elif kind == "log":
            self._active_log(payload)
        elif kind == "startup_auth_check":
            self._handle_startup_auth_result(payload)
        elif kind == "auth_status":
            self._set_auth_status_text(str(payload))
        elif kind == "request_stat":
            self._record_request_stat(str(payload or self.active_worker_area or "product"))
        elif kind == "progress":
            if self.active_worker_area == "translation":
                self._set_translation_runtime_status_text(f"{payload} | {self._translation_status_suffix()}")
            else:
                self.status_label.setText(f"{payload} | {self._product_status_suffix()}")
        elif kind == "pressure":
            self._handle_pressure(payload)
        elif kind == "product_order":
            self.product_result_order = dict(payload or {})
            self._sync_active_product_workbench_state()
            if self.results:
                self.results = ordered_product_results(self.results, self.product_result_order)
                self._sync_active_product_workbench_state()
                self._render_product_results()
        elif kind == "audit_candidates":
            self.submit_audit_candidate_product_ids = unique_product_ids(list(payload or []))
            self._sync_active_product_workbench_state()
            self.log(f"当前预览/预载可提交审核产品：{len(self.submit_audit_candidate_product_ids)} 个")
        elif kind == "translation_product_order":
            self.translation_product_order = dict(payload or {})
            if self.translation_results:
                self.translation_results = ordered_translation_results(self.translation_results, self.translation_product_order)
                self._render_translation_results()
        elif kind == "result":
            self._record_result_failures([payload])
            if isinstance(payload, TranslationResultRow):
                self.add_translation_result(payload)
            else:
                self.add_result(payload)
        elif kind == "result_batch":
            rows = list(payload or [])
            self._record_result_failures(rows)
            if rows and isinstance(rows[0], TranslationResultRow):
                self.add_translation_results(rows)
            else:
                self.add_results(rows)
        elif kind == "done":
            self._handle_done(payload)
        elif kind == "fatal":
            self._record_failure_stat(self.active_worker_area or "product")
            self._set_running(False)
            self._set_translation_running(False)
            if self.active_worker_area == "translation":
                self._set_translation_runtime_status_text(f"失败 | {self._translation_status_suffix()}")
                self.translation_log(payload)
            else:
                self.status_label.setText(f"失败 | {self._product_status_suffix()}")
                self.log(payload)
            QMessageBox.critical(self, "任务失败", str(payload).splitlines()[0])

    def _record_request_stat(self, area: str) -> None:
        if area not in REQUEST_STATS_AREAS:
            area = "product"
        try:
            self.request_stats.record_request(area)
        except Exception as exc:
            self._active_log(f"请求统计写入失败：{exc}")
            return
        self._refresh_request_stats_label(area)

    def _record_failure_stat(self, area: str, count: int = 1) -> None:
        if area not in REQUEST_STATS_AREAS or count <= 0:
            return
        try:
            self.request_stats.record_failure(area, count)
        except Exception as exc:
            self._active_log(f"请求失败统计写入失败：{exc}")
            return
        self._refresh_request_stats_label(area)

    def _record_result_failures(self, rows: list[Any]) -> None:
        if not rows:
            return
        area = self._stats_area_for_result(rows[0])
        failure_count = sum(1 for row in rows if getattr(row, "status", "") == "error")
        if failure_count:
            self._record_failure_stat(area, failure_count)

    def _stats_area_for_result(self, row: Any) -> str:
        if isinstance(row, TranslationResultRow):
            return "translation"
        return "product"

    def _refresh_request_stats_label(self, area: str) -> None:
        if area == "translation" and hasattr(self, "translation_runtime_status_label"):
            self.translation_runtime_status_label.setText(self._replace_request_stats(self.translation_runtime_status_label.text(), area))
        elif area == "image" and getattr(self, "product_image_workspace", None) is not None:
            self.product_image_workspace.set_request_stats_text(
                self.request_stats.summary_text("image")
            )
        elif area == "docking" and getattr(self, "docking_config_widget", None) is not None:
            self.docking_config_widget.set_request_stats_text(
                self.request_stats.summary_text("docking")
            )
        elif hasattr(self, "status_label"):
            self.status_label.setText(self._replace_request_stats(self.status_label.text(), "product"))

    def _replace_request_stats(self, text: str, area: str) -> str:
        base = str(text or "就绪").split(" | 请求 ", 1)[0]
        return f"{base} | {self.request_stats.summary_text(area)}"

    def _handle_done(self, payload: Any) -> None:
        rows = list(payload or [])
        if self.active_worker_area == "translation" or (rows and isinstance(rows[0], TranslationResultRow)):
            self.capture_translation_table_history()
            self.translation_results = ordered_translation_results(rows, self.translation_product_order)
            self._render_translation_results()
            self.register_current_translation_table_history()
            self._recount_translation_status()
            self._set_translation_runtime_status_text(self._translation_status_text("完成"))
            self._set_translation_running(False)
            self.translation_log(f"翻译任务完成 | {self._translation_status_suffix()}")
        elif self.active_product_mode == "submit":
            self._recount_product_status()
            self._sync_active_product_workbench_state()
            self.status_label.setText(self._product_status_text("完成"))
            self._set_running(False)
            self.log(f"提交审核完成 | {self._product_status_suffix()}")
            self.active_product_mode = ""
        else:
            self.results = ordered_product_results(rows, self.product_result_order)
            self._sync_active_product_workbench_state()
            self._render_product_results()
            self._recount_product_status()
            self._sync_active_product_workbench_state()
            self.status_label.setText(self._product_status_text("完成"))
            self._set_running(False)
            self.log(f"任务完成 | {self._product_status_suffix()}")
            self.active_product_mode = ""

    def _handle_pressure(self, payload: Any) -> None:
        data = payload if isinstance(payload, dict) else {}
        parallel = data.get("parallel")
        desired = data.get("desired")
        interval = data.get("interval")
        reason = str(data.get("reason") or "")
        text = f"实际并发={parallel}/{desired}" if parallel and desired else ""
        if text and interval is not None:
            text += f" | 间隔={interval_text(interval)}秒"
        if reason and text:
            text += f" | 降载：{reason}"
        elif reason:
            text = f"降载：{reason}"
        if data.get("area") == "translation":
            self.translation_pressure_text = text
            self._set_translation_runtime_status_text(self._translation_status_text("运行中"))
        else:
            self.product_pressure_text = text
            self._sync_active_product_workbench_state()
            self.status_label.setText(self._product_status_text("运行中"))

    def _status_text(self, prefix: str, total: int, error_count: int, verify_failed_count: int, area: str) -> str:
        return f"{prefix}：{total} 条结果 | error={error_count} | verify_failed={verify_failed_count} | {self.request_stats.summary_text(area)}"

    def _product_status_suffix(self) -> str:
        suffix = f"error={self.product_error_count} | verify_failed={self.product_verify_failed_count}"
        if self.product_pressure_text:
            suffix = f"{suffix} | {self.product_pressure_text}"
        return f"{suffix} | {self.request_stats.summary_text('product')}"

    def _translation_status_suffix(self) -> str:
        suffix = f"error={self.translation_error_count} | verify_failed={self.translation_verify_failed_count}"
        if self.translation_pressure_text:
            suffix = f"{suffix} | {self.translation_pressure_text}"
        return f"{suffix} | {self.request_stats.summary_text('translation')}"


    def _product_status_text(self, prefix: str) -> str:
        return self._status_text(prefix, len(self.results), self.product_error_count, self.product_verify_failed_count, "product")

    def _translation_status_text(self, prefix: str) -> str:
        return self._status_text(prefix, len(self.translation_results), self.translation_error_count, self.translation_verify_failed_count, "translation")


    def _recount_product_status(self) -> None:
        self.product_error_count = sum(1 for item in self.results if item.status == "error")
        self.product_verify_failed_count = sum(1 for item in self.results if item.status == "verify_failed")

    def _recount_translation_status(self) -> None:
        self.translation_error_count = sum(1 for item in self.translation_results if item.status == "error")
        self.translation_verify_failed_count = sum(1 for item in self.translation_results if item.status == "verify_failed")


    def _record_product_status(self, result: ResultRow) -> None:
        if result.status == "error":
            self.product_error_count += 1
        elif result.status == "verify_failed":
            self.product_verify_failed_count += 1


    def _record_translation_status(self, result: TranslationResultRow) -> None:
        if result.status == "error":
            self.translation_error_count += 1
        elif result.status == "verify_failed":
            self.translation_verify_failed_count += 1

    def add_result(self, result: ResultRow) -> None:
        self.product_result_model.append_results([result])
        self.results = self.product_result_model.rows
        self._record_product_status(result)
        self._sync_active_product_workbench_state()
        self.status_label.setText(self._product_status_text("运行中"))
        self.product_scroll_timer.start(250)

    def add_results(self, results: list[ResultRow]) -> None:
        if not results:
            return
        self.product_result_model.append_results(results)
        self.results = self.product_result_model.rows
        for result in results:
            self._record_product_status(result)
        self._sync_active_product_workbench_state()
        self.status_label.setText(self._product_status_text("运行中"))
        self.product_scroll_timer.start(250)



    def _insert_product_result(self, result: ResultRow) -> int:
        new_key = product_result_sort_key(result, self.product_result_order)
        row_index = len(self.results)
        while row_index > 0 and product_result_sort_key(self.results[row_index - 1], self.product_result_order) > new_key:
            row_index -= 1
        self.results.insert(row_index, result)
        return row_index

    def _product_table_values(self, result: ResultRow) -> list[Any]:
        return product_table_values(result)

    def add_translation_result(self, result: TranslationResultRow) -> None:
        self.translation_result_model.append_results([result])
        self.translation_results = self.translation_result_model.rows
        self._record_translation_status(result)
        self._set_translation_runtime_status_text(self._translation_status_text("运行中"))
        self.translation_scroll_timer.start(250)

    def add_translation_results(self, results: list[TranslationResultRow]) -> None:
        if not results:
            return
        self.translation_result_model.append_results(results)
        self.translation_results = self.translation_result_model.rows
        for result in results:
            self._record_translation_status(result)
        self._set_translation_runtime_status_text(self._translation_status_text("运行中"))
        self.translation_scroll_timer.start(250)

    def _insert_translation_result(self, result: TranslationResultRow) -> int:
        new_key = translation_result_sort_key(result, self.translation_product_order)
        row_index = len(self.translation_results)
        while row_index > 0 and translation_result_sort_key(self.translation_results[row_index - 1], self.translation_product_order) > new_key:
            row_index -= 1
        self.translation_results.insert(row_index, result)
        return row_index

    def _translation_table_values(self, result: TranslationResultRow) -> list[Any]:
        return translation_table_values(result)

    def _render_product_results(self) -> None:
        self._product_render_generation += 1
        self.product_result_model.set_results(self.results)
        self._sync_active_product_workbench_state()


    def _render_translation_results(self) -> None:
        self._translation_render_generation += 1
        self.translation_result_model.set_results(self.translation_results)
        self.refresh_translation_table_history_buttons()

    def _append_table_row(self, table: QTableWidget, row_index: int, values: list[Any]) -> None:
        self._append_table_rows(table, [values], row_index=row_index)

    def _append_table_rows(self, table: QTableWidget, rows: list[list[Any]], row_index: int | None = None) -> None:
        if not rows:
            return
        sorting_enabled = table.isSortingEnabled()
        signals_blocked = table.blockSignals(True)
        table.setSortingEnabled(False)
        table.setUpdatesEnabled(False)
        try:
            start_index = table.rowCount() if row_index is None else row_index
            table.setRowCount(max(table.rowCount(), start_index + len(rows)))
            for offset, values in enumerate(rows):
                target_row = start_index + offset
                for col_index, value in enumerate(values):
                    item = create_readonly_table_item(table, value)
                    table.setItem(target_row, col_index, item)
        finally:
            table.setUpdatesEnabled(True)
            table.setSortingEnabled(sorting_enabled)
            table.blockSignals(signals_blocked)

    def _scroll_product_table_to_bottom(self) -> None:
        row_count = self.product_result_model.rowCount()
        if row_count > 0:
            self.table.scrollTo(self.product_result_model.index(row_count - 1, 0))

    def _scroll_translation_table_to_bottom(self) -> None:
        row_count = self.translation_result_model.rowCount()
        if row_count > 0:
            self.translation_table.scrollTo(self.translation_result_model.index(row_count - 1, 0))


    def product_result_diff_text(self, result: ResultRow) -> str:
        old_parts = [
            str(result.old_value or ""),
            str(result.old_vendor_package_id or ""),
            str(result.old_connection_code or ""),
            str(result.old_introduction or ""),
        ]
        new_parts = [
            str(result.new_value or ""),
            str(result.new_vendor_package_id or ""),
            str(result.new_connection_code or ""),
            str(result.new_introduction or ""),
        ]
        old_text = "\n".join(part for part in old_parts if part)
        new_text = "\n".join(part for part in new_parts if part)
        if not old_text and not new_text:
            return ""
        if len(old_text) + len(new_text) > MAX_DIFF_TEXT_CHARS:
            return f"内容过长，已跳过实时 diff。old={len(old_text)} chars, new={len(new_text)} chars。请导出报告查看完整内容。"
        return "\n".join(
            difflib.unified_diff(
                old_text.splitlines(),
                new_text.splitlines(),
                fromfile="修改前",
                tofile="修改后",
                lineterm="",
            )
        )

    def product_result_detail_text(self, result: ResultRow) -> str:
        detail = [
            f"productId: {result.product_id}",
            f"packageId: {result.package_id}",
            f"resourceId: {result.resource_id}",
            f"packageName: {result.package_name}",
            f"field: {result.field_name}",
            f"oldValue: {result.old_value}",
            f"newValue: {result.new_value}",
            f"interface: {result.interface_name}",
            f"usedup_throttle: {result.usedup_throttle}",
            f"reset_time_calc: {result.reset_time_calc}",
            f"inst_adv: {result.inst_adv}",
            f"oldCostPrice: {result.old_cost_price}",
            f"newCostPrice: {result.new_cost_price}",
            f"oldVendorPackageId: {result.old_vendor_package_id}",
            f"newVendorPackageId: {result.new_vendor_package_id}",
            f"oldConnectionCode: {result.old_connection_code}",
            f"newConnectionCode: {result.new_connection_code}",
            f"submitAudit: {'是' if result.submit_audit else '否'}",
            f"status: {result.status}",
            f"row: {result.row_number}",
            "",
            "message:",
            result.message,
            "",
            "diff:",
            self.product_result_diff_text(result),
            "",
            "oldIntroduction:",
            self._limited_detail_text(result.old_introduction),
            "",
            "newIntroduction:",
            self._limited_detail_text(result.new_introduction),
        ]
        return "\n".join(detail)

    def selected_model_result(self, table: QTableView, model: ResultTableModel) -> Any | None:
        index = table.currentIndex()
        if not index.isValid():
            return None
        return model.result_at(index.row())

    def selected_product_result(self, table: QTableView, model: ProductResultTableModel) -> ResultRow | None:
        result = self.selected_model_result(table, model)
        return result if isinstance(result, ResultRow) else None

    def render_product_result_detail(
        self,
        table: QTableView,
        model: ProductResultTableModel,
        detail_text: PlainTextEdit,
    ) -> None:
        result = self.selected_product_result(table, model)
        if result is None:
            return
        detail_text.setPlainText(self.product_result_detail_text(result))

    def show_product_result_detail(
        self,
        table: QTableView,
        model: ProductResultTableModel,
        detail_text: PlainTextEdit,
    ) -> None:
        QTimer.singleShot(120, lambda: self.render_product_result_detail(table, model, detail_text))

    def open_product_result_preview(
        self,
        table: QTableView,
        model: ProductResultTableModel,
        snapshots: dict[str, ProductSnapshot],
        results: list[ResultRow],
    ) -> None:
        selected = self.selected_product_result(table, model)
        preview_results = [selected] if selected is not None else list(results)
        if not snapshots and not preview_results:
            QMessageBox.warning(self, "提示", "当前没有可预览的接口快照或结果报告")
            return
        dialog = PreviewDialog(snapshots, preview_results, self)
        dialog.exec()

    def show_selected_detail(self) -> None:
        self.product_detail_timer.start(120)

    def render_selected_detail(self) -> None:
        self.render_product_result_detail(self.table, self.product_result_model, self.detail_text)








    def translation_result_detail_text(self, result: TranslationResultRow) -> str:
        old_value = str(result.old_value or "")
        new_value = str(result.new_value or "")
        if len(old_value) + len(new_value) > MAX_DIFF_TEXT_CHARS:
            diff = f"内容过长，已跳过实时 diff。old={len(old_value)} chars, new={len(new_value)} chars。请导出报告查看完整内容。"
        else:
            diff = "\n".join(
                difflib.unified_diff(
                    old_value.splitlines(),
                    new_value.splitlines(),
                    fromfile="当前翻译",
                    tofile="目标翻译",
                    lineterm="",
                )
            )
        detail = [
            f"productId: {result.product_id}",
            f"locale: {result.locale}",
            f"moduleCode: {result.module_code}",
            f"fieldCode: {result.field_code}",
            f"fieldName: {result.field_name}",
            f"selfKey: {result.self_key}",
            f"online: {'是' if result.online else '否'}",
            f"interface: {result.interface_name}",
            f"status: {result.status}",
            f"row: {result.row_number}",
            "",
            "message:",
            result.message,
            "",
            "diff:",
            diff,
            "",
            "oldValue:",
            self._limited_detail_text(old_value),
            "",
            "newValue:",
            self._limited_detail_text(new_value),
        ]
        return "\n".join(detail)

    def selected_translation_result(self, table: QTableView, model: TranslationResultTableModel) -> TranslationResultRow | None:
        result = self.selected_model_result(table, model)
        return result if isinstance(result, TranslationResultRow) else None

    def render_translation_result_detail(
        self,
        table: QTableView,
        model: TranslationResultTableModel,
        detail_text: PlainTextEdit,
    ) -> None:
        result = self.selected_translation_result(table, model)
        if result is None:
            return
        detail_text.setPlainText(self.translation_result_detail_text(result))

    def show_translation_result_detail(
        self,
        table: QTableView,
        model: TranslationResultTableModel,
        detail_text: PlainTextEdit,
    ) -> None:
        QTimer.singleShot(120, lambda: self.render_translation_result_detail(table, model, detail_text))

    def open_translation_result_preview(
        self,
        table: QTableView,
        model: TranslationResultTableModel,
        snapshots: dict[str, TranslationSnapshot],
        results: list[TranslationResultRow],
    ) -> None:
        selected = self.selected_translation_result(table, model)
        preview_results = [selected] if selected is not None else list(results)
        if not snapshots and not preview_results:
            QMessageBox.warning(self, "提示", "当前没有可预览的翻译快照或结果报告")
            return
        dialog = TranslationPreviewDialog(snapshots, preview_results, self)
        dialog.exec()

    def show_selected_translation_detail(self) -> None:
        self.translation_detail_timer.start(120)

    def render_selected_translation_detail(self) -> None:
        self.render_translation_result_detail(self.translation_table, self.translation_result_model, self.translation_detail_text)

    def _limited_detail_text(self, value: Any) -> str:
        text = "" if value is None else str(value)
        if len(text) <= MAX_DETAIL_TEXT_CHARS:
            return text
        return text[:MAX_DETAIL_TEXT_CHARS] + f"\n\n...内容过长，已截断显示。总长度={len(text)} chars，请导出报告查看完整内容。"

    def _clear_table(self) -> None:
        self._product_render_generation += 1
        self._product_render_rows = []
        self._product_render_index = 0
        self.results = []
        self.product_result_model.set_results(self.results)
        if hasattr(self, "product_workbench_widgets"):
            self._sync_active_product_workbench_state()


    def _clear_translation_table(self) -> None:
        self._translation_render_generation += 1
        self._translation_render_rows = []
        self._translation_render_index = 0
        self.translation_results = []
        self.translation_result_model.set_results(self.translation_results)
        self.refresh_translation_table_history_buttons()

    def _set_running(self, running: bool) -> None:
        for button in [
            self.preload_btn,
            self.export_template_btn,
            self.apply_btn,
            self.submit_audit_btn,
            self.auth_btn,
        ]:
            button.setEnabled(not running)
        self.export_btn.setEnabled(not running)
        self.stop_btn.setEnabled(running)
        self.request_interval_edit.setEnabled(True)
        self.parallel_requests_edit.setEnabled(True)


    def _set_translation_running(self, running: bool) -> None:
        for button in [
            self.translation_rule_config_btn,
            self.translation_rule_generate_btn,
            self.translation_rule_apply_btn,
            self.translation_rule_auth_btn,
            self.translation_rule_edit_task_btn,
            self.translation_rule_reload_task_btn,
            self.translation_rule_load_task_btn,
            self.translation_rule_download_task_btn,
            self.translation_rule_load_detail_btn,
            self.translation_rule_detail_manager_btn,
            self.translation_rule_download_detail_btn,
            self.translation_rule_load_package_btn,
            self.translation_rule_package_manager_btn,
            self.translation_rule_download_package_btn,
        ]:
            button.setEnabled(not running)
        self.translation_rule_export_btn.setEnabled(not running)
        self.translation_rule_stop_btn.setEnabled(running)
        self.translation_request_interval_edit.setEnabled(True)
        self.translation_parallel_requests_edit.setEnabled(True)
        self.translation_reset_btn.setEnabled(not running)
        self.refresh_translation_table_history_buttons()

    def _set_translation_runtime_status_text(self, text: str) -> None:
        if hasattr(self, "translation_runtime_status_label"):
            self.translation_runtime_status_label.setText(self._replace_request_stats(text, "translation"))

    def capture_translation_table_history(self) -> None:
        if not self.translation_results:
            self.refresh_translation_table_history_buttons()
            return
        snapshot = (list(self.translation_results), dict(self.translation_product_order))
        if self.translation_table_history_index >= 0:
            current_rows, current_order = self.translation_table_history[self.translation_table_history_index]
            if current_rows == snapshot[0] and current_order == snapshot[1]:
                self.refresh_translation_table_history_buttons()
                return
            self.translation_table_history = self.translation_table_history[: self.translation_table_history_index + 1]
        self.translation_table_history.append(snapshot)
        if len(self.translation_table_history) > TRANSLATION_TABLE_HISTORY_LIMIT:
            self.translation_table_history = self.translation_table_history[-TRANSLATION_TABLE_HISTORY_LIMIT:]
        self.translation_table_history_index = len(self.translation_table_history) - 1
        self.refresh_translation_table_history_buttons()

    def register_current_translation_table_history(self) -> None:
        self.capture_translation_table_history()

    def restore_translation_table_history(self, delta: int) -> None:
        target_index = self.translation_table_history_index + delta
        if target_index < 0 or target_index >= len(self.translation_table_history):
            self.refresh_translation_table_history_buttons()
            return
        rows, product_order = self.translation_table_history[target_index]
        self.translation_table_history_index = target_index
        self.translation_results = list(rows)
        self.translation_product_order = dict(product_order)
        self._render_translation_results()
        self._recount_translation_status()
        self._set_translation_runtime_status_text(f"历史表格 {target_index + 1}/{len(self.translation_table_history)} | {self._translation_status_suffix()}")
        self.translation_detail_text.clear()
        self.refresh_translation_table_history_buttons()

    def refresh_translation_table_history_buttons(self) -> None:
        if not hasattr(self, "translation_table_prev_btn"):
            return
        running = bool(self.worker_thread and self.worker_thread.is_alive() and self.active_worker_area == "translation")
        self.translation_table_prev_btn.setEnabled(not running and self.translation_table_history_index > 0)
        self.translation_table_next_btn.setEnabled(not running and 0 <= self.translation_table_history_index < len(self.translation_table_history) - 1)

    def reset_translation_workspace(self) -> None:
        if self.worker_thread and self.worker_thread.is_alive():
            QMessageBox.warning(self, "提示", "任务正在运行")
            return
        self.translation_rule_runtime.task_path = ""
        self.translation_rule_runtime.detail_template_path = ""
        self.translation_rule_runtime.package_template_path = ""
        self.translation_snapshots.clear()
        self.pending_translation_plans.clear()
        self.last_saved_translation_products.clear()
        self.translation_results = []
        self.translation_product_order = {}
        self.translation_table_history.clear()
        self.translation_table_history_index = -1
        self.translation_error_count = 0
        self.translation_verify_failed_count = 0
        self.translation_pressure_text = ""
        self.translation_force_online_context_reset()
        self._clear_translation_table()
        self.translation_detail_text.clear()
        self.translation_log_text.clear()
        self._set_translation_runtime_status_text("就绪")
        self.translation_runtime_summary_label.setText("")
        self.translation_runtime_summary_label.setToolTip("")
        self.translation_rule_summary_label.setText("")
        self.translation_rule_summary_label.setToolTip("")
        self.refresh_translation_rule_template_statuses()
        self.refresh_translation_table_history_buttons()
        self.persist_app_settings()

    def translation_force_online_context_reset(self) -> None:
        self.translation_rule_runtime.online_context = TranslationOnlineContext()

    def log(self, message: str) -> None:
        line = f"[{dt.datetime.now().strftime('%H:%M:%S')}] {message}"
        self.log_text.appendPlainText(line)

    def translation_log(self, message: str) -> None:
        line = f"[{dt.datetime.now().strftime('%H:%M:%S')}] {message}"
        self.translation_log_text.appendPlainText(line)

    def product_image_log(self, message: str) -> None:
        workspace = getattr(self, "product_image_workspace", None)
        if workspace is not None and not getattr(workspace, "_closed", False):
            workspace.status_label.setText(message)

    def _active_log(self, message: str) -> None:
        if self.active_worker_area == "translation":
            self.translation_log(message)
        else:
            self.log(message)


def parse_cli_price_item(value: str) -> tuple[str, str, str]:
    parts = [part.strip() for part in value.split(":")]
    if len(parts) != 3 or not all(parts):
        raise argparse.ArgumentTypeError("--item 格式必须是 packageId:resourceId:newCostPrice")
    package_id, resource_id, cost_price = parts
    try:
        float(cost_price)
    except Exception as exc:
        raise argparse.ArgumentTypeError(f"newCostPrice 不是数字：{cost_price}") from exc
    return normalize_number_text(package_id), normalize_number_text(resource_id), normalize_number_text(cost_price)


def build_cli_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Ctrip 产品编辑工具。无参数启动 GUI；传子命令可直接调试接口。",
    )
    subparsers = parser.add_subparsers(dest="command")
    # --- 图片工作区子命令 ---
    image_show = subparsers.add_parser("image-show", help="读取产品图片工作区数据并输出所有语言站点信息（只读）")
    image_show.add_argument("--product-id", required=True, help="Ctrip productId")
    image_show.add_argument("--request-interval", type=float, default=CTRIP_REQUEST_INTERVAL_SECONDS, help="请求间隔秒，默认 0.2")
    image_show.add_argument("--output", default="", help="输出 JSON 文件路径")

    image_copy = subparsers.add_parser("image-copy-all", help="将源站点头图序列应用到全部站点并执行保存，必须加 --confirm-live-write")
    image_copy.add_argument("--product-id", required=True, help="Ctrip productId")
    image_copy.add_argument("--source", required=True, help="源站点 languageCode，例如 chinese")
    image_copy.add_argument("--request-interval", type=float, default=CTRIP_REQUEST_INTERVAL_SECONDS, help="请求间隔秒，默认 0.2")
    image_copy.add_argument("--output", default="", help="输出 JSON 文件路径")
    image_copy.add_argument("--confirm-live-write", action="store_true", help="确认执行真实写入")

    for command, help_text in (
        ("price-dry-run", "读取 PriceAndStock 并生成调价请求，不提交"),
        ("price-apply", "提交 PriceAndStock 调价请求并回读校验，必须加 --confirm-live-write"),
        ("price-effect", "提交 PriceAndStock 调价请求、主保存并正式读回校验，必须加 --confirm-live-write"),
    ):
        sub = subparsers.add_parser(command, help=help_text)
        sub.add_argument("--product-id", required=True, help="Ctrip productId")
        sub.add_argument(
            "--item",
            action="append",
            required=True,
            type=parse_cli_price_item,
            help="调价项，格式 packageId:resourceId:newCostPrice；可重复",
        )
        sub.add_argument("--category-id", help="可选。网页请求里的 categoryId，例如 250")
        sub.add_argument("--reserve-mode", help="可选。网页请求里的 reserveMode，例如 1")
        sub.add_argument("--product-version", help="可选。覆盖接口读取到的 productVersion")
        sub.add_argument("--request-interval", type=float, default=CTRIP_REQUEST_INTERVAL_SECONDS, help="请求间隔秒，默认 0.2")
        sub.add_argument("--output", default="", help=f"输出 JSON 文件路径；默认写入用户下载文件夹/{WRITE_RUNS_DIR_NAME}")
        if command in {"price-apply", "price-effect"}:
            sub.add_argument("--confirm-live-write", action="store_true", help="确认执行真实写入")
        if command == "price-effect":
            sub.add_argument(
                "--disable-empty-package",
                action="append",
                default=[],
                help="主保存前将指定无资源 packageId 的 PackageInfo active 设为 false；可重复",
            )
    return parser


def cli_log(message: str) -> None:
    print(f"[{dt.datetime.now().strftime('%H:%M:%S')}] {message}", file=sys.stderr)


def cli_output_path(product_id: str, command: str, output: str) -> Path:
    if output:
        path = Path(output)
        path.parent.mkdir(parents=True, exist_ok=True)
        return path
    run_dir = make_write_run_dir()
    return run_dir / f"{product_id}_{command}_{now_stamp()}.json"


def formal_price_record(
    client: CtripRequestsClient,
    product_id: str,
    package_id: str,
    resource_id: str,
    stop_event: threading.Event,
) -> dict[str, Any]:
    direct = client.get_resource_price_and_stock_direct(product_id, package_id, resource_id, stop_event)
    price_and_stock = direct.get("response", {}).get("priceAndStock")
    if not isinstance(price_and_stock, dict):
        raise RuntimeError("getResourcePriceAndStock 未返回 priceAndStock")
    cost_price = current_cost_price(price_and_stock, resource_id)
    sale_price = ""
    for resource_price in price_and_stock.get("resourcePriceList") or []:
        if str(resource_price.get("resourceId") or "") != str(resource_id):
            continue
        for price in resource_price.get("priceList") or []:
            if "salePrice" in price:
                sale_price = normalize_number_text(price.get("salePrice"))
                break
    return {
        "packageId": package_id,
        "resourceId": resource_id,
        "costPrice": cost_price,
        "salePrice": sale_price,
        "responseBaseData": direct.get("response", {}).get("responseBaseData"),
    }


def formal_cost_price(
    client: CtripRequestsClient,
    product_id: str,
    package_id: str,
    resource_id: str,
    stop_event: threading.Event,
) -> str:
    return normalize_number_text(formal_price_record(client, product_id, package_id, resource_id, stop_event).get("costPrice"))


def formal_sale_status(
    client: CtripRequestsClient,
    product_id: str,
    package_id: str,
    resource_id: str,
    stop_event: threading.Event,
) -> str:
    direct = client.get_resource_price_and_stock_direct(product_id, package_id, resource_id, stop_event)
    price_and_stock = direct.get("response", {}).get("priceAndStock")
    if not isinstance(price_and_stock, dict):
        raise RuntimeError("getResourcePriceAndStock 未返回 priceAndStock")
    sale_status = current_sale_status(price_and_stock, resource_id)
    if not sale_status:
        raise RuntimeError("getResourcePriceAndStock 未返回开/关班状态")
    return sale_status


def run_price_effect_cli(args: argparse.Namespace, client: CtripRequestsClient, stop_event: threading.Event, product_id: str) -> int:
    draft = client.load_product(product_id, stop_event)
    currency_context = client.load_product_currency_context(product_id, stop_event, refresh=True)
    package_info = copy.deepcopy(draft.package_info)
    disabled_packages: list[dict[str, Any]] = []
    disable_ids = {normalize_number_text(item) for item in getattr(args, "disable_empty_package", [])}
    if disable_ids:
        for item in package_info.get("packageInfoList") or []:
            if not isinstance(item, dict) or str(item.get("packageId") or "") not in disable_ids:
                continue
            before_active = item.get("active")
            if before_active is not False:
                item["active"] = False
                disabled_packages.append(
                    {
                        "packageId": item.get("packageId"),
                        "packageName": item.get("packageName"),
                        "oldActive": before_active,
                        "newActive": False,
                    }
                )

    package_info_save_response: dict[str, Any] | None = None
    if disabled_packages:
        package_info_save_response = client.save_package_info(draft, package_info, stop_event, currency_context=currency_context)
        if not response_success(package_info_save_response):
            raise RuntimeError(f"PackageInfo 保存失败：{response_message(package_info_save_response)}")

    before_formal = [
        formal_price_record(client, product_id, package_id, resource_id, stop_event)
        for package_id, resource_id, _new_cost_price in args.item
    ]

    price_stock_draft = client.load_product_price_stock_draft(product_id, stop_event, refresh=True)
    if args.category_id:
        price_stock_draft["categoryId"] = int(args.category_id) if str(args.category_id).isdigit() else args.category_id
    if args.reserve_mode:
        price_stock_draft["reserveMode"] = int(args.reserve_mode) if str(args.reserve_mode).isdigit() else args.reserve_mode
    if args.product_version:
        price_stock_draft["productVersion"] = int(args.product_version) if str(args.product_version).isdigit() else args.product_version
    ensure_price_stock_draft_lists(price_stock_draft)

    package_price_stock_list = price_stock_draft.get("packagePriceAndStockList") or []
    price_stock_by_package = {
        str(item.get("packageId") or ""): item
        for item in package_price_stock_list
        if isinstance(item, dict)
    }
    changes: list[dict[str, Any]] = []
    for package_id, resource_id, new_cost_price in args.item:
        package_price_stock = price_stock_by_package.get(package_id)
        if not isinstance(package_price_stock, dict):
            raise RuntimeError(f"PriceAndStock 草稿中未找到 packageId={package_id}")
        before_price_and_stock = package_price_stock_to_price_and_stock(package_price_stock)
        old_cost_price = current_cost_price(before_price_and_stock, resource_id)
        set_package_cost_price_draft(package_price_stock, resource_id, new_cost_price)
        draft_price_and_stock = copy.deepcopy(before_price_and_stock)
        draft_price_and_stock["resourcePriceList"] = copy.deepcopy((package_price_stock.get("price") or {}).get("resourcePriceDraftList") or [])
        changes.append(
            {
                "packageId": package_id,
                "resourceId": resource_id,
                "oldCostPriceInDraftSource": old_cost_price,
                "newCostPrice": new_cost_price,
                "afterCostPriceInDraftPayload": current_cost_price(draft_price_and_stock, resource_id),
            }
        )

    currency_context = build_currency_rewrite_context(product_id, price_stock_draft)
    price_payload = client.build_price_stock_save_payload(product_id, price_stock_draft, package_ids=None, currency_context=currency_context)
    price_response = client._request_json(SAVE_PRODUCT_DRAFT_URL, product_id, price_payload, stop_event, timeout=120)
    client.product_price_stock_cache.pop(str(product_id), None)
    client.product_price_stock_draft_cache.pop(str(product_id), None)
    if not response_success(price_response):
        raise RuntimeError(f"PriceAndStock 保存失败：{response_message(price_response)}")

    latest_draft = client.load_product(product_id, stop_event)
    latest_price_stock = client.load_product_price_stock_draft(product_id, stop_event, refresh=True)
    currency_context = build_currency_rewrite_context(product_id, latest_price_stock)
    main_payload = build_price_effect_main_save_payload(
        product_id,
        latest_draft.package_info,
        latest_price_stock,
        latest_draft.product_version,
        currency_context,
    )
    main_response = client._request_json(SAVE_PRODUCT_DRAFT_URL, product_id, main_payload, stop_event, timeout=120)

    after_formal: list[dict[str, Any]] = []
    for package_id, resource_id, new_cost_price in args.item:
        record = formal_price_record(client, product_id, package_id, resource_id, stop_event)
        record["expectedCostPrice"] = normalize_number_text(new_cost_price)
        record["ok"] = normalize_number_text(record.get("costPrice")) == normalize_number_text(new_cost_price)
        after_formal.append(record)

    record = {
        "createdAt": now_iso(),
        "command": args.command,
        "productId": product_id,
        "disabledPackages": disabled_packages,
        "packageInfoSaveResponseBaseData": package_info_save_response.get("responseBaseData") if isinstance(package_info_save_response, dict) else None,
        "beforeFormal": before_formal,
        "changes": changes,
        "priceSave": {
            "requestSummary": {
                "type": price_payload.get("type"),
                "draftTypes": price_payload.get("draftTypes"),
                "packageCount": len(price_payload.get("packagePriceAndStockList") or []),
                "productVersion": price_payload.get("productVersion"),
            },
            "responseBaseData": price_response.get("responseBaseData"),
        },
        "mainSave": {
            "requestSummary": {
                "type": main_payload.get("type"),
                "draftTypes": main_payload.get("draftTypes"),
                "draftTypesRequired": main_payload.get("draftTypesRequired"),
                "effectMarks": main_payload.get("effectMarks"),
                "packageCount": len(main_payload.get("packagePriceAndStockList") or []),
                "productVersion": main_payload.get("productVersion"),
            },
            "responseBaseData": main_response.get("responseBaseData"),
        },
        "afterFormal": after_formal,
        "success": response_success(price_response) and response_success(main_response) and all(item["ok"] for item in after_formal),
    }

    path = cli_output_path(product_id, args.command, args.output)
    path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "success": record["success"],
                "output": str(path),
                "changes": changes,
                "afterFormal": after_formal,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if record["success"] else 1


def run_image_show_cli(args: argparse.Namespace) -> int:
    product_id = normalize_number_text(args.product_id)
    stop_event = threading.Event()
    client = CtripRequestsClient(cli_log, request_interval_seconds=args.request_interval)
    info = client.load_product_info_draft(product_id, stop_event)
    rows = product_image_effective_language_rows(info)
    result = {
        "productId": product_id,
        "siteCount": len(rows),
        "sites": [
            {
                "languageCode": row.get("languageCode"),
                "languagelocale": row.get("languagelocale"),
                "imageCount": len(row.get("imageList", [])),
                "imageIds": [
                    item.get("imageId")
                    for item in row.get("imageList", [])
                    if isinstance(item, dict)
                ],
                "imageUrls": [
                    item.get("imageUrl")
                    for item in row.get("imageList", [])
                    if isinstance(item, dict)
                ],
            }
            for row in rows
            if isinstance(row, dict)
        ],
    }
    path = cli_output_path(product_id, args.command, args.output)
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    cli_log(f"产品 {product_id} 共 {len(rows)} 个语言站点")
    for row in rows:
        if not isinstance(row, dict):
            continue
        images = row.get("imageList", [])
        cli_log(
            f"  {row.get('languageCode')} ({row.get('languagelocale')})："
            f"{len(images) if isinstance(images, list) else 0} 张图片"
        )
    print(json.dumps({"success": True, "output": str(path)}, ensure_ascii=False, indent=2))
    return 0


def run_image_copy_all_cli(args: argparse.Namespace) -> int:
    if not args.confirm_live_write:
        print("拒绝执行真实写入：image-copy-all 必须添加 --confirm-live-write", file=sys.stderr)
        return 2
    product_id = normalize_number_text(args.product_id)
    source_code = args.source.strip()
    stop_event = threading.Event()
    client = CtripRequestsClient(cli_log, request_interval_seconds=args.request_interval)

    # 1. 读取产品信息
    info = client.load_product_info_draft(product_id, stop_event)
    rows = product_image_effective_language_rows(info)
    from product_image_workspace_state import copy_site_plan, make_product_editor_state
    state = make_product_editor_state(product_id, info, rows)

    if source_code not in state.sites:
        codes = list(state.sites)
        print(f"源站点 {source_code} 不在产品站点列表中。可用站点：{codes}", file=sys.stderr)
        return 1

    source_site = state.sites[source_code]
    target_codes = [code for code in state.sites if code != source_code]
    cli_log(f"将源站点 {source_site.label} ({source_code}) 的 {len(source_site.planned)} 张头图应用到其他 {len(target_codes)} 个站点")

    # 2. 复制到全部站点
    copy_site_plan(state, source_code, target_codes)

    # 3. 保存并验证
    verification = save_and_verify_product_image_workspace(
        client,
        state,
        stop_event,
    )

    result = {
        "productId": product_id,
        "sourceSite": source_code,
        "targetCount": len(target_codes),
        "verification": {
            "ok": verification.ok,
            "siteErrors": {k: v for k, v in verification.site_errors.items()},
            "siteCount": len(verification.actual_by_site),
            "sites": {
                code: [list(key) for key in keys]
                for code, keys in verification.actual_by_site.items()
            },
        },
    }
    path = cli_output_path(product_id, args.command, args.output)
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    if verification.ok:
        cli_log(f"保存成功！全部 {len(verification.actual_by_site)} 个站点已更新为源站点的头图序列")
    else:
        cli_log("校验失败：")
        for site, error in verification.site_errors.items():
            cli_log(f"  {site}：{error}")

    success = verification.ok
    print(json.dumps({"success": success, "output": str(path)}, ensure_ascii=False, indent=2))
    return 0 if success else 1


def run_image_cli(args: argparse.Namespace) -> int:
    if args.command == "image-show":
        return run_image_show_cli(args)
    if args.command == "image-copy-all":
        return run_image_copy_all_cli(args)
    return 1


def run_price_cli(args: argparse.Namespace) -> int:
    if args.command in {"price-apply", "price-effect"} and not args.confirm_live_write:
        print(f"拒绝执行真实写入：{args.command} 必须添加 --confirm-live-write", file=sys.stderr)
        return 2
    product_id = normalize_number_text(args.product_id)
    stop_event = threading.Event()
    client = CtripRequestsClient(cli_log, request_interval_seconds=args.request_interval)
    if args.command == "price-effect":
        return run_price_effect_cli(args, client, stop_event, product_id)
    price_stock_draft = client.load_product_price_stock_draft(product_id, stop_event, refresh=True)
    if args.category_id:
        price_stock_draft["categoryId"] = int(args.category_id) if str(args.category_id).isdigit() else args.category_id
    if args.reserve_mode:
        price_stock_draft["reserveMode"] = int(args.reserve_mode) if str(args.reserve_mode).isdigit() else args.reserve_mode
    if args.product_version:
        price_stock_draft["productVersion"] = int(args.product_version) if str(args.product_version).isdigit() else args.product_version

    package_price_stock_list = price_stock_draft.get("packagePriceAndStockList") or []
    price_stock_by_package = {
        str(item.get("packageId") or ""): item
        for item in package_price_stock_list
        if isinstance(item, dict)
    }
    changes: list[dict[str, Any]] = []
    package_ids: set[str] = set()
    for package_id, resource_id, new_cost_price in args.item:
        package_price_stock = price_stock_by_package.get(package_id)
        if not isinstance(package_price_stock, dict):
            raise RuntimeError(f"PriceAndStock 草稿中未找到 packageId={package_id}")
        before_price_and_stock = package_price_stock_to_price_and_stock(package_price_stock)
        old_cost_price = current_cost_price(before_price_and_stock, resource_id)
        set_package_cost_price(package_price_stock, resource_id, new_cost_price)
        after_price_and_stock = package_price_stock_to_price_and_stock(package_price_stock)
        changes.append(
            {
                "packageId": package_id,
                "resourceId": resource_id,
                "oldCostPrice": old_cost_price,
                "newCostPrice": new_cost_price,
                "afterCostPriceInPayload": current_cost_price(after_price_and_stock, resource_id),
            }
        )
        package_ids.add(package_id)

    currency_context = build_currency_rewrite_context(product_id, price_stock_draft)
    payload = client.build_price_stock_save_payload(product_id, price_stock_draft, package_ids, currency_context=currency_context)
    record: dict[str, Any] = {
        "createdAt": now_iso(),
        "command": args.command,
        "productId": product_id,
        "changes": changes,
        "request": payload,
        "applied": False,
    }

    if args.command == "price-apply":
        response = client.save_product_price_stock_draft(product_id, price_stock_draft, stop_event, package_ids, currency_context=currency_context)
        record["response"] = response
        record["applied"] = True
        verify_map = client.load_product_price_stock(product_id, stop_event, refresh=True)
        verify: list[dict[str, Any]] = []
        for package_id, resource_id, new_cost_price in args.item:
            verified_package = verify_map.get(package_id)
            verified_price_and_stock = package_price_stock_to_price_and_stock(verified_package) if isinstance(verified_package, dict) else {}
            verified_cost = current_cost_price(verified_price_and_stock, resource_id)
            verify.append(
                {
                    "packageId": package_id,
                    "resourceId": resource_id,
                    "expectedCostPrice": new_cost_price,
                    "verifiedCostPrice": verified_cost,
                    "ok": verified_cost == normalize_number_text(new_cost_price),
                }
            )
        record["verify"] = verify
        record["success"] = response_success(response) and all(item["ok"] for item in verify)
    else:
        record["success"] = True

    path = cli_output_path(product_id, args.command, args.output)
    path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"success": record["success"], "applied": record["applied"], "output": str(path), "changes": changes}, ensure_ascii=False, indent=2))
    return 0 if record["success"] else 1


def main() -> None:
    parser = build_cli_parser()
    args = parser.parse_args()
    if args.command in {"price-dry-run", "price-apply", "price-effect"}:
        raise SystemExit(run_price_cli(args))
    if args.command in {"image-show", "image-copy-all"}:
        raise SystemExit(run_image_cli(args))
    if QT_IMPORT_ERROR is not None:
        message = (
            "缺少 PyQt6，无法启动新版 GUI。\n\n"
            "请先在当前 Python 环境安装依赖：\n"
            "python3 -m pip install -r requirements.txt\n\n"
            f"当前错误：{QT_IMPORT_ERROR}"
        )
        try:
            import tkinter as tk
            from tkinter import messagebox

            root = tk.Tk()
            root.withdraw()
            messagebox.showerror("缺少 GUI 依赖", message)
            root.destroy()
        except Exception:
            print(message, file=sys.stderr)
        raise SystemExit(1)
    qt_app = QApplication(sys.argv)
    coordinator = ui_theme.SystemThemeCoordinator(qt_app, fluent_enabled=QFLUENT_AVAILABLE)
    coordinator.start()
    window = App()
    coordinator.themeApplied.connect(window._apply_global_theme)
    window._theme_coordinator = coordinator
    window._apply_global_theme()
    qt_app.aboutToQuit.connect(coordinator.stop)
    window.show()
    QTimer.singleShot(0, window.start_startup_auth_check)
    raise SystemExit(qt_app.exec())


if __name__ == "__main__":
    main()

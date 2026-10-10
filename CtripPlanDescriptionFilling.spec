# -*- mode: python ; coding: utf-8 -*-
"""Cross-platform PyInstaller spec for CtripPlanDescriptionFilling.

Build from the repository root:

    pyinstaller --clean --noconfirm CtripPlanDescriptionFilling.spec

This spec builds a single-file executable on Windows so the app can be shared as
one EXE. macOS keeps an app bundle because PyQt6/Qt plugins are more reliable
there when preserved as bundled files.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from PyInstaller.config import CONF
from PyInstaller.utils.hooks import collect_all, collect_data_files, collect_submodules


block_cipher = None
CONF["noconfirm"] = True

PROJECT_ROOT = Path(SPECPATH).resolve()
ENTRY_SCRIPT = PROJECT_ROOT / "ctrip_package_intro_filling.pyw"
APP_NAME = "CtripPlanDescriptionFilling"

is_macos = sys.platform == "darwin"

macos_codesign_identity = os.environ.get("MACOS_CODESIGN_IDENTITY") or None
macos_target_arch = os.environ.get("MACOS_TARGET_ARCH") or None

if is_macos:
    # PyInstaller otherwise logs bundle-signing failures as warnings and can
    # leave a build that macOS reports as damaged after download.
    os.environ.setdefault("PYINSTALLER_STRICT_BUNDLE_CODESIGN_ERROR", "1")
    os.environ.setdefault("PYINSTALLER_VERIFY_BUNDLE_SIGNATURE", "1")


def package_available(module_name: str) -> bool:
    try:
        __import__(module_name)
        return True
    except Exception:
        return False


datas = []
binaries = []
hiddenimports = [
    "openpyxl",
    "requests",
    "translation_rules",
    "ctrip_image_upload",
    "product_image_workspace",
    "product_image_workspace_state",
    "workflow_common",
    "ctrip_transport",
    "docking_config",
    "translation_management",
    "product_edit",
    "product_images",
    "PyQt6.QtCore",
    "PyQt6.QtGui",
    "PyQt6.QtNetwork",
    "PyQt6.QtPrintSupport",
    "PyQt6.QtSvg",
    "PyQt6.QtWidgets",
]

excludedimports = [
    "PyQt5",
    "PySide2",
    "PySide6",
    "tkinter",
    "unittest",
]

# qfluentwidgets performs dynamic imports and ships style/font/image data.
# collect_all keeps the same spec usable across package versions.
if package_available("qfluentwidgets"):
    qfw_datas, qfw_binaries, qfw_hiddenimports = collect_all("qfluentwidgets")
    datas += qfw_datas
    binaries += qfw_binaries
    hiddenimports += qfw_hiddenimports

# Keep only non-Qt package data explicit. PyInstaller's PyQt6 hooks are better
# at selecting the platform-specific Qt plugins without duplicating macOS
# framework symlinks.
for module_name in ("openpyxl", "certifi"):
    if package_available(module_name):
        datas += collect_data_files(module_name)

# Operator manual opened from the translation tab ("操作手册" link).
datas += [(str(PROJECT_ROOT / "docs" / "translation_ops_manual.md"), "docs")]

if package_available("charset_normalizer"):
    hiddenimports += collect_submodules("charset_normalizer")

if package_available("idna"):
    hiddenimports += collect_submodules("idna")

runtime_hooks = []


a = Analysis(
    [str(ENTRY_SCRIPT)],
    pathex=[str(PROJECT_ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=sorted(set(hiddenimports)),
    hookspath=[],
    hooksconfig={},
    runtime_hooks=runtime_hooks,
    excludes=excludedimports,
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

_workflow_common_module = PROJECT_ROOT / "workflow_common.py"
if not _workflow_common_module.is_file():
    raise FileNotFoundError(f"Required packaging module is missing: {_workflow_common_module}")
workflow_common_node = ("workflow_common", str(_workflow_common_module), "PYMODULE")
if not any(module_name == "workflow_common" for module_name, *_ in a.pure):
    a.pure.append(workflow_common_node)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

if is_macos:
    exe = EXE(
        pyz,
        a.scripts,
        [],
        exclude_binaries=True,
        name=APP_NAME,
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=False,
        console=False,
        disable_windowed_traceback=False,
        argv_emulation=True,
        target_arch=macos_target_arch,
        codesign_identity=macos_codesign_identity,
        entitlements_file=None,
    )
    coll = COLLECT(
        exe,
        a.binaries,
        a.zipfiles,
        a.datas,
        strip=False,
        upx=False,
        upx_exclude=[],
        name=APP_NAME,
    )
    app = BUNDLE(
        coll,
        name=f"{APP_NAME}.app",
        icon=None,
        bundle_identifier="com.ctrip.plan-description-filling",
        info_plist={
            "CFBundleDisplayName": "Ctrip Plan Description Filling",
            "CFBundleName": APP_NAME,
            "CFBundleShortVersionString": "1.0.0",
            "CFBundleVersion": "1.0.0",
            "LSMinimumSystemVersion": "11.0",
            "NSHighResolutionCapable": True,
        },
    )
else:
    exe = EXE(
        pyz,
        a.scripts,
        a.binaries,
        a.zipfiles,
        a.datas,
        [],
        exclude_binaries=False,
        name=APP_NAME,
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=False,
        console=False,
        disable_windowed_traceback=False,
        argv_emulation=False,
        target_arch=None,
        codesign_identity=None,
        entitlements_file=None,
    )

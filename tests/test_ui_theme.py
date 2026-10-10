import time
import subprocess
import sys
import unittest
from unittest.mock import patch

from PyQt6.QtCore import QCoreApplication, QEvent
from PyQt6.QtGui import QColor, QPalette
from PyQt6.QtWidgets import QApplication

import ui_theme


QT_APP = QApplication.instance() or QApplication([])


def palette_with(window: str, base: str, text: str, highlight: str, link: str) -> QPalette:
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor(window))
    palette.setColor(QPalette.ColorRole.Base, QColor(base))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor(base))
    palette.setColor(QPalette.ColorRole.Text, QColor(text))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(text))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor(text))
    palette.setColor(QPalette.ColorRole.PlaceholderText, QColor(text))
    palette.setColor(QPalette.ColorRole.Mid, QColor(text))
    palette.setColor(QPalette.ColorRole.Highlight, QColor(highlight))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#ffffff"))
    palette.setColor(QPalette.ColorRole.Link, QColor(link))
    return palette


class SemanticThemeTests(unittest.TestCase):
    def test_semantic_colors_follow_palette_roles(self):
        palette = palette_with("#101820", "#18242e", "#edf6fb", "#35a7ff", "#45c17c")
        colors = ui_theme.semantic_colors(palette)
        self.assertEqual(colors["window"], "#101820")
        self.assertEqual(colors["base"], "#18242e")
        self.assertEqual(colors["text"], "#edf6fb")
        self.assertEqual(colors["accent"], "#35a7ff")
        self.assertEqual(colors["loaded"], "#45c17c")
        self.assertNotEqual(colors["card"], "#ffffff")

    def test_mix_colors_clamps_weight(self):
        self.assertEqual(ui_theme.mix_colors(QColor("#000000"), QColor("#ffffff"), -1).name(), "#000000")
        self.assertEqual(ui_theme.mix_colors(QColor("#000000"), QColor("#ffffff"), 2).name(), "#ffffff")
        self.assertEqual(ui_theme.mix_colors(QColor("#000000"), QColor("#ffffff"), 0.5).name(), "#808080")


class ApplicationPaletteTests(unittest.TestCase):
    def test_windows_dark_falls_back_when_qt_palette_is_light(self):
        light = palette_with("#f5f5f5", "#ffffff", "#101828", "#0067c0", "#0067c0")
        result = ui_theme.application_palette_for_theme(light, dark=True, platform_name="Windows")
        self.assertTrue(ui_theme.is_dark_palette(result))
        self.assertEqual(result.highlight().color().name(), "#0067c0")
        self.assertGreater(result.text().color().lightness(), result.base().color().lightness())

    def test_windows_dark_fallback_link_meets_wcag_contrast(self):
        light = palette_with("#f5f5f5", "#ffffff", "#101828", "#0067c0", "#000080")
        result = ui_theme.application_palette_for_theme(light, dark=True, platform_name="Windows")
        self.assertEqual(result.highlight().color().name(), "#0067c0")
        self.assertGreaterEqual(
            ui_theme.contrast_ratio(result.link().color(), result.base().color()),
            4.5,
        )

    def test_windows_keeps_valid_native_dark_palette(self):
        dark = palette_with("#202124", "#292a2d", "#f1f3f4", "#4c8bf5", "#7aa2f7")
        result = ui_theme.application_palette_for_theme(dark, dark=True, platform_name="Windows")
        self.assertEqual(result.window().color().name(), "#202124")
        self.assertEqual(result.link().color().name(), "#7aa2f7")

    def test_windows_light_falls_back_when_current_palette_is_dark(self):
        dark = palette_with("#202124", "#292a2d", "#f1f3f4", "#4c8bf5", "#7aa2f7")
        result = ui_theme.application_palette_for_theme(dark, dark=False, platform_name="Windows")
        self.assertFalse(ui_theme.is_dark_palette(result))
        self.assertLess(result.text().color().lightness(), result.base().color().lightness())

    def test_windows_light_fallback_link_meets_wcag_contrast(self):
        dark = palette_with("#202124", "#292a2d", "#f1f3f4", "#4c8bf5", "#64d2ff")
        result = ui_theme.application_palette_for_theme(dark, dark=False, platform_name="Windows")
        self.assertEqual(result.highlight().color().name(), "#4c8bf5")
        self.assertGreaterEqual(
            ui_theme.contrast_ratio(result.link().color(), result.base().color()),
            4.5,
        )

    def test_macos_keeps_matching_native_palettes(self):
        light = palette_with("#ececec", "#ffffff", "#1d1d1f", "#0a84ff", "#007aff")
        dark = palette_with("#1e1e1e", "#262626", "#f5f5f7", "#0a84ff", "#64d2ff")
        self.assertEqual(ui_theme.application_palette_for_theme(light, False, "Darwin").window().color().name(), "#ececec")
        self.assertEqual(ui_theme.application_palette_for_theme(dark, True, "Darwin").window().color().name(), "#1e1e1e")


class SystemThemeCoordinatorTests(unittest.TestCase):
    def test_default_palette_source_handles_listener_before_external_palette(self):
        original = QT_APP.palette()
        initial_light = palette_with("#eeeeee", "#fefefe", "#202020", "#106ebe", "#005fb8")
        later_standard_dark = palette_with("#18191a", "#252627", "#f7f7f7", "#60a5fa", "#77b7ff")
        external_dark = palette_with("#111315", "#202326", "#fafafa", "#8b5cf6", "#a78bfa")
        standard = QPalette(initial_light)
        try:
            QT_APP.setPalette(initial_light)
            coordinator = ui_theme.SystemThemeCoordinator(QT_APP, platform_name="Windows", fluent_enabled=False)
            with patch.object(coordinator, "_standard_palette", side_effect=lambda: QPalette(standard)):
                coordinator.set_effective_dark_for_test(False)
                coordinator.apply_theme()

                # Listener arrives first while Qt/style still exposes light roles.
                coordinator.set_effective_dark_for_test(True)
                coordinator.apply_theme()
                self.assertTrue(ui_theme.is_dark_palette(QT_APP.palette()))
                self.assertNotEqual(QT_APP.palette().window().color().name(), initial_light.window().color().name())

                # current == last-applied: the production default must re-read style.
                standard = QPalette(later_standard_dark)
                coordinator.apply_theme()
                self.assertEqual(QT_APP.palette().window().color().name(), "#18191a")
                self.assertEqual(QT_APP.palette().link().color().name(), "#77b7ff")

                # A still-later external QApplication palette must supersede last-applied.
                QT_APP.setPalette(external_dark)
                coordinator.apply_theme()
                self.assertEqual(QT_APP.palette().window().color().name(), "#111315")
                self.assertEqual(QT_APP.palette().link().color().name(), "#a78bfa")
        finally:
            QT_APP.setPalette(original)

    def test_palette_source_restores_each_new_native_palette_across_theme_changes(self):
        original = QT_APP.palette()
        native_palettes = [
            palette_with("#eeeeee", "#fefefe", "#202020", "#106ebe", "#005fb8"),
            palette_with("#171717", "#242424", "#f8f8f8", "#60a5fa", "#77b7ff"),
            palette_with("#e8e8e8", "#fafafa", "#181818", "#8a4fff", "#6633cc"),
        ]
        index = 0

        def palette_source():
            return QPalette(native_palettes[index])

        try:
            coordinator = ui_theme.SystemThemeCoordinator(
                QT_APP,
                platform_name="Windows",
                fluent_enabled=False,
                palette_source=palette_source,
            )
            for next_index, dark in ((0, False), (1, True), (2, False), (1, True)):
                index = next_index
                coordinator.set_effective_dark_for_test(dark)
                coordinator.apply_theme()
                self.assertEqual(
                    QT_APP.palette().window().color().name(),
                    native_palettes[index].window().color().name(),
                )
                self.assertEqual(
                    QT_APP.palette().link().color().name(),
                    native_palettes[index].link().color().name(),
                )
        finally:
            QT_APP.setPalette(original)

    def test_schedule_refresh_coalesces_duplicate_events(self):
        coordinator = ui_theme.SystemThemeCoordinator(QT_APP, fluent_enabled=False)
        calls = []
        coordinator.apply_theme = lambda: calls.append(True)
        coordinator.schedule_refresh()
        coordinator.schedule_refresh()
        QT_APP.processEvents()
        self.assertEqual(calls, [True])

    def test_stop_without_listener_is_safe(self):
        coordinator = ui_theme.SystemThemeCoordinator(QT_APP, fluent_enabled=False)
        coordinator.stop()
        self.assertIsNone(coordinator.listener)

    def test_apply_theme_updates_application_palette_and_emits_once(self):
        original = QT_APP.palette()
        light = palette_with("#f5f5f5", "#ffffff", "#101828", "#0067c0", "#0067c0")
        try:
            QT_APP.setPalette(light)
            coordinator = ui_theme.SystemThemeCoordinator(QT_APP, platform_name="Windows", fluent_enabled=False)
            coordinator.set_effective_dark_for_test(True)
            emitted = []
            coordinator.themeApplied.connect(lambda: emitted.append(True))
            coordinator.apply_theme()
            self.assertTrue(ui_theme.is_dark_palette(QT_APP.palette()))
            self.assertEqual(emitted, [True])
        finally:
            QT_APP.setPalette(original)

    def test_reentrant_refresh_is_ignored(self):
        coordinator = ui_theme.SystemThemeCoordinator(QT_APP, fluent_enabled=False)
        coordinator._refreshing = True
        emitted = []
        coordinator.themeApplied.connect(lambda: emitted.append(True))
        coordinator.apply_theme()
        self.assertEqual(emitted, [])

    def test_start_failure_disables_fluent_cleans_listener_and_applies_native_palette(self):
        class FakeSignal:
            def connect(self, slot):
                self.slot = slot

            def disconnect(self, slot):
                self.slot = None

        class FailingStartListener:
            instance = None

            def __init__(self, parent):
                self.systemThemeChanged = FakeSignal()
                self.finished = FakeSignal()
                self.interruption_requested = False
                FailingStartListener.instance = self

            def start(self):
                raise RuntimeError("listener boom")

            def requestInterruption(self):
                self.interruption_requested = True

            def wait(self, timeout):
                return True

        class FakeConfig:
            themeChanged = FakeSignal()

        original = QT_APP.palette()
        light = palette_with("#f5f5f5", "#ffffff", "#101828", "#0067c0", "#0067c0")
        try:
            QT_APP.setPalette(light)
            with (
                patch.object(ui_theme, "FLUENT_THEME_AVAILABLE", True),
                patch.object(ui_theme, "setTheme"),
                patch.object(ui_theme, "SafeSystemThemeListener", FailingStartListener),
                patch.object(ui_theme, "qconfig", FakeConfig()),
            ):
                coordinator = ui_theme.SystemThemeCoordinator(QT_APP, platform_name="Windows")
                coordinator.set_effective_dark_for_test(True)
                emitted = []
                coordinator.themeApplied.connect(lambda: emitted.append(True))
                with self.assertLogs(ui_theme.LOGGER, level="WARNING") as logs:
                    coordinator.start()
            self.assertFalse(coordinator.fluent_enabled)
            self.assertIsNone(coordinator.listener)
            self.assertTrue(FailingStartListener.instance.interruption_requested)
            self.assertTrue(ui_theme.is_dark_palette(QT_APP.palette()))
            self.assertEqual(emitted, [True])
            self.assertEqual(len(logs.output), 1)
            self.assertIn("listener boom", logs.output[0])
        finally:
            QT_APP.setPalette(original)

    def test_start_failure_uses_auto_theme_value_resolved_before_listener_failure(self):
        class FakeSignal:
            def connect(self, slot):
                self.slot = slot

            def disconnect(self, slot):
                self.slot = None

        class FailingListener:
            def __init__(self, _parent=None):
                self.systemThemeChanged = FakeSignal()
                self.finished = FakeSignal()

            def start(self):
                raise RuntimeError("listener start failed")

            def requestInterruption(self):
                pass

            def wait(self, _timeout):
                return True

        class FakeConfig:
            themeChanged = FakeSignal()

        original = QT_APP.palette()
        light = palette_with("#f5f5f5", "#ffffff", "#101828", "#0067c0", "#0067c0")
        try:
            QT_APP.setPalette(light)
            with (
                patch.object(ui_theme, "FLUENT_THEME_AVAILABLE", True),
                patch.object(ui_theme, "setTheme"),
                patch.object(ui_theme, "isDarkTheme", return_value=True),
                patch.object(ui_theme, "SafeSystemThemeListener", FailingListener),
                patch.object(ui_theme, "qconfig", FakeConfig()),
                self.assertLogs(ui_theme.LOGGER, level="WARNING"),
            ):
                coordinator = ui_theme.SystemThemeCoordinator(QT_APP, platform_name="Windows")
                coordinator.start()
            self.assertFalse(coordinator.fluent_enabled)
            self.assertTrue(ui_theme.is_dark_palette(QT_APP.palette()))
        finally:
            QT_APP.setPalette(original)

    @unittest.skipUnless(ui_theme.SafeSystemThemeListener is not None, "QFluent listener unavailable")
    def test_real_listener_stop_is_cooperative_and_bounded(self):
        calls = []

        def theme():
            calls.append(True)
            return "Dark"

        with patch.object(ui_theme.darkdetect, "theme", side_effect=theme):
            listener = ui_theme.SafeSystemThemeListener()
            listener.start()
            deadline = time.monotonic() + 0.5
            while not calls and time.monotonic() < deadline:
                QT_APP.processEvents()
                time.sleep(0.01)
            self.assertTrue(calls)
            started = time.monotonic()
            listener.requestInterruption()
            self.assertTrue(listener.wait(500))
            self.assertLess(time.monotonic() - started, 0.5)

    @unittest.skipUnless(ui_theme.SafeSystemThemeListener is not None, "QFluent listener unavailable")
    def test_real_listener_survives_coordinator_destruction_without_qthread_parent(self):
        with (
            patch.object(ui_theme, "setTheme"),
            patch.object(ui_theme, "isDarkTheme", return_value=False),
            patch.object(ui_theme.darkdetect, "theme", return_value="Light"),
        ):
            coordinator = ui_theme.SystemThemeCoordinator(QT_APP)
            coordinator.start()
            listener = coordinator.listener
            self.assertIsNone(listener.parent())
            coordinator.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
            QT_APP.processEvents()
            self.assertTrue(listener.wait(500))

    def test_stop_terminates_listener_after_interruption_timeout(self):
        class FakeListener:
            def __init__(self):
                self.wait_results = [False, True]
                self.interruption_requested = False
                self.terminated = False
                self.wait_timeouts = []

            def requestInterruption(self):
                self.interruption_requested = True

            def terminate(self):
                self.terminated = True

            def wait(self, timeout):
                self.wait_timeouts.append(timeout)
                return self.wait_results.pop(0)

        coordinator = ui_theme.SystemThemeCoordinator(QT_APP, fluent_enabled=False)
        listener = FakeListener()
        coordinator.listener = listener
        with self.assertLogs(ui_theme.LOGGER, level="WARNING"):
            coordinator.stop()
        self.assertTrue(listener.interruption_requested)
        self.assertTrue(listener.terminated)
        self.assertEqual(listener.wait_timeouts, [2500, 2500])
        self.assertIsNone(coordinator.listener)

    def test_stop_guards_listener_when_fallback_timeout_expires_and_releases_on_finish(self):
        class FakeSignal:
            def __init__(self):
                self.slots = []

            def connect(self, slot):
                self.slots.append(slot)

            def emit(self):
                for slot in list(self.slots):
                    slot()

        class FakeListener:
            def __init__(self):
                self.finished = FakeSignal()

            def requestInterruption(self):
                pass

            def terminate(self):
                pass

            def wait(self, timeout):
                return False

        coordinator = ui_theme.SystemThemeCoordinator(QT_APP, fluent_enabled=False)
        listener = FakeListener()
        coordinator.listener = listener
        with self.assertLogs(ui_theme.LOGGER, level="WARNING"):
            coordinator.stop()
        self.assertIsNone(coordinator.listener)
        self.assertIn(listener, ui_theme._UNSTOPPABLE_LISTENER_GUARD)
        listener.finished.emit()
        self.assertNotIn(listener, ui_theme._UNSTOPPABLE_LISTENER_GUARD)

    def test_unstoppable_qthread_process_exit_is_safe_without_local_reference(self):
        script = r'''
import gc
import time
from PyQt6.QtCore import QThread
from PyQt6.QtWidgets import QApplication
import ui_theme

class StubbornThread(QThread):
    def run(self):
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline:
            self.msleep(50)

    def requestInterruption(self):
        return

    def terminate(self):
        return

    def wait(self, _timeout=0):
        return False

app = QApplication([])
coordinator = ui_theme.SystemThemeCoordinator(app, fluent_enabled=False)
coordinator.listener = StubbornThread()
coordinator.listener.start()
coordinator.stop()
assert coordinator.listener is None
del coordinator
gc.collect()
'''
        result = subprocess.run(
            [sys.executable, "-c", script],
            cwd=__import__("pathlib").Path(ui_theme.__file__).parent,
            env={**__import__("os").environ, "QT_QPA_PLATFORM": "offscreen"},
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("QThread: Destroyed while thread is still running", result.stderr)

    def test_guard_releases_real_qthread_that_finished_before_signal_connection(self):
        from PyQt6.QtCore import QThread

        class AlreadyFinishedThread(QThread):
            def run(self):
                return

        listener = AlreadyFinishedThread()
        listener.start()
        self.assertTrue(listener.wait(1000))
        self.assertTrue(listener.isFinished())
        try:
            ui_theme._guard_unstoppable_listener(listener)
            QT_APP.processEvents()
            self.assertNotIn(listener, ui_theme._UNSTOPPABLE_LISTENER_GUARD)
        finally:
            if listener in ui_theme._UNSTOPPABLE_LISTENER_GUARD:
                ui_theme._UNSTOPPABLE_LISTENER_GUARD.discard(listener)
                if not ui_theme.sip.ispyowned(listener):
                    ui_theme.sip.transferback(listener)

    def test_unexpected_listener_finish_disables_fluent_and_schedules_native_refresh(self):
        class FakeSignal:
            def __init__(self):
                self.slots = []

            def connect(self, slot):
                self.slots.append(slot)

            def disconnect(self, slot):
                self.slots.remove(slot)

        class RaisingSafeListener(ui_theme.SafeSystemThemeListener):
            def _run_listener(self):
                raise RuntimeError("listener thread boom")

        class FakeConfig:
            themeChanged = FakeSignal()

        with (
            patch.object(ui_theme, "FLUENT_THEME_AVAILABLE", True),
            patch.object(ui_theme, "setTheme"),
            patch.object(ui_theme, "isDarkTheme", return_value=False),
            patch.object(ui_theme, "SafeSystemThemeListener", RaisingSafeListener),
            patch.object(ui_theme, "qconfig", FakeConfig()),
        ):
            coordinator = ui_theme.SystemThemeCoordinator(QT_APP)
            emitted = []
            coordinator.themeApplied.connect(lambda: emitted.append(True))
            coordinator.start()
            emitted.clear()
            listener = coordinator.listener
            with self.assertLogs(ui_theme.LOGGER, level="WARNING") as logs:
                self.assertTrue(listener.wait(1000))
                QT_APP.processEvents()
                QT_APP.processEvents()
                QT_APP.processEvents()
            self.assertFalse(coordinator.fluent_enabled)
            self.assertIsNone(coordinator.listener)
            self.assertFalse(coordinator._scheduled)
            self.assertEqual(emitted, [True])
            self.assertEqual(len(logs.output), 1)
            self.assertIn("unexpectedly", logs.output[0])
            self.assertIn("RuntimeError: listener thread boom", logs.output[0])

    def test_unexpected_listener_finish_caches_latest_effective_theme_before_fallback(self):
        class FinishedListener:
            run_error = "RuntimeError: listener failed after theme switch"

            def isRunning(self):
                return False

        original = QT_APP.palette()
        light = palette_with("#f5f5f5", "#ffffff", "#101828", "#0067c0", "#0067c0")
        try:
            QT_APP.setPalette(light)
            coordinator = ui_theme.SystemThemeCoordinator(QT_APP, platform_name="Windows")
            coordinator._startup_effective_dark = False
            coordinator.listener = FinishedListener()
            with (
                patch.object(ui_theme, "isDarkTheme", return_value=True),
                self.assertLogs(ui_theme.LOGGER, level="WARNING"),
            ):
                coordinator._on_listener_finished()
                QT_APP.processEvents()
            self.assertFalse(coordinator.fluent_enabled)
            self.assertTrue(ui_theme.is_dark_palette(QT_APP.palette()))
        finally:
            QT_APP.setPalette(original)

    def test_normal_stop_does_not_warn_or_schedule_native_refresh(self):
        class FakeSignal:
            def __init__(self):
                self.slots = []

            def connect(self, slot):
                self.slots.append(slot)

            def disconnect(self, slot):
                self.slots.remove(slot)

            def emit(self):
                for slot in list(self.slots):
                    slot()

        class FakeListener:
            def __init__(self, parent):
                self.systemThemeChanged = FakeSignal()
                self.finished = FakeSignal()
                self.running = False

            def start(self):
                self.running = True

            def requestInterruption(self):
                pass

            def wait(self, timeout):
                self.running = False
                self.finished.emit()
                return True

            def isRunning(self):
                return self.running

        class FakeConfig:
            themeChanged = FakeSignal()

        with (
            patch.object(ui_theme, "FLUENT_THEME_AVAILABLE", True),
            patch.object(ui_theme, "setTheme"),
            patch.object(ui_theme, "SafeSystemThemeListener", FakeListener),
            patch.object(ui_theme, "qconfig", FakeConfig()),
        ):
            coordinator = ui_theme.SystemThemeCoordinator(QT_APP)
            coordinator.start()
            coordinator._scheduled = False
            with self.assertNoLogs(ui_theme.LOGGER, level="WARNING"):
                coordinator.stop()
            self.assertIsNone(coordinator.listener)
            self.assertFalse(coordinator._scheduled)

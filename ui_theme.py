from __future__ import annotations

import logging
import platform
from typing import Any, Callable

from PyQt6 import sip
from PyQt6.QtCore import QObject, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QPalette
from PyQt6.QtWidgets import QApplication

try:
    from qfluentwidgets import Theme, SystemThemeListener, isDarkTheme, qconfig, setTheme
    from qfluentwidgets.common.theme_listener import darkdetect
    FLUENT_THEME_AVAILABLE = True
except Exception:
    Theme = SystemThemeListener = darkdetect = isDarkTheme = qconfig = setTheme = None
    FLUENT_THEME_AVAILABLE = False


LOGGER = logging.getLogger(__name__)
_UNSTOPPABLE_LISTENER_GUARD: set[Any] = set()


def _guard_unstoppable_listener(listener: Any) -> None:
    """Keep a failed-stop QThread alive without Python deleting it at shutdown."""
    _UNSTOPPABLE_LISTENER_GUARD.add(listener)

    def release_guard() -> None:
        if listener not in _UNSTOPPABLE_LISTENER_GUARD:
            return
        _UNSTOPPABLE_LISTENER_GUARD.discard(listener)
        try:
            listener.deleteLater()
        except Exception:
            pass
    try:
        # PyQt6 does not expose sip.setdestroyonexit(). Transfer C++ ownership
        # instead so interpreter teardown cannot destroy a running QThread.
        sip.transferto(listener, None)
    except Exception as exc:
        # A non-SIP test double is harmless at interpreter teardown.
        if isinstance(listener, QObject):
            LOGGER.critical("Unable to transfer unstoppable QThread ownership: %s", exc)
    try:
        listener.finished.connect(release_guard)
    except Exception:
        return
    try:
        finished = bool(listener.isFinished()) or not bool(listener.isRunning())
    except Exception:
        finished = False
    if finished:
        # Covers the race where finished was emitted after the failed wait but
        # before the cleanup connection above was installed.
        release_guard()


if FLUENT_THEME_AVAILABLE:
    class SafeSystemThemeListener(SystemThemeListener):
        """QFluent-compatible listener whose worker loop is cooperatively cancellable."""

        _themeDetected = pyqtSignal(str)

        def __init__(self, parent: QObject | None = None):
            super().__init__(parent)
            self.run_error: str | None = None
            self._themeDetected.connect(self._apply_detected_theme)

        def run(self) -> None:
            try:
                self._run_listener()
            except BaseException as exc:
                self.run_error = f"{type(exc).__name__}: {exc}"

        def _run_listener(self) -> None:
            previous_theme: str | None = None
            while not self.isInterruptionRequested():
                detected = darkdetect.theme()
                theme = str(detected or "Light").lower()
                if theme != previous_theme:
                    previous_theme = theme
                    self._themeDetected.emit(theme)
                self.msleep(100)

        def _apply_detected_theme(self, theme: str) -> None:
            # QThread instances retain the creating (GUI) thread's affinity, so
            # this queued slot keeps QFluent configuration changes off the worker.
            self._onThemeChanged(theme)
else:
    SafeSystemThemeListener = None


def mix_colors(first: QColor, second: QColor, second_weight: float) -> QColor:
    weight = max(0.0, min(1.0, float(second_weight)))
    first_weight = 1.0 - weight
    return QColor(
        round(first.red() * first_weight + second.red() * weight),
        round(first.green() * first_weight + second.green() * weight),
        round(first.blue() * first_weight + second.blue() * weight),
    )


def is_dark_palette(palette: QPalette) -> bool:
    return palette.window().color().lightness() < 128


def _relative_luminance(color: QColor) -> float:
    channels = []
    for value in (color.redF(), color.greenF(), color.blueF()):
        channels.append(value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4)
    return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]


def contrast_ratio(first: QColor, second: QColor) -> float:
    lighter, darker = sorted((_relative_luminance(first), _relative_luminance(second)), reverse=True)
    return (lighter + 0.05) / (darker + 0.05)


def readable_color_from_hue(color: QColor, background: QColor, minimum_ratio: float = 4.5) -> QColor:
    """Keep the source hue while moving only lightness enough for readable text."""
    if contrast_ratio(color, background) >= minimum_ratio:
        return QColor(color)
    hue, saturation, lightness, alpha = color.getHsl()
    if hue < 0:
        saturation = 0
    for distance in range(1, 256):
        for candidate_lightness in (lightness + distance, lightness - distance):
            if not 0 <= candidate_lightness <= 255:
                continue
            candidate = QColor.fromHsl(max(0, hue), saturation, candidate_lightness, alpha)
            if contrast_ratio(candidate, background) >= minimum_ratio:
                return candidate
    return QColor("#ffffff") if contrast_ratio(QColor("#ffffff"), background) >= minimum_ratio else QColor("#000000")


def semantic_colors(palette: QPalette) -> dict[str, str]:
    window = palette.window().color()
    base = palette.base().color()
    button = palette.button().color()
    text = palette.text().color()
    muted = palette.placeholderText().color()
    border = palette.mid().color()
    accent = palette.highlight().color()
    accent_text = palette.highlightedText().color()
    link = palette.link().color()
    return {
        "window": window.name(),
        "base": base.name(),
        "card": mix_colors(window, base, 0.68).name(),
        "header": mix_colors(button, base, 0.32).name(),
        "subcard": mix_colors(window, base, 0.86).name(),
        "text": text.name(),
        "muted": muted.name(),
        "border": border.name(),
        "strong_border": mix_colors(border, text, 0.24).name(),
        "accent": accent.name(),
        "accent_text": accent_text.name(),
        "link": link.name(),
        "loaded": link.name(),
        "selection": accent.name(),
        "selection_text": accent_text.name(),
    }


def application_palette_for_theme(base: QPalette, dark: bool, platform_name: str) -> QPalette:
    result = QPalette(base)
    if is_dark_palette(result) == bool(dark):
        return result

    accent = result.highlight().color()
    link = result.link().color()
    if not dark:
        light_fallback = {
            QPalette.ColorRole.Window: "#f3f3f3",
            QPalette.ColorRole.WindowText: "#1b1b1b",
            QPalette.ColorRole.Base: "#ffffff",
            QPalette.ColorRole.AlternateBase: "#f5f5f5",
            QPalette.ColorRole.Text: "#1b1b1b",
            QPalette.ColorRole.Button: "#f3f3f3",
            QPalette.ColorRole.ButtonText: "#1b1b1b",
            QPalette.ColorRole.Mid: "#8a8a8a",
            QPalette.ColorRole.Light: "#ffffff",
            QPalette.ColorRole.HighlightedText: "#ffffff",
            QPalette.ColorRole.PlaceholderText: "#6f6f6f",
            QPalette.ColorRole.ToolTipBase: "#ffffff",
            QPalette.ColorRole.ToolTipText: "#1b1b1b",
        }
        for role, color in light_fallback.items():
            result.setColor(role, QColor(color))
        result.setColor(QPalette.ColorRole.Highlight, accent)
        result.setColor(
            QPalette.ColorRole.Link,
            readable_color_from_hue(link, result.base().color()),
        )
        return result

    fallback = {
        QPalette.ColorRole.Window: "#202124",
        QPalette.ColorRole.WindowText: "#f1f3f4",
        QPalette.ColorRole.Base: "#292a2d",
        QPalette.ColorRole.AlternateBase: "#303134",
        QPalette.ColorRole.Text: "#f1f3f4",
        QPalette.ColorRole.Button: "#303134",
        QPalette.ColorRole.ButtonText: "#f1f3f4",
        QPalette.ColorRole.Mid: "#5f6368",
        QPalette.ColorRole.Light: "#3c4043",
        QPalette.ColorRole.HighlightedText: "#ffffff",
        QPalette.ColorRole.PlaceholderText: "#9aa0a6",
        QPalette.ColorRole.ToolTipBase: "#303134",
        QPalette.ColorRole.ToolTipText: "#f1f3f4",
    }
    for role, color in fallback.items():
        result.setColor(role, QColor(color))
    result.setColor(QPalette.ColorRole.Highlight, accent)
    result.setColor(
        QPalette.ColorRole.Link,
        readable_color_from_hue(link, result.base().color()),
    )
    return result


class SystemThemeCoordinator(QObject):
    themeApplied = pyqtSignal()

    def __init__(
        self,
        app: QApplication,
        platform_name: str | None = None,
        fluent_enabled: bool = True,
        parent: QObject | None = None,
        palette_source: Callable[[], QPalette] | None = None,
    ):
        super().__init__(parent)
        self.app = app
        self.platform_name = platform_name or platform.system()
        self.fluent_enabled = bool(fluent_enabled and FLUENT_THEME_AVAILABLE)
        self.listener: Any = None
        self._refreshing = False
        self._scheduled = False
        self._test_dark: bool | None = None
        self._listener_theme_connected = False
        self._listener_finished_connected = False
        self._config_theme_connected = False
        self._stopping = False
        self._unexpected_finish_handled = False
        self._palette_source = palette_source
        self._last_applied_palette: QPalette | None = None
        self._startup_effective_dark: bool | None = None

    def set_effective_dark_for_test(self, dark: bool | None) -> None:
        self._test_dark = dark

    def effective_dark(self) -> bool:
        if self._test_dark is not None:
            return self._test_dark
        if self.fluent_enabled:
            return bool(isDarkTheme())
        if self._startup_effective_dark is not None:
            return self._startup_effective_dark
        return is_dark_palette(self.app.palette())

    def start(self) -> None:
        self._stopping = False
        self._unexpected_finish_handled = False
        if self.fluent_enabled:
            try:
                setTheme(Theme.AUTO, save=False)
                # Cache AUTO's resolved value before any later listener setup can
                # fail and force the native fallback path.
                self._startup_effective_dark = bool(isDarkTheme())
                self.listener = SafeSystemThemeListener(None)
                self.destroyed.connect(self.listener.requestInterruption)
                self.listener.systemThemeChanged.connect(self.schedule_refresh)
                self._listener_theme_connected = True
                self.listener.finished.connect(self._on_listener_finished)
                self._listener_finished_connected = True
                qconfig.themeChanged.connect(self.schedule_refresh)
                self._config_theme_connected = True
                self.listener.start()
            except Exception as exc:
                LOGGER.warning("Fluent system theme startup failed; falling back to native Qt palette: %s", exc)
                self.fluent_enabled = False
                self._stopping = True
                self._disconnect_fluent_signals()
                self._stop_listener()
        self.apply_theme()

    def _source_palette(self) -> QPalette:
        if self._palette_source is not None:
            return QPalette(self._palette_source())
        current = QPalette(self.app.palette())
        if self._last_applied_palette is None or current != self._last_applied_palette:
            return current
        return self._standard_palette()

    def _standard_palette(self) -> QPalette:
        return QPalette(self.app.style().standardPalette())

    def is_self_applied_palette(self) -> bool:
        return self._last_applied_palette is not None and self.app.palette() == self._last_applied_palette

    def _on_listener_finished(self) -> None:
        if self._stopping or self._unexpected_finish_handled or self.listener is None:
            return
        listener = self.listener
        self._unexpected_finish_handled = True
        detail = getattr(listener, "run_error", None)
        if detail:
            LOGGER.warning(
                "Fluent system theme listener ended unexpectedly (%s); falling back to native Qt palette",
                detail,
            )
        else:
            LOGGER.warning("Fluent system theme listener ended unexpectedly; falling back to native Qt palette")
        try:
            self._startup_effective_dark = bool(isDarkTheme())
        except Exception as exc:
            LOGGER.warning("Unable to preserve the latest Fluent theme during fallback: %s", exc)
        self.fluent_enabled = False
        self._disconnect_fluent_signals()
        try:
            stopped = not bool(listener.isRunning())
        except Exception:
            stopped = False
        if stopped and self.listener is listener:
            self.listener = None
        self.schedule_refresh()

    def schedule_refresh(self, *_args: object) -> None:
        if self._scheduled:
            return
        self._scheduled = True
        QTimer.singleShot(0, self._run_scheduled_refresh)

    def _run_scheduled_refresh(self) -> None:
        self._scheduled = False
        self.apply_theme()

    def apply_theme(self) -> None:
        if self._refreshing:
            return
        self._refreshing = True
        try:
            palette = application_palette_for_theme(self._source_palette(), self.effective_dark(), self.platform_name)
            self._last_applied_palette = QPalette(palette)
            self.app.setPalette(palette)
            self.themeApplied.emit()
        finally:
            self._refreshing = False
            if not self.fluent_enabled:
                self._startup_effective_dark = None

    def stop(self) -> None:
        self._stopping = True
        self._disconnect_fluent_signals()
        self._stop_listener()

    def _disconnect_fluent_signals(self) -> None:
        if self.listener is not None and self._listener_theme_connected:
            try:
                self.listener.systemThemeChanged.disconnect(self.schedule_refresh)
            except Exception:
                pass
            self._listener_theme_connected = False
        if self.listener is not None and self._listener_finished_connected:
            try:
                self.listener.finished.disconnect(self._on_listener_finished)
            except Exception:
                pass
            self._listener_finished_connected = False
        if self._config_theme_connected:
            try:
                qconfig.themeChanged.disconnect(self.schedule_refresh)
            except Exception:
                pass
            self._config_theme_connected = False

    def _stop_listener(self) -> None:
        if self.listener is None:
            return
        listener = self.listener
        stopped = False
        try:
            listener.requestInterruption()
            stopped = bool(listener.wait(2500))
        except Exception as exc:
            LOGGER.warning("System theme listener interruption failed: %s", exc)
        if not stopped:
            LOGGER.warning("System theme listener did not stop after interruption; forcing termination")
            try:
                listener.terminate()
                stopped = bool(listener.wait(2500))
            except Exception as exc:
                LOGGER.warning("System theme listener termination failed: %s", exc)
        if stopped:
            if self.listener is listener:
                self.listener = None
            return
        LOGGER.critical(
            "System theme listener is still running after termination; "
            "moving it to the process guard"
        )
        if self.listener is listener:
            self.listener = None
        _guard_unstoppable_listener(listener)

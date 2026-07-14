"""System tray icon and menu."""
from __future__ import annotations

from PySide6.QtCore import QRect, Qt, Signal
from PySide6.QtGui import (
    QAction,
    QActionGroup,
    QBrush,
    QColor,
    QIcon,
    QPainter,
    QPixmap,
)
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

from rephraser.core.llm.base import MODES


def _make_icon() -> QIcon:
    pixmap = QPixmap(64, 64)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setBrush(QBrush(QColor("#4f8cc9")))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawRoundedRect(QRect(4, 4, 56, 56), 14, 14)
    painter.setPen(QColor("white"))
    font = painter.font()
    font.setBold(True)
    font.setPixelSize(38)
    painter.setFont(font)
    painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, "R")
    painter.end()
    return QIcon(pixmap)


class TrayIcon(QSystemTrayIcon):
    enabled_toggled = Signal(bool)
    mode_selected = Signal(str)
    compose_requested = Signal()
    log_toggled = Signal(bool)
    settings_requested = Signal()
    quit_requested = Signal()

    def __init__(self, enabled: bool, mode: str, log_pairs: bool = False) -> None:
        super().__init__(_make_icon())
        self.setToolTip("Rephraser")

        menu = QMenu()
        self._enabled_action = QAction("Enabled", menu)
        self._enabled_action.setCheckable(True)
        self._enabled_action.setChecked(enabled)
        self._enabled_action.toggled.connect(self.enabled_toggled)
        menu.addAction(self._enabled_action)

        mode_menu = menu.addMenu("Mode")
        self._mode_group = QActionGroup(mode_menu)
        for name in MODES:
            action = QAction(name.capitalize(), mode_menu)
            action.setCheckable(True)
            action.setChecked(name == mode)
            action.triggered.connect(lambda _=False, n=name: self.mode_selected.emit(n))
            self._mode_group.addAction(action)
            mode_menu.addAction(action)

        compose_action = QAction("Compose...", menu)
        compose_action.triggered.connect(self.compose_requested)
        menu.addAction(compose_action)

        self._log_action = QAction("Log rephrases", menu)
        self._log_action.setCheckable(True)
        self._log_action.setChecked(log_pairs)
        self._log_action.toggled.connect(self.log_toggled)
        menu.addAction(self._log_action)

        menu.addSeparator()
        settings_action = QAction("Settings...", menu)
        settings_action.triggered.connect(self.settings_requested)
        menu.addAction(settings_action)

        quit_action = QAction("Quit", menu)
        quit_action.triggered.connect(self.quit_requested)
        menu.addAction(quit_action)

        self._menu = menu  # keep alive; QSystemTrayIcon does not take ownership
        self.setContextMenu(menu)

    def set_log_enabled(self, enabled: bool) -> None:
        """Sync the log toggle's checkmark (e.g. after Settings changed it)
        without re-emitting log_toggled."""
        self._log_action.blockSignals(True)
        self._log_action.setChecked(enabled)
        self._log_action.blockSignals(False)

    def notify(self, message: str, title: str = "Rephraser") -> None:
        self.showMessage(title, message, QSystemTrayIcon.MessageIcon.Warning, 4000)

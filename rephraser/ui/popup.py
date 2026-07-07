"""Frameless streaming result popup shown near the mouse cursor."""
from __future__ import annotations

from PySide6.QtCore import QEvent, QPoint, Qt, Signal
from PySide6.QtGui import QCursor, QGuiApplication, QKeyEvent
from PySide6.QtWidgets import QLabel, QPlainTextEdit, QVBoxLayout, QWidget

_STYLE = """
QWidget#popupRoot {
    background: #23272e;
    border: 1px solid #3d434d;
    border-radius: 8px;
}
QLabel { color: #9aa4b2; font-size: 11px; }
QLabel#title { color: #e6e9ef; font-size: 12px; font-weight: 600; }
QPlainTextEdit {
    background: #1b1e24;
    color: #e6e9ef;
    border: 1px solid #3d434d;
    border-radius: 6px;
    padding: 6px;
    font-size: 13px;
}
"""


class ResultPopup(QWidget):
    accepted = Signal(str)
    cancelled = Signal()

    def __init__(self) -> None:
        super().__init__(
            None,
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool,
        )
        self.setObjectName("popupRoot")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(_STYLE)
        self.setFixedSize(420, 220)

        self._title = QLabel("Rephrase")
        self._title.setObjectName("title")
        self._status = QLabel("")
        self._editor = QPlainTextEdit()
        self._editor.installEventFilter(self)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(6)
        layout.addWidget(self._title)
        layout.addWidget(self._editor)
        layout.addWidget(self._status)

        self._closing_silently = False
        self._done = False

    # -- session lifecycle ---------------------------------------------------
    def begin(self, mode: str) -> None:
        self._done = False
        self._closing_silently = False
        self._title.setText(f"Rephrase - {mode}")
        self._status.setText("Generating... (Esc to cancel)")
        self._editor.setPlainText("")
        self._editor.setReadOnly(True)
        self._move_near_cursor()
        self.show()
        self.raise_()
        self.activateWindow()
        self._editor.setFocus()

    def append_chunk(self, chunk: str) -> None:
        cursor = self._editor.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        cursor.insertText(chunk)
        self._editor.setTextCursor(cursor)

    def finish_stream(self) -> None:
        self._done = True
        self._editor.setReadOnly(False)
        self._status.setText("Enter: insert / Shift+Enter: newline / Esc: cancel")
        self._editor.setFocus()

    def dismiss(self) -> None:
        """Close without emitting cancelled (used by the app on errors/accept)."""
        self._closing_silently = True
        self.hide()

    # -- geometry --------------------------------------------------------
    def _move_near_cursor(self) -> None:
        cursor_pos = QCursor.pos()
        pos = cursor_pos + QPoint(12, 12)
        screen = QGuiApplication.screenAt(cursor_pos) or QGuiApplication.primaryScreen()
        area = screen.availableGeometry()
        x = min(max(pos.x(), area.left()), area.right() - self.width())
        y = min(max(pos.y(), area.top()), area.bottom() - self.height())
        self.move(x, y)

    # -- input handling ----------------------------------------------------
    def eventFilter(self, obj, event) -> bool:  # noqa: N802 (Qt naming)
        if obj is self._editor and event.type() == QEvent.Type.KeyPress:
            assert isinstance(event, QKeyEvent)
            if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                    return False  # let the editor insert a newline
                if self._done:
                    self._accept()
                return True
            if event.key() == Qt.Key.Key_Escape:
                self._cancel()
                return True
        return super().eventFilter(obj, event)

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        if event.key() == Qt.Key.Key_Escape:
            self._cancel()
            return
        super().keyPressEvent(event)

    def event(self, event) -> bool:  # noqa: N802
        if (
            event.type() == QEvent.Type.WindowDeactivate
            and self.isVisible()
            and not self._closing_silently
        ):
            # Transient popup: clicking elsewhere abandons the rephrase.
            self._cancel()
        return super().event(event)

    def closeEvent(self, event) -> None:  # noqa: N802
        if not self._closing_silently:
            self._cancel()
        super().closeEvent(event)

    # -- outcomes ----------------------------------------------------------
    def _accept(self) -> None:
        text = self._editor.toPlainText().strip()
        if not text:
            self._cancel()
            return
        self._closing_silently = True
        self.hide()
        self.accepted.emit(text)

    def _cancel(self) -> None:
        self._closing_silently = True
        self.hide()
        self.cancelled.emit()

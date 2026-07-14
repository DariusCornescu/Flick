"""Frameless streaming result popup shown near the mouse cursor."""
from __future__ import annotations

from PySide6.QtCore import QEvent, QPoint, Qt, Signal
from PySide6.QtGui import QCursor, QGuiApplication, QKeyEvent
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

_STYLE = """
QWidget#popupRoot {
    background: #23272e;
    border: 1px solid #3d434d;
    border-radius: 8px;
}
QLabel { color: #9aa4b2; font-size: 11px; }
QLabel#title { color: #e6e9ef; font-size: 12px; font-weight: 600; }
QPushButton#close {
    color: #9aa4b2;
    background: transparent;
    border: none;
    font-size: 16px;
    font-weight: 600;
    padding: 0;
}
QPushButton#close:hover { color: #e6e9ef; }
QLineEdit#context {
    background: #1b1e24;
    color: #e6e9ef;
    border: 1px solid #3d434d;
    border-radius: 6px;
    padding: 4px 6px;
    font-size: 12px;
}
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
    compose_submitted = Signal(str, str)

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
        self._title.setCursor(Qt.CursorShape.SizeAllCursor)  # drag handle hint
        # Click-away no longer dismisses the popup (only Esc does), so give a
        # visible affordance to close it.
        self._close_btn = QPushButton("×")
        self._close_btn.setObjectName("close")
        self._close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._close_btn.setFixedSize(20, 20)
        self._close_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)  # never steal editor focus
        self._close_btn.clicked.connect(self._cancel)
        # Optional per-session context, shown only in compose mode. Hidden
        # widgets take no layout space, so selection popups look unchanged.
        self._context_input = QLineEdit()
        self._context_input.setObjectName("context")
        self._context_input.setPlaceholderText(
            "Context (optional) - e.g. what you're working on"
        )
        self._context_input.setVisible(False)
        self._status = QLabel("")
        self._editor = QPlainTextEdit()
        self._editor.installEventFilter(self)

        title_row = QHBoxLayout()
        title_row.setContentsMargins(0, 0, 0, 0)
        title_row.setSpacing(6)
        title_row.addWidget(self._title, 1)
        title_row.addWidget(self._close_btn)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(6)
        layout.addLayout(title_row)
        layout.addWidget(self._context_input)
        layout.addWidget(self._editor)
        layout.addWidget(self._status)

        self._closing_silently = False
        self._done = False
        self._composing = False
        self._drag_offset: QPoint | None = None

    # -- session lifecycle ---------------------------------------------------
    def begin(self, mode: str) -> None:
        self._done = False
        self._closing_silently = False
        self._composing = False
        self._title.setText(f"Rephrase - {mode}")
        self._status.setText("Generating... (Esc to cancel)")
        self._context_input.setVisible(False)
        self._editor.setPlainText("")
        self._editor.setReadOnly(True)
        self._move_near_cursor()
        self.show()
        self.raise_()
        self.activateWindow()
        self._editor.setFocus()

    def begin_compose(self, mode: str) -> None:
        """Open empty and editable: type or paste text, Ctrl+Enter submits."""
        self._done = False
        self._closing_silently = False
        self._composing = True
        self._title.setText(f"Rephrase - {mode} (compose)")
        self._status.setText("Ctrl+Enter: rephrase / Esc: close")
        self._context_input.clear()
        self._context_input.setVisible(True)
        self._editor.setPlainText("")
        self._editor.setReadOnly(False)
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

    def clear_for_retry(self) -> None:
        """Discard a rejected first attempt: clear the editor and show a
        refining hint while the stricter retry streams into it."""
        self._done = False
        self._editor.setReadOnly(True)
        self._editor.setPlainText("")
        self._status.setText("Refining... (Esc to cancel)")

    def finish_stream(self, text: str | None = None) -> None:
        self._done = True
        if text is not None:
            # Replace the raw streamed chunks with the final (cleaned) result,
            # so what the user edits/accepts/pastes matches what was produced.
            self._editor.setPlainText(text)
            cursor = self._editor.textCursor()
            cursor.movePosition(cursor.MoveOperation.End)
            self._editor.setTextCursor(cursor)
        self._editor.setReadOnly(False)
        if self._composing:
            # A compose session has no target selection: Enter copies instead.
            self._status.setText("Enter: copy / Shift+Enter: newline / Esc: close")
        else:
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
                if self._composing and not self._done and not self._editor.isReadOnly():
                    # Compose typing phase: Ctrl+Enter submits, Enter is a newline.
                    if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
                        self._submit_compose()
                        return True
                    return False
                if self._done:
                    self._accept()
                return True
            if event.key() == Qt.Key.Key_Escape:
                self._cancel()
                return True
        return super().eventFilter(obj, event)

    def _submit_compose(self) -> None:
        text = self._editor.toPlainText().strip()
        if not text:
            return
        context = self._context_input.text().strip()
        self._context_input.setVisible(False)  # result replaces the compose UI
        self._editor.setPlainText("")  # the streamed result replaces the input
        self._editor.setReadOnly(True)
        self._status.setText("Generating... (Esc to cancel)")
        self.compose_submitted.emit(text, context)

    # -- dragging ------------------------------------------------------------
    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_offset = (
                event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            )
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._drag_offset is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_offset)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        self._drag_offset = None
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        if event.key() == Qt.Key.Key_Escape:
            self._cancel()
            return
        super().keyPressEvent(event)

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

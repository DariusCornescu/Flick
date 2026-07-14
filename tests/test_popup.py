"""Tests for the result popup: dragging, compose mode, deactivate rules."""
import pytest
from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QMouseEvent, QTextCursor

from rephraser.ui.popup import ResultPopup


@pytest.fixture
def popup(qtbot):
    widget = ResultPopup()
    qtbot.addWidget(widget)
    return widget


def _mouse(etype, local, global_, button, buttons):
    return QMouseEvent(
        etype,
        QPointF(*local),
        QPointF(*local),
        QPointF(*global_),
        button,
        buttons,
        Qt.KeyboardModifier.NoModifier,
    )


# -- dragging -----------------------------------------------------------------

def test_left_drag_moves_window(popup):
    popup.begin("formal")
    popup.move(100, 100)

    popup.mousePressEvent(
        _mouse(
            QEvent.Type.MouseButtonPress, (10, 10), (110, 110),
            Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
        )
    )
    popup.mouseMoveEvent(
        _mouse(
            QEvent.Type.MouseMove, (10, 10), (170, 150),
            Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton,
        )
    )

    assert popup.pos() == QPoint(160, 140)  # dragged by (60, 40)

    popup.mouseReleaseEvent(
        _mouse(
            QEvent.Type.MouseButtonRelease, (10, 10), (170, 150),
            Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton,
        )
    )
    popup.mouseMoveEvent(
        _mouse(
            QEvent.Type.MouseMove, (10, 10), (300, 300),
            Qt.MouseButton.NoButton, Qt.MouseButton.NoButton,
        )
    )
    assert popup.pos() == QPoint(160, 140)  # release ends the drag


# -- compose lifecycle ---------------------------------------------------------

def test_begin_compose_opens_editable_empty(popup):
    popup.begin_compose("prompt")
    assert popup.isVisible()
    assert not popup._editor.isReadOnly()
    assert popup._editor.toPlainText() == ""
    assert "compose" in popup._title.text().lower()


def test_ctrl_enter_submits_compose_text(popup, qtbot):
    popup.begin_compose("prompt")
    popup._editor.setPlainText("fa asta mai clar")

    with qtbot.waitSignal(popup.compose_submitted, timeout=1000) as blocker:
        qtbot.keyClick(
            popup._editor, Qt.Key.Key_Return, Qt.KeyboardModifier.ControlModifier
        )

    assert blocker.args == ["fa asta mai clar", ""]  # no context typed
    # the popup switched itself into the streaming state, input cleared
    assert popup._editor.isReadOnly()
    assert popup._editor.toPlainText() == ""


def test_compose_submits_session_context(popup, qtbot):
    popup.begin_compose("prompt")
    popup._context_input.setText("despre pagina de login")
    popup._editor.setPlainText("fa asta mai clar")

    with qtbot.waitSignal(popup.compose_submitted, timeout=1000) as blocker:
        qtbot.keyClick(
            popup._editor, Qt.Key.Key_Return, Qt.KeyboardModifier.ControlModifier
        )

    assert blocker.args == ["fa asta mai clar", "despre pagina de login"]


def test_selection_session_hides_context_input(popup):
    popup.begin_compose("prompt")
    assert popup._context_input.isVisible()
    popup.begin("formal")
    assert not popup._context_input.isVisible()


def test_plain_enter_in_compose_inserts_newline(popup, qtbot):
    popup.begin_compose("prompt")
    submitted = []
    popup.compose_submitted.connect(submitted.append)
    popup._editor.setPlainText("linia unu")
    popup._editor.moveCursor(QTextCursor.MoveOperation.End)

    qtbot.keyClick(popup._editor, Qt.Key.Key_Return)

    assert "\n" in popup._editor.toPlainText()
    assert submitted == []


def test_ctrl_enter_with_empty_text_does_not_submit(popup, qtbot):
    popup.begin_compose("prompt")
    submitted = []
    popup.compose_submitted.connect(submitted.append)
    popup._editor.setPlainText("   ")

    qtbot.keyClick(
        popup._editor, Qt.Key.Key_Return, Qt.KeyboardModifier.ControlModifier
    )

    assert submitted == []
    assert not popup._editor.isReadOnly()  # still composing


def test_compose_result_accepts_on_enter(popup, qtbot):
    popup.begin_compose("prompt")
    popup._editor.setPlainText("nota")
    qtbot.keyClick(
        popup._editor, Qt.Key.Key_Return, Qt.KeyboardModifier.ControlModifier
    )

    popup.append_chunk("Rezultat")
    popup.finish_stream()
    assert "copy" in popup._status.text().lower()

    with qtbot.waitSignal(popup.accepted, timeout=1000) as blocker:
        qtbot.keyClick(popup._editor, Qt.Key.Key_Return)
    assert blocker.args == ["Rezultat"]


def test_selection_result_hint_still_says_insert(popup):
    popup.begin("formal")
    popup.append_chunk("Result")
    popup.finish_stream()
    assert "insert" in popup._status.text().lower()


def test_finish_stream_replaces_editor_with_final_text(popup):
    # The delivered/edited text must be the cleaned final, not the raw stream.
    popup.begin("formal")
    popup.append_chunk('"Hello there."')  # raw, wrapped in quotes
    popup.finish_stream("Hello there.")   # cleaned final from the worker
    assert popup._editor.toPlainText() == "Hello there."


def test_compose_retry_keeps_copy_hint(popup, qtbot):
    popup.begin_compose("prompt")
    popup._editor.setPlainText("nota")
    qtbot.keyClick(
        popup._editor, Qt.Key.Key_Return, Qt.KeyboardModifier.ControlModifier
    )
    popup.append_chunk("bad first")
    popup.finish_stream("bad first")
    popup.clear_for_retry()
    assert popup._composing  # compose state survives a retry
    popup.append_chunk("good")
    popup.finish_stream("good")
    assert "copy" in popup._status.text().lower()  # still the compose hint


def test_clear_for_retry_resets_to_streaming_state(popup):
    popup.begin("formal")
    popup.append_chunk("bad first attempt")
    popup.finish_stream()  # done + editable

    popup.clear_for_retry()

    assert popup._editor.toPlainText() == ""
    assert popup._editor.isReadOnly()
    assert not popup._done  # Enter must not accept a mid-retry partial
    assert "refining" in popup._status.text().lower()


# -- click-away rules ----------------------------------------------------------

def test_compose_survives_click_away(popup):
    popup.begin_compose("prompt")
    fired = []
    popup.cancelled.connect(lambda: fired.append(1))

    popup.event(QEvent(QEvent.Type.WindowDeactivate))

    assert fired == []
    assert popup.isVisible()


def test_selection_session_survives_click_away(popup):
    # Regression: a hotkey/selection popup must NOT cancel when it loses focus.
    # A spurious WindowDeactivate arrives right after the simulated Ctrl+C, and
    # cancelling on it tore down the session mid-stream ("closes while typing").
    popup.begin("formal")
    fired = []
    popup.cancelled.connect(lambda: fired.append(1))

    popup.event(QEvent(QEvent.Type.WindowDeactivate))

    assert fired == []
    assert popup.isVisible()


def test_selection_survives_deactivate_after_prior_compose(popup):
    popup.begin_compose("prompt")
    popup.dismiss()
    popup.begin("formal")
    fired = []
    popup.cancelled.connect(lambda: fired.append(1))

    popup.event(QEvent(QEvent.Type.WindowDeactivate))

    assert fired == []
    assert popup.isVisible()


def test_streaming_selection_survives_deactivate(popup):
    popup.begin("formal")
    popup.append_chunk("partial")  # streaming: _done is False
    fired = []
    popup.cancelled.connect(lambda: fired.append(1))

    popup.event(QEvent(QEvent.Type.WindowDeactivate))

    assert fired == []
    assert popup.isVisible()


def test_done_selection_survives_deactivate(popup):
    popup.begin("formal")
    popup.append_chunk("Result")
    popup.finish_stream()  # done: editable
    fired = []
    popup.cancelled.connect(lambda: fired.append(1))

    popup.event(QEvent(QEvent.Type.WindowDeactivate))

    assert fired == []
    assert popup.isVisible()


def test_close_button_cancels(popup):
    popup.begin("formal")
    fired = []
    popup.cancelled.connect(lambda: fired.append(1))

    popup._close_btn.click()

    assert fired == [1]
    assert not popup.isVisible()


def test_escape_in_compose_cancels(popup, qtbot):
    popup.begin_compose("prompt")
    fired = []
    popup.cancelled.connect(lambda: fired.append(1))

    qtbot.keyClick(popup._editor, Qt.Key.Key_Escape)

    assert fired == [1]
    assert not popup.isVisible()

"""Tests for the clipboard round-trip (offscreen Qt clipboard)."""
import pytest
from PySide6.QtGui import QGuiApplication

from rephraser.core.capture import ClipboardCapture


@pytest.fixture
def capture(qapp):
    return ClipboardCapture()


def test_backup_and_restore(qapp, capture):
    QGuiApplication.clipboard().setText("original")
    backup = capture.backup_text()
    QGuiApplication.clipboard().setText("changed")
    capture.restore(backup)
    assert QGuiApplication.clipboard().text() == "original"


def test_restore_empty_backup_clears(qapp, capture):
    QGuiApplication.clipboard().setText("something")
    capture.restore("")
    assert QGuiApplication.clipboard().text() == ""


def test_capture_returns_copied_text(qapp, capture, monkeypatch):
    # Simulate the OS answering Ctrl+C by putting text on the clipboard.
    monkeypatch.setattr(
        capture, "_send_copy",
        lambda: QGuiApplication.clipboard().setText("selected words"),
    )
    assert capture.capture_selection(timeout_ms=200) == "selected words"


def test_capture_times_out_when_nothing_copied(qapp, capture, monkeypatch):
    monkeypatch.setattr(capture, "_send_copy", lambda: None)
    QGuiApplication.clipboard().setText("stale")
    assert capture.capture_selection(timeout_ms=120) is None


def test_paste_puts_text_on_clipboard(qapp, capture, monkeypatch):
    monkeypatch.setattr(capture, "_send_paste", lambda: None)
    capture.paste("new text")
    assert QGuiApplication.clipboard().text() == "new text"


def test_wait_for_chord_release_returns_when_released(qapp, capture, monkeypatch):
    states = iter([True, True, False])
    monkeypatch.setattr(
        capture, "_modifiers_physically_down", lambda: next(states, False)
    )
    assert capture._wait_for_chord_release(timeout_s=1.0) is True


def test_wait_for_chord_release_times_out_when_held(qapp, capture, monkeypatch):
    monkeypatch.setattr(capture, "_modifiers_physically_down", lambda: True)
    assert capture._wait_for_chord_release(timeout_s=0.05) is False


def test_prepare_falls_back_to_release_only_on_timeout(qapp, capture, monkeypatch):
    released = []
    monkeypatch.setattr(capture, "_release_modifiers", lambda: released.append(True))

    monkeypatch.setattr(capture, "_wait_for_chord_release", lambda: True)
    capture._prepare_for_keystroke()
    assert released == []

    monkeypatch.setattr(capture, "_wait_for_chord_release", lambda: False)
    capture._prepare_for_keystroke()
    assert released == [True]

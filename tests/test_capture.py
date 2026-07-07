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

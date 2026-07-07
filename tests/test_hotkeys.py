"""Tests for hotkey combo validation."""
from rephraser.core.hotkeys import HotkeyListener


def test_valid_combo():
    assert HotkeyListener.validate("<ctrl>+<alt>+r") is True


def test_invalid_combo():
    assert HotkeyListener.validate("not a hotkey") is False


def test_empty_combo():
    assert HotkeyListener.validate("") is False

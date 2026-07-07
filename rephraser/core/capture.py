"""Clipboard round-trip: backup -> simulated copy with polling -> paste -> restore.

Every method here must run on the Qt main thread (QClipboard is not
thread-safe). Key simulation uses pynput's Controller.
"""
from __future__ import annotations

import time

from PySide6.QtCore import QCoreApplication
from PySide6.QtGui import QGuiApplication
from pynput.keyboard import Controller, Key

# Invisible-separator sentinel: never realistically equals user content.
_SENTINEL = "⁣rephraser::sentinel⁣"

# Modifiers to release before simulating Ctrl+C/Ctrl+V, so keys still held
# from the hotkey chord don't combine with the simulated keystroke.
_MODIFIERS = (
    Key.ctrl, Key.ctrl_l, Key.ctrl_r,
    Key.alt, Key.alt_l, Key.alt_r, Key.alt_gr,
    Key.shift, Key.shift_l, Key.shift_r,
    Key.cmd,
)

POLL_INTERVAL_S = 0.02
DEFAULT_TIMEOUT_MS = 500


class ClipboardCapture:
    def __init__(self) -> None:
        self._keyboard = Controller()

    # -- clipboard state ---------------------------------------------------
    def backup_text(self) -> str:
        return QGuiApplication.clipboard().text()

    def restore(self, backup: str) -> None:
        clipboard = QGuiApplication.clipboard()
        if backup:
            clipboard.setText(backup)
        else:
            clipboard.clear()

    # -- capture -------------------------------------------------------------
    def capture_selection(self, timeout_ms: int = DEFAULT_TIMEOUT_MS) -> str | None:
        """Copy the current selection and return it, or None on timeout.

        Marks the clipboard with a sentinel, simulates Ctrl+C, then polls
        until the clipboard content changes away from the sentinel.
        """
        clipboard = QGuiApplication.clipboard()
        clipboard.setText(_SENTINEL)
        self._send_copy()

        deadline = time.monotonic() + timeout_ms / 1000.0
        while time.monotonic() < deadline:
            QCoreApplication.processEvents()
            text = clipboard.text()
            if text and text != _SENTINEL:
                return text
            time.sleep(POLL_INTERVAL_S)
        return None

    def paste(self, text: str) -> None:
        QGuiApplication.clipboard().setText(text)
        self._send_paste()

    # -- key simulation (patched out in tests) --------------------------------
    def _release_modifiers(self) -> None:
        for key in _MODIFIERS:
            try:
                self._keyboard.release(key)
            except Exception:  # noqa: BLE001 - a single stuck key must not abort
                pass
        time.sleep(0.05)

    def _send_copy(self) -> None:
        self._release_modifiers()
        with self._keyboard.pressed(Key.ctrl):
            self._keyboard.press("c")
            self._keyboard.release("c")

    def _send_paste(self) -> None:
        self._release_modifiers()
        with self._keyboard.pressed(Key.ctrl):
            self._keyboard.press("v")
            self._keyboard.release("v")

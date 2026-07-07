"""Clipboard round-trip: backup -> simulated copy with polling -> paste -> restore.

Every method here must run on the Qt main thread (QClipboard is not
thread-safe). Key simulation uses pynput's Controller.
"""
from __future__ import annotations

import ctypes
import sys
import time

from PySide6.QtCore import QCoreApplication, QEventLoop
from PySide6.QtGui import QGuiApplication
from pynput.keyboard import Controller, Key, KeyCode

# Invisible-separator sentinel: never realistically equals user content.
_SENTINEL = "⁣rephraser::sentinel⁣"

# Modifiers to force-release as a fallback when the user keeps holding the
# hotkey chord, so held keys don't combine with the simulated keystroke.
_MODIFIERS = (
    Key.ctrl, Key.ctrl_l, Key.ctrl_r,
    Key.alt, Key.alt_l, Key.alt_r, Key.alt_gr,
    Key.shift, Key.shift_l, Key.shift_r,
    Key.cmd,
)

# Physical (GetAsyncKeyState) modifier VKs: SHIFT, CONTROL, ALT, LWIN, RWIN.
_VK_MODIFIERS = (0x10, 0x11, 0x12, 0x5B, 0x5C)

# Virtual keys for the copy/paste letters. Using VKs instead of characters
# matters on non-Latin layouts: pynput resolves a character via VkKeyScan and,
# when the active layout has no 'c'/'v', falls back to VK_PACKET, which TYPES
# the literal letter into the target app instead of firing the shortcut.
_KEY_C = KeyCode.from_vk(0x43)
_KEY_V = KeyCode.from_vk(0x56)

POLL_INTERVAL_S = 0.02
DEFAULT_TIMEOUT_MS = 500
CHORD_RELEASE_TIMEOUT_S = 1.5


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
            # Pump non-input events only: dispatching user input here would let
            # tray menu actions (Quit/Settings) re-enter the app mid-capture.
            QCoreApplication.processEvents(
                QEventLoop.ProcessEventsFlag.ExcludeUserInputEvents
            )
            text = clipboard.text()
            if text and text != _SENTINEL:
                return text
            time.sleep(POLL_INTERVAL_S)
        return None

    def paste(self, text: str) -> None:
        QGuiApplication.clipboard().setText(text)
        self._send_paste()

    # -- key simulation (patched out in tests) --------------------------------
    def _modifiers_physically_down(self) -> bool:
        """True while any modifier key is physically held (Windows only)."""
        if not sys.platform.startswith("win"):
            return False
        get_state = ctypes.windll.user32.GetAsyncKeyState
        return any(get_state(vk) & 0x8000 for vk in _VK_MODIFIERS)

    def _wait_for_chord_release(
        self, timeout_s: float = CHORD_RELEASE_TIMEOUT_S
    ) -> bool:
        """Wait until the user physically releases the hotkey chord.

        Injecting modifier keyups while the chord is still held makes the
        still-autorepeating letter key arrive unmodified in the target app
        (typing over the selection) and desyncs pynput's GlobalHotKeys state,
        so prefer waiting for a real release over injecting one.
        """
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            if not self._modifiers_physically_down():
                return True
            time.sleep(0.01)
        return False

    def _prepare_for_keystroke(self) -> None:
        if not self._wait_for_chord_release():
            # User is still holding keys after the grace period - fall back to
            # logically releasing them so the simulated shortcut stays clean.
            self._release_modifiers()
        time.sleep(0.02)

    def _release_modifiers(self) -> None:
        for key in _MODIFIERS:
            try:
                self._keyboard.release(key)
            except Exception:  # noqa: BLE001 - a single stuck key must not abort
                pass
        time.sleep(0.05)

    def _send_copy(self) -> None:
        self._prepare_for_keystroke()
        with self._keyboard.pressed(Key.ctrl):
            self._keyboard.press(_KEY_C)
            self._keyboard.release(_KEY_C)

    def _send_paste(self) -> None:
        self._prepare_for_keystroke()
        with self._keyboard.pressed(Key.ctrl):
            self._keyboard.press(_KEY_V)
            self._keyboard.release(_KEY_V)

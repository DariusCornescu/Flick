"""Global hotkey listener (pynput) bridged to Qt via a Signal.

The pynput callback runs on the listener thread; `triggered` is emitted from
there and delivered to main-thread slots through Qt's queued connections.
Never touch UI from this module.
"""
from __future__ import annotations

from PySide6.QtCore import QObject, Signal
from pynput import keyboard


class HotkeyListener(QObject):
    triggered = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._listener: keyboard.GlobalHotKeys | None = None

    @staticmethod
    def validate(combo: str) -> bool:
        """True if *combo* is a parseable pynput hotkey like '<ctrl>+<alt>+r'."""
        if not combo:
            return False
        try:
            keyboard.HotKey.parse(combo)
        except ValueError:
            return False
        return True

    def start(self, combo: str) -> None:
        """(Re)start listening for *combo*. Raises ValueError if unparseable."""
        keyboard.HotKey.parse(combo)  # fail fast before tearing down the old one
        self.stop()
        self._listener = keyboard.GlobalHotKeys({combo: self._on_hotkey})
        self._listener.daemon = True
        self._listener.start()

    def stop(self) -> None:
        if self._listener is not None:
            self._listener.stop()
            self._listener = None

    def _on_hotkey(self) -> None:
        # Listener thread: only emit; Qt queues delivery to the main thread.
        self.triggered.emit()

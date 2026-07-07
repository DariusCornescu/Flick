"""App-level manual (compose) sessions: copy instead of paste, no restore."""
import threading
from types import SimpleNamespace

from PySide6.QtCore import QObject

from rephraser.app import RephraserApp
from rephraser.core.llm.base import ProviderError, RephraseProvider


class RecordingCapture:
    def __init__(self):
        self.copied = []
        self.pasted = []
        self.restored = []

    def copy(self, text):
        self.copied.append(text)

    def paste(self, text):
        self.pasted.append(text)

    def restore(self, backup):
        self.restored.append(backup)


class RecordingPopup:
    def __init__(self):
        self.compose_begun = []
        self.dismissed = 0

    def begin_compose(self, mode):
        self.compose_begun.append(mode)

    def dismiss(self):
        self.dismissed += 1


class RecordingTray:
    def __init__(self):
        self.notices = []

    def notify(self, message):
        self.notices.append(message)


class RecordingBlockingProvider(RephraseProvider):
    """Records the rephrase call, then blocks until cancelled."""

    name = "fake"

    def __init__(self):
        self.calls = []
        self.streaming = threading.Event()
        self._released = threading.Event()

    def rephrase(self, text, mode):
        self.calls.append((text, mode))
        yield "chunk "
        self.streaming.set()
        self._released.wait(timeout=5.0)
        return

    def cancel(self):
        self._released.set()


class _StubApp(RephraserApp):
    """RephraserApp with the UI-heavy __init__ bypassed."""

    def __init__(self):
        QObject.__init__(self)
        self._busy = False
        self._backup = ""
        self._worker = None
        self._retired_workers = set()
        self._manual_session = False
        self._capture = RecordingCapture()
        self._popup = RecordingPopup()
        self._tray = RecordingTray()
        self._config = SimpleNamespace(mode="formal")


def test_open_compose_begins_manual_session(qapp):
    app = _StubApp()
    app._open_compose()
    assert app._busy is True
    assert app._manual_session is True
    assert app._popup.compose_begun == ["formal"]


def test_open_compose_ignored_while_busy(qapp):
    app = _StubApp()
    app._busy = True
    app._open_compose()
    assert app._popup.compose_begun == []
    assert app._manual_session is False


def test_manual_accept_copies_instead_of_pasting(qapp):
    app = _StubApp()
    app._busy = True
    app._manual_session = True

    app._on_accepted("rezultatul final")

    assert app._capture.copied == ["rezultatul final"]
    assert app._capture.pasted == []
    assert app._capture.restored == []
    assert app._busy is False
    assert app._manual_session is False


def test_manual_cancel_leaves_clipboard_alone(qapp):
    app = _StubApp()
    app._busy = True
    app._manual_session = True
    app._backup = ""

    app._on_cancelled()

    assert app._capture.restored == []  # restore("") would wipe the clipboard
    assert app._busy is False


def test_selection_cancel_still_restores(qapp):
    app = _StubApp()
    app._busy = True
    app._backup = "old clipboard"

    app._on_cancelled()

    assert app._capture.restored == ["old clipboard"]


def test_compose_submit_starts_worker_with_typed_text(qapp):
    app = _StubApp()
    app._busy = True
    app._manual_session = True
    provider = RecordingBlockingProvider()
    app._make_provider = lambda: provider

    app._on_compose_submitted("textul meu")
    try:
        assert app._worker is not None
        assert provider.streaming.wait(timeout=5.0)
        assert provider.calls == [("textul meu", "formal")]
    finally:
        worker = app._worker
        if worker is not None:
            worker.cancel()
            assert worker.wait(5000)


def test_compose_submit_provider_error_finishes_session(qapp):
    app = _StubApp()
    app._busy = True
    app._manual_session = True

    def boom():
        raise ProviderError("no key configured")

    app._make_provider = boom

    app._on_compose_submitted("x")

    assert app._tray.notices and "no key" in app._tray.notices[0]
    assert app._popup.dismissed == 1
    assert app._busy is False
    assert app._manual_session is False

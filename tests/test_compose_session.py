"""App-level manual (compose) sessions: copy instead of paste, no restore."""
import threading
from types import SimpleNamespace

from PySide6.QtCore import QObject

from rephraser.app import RephraserApp, RephraseWorker
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
        self.finished = 0
        self.retries = 0
        self.chunks = []
        self.final_text = None

    def begin_compose(self, mode):
        self.compose_begun.append(mode)

    def append_chunk(self, chunk):
        self.chunks.append(chunk)

    def clear_for_retry(self):
        self.retries += 1
        self.chunks = []

    def finish_stream(self, text=None):
        self.finished += 1
        self.final_text = text

    def dismiss(self):
        self.dismissed += 1


class RecordingTray:
    def __init__(self):
        self.notices = []
        self.log_enabled_calls = []

    def notify(self, message):
        self.notices.append(message)

    def set_log_enabled(self, enabled):
        self.log_enabled_calls.append(enabled)


class RecordingBlockingProvider(RephraseProvider):
    """Records the rephrase call, then blocks until cancelled."""

    name = "fake"

    def __init__(self):
        self.calls = []
        self.streaming = threading.Event()
        self._released = threading.Event()

    def rephrase(self, text, mode, context="", strict=False):
        self.calls.append((text, mode, context))
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
        self._config = SimpleNamespace(
            mode="formal",
            default_context="",
            log_pairs=False,
            provider="ollama",
            ollama_model="gemma3:12b",
            anthropic_model="claude-sonnet-5",
            hotkey="<ctrl>+<alt>+r",
        )
        self._log_input = ""
        self._log_mode = ""
        self._log_context = ""
        self._log_provider = ""
        self._log_model = ""
        self._log_raw = ""


def test_open_compose_begins_manual_session(qapp):
    app = _StubApp()
    app._open_compose()
    assert app._busy is True
    assert app._manual_session is True
    assert app._popup.compose_begun == ["formal"]


def test_open_compose_shows_pretty_translate_label(qapp):
    app = _StubApp()
    app._config.mode = "translate:German"
    app._open_compose()
    assert app._popup.compose_begun == ["translate → German"]


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

    app._on_compose_submitted("textul meu", "despre login")
    try:
        assert app._worker is not None
        assert provider.streaming.wait(timeout=5.0)
        assert provider.calls == [("textul meu", "formal", "despre login")]
    finally:
        worker = app._worker
        if worker is not None:
            worker.cancel()
            assert worker.wait(5000)


def test_logs_pair_on_accept_when_enabled(qapp, monkeypatch):
    app = _StubApp()
    app._config.log_pairs = True
    app._busy = True
    app._manual_session = True
    app._log_input = "raw input"
    app._log_mode = "formal"
    app._log_context = "ctx"
    app._log_provider = "ollama"
    app._log_model = "gemma3:12b"
    records = []
    monkeypatch.setattr("rephraser.core.dataset.log_rephrase", records.append)

    app._on_stream_done("RAW OUTPUT")  # retains the raw model output
    app._on_accepted("FINAL")          # writes the record, then copies

    assert len(records) == 1
    record = records[0]
    assert record["input"] == "raw input"
    assert record["mode"] == "formal"
    assert record["context"] == "ctx"
    assert record["output"] == "RAW OUTPUT"
    assert record["final"] == "FINAL"
    assert record["edited"] is True
    assert app._capture.copied == ["FINAL"]


def test_no_log_when_disabled(qapp, monkeypatch):
    app = _StubApp()
    app._config.log_pairs = False
    app._busy = True
    app._manual_session = True
    app._log_raw = "RAW"
    records = []
    monkeypatch.setattr("rephraser.core.dataset.log_rephrase", records.append)

    app._on_accepted("FINAL")

    assert records == []


class EchoThenFixProvider(RephraseProvider):
    """Echoes on the first attempt, returns a clean rewrite on the strict one."""

    name = "echo-then-fix"

    def __init__(self):
        self.calls = []

    def rephrase(self, text, mode, context="", strict=False):
        self.calls.append(strict)
        yield "Rewritten properly." if strict else text


def test_retry_logs_only_second_attempt_output(qapp, monkeypatch):
    # End-to-end: a rephrase that retries then is accepted must log the SECOND
    # attempt's output, never the echoed first attempt.
    app = _StubApp()
    app._config.log_pairs = True
    app._busy = True
    app._manual_session = True
    app._stash_log_meta("please rewrite this", "")
    records = []
    monkeypatch.setattr("rephraser.core.dataset.log_rephrase", records.append)

    provider = EchoThenFixProvider()
    worker = RephraseWorker(provider, "please rewrite this", "formal")
    app._worker = worker
    worker.chunk.connect(app._on_chunk)
    worker.retrying.connect(app._on_retrying)
    worker.finished_ok.connect(app._on_stream_done)
    worker.failed.connect(app._on_failed)
    worker.start()
    assert worker.wait(5000)
    qapp.processEvents()
    qapp.processEvents()

    assert provider.calls == [False, True]  # echoed, then strict retry
    assert app._popup.retries == 1          # clear_for_retry fired once
    assert app._log_raw == "Rewritten properly."

    app._on_accepted("Rewritten properly.")

    assert len(records) == 1
    assert records[0]["output"] == "Rewritten properly."
    assert "please rewrite this" not in records[0]["output"]
    assert records[0]["edited"] is False


def test_open_settings_syncs_tray_log_toggle(qapp, monkeypatch):
    app = _StubApp()

    class _AcceptDialog:
        def __init__(self, cfg):
            cfg.log_pairs = True  # user enabled logging in the dialog

        def exec(self):
            return True

    monkeypatch.setattr("rephraser.app.SettingsDialog", _AcceptDialog)
    app._open_settings()
    assert app._tray.log_enabled_calls == [True]


def test_open_settings_rejected_does_not_sync(qapp, monkeypatch):
    app = _StubApp()

    class _RejectDialog:
        def __init__(self, cfg):
            pass

        def exec(self):
            return False

    monkeypatch.setattr("rephraser.app.SettingsDialog", _RejectDialog)
    app._open_settings()
    assert app._tray.log_enabled_calls == []


def test_compose_submit_provider_error_finishes_session(qapp):
    app = _StubApp()
    app._busy = True
    app._manual_session = True

    def boom():
        raise ProviderError("no key configured")

    app._make_provider = boom

    app._on_compose_submitted("x", "")

    assert app._tray.notices and "no key" in app._tray.notices[0]
    assert app._popup.dismissed == 1
    assert app._busy is False
    assert app._manual_session is False

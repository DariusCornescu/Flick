"""Entry point - wires hotkey, capture, providers, popup, tray together."""
from __future__ import annotations

import os
import sys
from datetime import datetime, timezone

from PySide6.QtCore import QObject, QThread, QTimer, Signal
from PySide6.QtWidgets import QApplication, QSystemTrayIcon

from rephraser import config as config_mod
from rephraser.config import Config
from rephraser.core.capture import ClipboardCapture
from rephraser.core import dataset
from rephraser.core.hotkeys import HotkeyListener
from rephraser.core.llm.anthropic import AnthropicProvider
from rephraser.core.llm.base import ProviderError, RephraseProvider
from rephraser.core.llm.ollama import OllamaProvider
from rephraser.core.quality import clean_output, needs_retry
from rephraser.ui.popup import ResultPopup
from rephraser.ui.settings import SettingsDialog
from rephraser.ui.tray import TrayIcon

FOCUS_RETURN_DELAY_MS = 150
CLIPBOARD_RESTORE_DELAY_MS = 500
QUIT_WORKER_WAIT_MS = 2000


class RephraseWorker(QThread):
    chunk = Signal(str)
    finished_ok = Signal(str)
    failed = Signal(str)
    retrying = Signal()  # first attempt failed the quality guard; re-streaming

    def __init__(
        self, provider: RephraseProvider, text: str, mode: str, context: str = ""
    ) -> None:
        super().__init__()
        self._provider = provider
        self._text = text
        self._mode = mode
        self._context = context

    def cancel(self) -> None:
        """Main-thread: stop the loop and abort any blocked provider read."""
        self.requestInterruption()
        try:
            self._provider.cancel()
        except Exception:  # noqa: BLE001 - cancellation must never crash the UI
            pass

    def run(self) -> None:  # worker thread - signals only, no UI
        raw = self._attempt(strict=False)
        if raw is None:
            return  # interrupted, or a failure was already reported
        if not self.isInterruptionRequested() and needs_retry(
            self._text, raw, self._mode
        ):
            # First attempt echoed/refused/was empty: clear the popup and make
            # one stricter, lower-temperature retry. Bounded to a single retry.
            self.retrying.emit()
            retry = self._attempt(strict=True)
            if retry is None:
                return
            raw = retry
        if self.isInterruptionRequested():
            return  # cancelled: the session is torn down, report no outcome
        final = clean_output(raw)
        if final:
            self.finished_ok.emit(final)
        else:
            self.failed.emit("The model returned an empty response.")

    def _attempt(self, strict: bool) -> str | None:
        """Stream one pass and return the raw joined text.

        Returns None if the worker was interrupted mid-stream or a failure was
        already emitted (the caller then stops without reporting an outcome)."""
        parts: list[str] = []
        try:
            for piece in self._provider.rephrase(
                self._text, self._mode, self._context, strict=strict
            ):
                if self.isInterruptionRequested():
                    return None
                parts.append(piece)
                self.chunk.emit(piece)
        except ProviderError as exc:
            if not self.isInterruptionRequested():
                self.failed.emit(str(exc))
            return None
        except Exception as exc:  # noqa: BLE001 - last resort: never crash the app
            if not self.isInterruptionRequested():
                self.failed.emit(f"Unexpected error: {exc}")
            return None
        if self.isInterruptionRequested():
            return None
        return "".join(parts)


class RephraserApp(QObject):
    def __init__(self, app: QApplication) -> None:
        super().__init__(app)
        self._app = app
        self._config = Config.load()
        self._busy = False
        self._backup = ""
        # True for tray-opened compose sessions: text is typed, not selected,
        # so the result is copied to the clipboard instead of pasted.
        self._manual_session = False
        self._worker: RephraseWorker | None = None
        # Workers we told to stop but whose threads may still be running.
        # Holding a reference keeps the QThread wrapper alive until `finished`
        # is delivered; letting it be garbage-collected while the thread runs
        # aborts the process (QThread destroyed while running).
        self._retired_workers: set[RephraseWorker] = set()
        self._reset_log_meta()

        self._capture = ClipboardCapture()
        self._popup = ResultPopup()
        self._popup.accepted.connect(self._on_accepted)
        self._popup.cancelled.connect(self._on_cancelled)
        self._popup.compose_submitted.connect(self._on_compose_submitted)

        self._tray = TrayIcon(
            self._config.enabled, self._config.mode, self._config.log_pairs
        )
        self._tray.enabled_toggled.connect(self._on_enabled_toggled)
        self._tray.mode_selected.connect(self._on_mode_selected)
        self._tray.compose_requested.connect(self._open_compose)
        self._tray.log_toggled.connect(self._on_log_toggled)
        self._tray.settings_requested.connect(self._open_settings)
        self._tray.quit_requested.connect(self._quit)
        self._tray.show()

        self._listener = HotkeyListener(self)
        self._listener.triggered.connect(self._on_hotkey)
        self._start_listener()

    # -- tray/menu ---------------------------------------------------------
    def _on_enabled_toggled(self, enabled: bool) -> None:
        self._config.enabled = enabled
        self._config.save()

    def _on_mode_selected(self, mode: str) -> None:
        self._config.mode = mode
        self._config.save()

    def _on_log_toggled(self, enabled: bool) -> None:
        self._config.log_pairs = enabled
        self._config.save()

    def _open_settings(self) -> None:
        old_hotkey = self._config.hotkey
        dialog = SettingsDialog(self._config)
        accepted = dialog.exec()
        if accepted:
            # Settings may have changed log_pairs; keep the tray toggle in sync.
            self._tray.set_log_enabled(self._config.log_pairs)
            if self._config.hotkey != old_hotkey:
                self._start_listener()

    def _quit(self) -> None:
        self._listener.stop()
        worker = self._worker
        self._stop_worker()
        if self._busy:
            # Session in flight: honor the restore guarantee before exiting.
            try:
                self._capture.restore(self._backup)
            except Exception:  # noqa: BLE001
                pass
        self._tray.hide()
        self._app.quit()
        if worker is not None and worker.isRunning() and not worker.wait(
            QUIT_WORKER_WAIT_MS
        ):
            # Worker is stuck in a blocking network read; interpreter teardown
            # with a live QThread would abort. Nothing left to save - exit hard.
            os._exit(0)

    def _start_listener(self) -> None:
        try:
            self._listener.start(self._config.hotkey)
        except ValueError:
            self._tray.notify(
                f"Invalid hotkey '{self._config.hotkey}' - falling back to default."
            )
            self._config.hotkey = config_mod.DEFAULT_HOTKEY
            self._config.save()
            self._listener.start(self._config.hotkey)

    # -- rephrase session -----------------------------------------------------
    def _on_hotkey(self) -> None:
        """Main-thread slot (queued from the listener thread)."""
        if self._busy or not self._config.enabled:
            return
        if QApplication.activeModalWidget() is not None:
            # A modal dialog (e.g. Settings) would block the popup's input,
            # wedging the session with no way to accept or cancel.
            return
        self._busy = True

        try:
            provider = self._make_provider()
        except ProviderError as exc:
            self._tray.notify(str(exc))
            self._busy = False
            return
        except Exception as exc:  # noqa: BLE001 - never wedge the busy flag
            self._tray.notify(f"Rephraser error: {exc}")
            self._busy = False
            return

        have_backup = False
        try:
            self._backup = self._capture.backup_text()
            have_backup = True
            text = self._capture.capture_selection()
            if not text or not text.strip():
                self._tray.notify("No text selected (or the app blocked the copy).")
                # The simulated Ctrl+C may still land in a slow target app;
                # delay the restore so a late copy can't clobber it afterwards.
                QTimer.singleShot(
                    CLIPBOARD_RESTORE_DELAY_MS,
                    lambda: self._finish_session(restore=True),
                )
                return

            self._stash_log_meta(text, self._config.default_context)
            self._popup.begin(self._config.mode)
            self._worker = RephraseWorker(
                provider, text, self._config.mode,
                context=self._config.default_context,
            )
            self._worker.chunk.connect(self._on_chunk)
            self._worker.retrying.connect(self._on_retrying)
            self._worker.finished_ok.connect(self._on_stream_done)
            self._worker.failed.connect(self._on_failed)
            self._worker.start()
        except Exception as exc:  # noqa: BLE001 - never wedge the busy flag
            self._tray.notify(f"Rephraser error: {exc}")
            self._popup.dismiss()
            self._finish_session(restore=have_backup)

    # -- compose session ------------------------------------------------------
    def _open_compose(self) -> None:
        """Tray-menu entry: open the popup empty so text can be typed/pasted."""
        if self._busy or QApplication.activeModalWidget() is not None:
            return
        self._busy = True
        self._manual_session = True
        self._popup.begin_compose(self._config.mode)

    def _on_compose_submitted(self, text: str, context: str) -> None:
        """Compose text submitted; the popup already shows its streaming state.

        A per-session *context* typed in the popup overrides the standing
        default context from Settings."""
        try:
            provider = self._make_provider()
        except ProviderError as exc:
            self._tray.notify(str(exc))
            self._popup.dismiss()
            self._finish_session(restore=False)
            return
        except Exception as exc:  # noqa: BLE001 - never wedge the busy flag
            self._tray.notify(f"Rephraser error: {exc}")
            self._popup.dismiss()
            self._finish_session(restore=False)
            return
        effective_context = context or self._config.default_context
        self._stash_log_meta(text, effective_context)
        self._worker = RephraseWorker(
            provider, text, self._config.mode, context=effective_context
        )
        self._worker.chunk.connect(self._on_chunk)
        self._worker.retrying.connect(self._on_retrying)
        self._worker.finished_ok.connect(self._on_stream_done)
        self._worker.failed.connect(self._on_failed)
        self._worker.start()

    def _make_provider(self) -> RephraseProvider:
        if self._config.provider == "anthropic":
            key = config_mod.get_api_key("anthropic")
            if not key:
                raise ProviderError("No Anthropic API key configured - open Settings.")
            return AnthropicProvider(
                api_key=key,
                model=self._config.anthropic_model,
                timeout=self._config.request_timeout,
            )
        return OllamaProvider(
            self._config.ollama_url,
            self._config.ollama_model,
            timeout=self._config.request_timeout,
        )

    # -- worker slots (main thread) -----------------------------------------
    def _on_chunk(self, piece: str) -> None:
        if self.sender() is self._worker:
            self._popup.append_chunk(piece)

    def _on_retrying(self) -> None:
        if self.sender() is self._worker:
            # Discard the rejected first attempt and show a refining state; the
            # stricter retry streams into the cleared popup.
            self._popup.clear_for_retry()

    def _on_stream_done(self, full_text: str) -> None:
        if self.sender() is self._worker:
            self._log_raw = full_text  # retained for the training-data log
            self._popup.finish_stream()

    def _on_failed(self, message: str) -> None:
        if self.sender() is not self._worker:
            return
        self._popup.dismiss()
        self._tray.notify(message)
        self._finish_session(restore=True)

    # -- popup outcomes --------------------------------------------------------
    def _on_accepted(self, text: str) -> None:
        self._write_log_record(text)
        if self._manual_session:
            # No target selection to replace: the result goes to the clipboard.
            try:
                self._capture.copy(text)
            except Exception as exc:  # noqa: BLE001 - still release the session
                self._tray.notify(f"Copy failed: {exc}")
            self._finish_session(restore=False)
            return
        # Popup is hidden; give focus time to return to the target window.
        QTimer.singleShot(FOCUS_RETURN_DELAY_MS, lambda: self._paste_and_restore(text))

    def _paste_and_restore(self, text: str) -> None:
        try:
            self._capture.paste(text)
        except Exception as exc:  # noqa: BLE001 - still restore + release busy
            self._tray.notify(f"Paste failed: {exc}")
        QTimer.singleShot(
            CLIPBOARD_RESTORE_DELAY_MS, lambda: self._finish_session(restore=True)
        )

    def _on_cancelled(self) -> None:
        if not self._busy:
            return
        self._finish_session(restore=True)

    # -- session teardown -------------------------------------------------------
    def _stop_worker(self) -> None:
        worker = self._worker
        self._worker = None
        if worker is None:
            return
        if worker.isRunning():
            worker.cancel()
            self._retired_workers.add(worker)
            worker.finished.connect(lambda w=worker: self._reap_worker(w))
        else:
            worker.deleteLater()

    def _reap_worker(self, worker: RephraseWorker) -> None:
        self._retired_workers.discard(worker)
        worker.deleteLater()

    # -- training-data logging -------------------------------------------------
    def _reset_log_meta(self) -> None:
        self._log_input = ""
        self._log_mode = ""
        self._log_context = ""
        self._log_provider = ""
        self._log_model = ""
        self._log_raw = ""

    def _stash_log_meta(self, text: str, context: str) -> None:
        """Capture the inputs of the current session so an accepted result can
        be logged as a training pair. Cheap and always safe to call."""
        self._log_input = text
        self._log_mode = self._config.mode
        self._log_context = context
        self._log_provider = self._config.provider
        self._log_model = (
            self._config.anthropic_model
            if self._config.provider == "anthropic"
            else self._config.ollama_model
        )
        self._log_raw = ""

    def _write_log_record(self, final: str) -> None:
        if not self._config.log_pairs:
            return
        try:
            dataset.log_rephrase(
                {
                    "ts": datetime.now(timezone.utc).isoformat(),
                    "provider": self._log_provider,
                    "model": self._log_model,
                    "mode": self._log_mode,
                    "context": self._log_context,
                    "input": self._log_input,
                    "output": self._log_raw,
                    "final": final,
                    "edited": final != self._log_raw,
                }
            )
        except Exception:  # noqa: BLE001 - logging must never break the paste flow
            pass

    def _finish_session(self, restore: bool) -> None:
        self._stop_worker()
        # Manual sessions never took a clipboard backup; restoring would wipe
        # the clipboard (or the just-copied result) with an empty string.
        if restore and not self._manual_session:
            try:
                self._capture.restore(self._backup)
            except Exception:  # noqa: BLE001 - busy flag must always reset
                pass
        self._backup = ""
        self._busy = False
        self._manual_session = False
        self._reset_log_meta()


def main() -> int:
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    app.setApplicationName("Rephraser")

    if not QSystemTrayIcon.isSystemTrayAvailable():
        print("System tray is not available; Rephraser cannot run.", file=sys.stderr)
        return 1

    rephraser = RephraserApp(app)  # noqa: F841 - kept alive by parent QApplication
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())

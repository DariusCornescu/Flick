"""Cancel plumbing: RephraseProvider.cancel() -> RephraseWorker -> _stop_worker."""
import threading

import pytest
import shiboken6
from PySide6.QtCore import QObject, Qt

from rephraser.app import RephraserApp, RephraseWorker
from rephraser.core.llm.base import ProviderError, RephraseProvider


class BlockingProvider(RephraseProvider):
    """Yields one chunk, then blocks like a provider stuck in a socket read."""

    name = "fake"

    def __init__(self):
        self.cancel_calls = 0
        self.streaming = threading.Event()
        self._released = threading.Event()

    def rephrase(self, text, mode):
        yield "first "
        self.streaming.set()
        if not self._released.wait(timeout=5.0):
            raise AssertionError("blocked read was never aborted by cancel()")
        return  # aborted: end quietly, like the real providers after cancel()

    def cancel(self):
        self.cancel_calls += 1
        self._released.set()


class _StopOnlyApp(RephraserApp):
    """RephraserApp with the UI-heavy __init__ bypassed; exercises only the
    worker-teardown paths under test."""

    def __init__(self):
        QObject.__init__(self)
        self._worker = None
        self._retired_workers = set()


@pytest.fixture
def start_worker(qapp):
    workers = []

    def _start(provider):
        worker = RephraseWorker(provider, "hi", "formal")
        workers.append((worker, provider))
        worker.start()
        return worker

    yield _start
    for worker, provider in workers:
        provider.cancel()  # unblock the fake read if a test failed early
        if shiboken6.isValid(worker):  # already-reaped workers have finished
            worker.requestInterruption()
            assert worker.wait(5000)


def test_provider_cancel_is_optional_noop():
    class MinimalProvider(RephraseProvider):
        name = "minimal"

        def rephrase(self, text, mode):
            yield "x"

    MinimalProvider().cancel()  # base-class hook exists and is a safe no-op


def test_worker_cancel_aborts_blocked_provider(start_worker):
    provider = BlockingProvider()
    worker = start_worker(provider)
    outcomes = []
    worker.finished_ok.connect(
        lambda text: outcomes.append(("ok", text)),
        Qt.ConnectionType.DirectConnection,
    )
    worker.failed.connect(
        lambda msg: outcomes.append(("failed", msg)),
        Qt.ConnectionType.DirectConnection,
    )
    assert provider.streaming.wait(timeout=5.0)

    worker.cancel()

    assert worker.wait(5000)  # exits promptly, not after a read timeout
    assert provider.cancel_calls == 1
    assert outcomes == []  # a cancelled worker reports no outcome


def test_cancelled_worker_suppresses_late_failure(start_worker):
    # A cancel-unaware provider (base no-op cancel) stays blocked after Esc
    # and eventually fails like a read timeout; the cancelled worker must
    # still report no outcome.
    class RaisingOnAbortProvider(RephraseProvider):
        name = "raising"

        def __init__(self):
            self.streaming = threading.Event()
            self.release = threading.Event()

        def rephrase(self, text, mode):
            yield "first "
            self.streaming.set()
            if not self.release.wait(timeout=5.0):
                raise AssertionError("test never released the blocked read")
            raise ProviderError("stream timed out")

        def cancel(self):
            self.release.set()  # only so the fixture can always unblock it

    provider = RaisingOnAbortProvider()
    worker = start_worker(provider)
    outcomes = []
    worker.finished_ok.connect(
        lambda text: outcomes.append(("ok", text)),
        Qt.ConnectionType.DirectConnection,
    )
    worker.failed.connect(
        lambda msg: outcomes.append(("failed", msg)),
        Qt.ConnectionType.DirectConnection,
    )
    assert provider.streaming.wait(timeout=5.0)

    worker.requestInterruption()  # cancel without a transport abort
    provider.release.set()  # ...then the blocked read fails on its own

    assert worker.wait(5000)
    assert outcomes == []  # the late ProviderError must not surface


def test_stop_worker_cancels_running_worker(start_worker):
    provider = BlockingProvider()
    worker = start_worker(provider)
    assert provider.streaming.wait(timeout=5.0)

    holder = _StopOnlyApp()
    holder._worker = worker
    holder._stop_worker()

    assert provider.cancel_calls == 1  # abort reached the provider transport
    assert holder._worker is None
    assert worker.wait(5000)

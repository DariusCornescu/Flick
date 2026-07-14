"""Quality guard + single corrective retry orchestrated by RephraseWorker."""
import pytest
import shiboken6
from PySide6.QtCore import Qt

from rephraser.app import RephraseWorker
from rephraser.core.llm.base import RephraseProvider


class EchoThenFixProvider(RephraseProvider):
    """Echoes the input on the first (non-strict) attempt; on the strict retry
    returns a clean rewrite wrapped in quotes (to exercise clean_output)."""

    name = "echo-then-fix"

    def __init__(self):
        self.calls = []

    def rephrase(self, text, mode, context="", strict=False):
        self.calls.append(strict)
        if strict:
            yield '"Rewritten properly."'
        else:
            yield text


class AlwaysEchoProvider(RephraseProvider):
    name = "always-echo"

    def __init__(self):
        self.calls = []

    def rephrase(self, text, mode, context="", strict=False):
        self.calls.append(strict)
        yield text


class GoodProvider(RephraseProvider):
    name = "good"

    def __init__(self):
        self.calls = []

    def rephrase(self, text, mode, context="", strict=False):
        self.calls.append(strict)
        yield "A clearly different rewrite."


@pytest.fixture
def run_worker(qapp):
    workers = []

    def _run(provider, text="please rewrite this", mode="formal"):
        worker = RephraseWorker(provider, text, mode)
        outcomes = []
        retrying = []
        # DirectConnection: slots run in the worker thread, so they have all
        # fired by the time worker.wait() returns (mirrors tests/test_cancel.py).
        worker.finished_ok.connect(
            lambda t: outcomes.append(("ok", t)), Qt.ConnectionType.DirectConnection
        )
        worker.failed.connect(
            lambda m: outcomes.append(("failed", m)), Qt.ConnectionType.DirectConnection
        )
        worker.retrying.connect(
            lambda: retrying.append(1), Qt.ConnectionType.DirectConnection
        )
        workers.append(worker)
        worker.start()
        assert worker.wait(5000)
        return outcomes, retrying

    yield _run
    for worker in workers:
        if shiboken6.isValid(worker) and worker.isRunning():
            worker.requestInterruption()
            worker.wait(5000)


def test_no_retry_on_good_output(run_worker):
    provider = GoodProvider()
    outcomes, retrying = run_worker(provider)
    assert retrying == []
    assert outcomes == [("ok", "A clearly different rewrite.")]
    assert provider.calls == [False]


def test_retry_on_echo_then_cleans_second_attempt(run_worker):
    provider = EchoThenFixProvider()
    outcomes, retrying = run_worker(provider)
    assert retrying == [1]
    assert outcomes == [("ok", "Rewritten properly.")]  # wrapping quotes stripped
    assert provider.calls == [False, True]


def test_retry_is_bounded_to_one(run_worker):
    provider = AlwaysEchoProvider()
    outcomes, retrying = run_worker(provider, text="please rewrite this")
    assert retrying == [1]
    assert provider.calls == [False, True]  # exactly one retry, never loops
    assert outcomes == [("ok", "please rewrite this")]  # cleaned echo emitted

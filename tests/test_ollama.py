"""Tests for the Ollama provider (mocked HTTP)."""
import json
import socket
import threading

import pytest
import requests

from rephraser.core.llm.base import ProviderError
from rephraser.core.llm.ollama import OllamaProvider


class FakeResponse:
    def __init__(self, lines, status=200):
        self._lines = lines
        self.status_code = status
        self.closed = False

    def iter_lines(self, decode_unicode=False):
        yield from self._lines

    def json(self):
        return json.loads(self._lines[0])

    def close(self):
        self.closed = True

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


class FakeSocket:
    """Records the shutdown() call that aborts a blocked recv()."""

    def __init__(self, on_shutdown=None):
        self.shutdown_how = None
        self._on_shutdown = on_shutdown

    def shutdown(self, how):
        self.shutdown_how = how
        if self._on_shutdown is not None:
            self._on_shutdown()


class StalledFakeResponse(FakeResponse):
    """Serves its lines, then stalls like an idle socket until aborted.

    Mirrors the real transport: a read blocked in ``iter_lines`` only fails
    once the underlying socket (``raw.connection.sock``) is shut down from
    another thread - ``Response.close()`` alone cannot interrupt it.
    """

    class _Raw:
        class _Connection:
            sock = None

        def __init__(self):
            self.connection = self._Connection()

    def __init__(self, lines):
        super().__init__(lines)
        self.stalled = threading.Event()
        self._aborted = threading.Event()
        self.raw = self._Raw()
        self.raw.connection.sock = FakeSocket(on_shutdown=self._aborted.set)

    @property
    def sock(self):
        return self.raw.connection.sock

    def iter_lines(self, decode_unicode=False):
        yield from self._lines
        self.stalled.set()
        if not self._aborted.wait(timeout=5.0):
            raise AssertionError("stalled read was never aborted by shutdown()")
        raise requests.ConnectionError("Connection aborted.")


def test_streams_chunks(monkeypatch):
    lines = [
        json.dumps({"message": {"content": "Hello"}, "done": False}),
        "",
        json.dumps({"message": {"content": " world"}, "done": False}),
        json.dumps({"message": {"content": ""}, "done": True}),
    ]
    captured = {}

    def fake_post(url, json=None, stream=False, timeout=None):
        captured["url"] = url
        captured["payload"] = json
        return FakeResponse(lines)

    monkeypatch.setattr(requests, "post", fake_post)
    provider = OllamaProvider("http://localhost:11434", "llama3.2")
    chunks = list(provider.rephrase("hi", "formal"))
    assert "".join(chunks) == "Hello world"
    assert captured["url"] == "http://localhost:11434/api/chat"
    assert captured["payload"]["model"] == "llama3.2"
    assert captured["payload"]["stream"] is True
    msgs = captured["payload"]["messages"]
    assert msgs[0]["role"] == "system"
    assert msgs[-1] == {"role": "user", "content": "hi"}
    middle = msgs[1:-1]  # few-shot example turns
    assert middle, "expected few-shot example turns between system and user"
    for i, m in enumerate(middle):
        assert m["role"] == ("user" if i % 2 == 0 else "assistant")
    assert captured["payload"]["options"]["num_ctx"] >= 8192


def test_connection_error_maps_to_provider_error(monkeypatch):
    def fake_post(*args, **kwargs):
        raise requests.ConnectionError("refused")

    monkeypatch.setattr(requests, "post", fake_post)
    provider = OllamaProvider("http://localhost:11434", "llama3.2")
    with pytest.raises(ProviderError, match="not reachable"):
        list(provider.rephrase("hi", "formal"))


def test_timeout_maps_to_provider_error(monkeypatch):
    def fake_post(*args, **kwargs):
        raise requests.Timeout("slow")

    monkeypatch.setattr(requests, "post", fake_post)
    provider = OllamaProvider("http://localhost:11434", "llama3.2")
    with pytest.raises(ProviderError, match="timed out"):
        list(provider.rephrase("hi", "formal"))


def test_http_error_maps_to_provider_error(monkeypatch):
    lines = [json.dumps({"error": "model 'nope' not found"})]
    monkeypatch.setattr(requests, "post", lambda *a, **k: FakeResponse(lines, status=404))
    provider = OllamaProvider("http://localhost:11434", "nope")
    with pytest.raises(ProviderError, match="not found"):
        list(provider.rephrase("hi", "formal"))


def test_stream_error_line_raises(monkeypatch):
    lines = [json.dumps({"error": "model 'nope' not found"})]
    monkeypatch.setattr(requests, "post", lambda *a, **k: FakeResponse(lines))
    provider = OllamaProvider("http://localhost:11434", "nope")
    with pytest.raises(ProviderError, match="not found"):
        list(provider.rephrase("hi", "formal"))


# -- cancel() ----------------------------------------------------------------

def test_cancel_shuts_down_streaming_socket(monkeypatch):
    lines = [json.dumps({"message": {"content": "Hello"}, "done": False})]
    response = StalledFakeResponse(lines)
    monkeypatch.setattr(requests, "post", lambda *a, **k: response)
    provider = OllamaProvider("http://localhost:11434", "llama3.2")
    stream = provider.rephrase("hi", "formal")
    assert next(stream) == "Hello"

    provider.cancel()

    # cancel() must shut the socket down itself: only shutdown() can abort a
    # recv() already blocked in another thread (Response.close() cannot).
    assert response.sock.shutdown_how == socket.SHUT_RDWR
    assert list(stream) == []  # the aborted read ends the stream quietly
    assert response.closed  # released by the reader side once unblocked


def test_cancel_unblocks_stalled_read_promptly(monkeypatch):
    lines = [json.dumps({"message": {"content": "Hello"}, "done": False})]
    response = StalledFakeResponse(lines)
    monkeypatch.setattr(requests, "post", lambda *a, **k: response)
    provider = OllamaProvider("http://localhost:11434", "llama3.2")

    chunks: list[str] = []
    errors: list[BaseException] = []

    def consume():
        try:
            chunks.extend(provider.rephrase("hi", "formal"))
        except BaseException as exc:  # noqa: BLE001 - recorded for assertion
            errors.append(exc)

    reader = threading.Thread(target=consume, daemon=True)
    reader.start()
    assert response.stalled.wait(timeout=5.0)

    provider.cancel()
    reader.join(timeout=5.0)

    # The fake raises AssertionError (captured in `errors`) if the socket was
    # never shut down, so a clean exit proves cancel aborted the blocked read.
    assert not reader.is_alive()
    assert errors == []
    assert chunks == ["Hello"]
    assert response.sock.shutdown_how == socket.SHUT_RDWR
    assert response.closed


def test_cancel_before_response_arrives_discards_response(monkeypatch):
    # cancel() lands while requests.post() is still connecting: the response
    # must be closed as soon as it materializes, and never be read.
    lines = [json.dumps({"message": {"content": "late"}, "done": True})]
    response = FakeResponse(lines)
    provider = OllamaProvider("http://localhost:11434", "llama3.2")

    def fake_post(*args, **kwargs):
        provider.cancel()  # simulates cancel racing the connect phase
        return response

    monkeypatch.setattr(requests, "post", fake_post)
    assert list(provider.rephrase("hi", "formal")) == []
    assert response.closed


def test_cancel_without_request_is_noop():
    OllamaProvider("http://localhost:11434", "llama3.2").cancel()


def test_cancel_twice_and_after_completion_is_safe(monkeypatch):
    lines = [json.dumps({"message": {"content": "Hi"}, "done": True})]
    response = FakeResponse(lines)
    monkeypatch.setattr(requests, "post", lambda *a, **k: response)
    provider = OllamaProvider("http://localhost:11434", "llama3.2")
    assert "".join(provider.rephrase("hi", "formal")) == "Hi"

    provider.cancel()  # after completion: transport already released
    provider.cancel()  # and cancel stays idempotent


def test_urllib3_still_exposes_socket_abort_path():
    """Canary: cancel() aborts a blocked read via the undocumented
    response.raw.connection.sock path. If a urllib3 upgrade renames it,
    cancel() silently degrades to close() - which cannot abort a recv()
    already blocked in another thread - so fail loudly here instead."""
    import inspect

    import urllib3

    assert isinstance(
        inspect.getattr_static(urllib3.response.HTTPResponse, "connection", None),
        property,
    )
    assert hasattr(urllib3.connection.HTTPConnection("localhost"), "sock")

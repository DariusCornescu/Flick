"""Tests for the Anthropic provider (mocked SDK client)."""
import threading
from contextlib import contextmanager

import anthropic
import httpx
import pytest

from rephraser.core.llm.anthropic import AnthropicProvider
from rephraser.core.llm.base import ProviderError


class FakeClient:
    def __init__(self, chunks=None, error=None):
        self._chunks = chunks or []
        self._error = error
        self.kwargs = None
        outer = self

        class _Messages:
            @contextmanager
            def stream(self, **kwargs):
                outer.kwargs = kwargs
                if outer._error is not None:
                    raise outer._error

                class _Stream:
                    text_stream = iter(outer._chunks)

                yield _Stream()

        self.messages = _Messages()


def _provider(fake):
    provider = AnthropicProvider(api_key="sk-test", model="claude-opus-4-8")
    provider._client = fake
    return provider


def _fake_httpx_request():
    return httpx.Request("POST", "https://api.anthropic.com/v1/messages")


def _fake_httpx_response(status):
    return httpx.Response(status, request=_fake_httpx_request())


def test_streams_chunks():
    fake = FakeClient(chunks=["Good ", "morning."])
    provider = _provider(fake)
    assert "".join(provider.rephrase("gm", "formal")) == "Good morning."
    assert fake.kwargs["model"] == "claude-opus-4-8"
    assert fake.kwargs["messages"] == [{"role": "user", "content": "gm"}]
    assert "ONLY the rewritten text" in fake.kwargs["system"]


def test_auth_error_maps_to_provider_error():
    error = anthropic.AuthenticationError(
        message="bad key", response=_fake_httpx_response(401), body=None
    )
    provider = _provider(FakeClient(error=error))
    with pytest.raises(ProviderError, match="API key"):
        list(provider.rephrase("hi", "formal"))


def test_connection_error_maps_to_provider_error():
    error = anthropic.APIConnectionError(request=_fake_httpx_request())
    provider = _provider(FakeClient(error=error))
    with pytest.raises(ProviderError, match="unreachable"):
        list(provider.rephrase("hi", "formal"))


def test_timeout_maps_to_provider_error():
    error = anthropic.APITimeoutError(request=_fake_httpx_request())
    provider = _provider(FakeClient(error=error))
    with pytest.raises(ProviderError, match="timed out"):
        list(provider.rephrase("hi", "formal"))


# -- cancel() ----------------------------------------------------------------

class FakeStream:
    """Mimics the SDK's MessageStream: serves chunks, then stalls until a
    cross-thread close() aborts the blocked read."""

    def __init__(self, chunks):
        self._chunks = chunks
        self.closed = False
        self.stalled = threading.Event()
        self._closed_event = threading.Event()

    def close(self):
        self.closed = True
        self._closed_event.set()

    @property
    def text_stream(self):
        def gen():
            yield from self._chunks
            self.stalled.set()
            if not self._closed_event.wait(timeout=5.0):
                raise AssertionError("stalled read was never unblocked by close()")
            raise httpx.ReadError("connection closed")

        return gen()


class FakeStreamClient:
    """Client whose messages.stream() context yields a FakeStream and, like
    the real MessageStreamManager, closes it on exit."""

    def __init__(self, stream):
        self.stream = stream
        self.exited = False
        outer = self

        class _Messages:
            @contextmanager
            def stream(self, **kwargs):
                try:
                    yield outer.stream
                finally:
                    outer.stream.close()
                    outer.exited = True

        self.messages = _Messages()


def test_cancel_closes_active_stream():
    stream = FakeStream(["Good "])
    provider = _provider(FakeStreamClient(stream))
    gen = provider.rephrase("gm", "formal")
    assert next(gen) == "Good "

    provider.cancel()

    assert stream.closed  # closed by cancel() itself, not by later iteration
    assert list(gen) == []  # the aborted read ends the stream quietly


def test_cancel_unblocks_stalled_read_promptly():
    stream = FakeStream(["Good "])
    provider = _provider(FakeStreamClient(stream))

    chunks: list[str] = []
    errors: list[BaseException] = []

    def consume():
        try:
            chunks.extend(provider.rephrase("gm", "formal"))
        except BaseException as exc:  # noqa: BLE001 - recorded for assertion
            errors.append(exc)

    reader = threading.Thread(target=consume, daemon=True)
    reader.start()
    assert stream.stalled.wait(timeout=5.0)

    provider.cancel()
    reader.join(timeout=5.0)

    # The fake raises AssertionError (captured in `errors`) if close() never
    # arrived, so surviving with no error proves cancel unblocked the read.
    assert not reader.is_alive()
    assert errors == []
    assert chunks == ["Good "]
    assert stream.closed


def test_cancel_before_stream_opens_discards_stream():
    # cancel() lands before the stream context is entered: the request may
    # already be in flight, but the stream must be closed without reading.
    stream = FakeStream(["late"])
    client = FakeStreamClient(stream)
    provider = _provider(client)

    provider.cancel()

    assert list(provider.rephrase("gm", "formal")) == []
    assert stream.closed
    assert client.exited
    assert not stream.stalled.is_set()  # text_stream was never pulled


def test_cancel_without_request_is_noop():
    AnthropicProvider(api_key="sk-test").cancel()


def test_cancel_twice_and_after_completion_is_safe():
    fake = FakeClient(chunks=["Done."])
    provider = _provider(fake)
    assert "".join(provider.rephrase("hi", "formal")) == "Done."

    provider.cancel()  # after completion: stream already deregistered
    provider.cancel()  # and cancel stays idempotent

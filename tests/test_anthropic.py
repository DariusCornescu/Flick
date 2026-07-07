"""Tests for the Anthropic provider (mocked SDK client)."""
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

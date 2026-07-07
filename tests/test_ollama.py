"""Tests for the Ollama provider (mocked HTTP)."""
import json

import pytest
import requests

from rephraser.core.llm.base import ProviderError
from rephraser.core.llm.ollama import OllamaProvider


class FakeResponse:
    def __init__(self, lines, status=200):
        self._lines = lines
        self.status_code = status

    def iter_lines(self, decode_unicode=False):
        yield from self._lines

    def json(self):
        return json.loads(self._lines[0])

    def close(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


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
    assert captured["payload"]["messages"][0]["role"] == "system"
    assert captured["payload"]["messages"][1] == {"role": "user", "content": "hi"}


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

"""Local Ollama provider - offline rephrasing via POST /api/chat (NDJSON stream)."""
from __future__ import annotations

import json
from collections.abc import Iterator

import requests

from .base import ProviderError, RephraseProvider, system_prompt

CONNECT_TIMEOUT_S = 5.0


class OllamaProvider(RephraseProvider):
    name = "ollama"

    def __init__(self, base_url: str, model: str, timeout: float = 60.0) -> None:
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._timeout = timeout

    def rephrase(self, text: str, mode: str) -> Iterator[str]:
        payload = {
            "model": self._model,
            "stream": True,
            "messages": [
                {"role": "system", "content": system_prompt(mode)},
                {"role": "user", "content": text},
            ],
        }
        try:
            response = requests.post(
                f"{self._base_url}/api/chat",
                json=payload,
                stream=True,
                timeout=(CONNECT_TIMEOUT_S, self._timeout),
            )
        except requests.ConnectionError as exc:
            raise ProviderError(
                "Ollama is not reachable - is it running? (ollama serve)"
            ) from exc
        except requests.Timeout as exc:
            raise ProviderError("Ollama request timed out.") from exc

        with response:
            if response.status_code >= 400:
                raise ProviderError(f"Ollama error: {self._error_detail(response)}")
            try:
                for line in response.iter_lines(decode_unicode=True):
                    if not line:
                        continue
                    data = json.loads(line)
                    if "error" in data:
                        raise ProviderError(f"Ollama error: {data['error']}")
                    chunk = data.get("message", {}).get("content", "")
                    if chunk:
                        yield chunk
                    if data.get("done"):
                        return
            except requests.Timeout as exc:
                raise ProviderError("Ollama stream timed out.") from exc
            except (requests.RequestException, json.JSONDecodeError) as exc:
                raise ProviderError(f"Ollama stream failed: {exc}") from exc

    @staticmethod
    def _error_detail(response: requests.Response) -> str:
        try:
            return response.json().get("error", f"HTTP {response.status_code}")
        except (ValueError, AttributeError):
            return f"HTTP {response.status_code}"

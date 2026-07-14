"""Local Ollama provider - offline rephrasing via POST /api/chat (NDJSON stream)."""
from __future__ import annotations

import json
import socket
import threading
from collections.abc import Iterator

import requests

from .base import ProviderError, RephraseProvider, example_messages, system_prompt

CONNECT_TIMEOUT_S = 5.0


class OllamaProvider(RephraseProvider):
    name = "ollama"

    def __init__(self, base_url: str, model: str, timeout: float = 60.0) -> None:
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._timeout = timeout
        self._cancel_lock = threading.Lock()
        self._cancelled = False
        self._response: requests.Response | None = None

    def cancel(self) -> None:
        with self._cancel_lock:
            self._cancelled = True
            response = self._response
        if response is None:
            return
        # Only socket.shutdown() can abort a recv() already blocked in the
        # worker thread; Response.close() can't take the buffered reader's
        # lock until that read returns (i.e. after the full read timeout).
        try:
            sock = response.raw.connection.sock
        except AttributeError:
            sock = None
        try:
            if sock is not None:
                sock.shutdown(socket.SHUT_RDWR)
            else:
                response.close()
        except Exception:  # noqa: BLE001 - best-effort abort
            pass

    def rephrase(self, text: str, mode: str) -> Iterator[str]:
        try:
            yield from self._stream_chat(text, mode)
        except Exception:  # noqa: BLE001 - cross-thread close raises varied types
            if self._cancelled:
                return  # aborted by cancel(); the outcome no longer matters
            raise

    def _stream_chat(self, text: str, mode: str) -> Iterator[str]:
        payload = {
            "model": self._model,
            "stream": True,
            # Low temperature: rephrasing wants faithful, stable rewrites, not
            # creative variance (small models echo or drift languages at 0.8).
            # num_ctx gives headroom for the system prompt + few-shot examples
            # + the user's text so nothing is silently truncated on gemma3:12b.
            "options": {"temperature": 0.3, "num_ctx": 8192},
            "messages": [
                {"role": "system", "content": system_prompt(mode)},
                *example_messages(mode),
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

        with self._cancel_lock:
            registered = not self._cancelled
            if registered:
                self._response = response
        if not registered:
            # cancel() won the race while the request was connecting.
            response.close()
            return

        try:
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
                    # requests wraps mid-stream read timeouts in ConnectionError,
                    # so this branch covers both dropped and stalled streams.
                    raise ProviderError(
                        f"Ollama stream failed (connection lost or timed out): {exc}"
                    ) from exc
        finally:
            with self._cancel_lock:
                self._response = None

    @staticmethod
    def _error_detail(response: requests.Response) -> str:
        try:
            return response.json().get("error", f"HTTP {response.status_code}")
        except (ValueError, AttributeError):
            return f"HTTP {response.status_code}"

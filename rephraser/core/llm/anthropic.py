"""Anthropic provider - streams a rewrite via the Messages API (official SDK)."""
from __future__ import annotations

import threading
from collections.abc import Iterator
from typing import Any

import anthropic

from .base import ProviderError, RephraseProvider, system_prompt

DEFAULT_MODEL = "claude-sonnet-5"
MAX_TOKENS = 8192


class AnthropicProvider(RephraseProvider):
    name = "anthropic"

    def __init__(
        self,
        api_key: str,
        model: str = DEFAULT_MODEL,
        timeout: float = 60.0,
    ) -> None:
        self._model = model
        self._client = anthropic.Anthropic(
            api_key=api_key, timeout=timeout, max_retries=1
        )
        self._cancel_lock = threading.Lock()
        self._cancelled = False
        self._stream: Any = None  # anthropic MessageStream while one is live

    def cancel(self) -> None:
        # MessageStream.close() closes the underlying HTTP response, making a
        # blocked read in the worker thread fail immediately instead of
        # waiting out the read timeout. (Relies on httpx's close aborting a
        # cross-thread recv - true on Windows; on POSIX a socket-shutdown
        # approach like OllamaProvider's would be the portable idiom.)
        with self._cancel_lock:
            self._cancelled = True
            stream = self._stream
        if stream is not None:
            try:
                stream.close()
            except Exception:  # noqa: BLE001 - best-effort abort
                pass

    def rephrase(self, text: str, mode: str) -> Iterator[str]:
        try:
            yield from self._stream_text(text, mode)
        except Exception:  # noqa: BLE001 - cross-thread close raises varied types
            if self._cancelled:
                return  # aborted by cancel(); the outcome no longer matters
            raise

    def _stream_text(self, text: str, mode: str) -> Iterator[str]:
        try:
            with self._client.messages.stream(
                model=self._model,
                max_tokens=MAX_TOKENS,
                system=system_prompt(mode),
                messages=[{"role": "user", "content": text}],
            ) as stream:
                with self._cancel_lock:
                    registered = not self._cancelled
                    if registered:
                        self._stream = stream
                if not registered:
                    # cancel() won the race while the request was opening;
                    # the context manager closes the never-read stream.
                    return
                try:
                    yield from stream.text_stream
                finally:
                    with self._cancel_lock:
                        self._stream = None
        except anthropic.AuthenticationError as exc:
            raise ProviderError(
                "Anthropic rejected the API key - update it in Settings."
            ) from exc
        except anthropic.RateLimitError as exc:
            raise ProviderError(
                "Anthropic rate limit hit - try again shortly."
            ) from exc
        except anthropic.APIStatusError as exc:
            raise ProviderError(f"Anthropic API error ({exc.status_code}).") from exc
        except anthropic.APITimeoutError as exc:
            # Must precede APIConnectionError (its parent class).
            raise ProviderError("Anthropic request timed out.") from exc
        except anthropic.APIConnectionError as exc:
            raise ProviderError(
                "Anthropic API unreachable - check your internet connection."
            ) from exc

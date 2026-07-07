"""Anthropic provider - streams a rewrite via the Messages API (official SDK)."""
from __future__ import annotations

from collections.abc import Iterator

import anthropic

from .base import ProviderError, RephraseProvider, system_prompt

DEFAULT_MODEL = "claude-opus-4-8"
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

    def rephrase(self, text: str, mode: str) -> Iterator[str]:
        try:
            with self._client.messages.stream(
                model=self._model,
                max_tokens=MAX_TOKENS,
                system=system_prompt(mode),
                messages=[{"role": "user", "content": text}],
            ) as stream:
                yield from stream.text_stream
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

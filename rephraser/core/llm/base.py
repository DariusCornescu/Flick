"""Provider interface and rephrasing mode prompts."""
from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterator

_OUTPUT_ONLY = (
    " Respond with ONLY the rewritten text - no preamble, no explanations, no"
    " quotation marks around the result, no markdown fences. Preserve the"
    " original language of the text. Your entire response is inserted directly"
    " into the user's document in place of the original text."
)

MODES: dict[str, str] = {
    "formal": (
        "You rewrite text in a professional, formal tone suitable for business"
        " communication, preserving the meaning." + _OUTPUT_ONLY
    ),
    "concise": (
        "You compress text to be as concise as possible while preserving its"
        " full meaning and tone." + _OUTPUT_ONLY
    ),
    "grammar": (
        "You fix grammar, spelling, and punctuation mistakes only. Do not"
        " change the style, tone, or word choice beyond what is needed to"
        " correct errors." + _OUTPUT_ONLY
    ),
    "casual": (
        "You rewrite text in a relaxed, casual, friendly tone, preserving the"
        " meaning." + _OUTPUT_ONLY
    ),
}


def system_prompt(mode: str) -> str:
    """Return the system prompt for *mode*; raises KeyError for unknown modes."""
    return MODES[mode]


class ProviderError(RuntimeError):
    """A user-presentable provider failure (unreachable, auth, timeout...)."""


class RephraseProvider(ABC):
    """Streams a rephrased version of the given text."""

    name: str = "base"

    @abstractmethod
    def rephrase(self, text: str, mode: str) -> Iterator[str]:
        """Yield chunks of the rewritten text. Raises ProviderError on failure."""

    def cancel(self) -> None:
        """Abort an in-flight :meth:`rephrase` promptly. Thread-safe.

        Called from a different thread than the one consuming ``rephrase``
        (the UI thread, while a worker is blocked in a network read).
        Implementations close their underlying transport so the blocked read
        fails immediately instead of waiting out the read timeout; the
        aborted ``rephrase`` then ends quietly rather than raising. A cancel
        that lands while the request is still connecting (no transport to
        close yet) takes effect as soon as the transport materializes.
        Cancel is sticky: create a new provider for the next request.
        Default is a no-op, meaning the worker can only stop between
        chunks."""

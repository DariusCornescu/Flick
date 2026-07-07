"""Provider interface and rephrasing mode prompts."""
from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterator

_OUTPUT_ONLY = (
    " Respond with ONLY the rewritten text - no preamble, no explanations, no"
    " quotation marks around the result, no markdown fences. The rewrite must"
    " be in the exact same language as the original text (with that language's"
    " correct diacritics and spelling). Never translate. Always apply the"
    " requested change - do not return the original text unchanged - and do"
    " not alter the meaning of the text. Your entire response is inserted"
    " directly into the user's document in place of the original text."
)

MODES: dict[str, str] = {
    "formal": (
        "You rewrite text in a professional, formal tone suitable for business"
        " communication, preserving the meaning." + _OUTPUT_ONLY
    ),
    "concise": (
        "You shorten text. Rewrite it in as few words as possible while"
        " keeping every fact and intention. Aggressively cut filler words,"
        " hedging, and redundancy. The rewrite must be noticeably shorter"
        " than the original." + _OUTPUT_ONLY
    ),
    "grammar": (
        "You fix grammar, spelling, and punctuation mistakes only. Do not"
        " change the style, tone, or word choice beyond what is needed to"
        " correct errors." + _OUTPUT_ONLY
    ),
    "casual": (
        "You make text sound relaxed and friendly. Rewrite it the way you"
        " would say it to a colleague you know well: everyday words,"
        " contractions where the language has them, no stiff or bureaucratic"
        " phrasing. The rewording must be clearly different from the"
        " original." + _OUTPUT_ONLY
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

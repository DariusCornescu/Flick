"""Post-generation output cleanup and a heuristic for when to retry.

Small local models sometimes wrap the rewrite in quotes or a code fence, prefix
it with a chatty preamble, echo the input unchanged, or refuse the task. These
pure helpers run after a stream completes: `clean_output` removes cosmetic
wrappers, and `needs_retry` decides whether a stricter second attempt is worth
making. Both are conservative - they must never mangle a genuine rewrite or
trigger a retry on legitimate content (a spurious retry doubles the wait on a
slow local model), so every pattern is deliberately narrow.
"""
from __future__ import annotations

import re

# Opening -> closing quote pairs the model might wrap the whole result in.
_QUOTE_PAIRS = (
    ('"', '"'),
    ("“", "”"),
    ("„", "”"),
    ("«", "»"),
    ("'", "'"),
)

# A leading line is stripped only when it is unmistakably a chatty preamble:
# an "here is the rewritten/result/text ...:" announce line (optionally led by
# an interjection), a bare interjection line, or the Romanian equivalents. A
# real content heading like "Here are the steps:" or "Here is the plan:" does
# NOT reference the output and is preserved.
_PREAMBLE = re.compile(
    r"^(?:(?:sure|certainly|of course|okay|ok|absolutely)[,.!]?\s*)?"
    r"here(?:'s| is| are)(?: the)?\s+"
    r"(?:rewritten|rewrite|rephrased|revised|result|text|version|following)"
    r"[^\n]*:\s*$",
    re.IGNORECASE,
)
_INTERJECTION_ONLY = re.compile(
    r"^(?:sure|certainly|of course|okay|ok|absolutely)[,.!]?\s*$",
    re.IGNORECASE,
)
# Like _PREAMBLE, an "iată ...:" line is stripped only when it references the
# output (textul/rezultatul/varianta/... rescris), so a real content heading
# like "Iată pașii de urmat:" is preserved.
_PREAMBLE_RO = re.compile(
    r"^(?:"
    r"iată[^\n]*\b(?:textul|rezultatul|varianta|versiunea|reformularea|"
    r"rescris|rescrisă|reformulat|reformulată)\b[^\n]*:|"
    r"rezultat(?:ul)?:|"
    r"textul rescris:"
    r")\s*$",
    re.IGNORECASE,
)

_FENCE = re.compile(r"^```[^\n]*\n(.*?)\n?```$", re.DOTALL)

# Meta-refusals: the model declining the task, not content that happens to
# express apology or inability. Every alternative references the task, help,
# a task object (that/this/your request), or an "as an AI ..." marker, so
# ordinary rewrites like "I am unable to attend", "I can't make it tomorrow",
# "I can't help you move", or "nu pot ajunge mâine" do NOT match.
_REFUSAL = re.compile(
    r"(?:"
    r"as an ai (?:language model|assistant|chatbot)\b|"
    r"as a language model\b|"
    r"i (?:can'?t|cannot|(?:'m|am) unable to|won'?t)\s+"
    r"(?:"
    r"help (?:you )?with (?:that|this)|"
    r"assist (?:you )?with (?:that|this)|"
    r"do (?:that|this)|"
    r"comply\b|"
    r"rewrite (?:that|this|the text|it)|"
    r"rephrase (?:that|this|the text|it)|"
    r"process (?:that|this|your request)|"
    r"fulfil(?:l)? (?:that|this|your request)|"
    r"generate (?:that|this)"
    r")|"
    r"i (?:can'?t|cannot) help with (?:that|this)\b|"
    r"nu pot (?:să )?(?:reformula|rescrie|rescriu|te ajut cu (?:asta|aceasta)|"
    r"face (?:asta|acest lucru)|îndeplini)\b|"
    r"ca (?:un )?asistent (?:ai|virtual|de limbaj)\b"
    r")",
    re.IGNORECASE,
)


def clean_output(text: str) -> str:
    """Remove cosmetic wrappers (fences, wrapping quotes, a preamble line)."""
    result = text.strip()
    result = _strip_code_fence(result)
    result = _strip_preamble(result)
    result = _strip_wrapping_quotes(result)
    return result.strip()


def _strip_code_fence(text: str) -> str:
    match = _FENCE.match(text)
    if not match:
        return text
    inner = match.group(1)
    # Do not strip when the fence delimiter recurs inside: the output may be a
    # legitimate multi-block rewrite, and stripping would orphan inner fences.
    if "```" in inner:
        return text
    return inner.strip()


def _strip_preamble(text: str) -> str:
    head, sep, rest = text.partition("\n")
    if not sep:
        return text
    line = head.strip()
    if _PREAMBLE.match(line) or _INTERJECTION_ONLY.match(line) or _PREAMBLE_RO.match(line):
        return rest.strip()
    return text


def _strip_wrapping_quotes(text: str) -> str:
    for open_q, close_q in _QUOTE_PAIRS:
        if (
            text.startswith(open_q)
            and text.endswith(close_q)
            and len(text) > len(open_q) + len(close_q)
        ):
            inner = text[len(open_q): len(text) - len(close_q)]
            # Only strip when the quote does not recur inside; otherwise the
            # wrappers may be part of a real quotation and stripping mangles it.
            if open_q not in inner and close_q not in inner:
                return inner.strip()
    return text


def _normalized(text: str) -> str:
    return " ".join(text.split()).casefold()


def needs_retry(original: str, result: str, mode: str) -> bool:
    """True when *result* should be re-generated with a stricter prompt.

    Fires on an empty response, on an echo of the input (except in ``grammar``
    mode, where returning already-correct text is valid), or on a meta-refusal
    to perform the task."""
    result = result.strip()
    if not result:
        return True
    if mode != "grammar" and _normalized(result) == _normalized(original):
        return True
    if _REFUSAL.search(result):
        return True
    return False

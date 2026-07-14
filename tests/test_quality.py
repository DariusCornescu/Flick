"""Tests for output cleanup and the retry heuristic."""
from rephraser.core.quality import clean_output, needs_retry


# -- clean_output --------------------------------------------------------------

def test_strips_wrapping_double_quotes():
    assert clean_output('"Hello there."') == "Hello there."


def test_strips_curly_quotes():
    assert clean_output("“Hello there.”") == "Hello there."


def test_strips_romanian_low_quotes():
    assert clean_output("„Salut acolo.”") == "Salut acolo."


def test_strips_bare_code_fence():
    assert clean_output("```\nHello there.\n```") == "Hello there."


def test_strips_language_tagged_code_fence():
    assert clean_output("```text\nHello there.\n```") == "Hello there."


def test_strips_leading_preamble_line():
    assert clean_output("Here is the rewritten text:\nHello there.") == "Hello there."
    assert clean_output("Sure, here's the rewrite:\nHello there.") == "Hello there."
    assert clean_output("Rezultat:\nSalut acolo.") == "Salut acolo."


def test_keeps_legitimate_colon_headings():
    # A first line ending in ':' that is real content (a heading/intro of a
    # list or instructional rewrite), not a chatty preamble, must survive.
    for text in (
        "Here are the steps:\nBoil the water.\nAdd the pasta.",
        "Here is the plan:\nShip on Friday.",
        "Sure, here are three reasons this matters:\nSpeed.\nCost.",
        "OK team, here is the deal:\nWe launch Monday.",
    ):
        assert clean_output(text) == text


def test_keeps_multiblock_output_with_inner_fences():
    # Output that both starts and ends with a fence but contains its own inner
    # fences (e.g. a before/after) must not be corrupted by stripping.
    text = "```\nold wording\n```\nbecomes\n```\nnew wording\n```"
    assert clean_output(text) == text


def test_keeps_internal_quotes():
    assert clean_output('He said "hi" to me.') == 'He said "hi" to me.'


def test_keeps_wrapping_quotes_when_quote_recurs_inside():
    # Ambiguous: stripping could mangle a real quoted fragment, so leave it.
    assert clean_output('"He said "hi"."') == '"He said "hi"."'


def test_does_not_strip_a_non_preamble_first_line():
    text = "First point: do the thing.\nSecond point."
    assert clean_output(text) == text


def test_trims_whitespace():
    assert clean_output("  Hello there.  ") == "Hello there."


def test_empty_stays_empty():
    assert clean_output("   ") == ""


# -- needs_retry ---------------------------------------------------------------

def test_retry_on_empty():
    assert needs_retry("hi", "", "formal")
    assert needs_retry("hi", "   ", "formal")


def test_retry_on_exact_echo_case_and_space_insensitive():
    assert needs_retry("Hello there.", "hello there.", "formal")
    assert needs_retry("Fix this", "Fix   this", "concise")


def test_grammar_mode_allows_unchanged_text():
    # Already-correct text is a valid grammar result; must not loop.
    assert not needs_retry("This is fine.", "This is fine.", "grammar")


def test_retry_on_meta_refusal_en_and_ro():
    assert needs_retry("some text", "As an AI, I cannot rewrite this.", "formal")
    assert needs_retry("some text", "I'm sorry, but I can't help with that.", "formal")
    assert needs_retry("ceva text", "Îmi pare rău, dar nu pot face asta.", "formal")


def test_no_retry_when_content_merely_mentions_inability():
    # Rephrasing an apology or a statement of inability is normal content,
    # not the model refusing the task.
    assert not needs_retry(
        "i cant make it tomorrow", "I am unable to attend tomorrow.", "formal"
    )
    assert not needs_retry("sorry im late", "I am sorry for being late.", "casual")


def test_no_retry_on_polite_declines_en():
    # "I'm sorry, but I can't <do a real-world thing>" is valid rewritten
    # content, not a task refusal.
    assert not needs_retry(
        "sorry i cant make it tmrw", "I'm sorry, but I can't make it tomorrow.", "formal"
    )
    assert not needs_retry(
        "cant help but feel excited",
        "I can't help but feel excited about the launch.",
        "casual",
    )
    assert not needs_retry(
        "cant help u move sat", "I can't help you move on Saturday.", "casual"
    )
    assert not needs_retry(
        "cant do refund today", "I cannot process your refund today.", "formal"
    )
    assert not needs_retry(
        "we cant make enough money",
        "I can't generate enough revenue this quarter.",
        "formal",
    )


def test_no_retry_on_ai_as_content():
    assert not needs_retry(
        "as an ai researcher i love this", "As an AI researcher, I love this field.", "formal"
    )


def test_no_retry_on_romanian_polite_declines():
    assert not needs_retry(
        "nu pot ajunge maine", "Îmi pare rău, dar nu pot ajunge mâine.", "formal"
    )
    assert not needs_retry(
        "nu pot sa te ajut cu mutarea", "Nu pot să te ajut cu mutarea.", "formal"
    )


def test_still_retries_genuine_task_refusals():
    assert needs_retry("x", "As an AI language model, I cannot comply.", "formal")
    assert needs_retry("x", "I can't help with that.", "formal")
    assert needs_retry("x", "I cannot rewrite this text.", "formal")
    assert needs_retry("ceva", "Nu pot reformula acest text.", "formal")


def test_no_retry_on_a_good_rewrite():
    assert not needs_retry(
        "hey send me the file", "Could you please send me the file?", "formal"
    )

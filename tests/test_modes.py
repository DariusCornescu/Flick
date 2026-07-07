"""Tests for the rephrase modes and provider base."""
import pytest

from rephraser.core.llm.base import MODES, system_prompt


def test_all_modes_present():
    assert set(MODES) == {"formal", "concise", "grammar", "casual"}


def test_prompts_demand_output_only():
    for mode in MODES:
        prompt = system_prompt(mode)
        assert "ONLY the rewritten text" in prompt


def test_unknown_mode_raises():
    with pytest.raises(KeyError):
        system_prompt("pirate")

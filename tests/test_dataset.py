"""Tests for opt-in local rephrase-pair logging."""
import json

import pytest

from rephraser.config import Config
from rephraser.core import dataset


@pytest.fixture(autouse=True)
def appdata(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    return tmp_path


def test_log_path_is_under_appdata():
    assert dataset.log_path() == Config.path().parent / "training_data.jsonl"


def test_log_rephrase_appends_jsonl_lines():
    dataset.log_rephrase({"input": "a", "final": "b"})
    dataset.log_rephrase({"input": "c", "final": "d"})

    lines = dataset.log_path().read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0]) == {"input": "a", "final": "b"}
    assert json.loads(lines[1]) == {"input": "c", "final": "d"}


def test_log_rephrase_preserves_diacritics():
    dataset.log_rephrase({"final": "Adaugă validare și mesajele de eroare."})
    raw = dataset.log_path().read_text(encoding="utf-8")
    assert "Adaugă validare și mesajele de eroare." in raw  # not \\u-escaped


def test_log_rephrase_is_best_effort(monkeypatch):
    # A write failure must be swallowed, never propagate into the paste flow.
    def boom(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr("pathlib.Path.open", boom)
    dataset.log_rephrase({"input": "x"})  # must not raise

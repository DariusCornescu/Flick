"""Tests for rephraser.config."""
import json

import pytest

from rephraser.config import Config


@pytest.fixture(autouse=True)
def appdata(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    return tmp_path


def test_defaults_when_no_file():
    cfg = Config.load()
    assert cfg.provider == "ollama"
    assert cfg.hotkey == "<ctrl>+<alt>+r"
    assert cfg.mode == "formal"
    assert cfg.enabled is True


def test_round_trip(appdata):
    cfg = Config(provider="anthropic", mode="casual", hotkey="<ctrl>+<alt>+q")
    cfg.save()
    assert (appdata / "Rephraser" / "config.json").exists()
    loaded = Config.load()
    assert loaded == cfg


def test_corrupt_file_returns_defaults(appdata):
    path = appdata / "Rephraser" / "config.json"
    path.parent.mkdir(parents=True)
    path.write_text("{not json", encoding="utf-8")
    assert Config.load() == Config()


def test_non_dict_file_returns_defaults(appdata):
    path = appdata / "Rephraser" / "config.json"
    path.parent.mkdir(parents=True)
    path.write_text("[1, 2]", encoding="utf-8")
    assert Config.load() == Config()


def test_unknown_keys_ignored(appdata):
    path = appdata / "Rephraser" / "config.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"provider": "anthropic", "bogus": 1}), encoding="utf-8")
    assert Config.load().provider == "anthropic"

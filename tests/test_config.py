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
    assert cfg.ollama_model == "gemma3:12b"
    assert cfg.anthropic_model == "claude-sonnet-5"


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


def test_wrong_typed_values_fall_back_to_defaults(appdata):
    path = appdata / "Rephraser" / "config.json"
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(
            {
                "ollama_url": 123,
                "enabled": "yes",
                "request_timeout": "60",
                "mode": "casual",
            }
        ),
        encoding="utf-8",
    )
    cfg = Config.load()
    assert cfg.ollama_url == Config().ollama_url
    assert cfg.enabled is True
    assert cfg.request_timeout == 60.0
    assert cfg.mode == "casual"


def test_request_timeout_accepts_int(appdata):
    path = appdata / "Rephraser" / "config.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"request_timeout": 30}), encoding="utf-8")
    cfg = Config.load()
    assert cfg.request_timeout == 30.0
    assert isinstance(cfg.request_timeout, float)


def test_launch_command_bootstraps_package_root():
    from rephraser.config import _launch_command

    command = _launch_command()
    assert "runpy.run_module('rephraser.app'" in command
    assert "sys.path.insert" in command
    assert " -m rephraser.app" not in command

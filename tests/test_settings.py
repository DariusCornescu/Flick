"""Tests for the Settings dialog write-back (offscreen)."""
import pytest

from rephraser import config as config_mod
from rephraser.config import Config
from rephraser.ui.settings import SettingsDialog


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    # Do not touch the real registry or credential store during the test.
    monkeypatch.setattr(config_mod, "is_run_on_startup", lambda: False)
    monkeypatch.setattr(config_mod, "set_run_on_startup", lambda enable: None)
    monkeypatch.setattr(config_mod, "get_api_key", lambda provider: None)
    return tmp_path


def test_save_persists_log_pairs_and_context(qapp):
    cfg = Config()
    dialog = SettingsDialog(cfg)
    dialog._log_pairs.setChecked(True)
    dialog._default_context.setText("building a CLI tool")

    dialog._save()

    assert cfg.log_pairs is True
    assert cfg.default_context == "building a CLI tool"
    reloaded = Config.load()
    assert reloaded.log_pairs is True
    assert reloaded.default_context == "building a CLI tool"


def test_save_can_clear_default_context(qapp):
    cfg = Config(default_context="old context")
    dialog = SettingsDialog(cfg)
    dialog._default_context.setText("")

    dialog._save()

    assert cfg.default_context == ""
    assert Config.load().default_context == ""

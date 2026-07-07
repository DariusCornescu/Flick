"""Persistent settings (JSON in %APPDATA%) and secure API-key storage (keyring)."""
from __future__ import annotations

import dataclasses
import json
import os
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

import keyring
import keyring.errors

APP_NAME = "Rephraser"
KEYRING_SERVICE = "rephraser"
DEFAULT_HOTKEY = "<ctrl>+<alt>+r"
RUN_VALUE_NAME = "Rephraser"


@dataclass
class Config:
    provider: str = "ollama"  # "ollama" | "anthropic"
    ollama_url: str = "http://localhost:11434"
    # gemma3 is multilingual (Romanian + English included); llama3.2 is not.
    ollama_model: str = "gemma3:4b"
    anthropic_model: str = "claude-opus-4-8"
    hotkey: str = DEFAULT_HOTKEY
    mode: str = "formal"
    enabled: bool = True
    request_timeout: float = 60.0

    @staticmethod
    def path() -> Path:
        base = os.environ.get("APPDATA") or str(Path.home())
        return Path(base) / APP_NAME / "config.json"

    @classmethod
    def load(cls) -> "Config":
        try:
            data = json.loads(cls.path().read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            return cls()
        if not isinstance(data, dict):
            return cls()
        # Keep only known fields whose JSON value matches the field's type;
        # a hand-edited config must never crash a provider later on.
        defaults = cls()
        known = {f.name for f in dataclasses.fields(cls)}
        clean: dict[str, object] = {}
        for key, value in data.items():
            if key not in known:
                continue
            default = getattr(defaults, key)
            if isinstance(default, bool):
                accepted = isinstance(value, bool)
            elif isinstance(default, float):
                accepted = isinstance(value, (int, float)) and not isinstance(value, bool)
                value = float(value) if accepted else value
            else:
                accepted = isinstance(value, type(default))
            if accepted:
                clean[key] = value
        return cls(**clean)  # type: ignore[arg-type]

    def save(self) -> None:
        path = self.path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")


def get_api_key(provider: str) -> str | None:
    try:
        return keyring.get_password(KEYRING_SERVICE, provider)
    except keyring.errors.KeyringError:
        return None


def set_api_key(provider: str, key: str) -> None:
    if key:
        keyring.set_password(KEYRING_SERVICE, provider, key)
        return
    try:
        keyring.delete_password(KEYRING_SERVICE, provider)
    except keyring.errors.KeyringError:
        pass


def _launch_command() -> str:
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}"'
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    interpreter = pythonw if pythonw.exists() else Path(sys.executable)
    # Run-key commands start in a system directory, where `-m rephraser.app`
    # is not importable from a source checkout. Bootstrap sys.path explicitly
    # so startup works without the package being pip-installed.
    package_root = Path(__file__).resolve().parent.parent
    bootstrap = (
        "import sys, runpy; "
        f"sys.path.insert(0, {str(package_root)!r}); "
        "runpy.run_module('rephraser.app', run_name='__main__')"
    )
    return f'"{interpreter}" -c "{bootstrap}"'


def set_run_on_startup(enable: bool) -> None:
    import winreg

    with winreg.OpenKey(
        winreg.HKEY_CURRENT_USER,
        r"Software\Microsoft\Windows\CurrentVersion\Run",
        0,
        winreg.KEY_SET_VALUE,
    ) as key:
        if enable:
            winreg.SetValueEx(key, RUN_VALUE_NAME, 0, winreg.REG_SZ, _launch_command())
        else:
            try:
                winreg.DeleteValue(key, RUN_VALUE_NAME)
            except FileNotFoundError:
                pass


def is_run_on_startup() -> bool:
    import winreg

    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Run",
        ) as key:
            winreg.QueryValueEx(key, RUN_VALUE_NAME)
            return True
    except OSError:
        return False

# Hotkey Rephraser Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Windows tray app that rephrases selected text anywhere via a global hotkey (Ctrl+Alt+R), streaming the result from Ollama or the Anthropic API into an editable popup, then pasting it back and restoring the clipboard.

**Architecture:** pynput listener thread → Qt Signal → main thread. Main thread does all clipboard/UI work; the LLM call streams from a QThread worker via signals. Providers implement a common `RephraseProvider.rephrase(text, mode) -> Iterator[str]` interface.

**Tech Stack:** Python 3.11+, PySide6, pynput, keyring, requests (Ollama), anthropic SDK.

**Environment note:** run tests with `QT_QPA_PLATFORM=offscreen` (set in `tests/conftest.py`). Commands below assume a venv at `.venv` with `requirements.txt` + `requirements-dev.txt` installed.

---

### Task 1: Scaffolding

**Files:**
- Create: `requirements.txt`, `requirements-dev.txt`, `.gitignore`
- Create: `rephraser/__init__.py`, `rephraser/core/__init__.py`, `rephraser/core/llm/__init__.py`, `rephraser/ui/__init__.py`, `tests/__init__.py`, `tests/conftest.py`

- [ ] **Step 1: Write requirements.txt**

```
PySide6>=6.7
pynput>=1.7.6
keyring>=25.0
requests>=2.32
anthropic>=0.45
```

- [ ] **Step 2: Write requirements-dev.txt**

```
-r requirements.txt
pytest>=8.0
pytest-qt>=4.4
```

- [ ] **Step 3: Write .gitignore** (standard Python: `__pycache__/`, `.venv/`, `*.pyc`, `.pytest_cache/`, `dist/`, `build/`)

- [ ] **Step 4: Write empty `__init__.py` files** (all empty except `rephraser/__init__.py` which gets `__version__ = "0.1.0"`)

- [ ] **Step 5: Write tests/conftest.py**

```python
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
```

- [ ] **Step 6: Create venv, install dev deps**

Run: `python -m venv .venv && .venv/Scripts/pip install -r requirements-dev.txt`
Expected: installs succeed.

- [ ] **Step 7: Commit** — `feat: scaffold rephraser package`

---

### Task 2: Config (`rephraser/config.py`)

**Files:**
- Create: `rephraser/config.py`
- Test: `tests/test_config.py`

- [ ] **Step 1: Write the failing tests**

```python
"""Tests for rephraser.config."""
import json

import pytest

from rephraser import config as config_mod
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


def test_unknown_keys_ignored(appdata):
    path = appdata / "Rephraser" / "config.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"provider": "anthropic", "bogus": 1}), encoding="utf-8")
    assert Config.load().provider == "anthropic"
```

- [ ] **Step 2: Run to verify failure** — `pytest tests/test_config.py -v` → import error.

- [ ] **Step 3: Implement rephraser/config.py**

```python
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
    ollama_model: str = "llama3.2"
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
        known = {f.name for f in dataclasses.fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in known})

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
    return f'"{interpreter}" -m rephraser.app'


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
```

- [ ] **Step 4: Run tests** — `pytest tests/test_config.py -v` → PASS.
- [ ] **Step 5: Commit** — `feat: add JSON config and keyring/API-key + startup helpers`

---

### Task 3: Provider interface & modes (`rephraser/core/llm/base.py`)

**Files:**
- Create: `rephraser/core/llm/base.py`
- Test: `tests/test_modes.py`

- [ ] **Step 1: Write the failing tests**

```python
"""Tests for the rephrase modes and provider base."""
from rephraser.core.llm.base import MODES, system_prompt


def test_all_modes_present():
    assert set(MODES) == {"formal", "concise", "grammar", "casual"}


def test_prompts_demand_output_only():
    for mode in MODES:
        prompt = system_prompt(mode)
        assert "ONLY the rewritten text" in prompt


def test_unknown_mode_raises():
    import pytest

    with pytest.raises(KeyError):
        system_prompt("pirate")
```

- [ ] **Step 2: Run to verify failure.**

- [ ] **Step 3: Implement rephraser/core/llm/base.py**

```python
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
```

- [ ] **Step 4: Run tests** → PASS.
- [ ] **Step 5: Commit** — `feat: add RephraseProvider interface and mode prompts`

---

### Task 4: Clipboard capture (`rephraser/core/capture.py`) — riskiest part, do early

**Files:**
- Create: `rephraser/core/capture.py`
- Test: `tests/test_capture.py`

Main-thread only. Backs up clipboard text, simulates Ctrl+C (after releasing the hotkey's own modifiers so a held Alt doesn't turn it into Ctrl+Alt+C), polls the clipboard for change against a sentinel with a ~500 ms deadline, pastes with Ctrl+V, restores.

- [ ] **Step 1: Write the failing tests**

```python
"""Tests for the clipboard round-trip (offscreen Qt clipboard)."""
import pytest
from PySide6.QtGui import QGuiApplication

from rephraser.core.capture import ClipboardCapture


@pytest.fixture
def capture(qapp):
    return ClipboardCapture()


def test_backup_and_restore(qapp, capture):
    QGuiApplication.clipboard().setText("original")
    backup = capture.backup_text()
    QGuiApplication.clipboard().setText("changed")
    capture.restore(backup)
    assert QGuiApplication.clipboard().text() == "original"


def test_capture_returns_copied_text(qapp, capture, monkeypatch):
    # Simulate the OS answering Ctrl+C by putting text on the clipboard.
    monkeypatch.setattr(
        capture, "_send_copy",
        lambda: QGuiApplication.clipboard().setText("selected words"),
    )
    assert capture.capture_selection(timeout_ms=200) == "selected words"


def test_capture_times_out_when_nothing_copied(qapp, capture, monkeypatch):
    monkeypatch.setattr(capture, "_send_copy", lambda: None)
    QGuiApplication.clipboard().setText("stale")
    assert capture.capture_selection(timeout_ms=120) is None


def test_paste_puts_text_on_clipboard(qapp, capture, monkeypatch):
    monkeypatch.setattr(capture, "_send_paste", lambda: None)
    capture.paste("new text")
    assert QGuiApplication.clipboard().text() == "new text"
```

- [ ] **Step 2: Run to verify failure.**

- [ ] **Step 3: Implement rephraser/core/capture.py**

```python
"""Clipboard round-trip: backup -> simulated copy with polling -> paste -> restore.

Every method here must run on the Qt main thread (QClipboard is not
thread-safe). Key simulation uses pynput's Controller.
"""
from __future__ import annotations

import time

from PySide6.QtCore import QCoreApplication
from PySide6.QtGui import QGuiApplication
from pynput.keyboard import Controller, Key

# Invisible-separator sentinel: never realistically equals user content.
_SENTINEL = "⁣rephraser::sentinel⁣"

# Modifiers to release before simulating Ctrl+C/Ctrl+V, so keys still held
# from the hotkey chord don't combine with the simulated keystroke.
_MODIFIERS = (
    Key.ctrl, Key.ctrl_l, Key.ctrl_r,
    Key.alt, Key.alt_l, Key.alt_r, Key.alt_gr,
    Key.shift, Key.shift_l, Key.shift_r,
    Key.cmd,
)

POLL_INTERVAL_S = 0.02
DEFAULT_TIMEOUT_MS = 500


class ClipboardCapture:
    def __init__(self) -> None:
        self._keyboard = Controller()

    # -- clipboard state ---------------------------------------------------
    def backup_text(self) -> str:
        return QGuiApplication.clipboard().text()

    def restore(self, backup: str) -> None:
        clipboard = QGuiApplication.clipboard()
        if backup:
            clipboard.setText(backup)
        else:
            clipboard.clear()

    # -- capture -----------------------------------------------------------
    def capture_selection(self, timeout_ms: int = DEFAULT_TIMEOUT_MS) -> str | None:
        """Copy the current selection and return it, or None on timeout.

        Marks the clipboard with a sentinel, simulates Ctrl+C, then polls
        until the clipboard content changes away from the sentinel.
        """
        clipboard = QGuiApplication.clipboard()
        clipboard.setText(_SENTINEL)
        self._send_copy()

        deadline = time.monotonic() + timeout_ms / 1000.0
        while time.monotonic() < deadline:
            QCoreApplication.processEvents()
            text = clipboard.text()
            if text and text != _SENTINEL:
                return text
            time.sleep(POLL_INTERVAL_S)
        return None

    def paste(self, text: str) -> None:
        QGuiApplication.clipboard().setText(text)
        self._send_paste()

    # -- key simulation (patched out in tests) ------------------------------
    def _release_modifiers(self) -> None:
        for key in _MODIFIERS:
            try:
                self._keyboard.release(key)
            except Exception:  # noqa: BLE001 - a single stuck key must not abort
                pass
        time.sleep(0.05)

    def _send_copy(self) -> None:
        self._release_modifiers()
        with self._keyboard.pressed(Key.ctrl):
            self._keyboard.press("c")
            self._keyboard.release("c")

    def _send_paste(self) -> None:
        self._release_modifiers()
        with self._keyboard.pressed(Key.ctrl):
            self._keyboard.press("v")
            self._keyboard.release("v")
```

- [ ] **Step 4: Run tests** — `pytest tests/test_capture.py -v` → PASS (pytest-qt provides `qapp`).
- [ ] **Step 5: Commit** — `feat: add clipboard round-trip with sentinel polling`

---

### Task 5: Global hotkey listener (`rephraser/core/hotkeys.py`)

**Files:**
- Create: `rephraser/core/hotkeys.py`
- Test: `tests/test_hotkeys.py`

- [ ] **Step 1: Write the failing tests**

```python
"""Tests for hotkey combo validation."""
from rephraser.core.hotkeys import HotkeyListener


def test_valid_combo():
    assert HotkeyListener.validate("<ctrl>+<alt>+r") is True


def test_invalid_combo():
    assert HotkeyListener.validate("not a hotkey") is False


def test_empty_combo():
    assert HotkeyListener.validate("") is False
```

- [ ] **Step 2: Run to verify failure.**

- [ ] **Step 3: Implement rephraser/core/hotkeys.py**

```python
"""Global hotkey listener (pynput) bridged to Qt via a Signal.

The pynput callback runs on the listener thread; `triggered` is emitted from
there and delivered to main-thread slots through Qt's queued connections.
Never touch UI from this module.
"""
from __future__ import annotations

from PySide6.QtCore import QObject, Signal
from pynput import keyboard


class HotkeyListener(QObject):
    triggered = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._listener: keyboard.GlobalHotKeys | None = None

    @staticmethod
    def validate(combo: str) -> bool:
        """True if *combo* is a parseable pynput hotkey like '<ctrl>+<alt>+r'."""
        if not combo:
            return False
        try:
            keyboard.HotKey.parse(combo)
        except ValueError:
            return False
        return True

    def start(self, combo: str) -> None:
        """(Re)start listening for *combo*. Raises ValueError if unparseable."""
        keyboard.HotKey.parse(combo)  # fail fast before tearing down the old one
        self.stop()
        self._listener = keyboard.GlobalHotKeys({combo: self._on_hotkey})
        self._listener.daemon = True
        self._listener.start()

    def stop(self) -> None:
        if self._listener is not None:
            self._listener.stop()
            self._listener = None

    def _on_hotkey(self) -> None:
        # Listener thread: only emit; Qt queues delivery to the main thread.
        self.triggered.emit()
```

- [ ] **Step 4: Run tests** → PASS.
- [ ] **Step 5: Commit** — `feat: add global hotkey listener with Qt signal bridge`

---

### Task 6: Ollama provider (`rephraser/core/llm/ollama.py`)

**Files:**
- Create: `rephraser/core/llm/ollama.py`
- Test: `tests/test_ollama.py`

- [ ] **Step 1: Write the failing tests**

```python
"""Tests for the Ollama provider (mocked HTTP)."""
import json

import pytest
import requests

from rephraser.core.llm.base import ProviderError
from rephraser.core.llm.ollama import OllamaProvider


class FakeResponse:
    def __init__(self, lines, status=200):
        self._lines = lines
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(response=self)

    def iter_lines(self, decode_unicode=False):
        yield from self._lines

    def json(self):
        return json.loads(self._lines[0])

    def close(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


def test_streams_chunks(monkeypatch):
    lines = [
        json.dumps({"message": {"content": "Hello"}, "done": False}),
        "",
        json.dumps({"message": {"content": " world"}, "done": False}),
        json.dumps({"message": {"content": ""}, "done": True}),
    ]
    captured = {}

    def fake_post(url, json=None, stream=False, timeout=None):
        captured["url"] = url
        captured["payload"] = json
        return FakeResponse(lines)

    monkeypatch.setattr(requests, "post", fake_post)
    provider = OllamaProvider("http://localhost:11434", "llama3.2")
    chunks = list(provider.rephrase("hi", "formal"))
    assert "".join(chunks) == "Hello world"
    assert captured["url"] == "http://localhost:11434/api/chat"
    assert captured["payload"]["model"] == "llama3.2"
    assert captured["payload"]["stream"] is True
    assert captured["payload"]["messages"][0]["role"] == "system"
    assert captured["payload"]["messages"][1] == {"role": "user", "content": "hi"}


def test_connection_error_maps_to_provider_error(monkeypatch):
    def fake_post(*args, **kwargs):
        raise requests.ConnectionError("refused")

    monkeypatch.setattr(requests, "post", fake_post)
    provider = OllamaProvider("http://localhost:11434", "llama3.2")
    with pytest.raises(ProviderError, match="not reachable"):
        list(provider.rephrase("hi", "formal"))


def test_stream_error_line_raises(monkeypatch):
    lines = [json.dumps({"error": "model 'nope' not found"})]
    monkeypatch.setattr(requests, "post", lambda *a, **k: FakeResponse(lines))
    provider = OllamaProvider("http://localhost:11434", "nope")
    with pytest.raises(ProviderError, match="not found"):
        list(provider.rephrase("hi", "formal"))
```

- [ ] **Step 2: Run to verify failure.**

- [ ] **Step 3: Implement rephraser/core/llm/ollama.py**

```python
"""Local Ollama provider - offline rephrasing via POST /api/chat (NDJSON stream)."""
from __future__ import annotations

import json
from collections.abc import Iterator

import requests

from .base import ProviderError, RephraseProvider, system_prompt

CONNECT_TIMEOUT_S = 5.0


class OllamaProvider(RephraseProvider):
    name = "ollama"

    def __init__(self, base_url: str, model: str, timeout: float = 60.0) -> None:
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._timeout = timeout

    def rephrase(self, text: str, mode: str) -> Iterator[str]:
        payload = {
            "model": self._model,
            "stream": True,
            "messages": [
                {"role": "system", "content": system_prompt(mode)},
                {"role": "user", "content": text},
            ],
        }
        try:
            response = requests.post(
                f"{self._base_url}/api/chat",
                json=payload,
                stream=True,
                timeout=(CONNECT_TIMEOUT_S, self._timeout),
            )
        except requests.ConnectionError as exc:
            raise ProviderError(
                "Ollama is not reachable - is it running? (ollama serve)"
            ) from exc
        except requests.Timeout as exc:
            raise ProviderError("Ollama request timed out.") from exc

        with response:
            if response.status_code >= 400:
                raise ProviderError(f"Ollama error: {self._error_detail(response)}")
            try:
                for line in response.iter_lines(decode_unicode=True):
                    if not line:
                        continue
                    data = json.loads(line)
                    if "error" in data:
                        raise ProviderError(f"Ollama error: {data['error']}")
                    chunk = data.get("message", {}).get("content", "")
                    if chunk:
                        yield chunk
                    if data.get("done"):
                        return
            except requests.Timeout as exc:
                raise ProviderError("Ollama stream timed out.") from exc
            except (requests.RequestException, json.JSONDecodeError) as exc:
                raise ProviderError(f"Ollama stream failed: {exc}") from exc

    @staticmethod
    def _error_detail(response: requests.Response) -> str:
        try:
            return response.json().get("error", f"HTTP {response.status_code}")
        except (ValueError, AttributeError):
            return f"HTTP {response.status_code}"
```

- [ ] **Step 4: Run tests** → PASS.
- [ ] **Step 5: Commit** — `feat: add streaming Ollama provider`

---

### Task 7: Anthropic provider (`rephraser/core/llm/anthropic.py`)

**Files:**
- Create: `rephraser/core/llm/anthropic.py`
- Test: `tests/test_anthropic.py`

Uses the official `anthropic` SDK (`messages.stream` → `text_stream`). Default model `claude-opus-4-8`. No sampling params, no `thinking` param (off by default on Opus 4.8 → lowest latency).

- [ ] **Step 1: Write the failing tests**

```python
"""Tests for the Anthropic provider (mocked SDK client)."""
from contextlib import contextmanager

import anthropic
import pytest

from rephraser.core.llm.anthropic import AnthropicProvider
from rephraser.core.llm.base import ProviderError


class FakeClient:
    def __init__(self, chunks=None, error=None):
        self._chunks = chunks or []
        self._error = error
        self.kwargs = None
        outer = self

        class _Messages:
            @contextmanager
            def stream(self, **kwargs):
                outer.kwargs = kwargs
                if outer._error is not None:
                    raise outer._error

                class _Stream:
                    text_stream = iter(outer._chunks)

                yield _Stream()

        self.messages = _Messages()


def _provider(fake):
    provider = AnthropicProvider(api_key="sk-test", model="claude-opus-4-8")
    provider._client = fake
    return provider


def test_streams_chunks():
    fake = FakeClient(chunks=["Good ", "morning."])
    provider = _provider(fake)
    assert "".join(provider.rephrase("gm", "formal")) == "Good morning."
    assert fake.kwargs["model"] == "claude-opus-4-8"
    assert fake.kwargs["messages"] == [{"role": "user", "content": "gm"}]
    assert "ONLY the rewritten text" in fake.kwargs["system"]


def test_auth_error_maps_to_provider_error():
    error = anthropic.AuthenticationError(
        message="bad key", response=_fake_httpx_response(401), body=None
    )
    provider = _provider(FakeClient(error=error))
    with pytest.raises(ProviderError, match="API key"):
        list(provider.rephrase("hi", "formal"))


def test_connection_error_maps_to_provider_error():
    error = anthropic.APIConnectionError(request=_fake_httpx_request())
    provider = _provider(FakeClient(error=error))
    with pytest.raises(ProviderError, match="unreachable"):
        list(provider.rephrase("hi", "formal"))


def _fake_httpx_request():
    import httpx

    return httpx.Request("POST", "https://api.anthropic.com/v1/messages")


def _fake_httpx_response(status):
    import httpx

    return httpx.Response(status, request=_fake_httpx_request())
```

- [ ] **Step 2: Run to verify failure.**

- [ ] **Step 3: Implement rephraser/core/llm/anthropic.py**

```python
"""Anthropic provider - streams a rewrite via the Messages API (official SDK)."""
from __future__ import annotations

from collections.abc import Iterator

import anthropic

from .base import ProviderError, RephraseProvider, system_prompt

DEFAULT_MODEL = "claude-opus-4-8"
MAX_TOKENS = 8192


class AnthropicProvider(RephraseProvider):
    name = "anthropic"

    def __init__(
        self,
        api_key: str,
        model: str = DEFAULT_MODEL,
        timeout: float = 60.0,
    ) -> None:
        self._model = model
        self._client = anthropic.Anthropic(api_key=api_key, timeout=timeout, max_retries=1)

    def rephrase(self, text: str, mode: str) -> Iterator[str]:
        try:
            with self._client.messages.stream(
                model=self._model,
                max_tokens=MAX_TOKENS,
                system=system_prompt(mode),
                messages=[{"role": "user", "content": text}],
            ) as stream:
                yield from stream.text_stream
        except anthropic.AuthenticationError as exc:
            raise ProviderError(
                "Anthropic rejected the API key - update it in Settings."
            ) from exc
        except anthropic.RateLimitError as exc:
            raise ProviderError("Anthropic rate limit hit - try again shortly.") from exc
        except anthropic.APIStatusError as exc:
            raise ProviderError(f"Anthropic API error ({exc.status_code}).") from exc
        except anthropic.APITimeoutError as exc:
            raise ProviderError("Anthropic request timed out.") from exc
        except anthropic.APIConnectionError as exc:
            raise ProviderError(
                "Anthropic API unreachable - check your internet connection."
            ) from exc
```

Note: `APITimeoutError` subclasses `APIConnectionError`, so it must be caught first.

- [ ] **Step 4: Run tests** → PASS.
- [ ] **Step 5: Commit** — `feat: add streaming Anthropic provider`

---

### Task 8: Result popup (`rephraser/ui/popup.py`)

**Files:**
- Create: `rephraser/ui/popup.py`

Frameless, always-on-top, appears near the cursor. Read-only while streaming; editable when done. Enter accepts (Shift+Enter = newline), Esc cancels, deactivation cancels.

- [ ] **Step 1: Implement rephraser/ui/popup.py**

```python
"""Frameless streaming result popup shown near the mouse cursor."""
from __future__ import annotations

from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtGui import QCursor, QGuiApplication, QKeyEvent
from PySide6.QtWidgets import QLabel, QPlainTextEdit, QVBoxLayout, QWidget

_STYLE = """
QWidget#popupRoot {
    background: #23272e;
    border: 1px solid #3d434d;
    border-radius: 8px;
}
QLabel { color: #9aa4b2; font-size: 11px; }
QLabel#title { color: #e6e9ef; font-size: 12px; font-weight: 600; }
QPlainTextEdit {
    background: #1b1e24;
    color: #e6e9ef;
    border: 1px solid #3d434d;
    border-radius: 6px;
    padding: 6px;
    font-size: 13px;
}
"""


class ResultPopup(QWidget):
    accepted = Signal(str)
    cancelled = Signal()

    def __init__(self) -> None:
        super().__init__(
            None,
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool,
        )
        self.setObjectName("popupRoot")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(_STYLE)
        self.setFixedSize(420, 220)

        self._title = QLabel("Rephrase", objectName="title")
        self._status = QLabel("")
        self._editor = QPlainTextEdit()
        self._editor.installEventFilter(self)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(6)
        layout.addWidget(self._title)
        layout.addWidget(self._editor)
        layout.addWidget(self._status)

        self._streaming = False
        self._closing_silently = False
        self._done = False

    # -- session lifecycle ---------------------------------------------------
    def begin(self, mode: str) -> None:
        self._streaming = True
        self._done = False
        self._closing_silently = False
        self._title.setText(f"Rephrase - {mode}")
        self._status.setText("Generating... (Esc to cancel)")
        self._editor.setPlainText("")
        self._editor.setReadOnly(True)
        self._move_near_cursor()
        self.show()
        self.raise_()
        self.activateWindow()
        self._editor.setFocus()

    def append_chunk(self, chunk: str) -> None:
        cursor = self._editor.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        cursor.insertText(chunk)
        self._editor.setTextCursor(cursor)

    def finish_stream(self) -> None:
        self._streaming = False
        self._done = True
        self._editor.setReadOnly(False)
        self._status.setText("Enter: insert / Shift+Enter: newline / Esc: cancel")
        self._editor.setFocus()

    def dismiss(self) -> None:
        """Close without emitting cancelled (used by the app on errors/accept)."""
        self._closing_silently = True
        self.hide()

    # -- geometry --------------------------------------------------------
    def _move_near_cursor(self) -> None:
        pos = QCursor.pos() + type(QCursor.pos())(12, 12)
        screen = QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
        area = screen.availableGeometry()
        x = min(max(pos.x(), area.left()), area.right() - self.width())
        y = min(max(pos.y(), area.top()), area.bottom() - self.height())
        self.move(x, y)

    # -- input handling ----------------------------------------------------
    def eventFilter(self, obj, event) -> bool:  # noqa: N802 (Qt naming)
        if obj is self._editor and event.type() == QEvent.Type.KeyPress:
            assert isinstance(event, QKeyEvent)
            if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                    return False  # let the editor insert a newline
                if self._done:
                    self._accept()
                return True
            if event.key() == Qt.Key.Key_Escape:
                self._cancel()
                return True
        return super().eventFilter(obj, event)

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        if event.key() == Qt.Key.Key_Escape:
            self._cancel()
            return
        super().keyPressEvent(event)

    def event(self, event) -> bool:  # noqa: N802
        if event.type() == QEvent.Type.WindowDeactivate and self.isVisible():
            # Transient popup: clicking elsewhere abandons the rephrase.
            if not self._closing_silently:
                self._cancel()
        return super().event(event)

    def closeEvent(self, event) -> None:  # noqa: N802
        if not self._closing_silently:
            self._cancel()
        super().closeEvent(event)

    # -- outcomes ----------------------------------------------------------
    def _accept(self) -> None:
        text = self._editor.toPlainText().strip()
        if not text:
            self._cancel()
            return
        self._closing_silently = True
        self.hide()
        self.accepted.emit(text)

    def _cancel(self) -> None:
        self._closing_silently = True
        self.hide()
        self.cancelled.emit()
```

- [ ] **Step 2: Run full test suite** (no new tests; popup is exercised in manual checklist) → PASS.
- [ ] **Step 3: Commit** — `feat: add frameless streaming result popup`

---

### Task 9: Tray icon (`rephraser/ui/tray.py`)

**Files:**
- Create: `rephraser/ui/tray.py`

- [ ] **Step 1: Implement rephraser/ui/tray.py**

```python
"""System tray icon and menu."""
from __future__ import annotations

from PySide6.QtCore import QRect, Qt, Signal
from PySide6.QtGui import QAction, QActionGroup, QBrush, QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

from rephraser.core.llm.base import MODES


def _make_icon() -> QIcon:
    pixmap = QPixmap(64, 64)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setBrush(QBrush(QColor("#4f8cc9")))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawRoundedRect(QRect(4, 4, 56, 56), 14, 14)
    painter.setPen(QColor("white"))
    font = painter.font()
    font.setBold(True)
    font.setPixelSize(38)
    painter.setFont(font)
    painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, "R")
    painter.end()
    return QIcon(pixmap)


class TrayIcon(QSystemTrayIcon):
    enabled_toggled = Signal(bool)
    mode_selected = Signal(str)
    settings_requested = Signal()
    quit_requested = Signal()

    def __init__(self, enabled: bool, mode: str) -> None:
        super().__init__(_make_icon())
        self.setToolTip("Rephraser")

        menu = QMenu()
        self._enabled_action = QAction("Enabled", menu, checkable=True, checked=enabled)
        self._enabled_action.toggled.connect(self.enabled_toggled)
        menu.addAction(self._enabled_action)

        mode_menu = menu.addMenu("Mode")
        self._mode_group = QActionGroup(mode_menu)
        self._mode_actions: dict[str, QAction] = {}
        for name in MODES:
            action = QAction(name.capitalize(), mode_menu, checkable=True)
            action.setChecked(name == mode)
            action.triggered.connect(lambda _=False, n=name: self.mode_selected.emit(n))
            self._mode_group.addAction(action)
            mode_menu.addAction(action)
            self._mode_actions[name] = action

        menu.addSeparator()
        settings_action = QAction("Settings...", menu)
        settings_action.triggered.connect(self.settings_requested)
        menu.addAction(settings_action)

        quit_action = QAction("Quit", menu)
        quit_action.triggered.connect(self.quit_requested)
        menu.addAction(quit_action)

        self._menu = menu  # keep alive; QSystemTrayIcon does not take ownership
        self.setContextMenu(menu)

    def set_mode(self, mode: str) -> None:
        action = self._mode_actions.get(mode)
        if action:
            action.setChecked(True)

    def notify(self, message: str, title: str = "Rephraser") -> None:
        self.showMessage(title, message, QSystemTrayIcon.MessageIcon.Warning, 4000)
```

- [ ] **Step 2: Commit** — `feat: add system tray icon and menu`

---

### Task 10: Settings dialog (`rephraser/ui/settings.py`)

**Files:**
- Create: `rephraser/ui/settings.py`

- [ ] **Step 1: Implement rephraser/ui/settings.py**

```python
"""Settings dialog: provider, models, API key, hotkey, run-on-startup."""
from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLineEdit,
    QMessageBox,
    QVBoxLayout,
)

from rephraser import config as config_mod
from rephraser.config import Config
from rephraser.core.hotkeys import HotkeyListener


class SettingsDialog(QDialog):
    def __init__(self, cfg: Config, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Rephraser Settings")
        self.setMinimumWidth(380)
        self._cfg = cfg

        self._provider = QComboBox()
        self._provider.addItems(["ollama", "anthropic"])
        self._provider.setCurrentText(cfg.provider)

        self._ollama_url = QLineEdit(cfg.ollama_url)
        self._ollama_model = QLineEdit(cfg.ollama_model)
        self._anthropic_model = QLineEdit(cfg.anthropic_model)

        self._api_key = QLineEdit()
        self._api_key.setEchoMode(QLineEdit.EchoMode.Password)
        if config_mod.get_api_key("anthropic"):
            self._api_key.setPlaceholderText("(stored - leave blank to keep)")
        else:
            self._api_key.setPlaceholderText("sk-ant-...")

        self._hotkey = QLineEdit(cfg.hotkey)
        self._startup = QCheckBox("Start with Windows")
        try:
            self._startup.setChecked(config_mod.is_run_on_startup())
        except OSError:
            self._startup.setEnabled(False)

        form = QFormLayout()
        form.addRow("Provider:", self._provider)
        form.addRow("Ollama URL:", self._ollama_url)
        form.addRow("Ollama model:", self._ollama_model)
        form.addRow("Anthropic model:", self._anthropic_model)
        form.addRow("Anthropic API key:", self._api_key)
        form.addRow("Hotkey:", self._hotkey)
        form.addRow("", self._startup)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

    def _save(self) -> None:
        combo = self._hotkey.text().strip()
        if not HotkeyListener.validate(combo):
            QMessageBox.warning(
                self,
                "Invalid hotkey",
                "Use the pynput format, e.g. <ctrl>+<alt>+r",
            )
            return

        self._cfg.provider = self._provider.currentText()
        self._cfg.ollama_url = self._ollama_url.text().strip() or self._cfg.ollama_url
        self._cfg.ollama_model = self._ollama_model.text().strip() or self._cfg.ollama_model
        self._cfg.anthropic_model = (
            self._anthropic_model.text().strip() or self._cfg.anthropic_model
        )
        self._cfg.hotkey = combo
        self._cfg.save()

        new_key = self._api_key.text().strip()
        if new_key:
            config_mod.set_api_key("anthropic", new_key)

        if self._startup.isEnabled():
            try:
                config_mod.set_run_on_startup(self._startup.isChecked())
            except OSError as exc:
                QMessageBox.warning(self, "Startup", f"Could not update startup entry: {exc}")

        self.accept()
```

- [ ] **Step 2: Commit** — `feat: add settings dialog`

---

### Task 11: Application wiring (`rephraser/app.py`)

**Files:**
- Create: `rephraser/app.py`

Owns the busy flag (re-entrancy lock, main-thread only), the worker thread, and the accept/cancel/fail flows. Exactly one clipboard restore + busy reset per session, centralized in `_finish_session`.

- [ ] **Step 1: Implement rephraser/app.py**

```python
"""Entry point - wires hotkey, capture, providers, popup, tray together."""
from __future__ import annotations

import sys

from PySide6.QtCore import QObject, QThread, QTimer, Signal
from PySide6.QtWidgets import QApplication, QSystemTrayIcon

from rephraser import config as config_mod
from rephraser.config import Config
from rephraser.core.capture import ClipboardCapture
from rephraser.core.hotkeys import HotkeyListener
from rephraser.core.llm.anthropic import AnthropicProvider
from rephraser.core.llm.base import ProviderError, RephraseProvider
from rephraser.core.llm.ollama import OllamaProvider
from rephraser.ui.popup import ResultPopup
from rephraser.ui.settings import SettingsDialog
from rephraser.ui.tray import TrayIcon

FOCUS_RETURN_DELAY_MS = 150
CLIPBOARD_RESTORE_DELAY_MS = 500


class RephraseWorker(QThread):
    chunk = Signal(str)
    finished_ok = Signal(str)
    failed = Signal(str)

    def __init__(self, provider: RephraseProvider, text: str, mode: str) -> None:
        super().__init__()
        self._provider = provider
        self._text = text
        self._mode = mode

    def run(self) -> None:  # worker thread - signals only, no UI
        parts: list[str] = []
        try:
            for piece in self._provider.rephrase(self._text, self._mode):
                if self.isInterruptionRequested():
                    return
                parts.append(piece)
                self.chunk.emit(piece)
        except ProviderError as exc:
            self.failed.emit(str(exc))
            return
        except Exception as exc:  # noqa: BLE001 - last-resort: never crash the app
            self.failed.emit(f"Unexpected error: {exc}")
            return
        result = "".join(parts).strip()
        if result:
            self.finished_ok.emit(result)
        else:
            self.failed.emit("The model returned an empty response.")


class RephraserApp(QObject):
    def __init__(self, app: QApplication) -> None:
        super().__init__(app)
        self._app = app
        self._config = Config.load()
        self._busy = False
        self._backup = ""
        self._worker: RephraseWorker | None = None

        self._capture = ClipboardCapture()
        self._popup = ResultPopup()
        self._popup.accepted.connect(self._on_accepted)
        self._popup.cancelled.connect(self._on_cancelled)

        self._tray = TrayIcon(self._config.enabled, self._config.mode)
        self._tray.enabled_toggled.connect(self._on_enabled_toggled)
        self._tray.mode_selected.connect(self._on_mode_selected)
        self._tray.settings_requested.connect(self._open_settings)
        self._tray.quit_requested.connect(self._quit)
        self._tray.show()

        self._listener = HotkeyListener(self)
        self._listener.triggered.connect(self._on_hotkey)
        self._start_listener()

    # -- tray/menu ---------------------------------------------------------
    def _on_enabled_toggled(self, enabled: bool) -> None:
        self._config.enabled = enabled
        self._config.save()

    def _on_mode_selected(self, mode: str) -> None:
        self._config.mode = mode
        self._config.save()

    def _open_settings(self) -> None:
        old_hotkey = self._config.hotkey
        dialog = SettingsDialog(self._config)
        if dialog.exec() and self._config.hotkey != old_hotkey:
            self._start_listener()

    def _quit(self) -> None:
        self._listener.stop()
        self._stop_worker()
        self._tray.hide()
        self._app.quit()

    def _start_listener(self) -> None:
        try:
            self._listener.start(self._config.hotkey)
        except ValueError:
            self._tray.notify(
                f"Invalid hotkey '{self._config.hotkey}' - falling back to default."
            )
            self._config.hotkey = config_mod.DEFAULT_HOTKEY
            self._config.save()
            self._listener.start(self._config.hotkey)

    # -- rephrase session ----------------------------------------------------
    def _on_hotkey(self) -> None:
        """Main-thread slot (queued from the listener thread)."""
        if self._busy or not self._config.enabled:
            return
        self._busy = True

        try:
            provider = self._make_provider()
        except ProviderError as exc:
            self._tray.notify(str(exc))
            self._busy = False
            return

        self._backup = self._capture.backup_text()
        text = self._capture.capture_selection()
        if not text or not text.strip():
            self._tray.notify("No text selected (or the app blocked the copy).")
            self._finish_session(restore=True)
            return

        self._popup.begin(self._config.mode)
        self._worker = RephraseWorker(provider, text, self._config.mode)
        self._worker.chunk.connect(self._on_chunk)
        self._worker.finished_ok.connect(self._on_stream_done)
        self._worker.failed.connect(self._on_failed)
        self._worker.start()

    def _make_provider(self) -> RephraseProvider:
        if self._config.provider == "anthropic":
            key = config_mod.get_api_key("anthropic")
            if not key:
                raise ProviderError("No Anthropic API key configured - open Settings.")
            return AnthropicProvider(
                api_key=key,
                model=self._config.anthropic_model,
                timeout=self._config.request_timeout,
            )
        return OllamaProvider(
            self._config.ollama_url,
            self._config.ollama_model,
            timeout=self._config.request_timeout,
        )

    # -- worker slots (main thread) -----------------------------------------
    def _on_chunk(self, piece: str) -> None:
        if self.sender() is self._worker:
            self._popup.append_chunk(piece)

    def _on_stream_done(self, _full_text: str) -> None:
        if self.sender() is self._worker:
            self._popup.finish_stream()

    def _on_failed(self, message: str) -> None:
        if self.sender() is not self._worker:
            return
        self._popup.dismiss()
        self._tray.notify(message)
        self._finish_session(restore=True)

    # -- popup outcomes -------------------------------------------------------
    def _on_accepted(self, text: str) -> None:
        # Popup is hidden; give focus time to return to the target window.
        QTimer.singleShot(FOCUS_RETURN_DELAY_MS, lambda: self._paste_and_restore(text))

    def _paste_and_restore(self, text: str) -> None:
        self._capture.paste(text)
        QTimer.singleShot(
            CLIPBOARD_RESTORE_DELAY_MS, lambda: self._finish_session(restore=True)
        )

    def _on_cancelled(self) -> None:
        if not self._busy:
            return
        self._finish_session(restore=True)

    # -- session teardown ------------------------------------------------------
    def _stop_worker(self) -> None:
        worker = self._worker
        self._worker = None
        if worker is not None and worker.isRunning():
            worker.requestInterruption()
            worker.finished.connect(worker.deleteLater)
        elif worker is not None:
            worker.deleteLater()

    def _finish_session(self, restore: bool) -> None:
        self._stop_worker()
        if restore:
            self._capture.restore(self._backup)
        self._backup = ""
        self._busy = False


def main() -> int:
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    app.setApplicationName("Rephraser")

    if not QSystemTrayIcon.isSystemTrayAvailable():
        print("System tray is not available; Rephraser cannot run.", file=sys.stderr)
        return 1

    rephraser = RephraserApp(app)  # noqa: F841 - kept alive by parent QApplication
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: Smoke test (offscreen import + construction)**

Run: `QT_QPA_PLATFORM=offscreen .venv/Scripts/python -c "import rephraser.app"` → no error.

- [ ] **Step 3: Run full suite** — `pytest -v` → all PASS.
- [ ] **Step 4: Commit** — `feat: wire app entry point with re-entrancy lock and worker thread`

---

### Task 12: README

**Files:**
- Create: `README.md`

Sections: what it is; requirements; install (venv + pip); running (`python -m rephraser.app`); usage flow; providers (Ollama default, `ollama pull llama3.2`; Anthropic key via Settings → Credential Manager); modes; hotkey format; run on startup; configuration file location; limitations (text-only clipboard restore, elevated windows); manual test checklist (copy round-trip in Notepad, cancel restores clipboard, empty selection notification, Ollama stopped notification, hotkey re-entry ignored).

- [ ] **Step 1: Write README.md** (content per outline above, concrete commands included)
- [ ] **Step 2: Commit** — `docs: add README with install/usage/config instructions`

---

### Task 13: Verification & review

- [ ] **Step 1:** `pytest -v` → all green.
- [ ] **Step 2:** Offscreen smoke construction of `RephraserApp` (guarded — tray may be unavailable offscreen; import-level smoke acceptable).
- [ ] **Step 3:** Multi-agent adversarial code review (threading/Qt correctness, spec compliance, Windows specifics); fix confirmed findings.
- [ ] **Step 4:** Push branch `feat/hotkey-rephraser`, open PR titled `feat: global-hotkey text rephraser (PySide6 + Ollama/Anthropic)`.

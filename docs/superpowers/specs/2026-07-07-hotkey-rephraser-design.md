# Hotkey Rephraser — Design

Date: 2026-07-07
Status: Approved (spec provided fully-formed by Darius; open points resolved below)

## Purpose

A Windows tray application that rephrases the currently selected text in *any*
application. The user presses a global hotkey (default `Ctrl+Alt+R`); the app
copies the selection, streams a rephrased version from an LLM into a small
popup near the cursor, and on confirmation pastes the result back in place —
restoring the user's original clipboard afterwards.

## Core flow

1. Global hotkey fires (pynput listener thread) → marshalled to the Qt main
   thread via a Signal.
2. Re-entrancy guard: if a rephrase is already in flight, the press is ignored.
3. Back up current clipboard (text; non-text content is treated as empty and
   restored as empty — see Limitations).
4. Simulate `Ctrl+C`. Before doing so, simulate *releases* of the hotkey's own
   modifiers (Ctrl/Alt/Shift) so a still-held `Alt` doesn't turn the copy into
   `Ctrl+Alt+C`.
5. Poll the clipboard until its contents change from a sentinel (or non-empty
   new text appears), with a ~500 ms timeout — no fixed sleep. Implementation:
   clear/mark the clipboard before copying, then poll every ~25 ms.
6. Timeout or empty text → tray notification ("No text selected"), restore
   clipboard, stop.
7. Send text + active mode's system prompt to the active provider; stream
   tokens into the popup.
8. Popup: frameless, near cursor, read-only while streaming, editable when the
   stream finishes. `Enter` accepts (`Shift+Enter` inserts a newline), `Esc`
   cancels. Losing focus cancels too (it's a transient popup).
9. Accept → put result on clipboard → simulate `Ctrl+V` → after a ~500 ms
   delay (paste is async in the target app) restore the original clipboard.
10. Cancel/error → restore the original clipboard immediately.

## Architecture

```
rephraser/
  core/
    hotkeys.py      # HotkeyListener: pynput GlobalHotKeys wrapper, QObject signal bridge
    capture.py      # ClipboardCapture: backup/copy-poll/paste/restore (main thread only)
    llm/
      base.py       # RephraseProvider ABC: rephrase(text, mode) -> Iterator[str]; MODES dict
      ollama.py     # OllamaProvider: POST /api/chat, stream=True (requests)
      anthropic.py  # AnthropicProvider: Messages API, stream (requests, SSE)
  ui/
    tray.py         # TrayIcon: enable/disable, mode submenu, settings, quit, notifications
    popup.py        # ResultPopup: frameless QPlainTextEdit near cursor, streaming append
    settings.py     # SettingsDialog: provider/model/API key/hotkey/startup toggle
  config.py         # Config dataclass <-> %APPDATA%/Rephraser/config.json; keyring for API key
  app.py            # RephraserApp: wires everything, owns worker thread + re-entrancy flag
```

## Key decisions (points the spec left open)

- **HTTP clients:** `requests` with `stream=True` for Ollama (NDJSON lines
  from `POST /api/chat`). The Anthropic provider uses the official `anthropic`
  SDK (`client.messages.stream(...)` → `text_stream`) — the SDK is the
  canonical integration path for Python; default model `claude-opus-4-8`.
  No sampling parameters (removed on current models); thinking left off for
  low latency.
- **Hotkey format:** pynput `GlobalHotKeys` syntax stored in config
  (`"<ctrl>+<alt>+r"`). Settings dialog validates by attempting to parse.
- **Streaming vs. editing:** the popup's editor is read-only during streaming
  and becomes editable when the stream ends (or errors). This avoids fighting
  the user's caret while appending tokens.
- **Worker threading:** the LLM call runs in a `QThread` worker emitting
  `chunk`/`finished`/`failed` signals. All UI and clipboard work stays on the
  main thread.
- **Re-entrancy:** a single boolean "busy" flag owned by the main thread
  (checked/set in the slot that handles the hotkey signal, cleared when the
  popup closes and clipboard restore completes). The listener thread never
  reads it — it just emits; the main thread ignores redundant requests.
- **Clipboard restore timing:** restore is deferred ~500 ms after `Ctrl+V` so
  the target app has read the clipboard.
- **Run on startup:** `HKCU\...\CurrentVersion\Run` registry value via
  `winreg`, pointing at `pythonw.exe -m rephraser.app` (or the frozen exe).
- **API key storage:** `keyring` service `"rephraser"`, username = provider
  name. Config JSON never contains the key.
- **Errors:** every failure path (LLM unreachable, timeout, empty selection,
  keyring missing) surfaces as a tray balloon; exceptions are caught at the
  worker boundary and in the hotkey slot.

## Rephrasing modes

`MODES: dict[str, str]` mapping mode → system prompt. All prompts end with an
explicit instruction: output ONLY the rewritten text — no preamble, no quotes,
no explanations, no markdown fences.

- `formal`, `concise`, `grammar`, `casual` (as specified).

## Testing

`pytest` with `QT_QPA_PLATFORM=offscreen`:

- `config`: round-trip save/load, defaults on missing/corrupt file.
- `capture`: poll-until-changed logic against the offscreen clipboard,
  timeout path, backup/restore.
- `providers`: request payload construction and stream parsing with mocked
  HTTP responses (Ollama NDJSON, Anthropic SSE), error mapping.
- `modes`: every prompt contains the "output only" clause.

Hotkey simulation and real paste round-trips need an interactive desktop and
are covered by a manual test checklist in the README, not CI.

## Limitations (accepted)

- Only text clipboard content is backed up/restored; copying an image before
  a rephrase loses it on restore. Documented in README.
- Apps that block simulated input (elevated windows, secure desktops) won't
  work — Windows UIPI restriction, not fixable from user-land Python.

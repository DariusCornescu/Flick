# Rephraser

A Windows tray application that rephrases the text you have selected in **any**
application. Press a global hotkey (default `Ctrl+Alt+R`), watch the rewrite
stream into a small popup near your cursor, tweak it if you like, press
`Enter` — and it replaces your selection. Your clipboard is restored afterwards.

Works fully offline with a local [Ollama](https://ollama.com) model, or with
the Anthropic API.

## How it works

1. The hotkey fires → your current clipboard is backed up.
2. The app simulates `Ctrl+C` and polls the clipboard (up to ~500 ms) for the
   copied selection — no fixed sleeps.
3. The text plus the active mode's system prompt is streamed through the
   configured LLM provider.
4. A frameless popup near the cursor shows the result as it is generated.
   When the stream finishes you can edit it. `Enter` inserts,
   `Shift+Enter` adds a newline, `Esc` cancels (clicking elsewhere cancels too).
5. On confirm the result is placed on the clipboard, `Ctrl+V` is simulated,
   and ~0.5 s later your original clipboard is restored.

## Requirements

- Windows 10/11
- Python 3.11+
- For the default provider: a running [Ollama](https://ollama.com) instance
- For the Anthropic provider: an Anthropic API key

## Install

```powershell
git clone https://github.com/DariusCornescu/Flick.git
cd Flick
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
```

If you want the default local provider:

```powershell
ollama pull llama3.2
```

## Run

```powershell
.venv\Scripts\python -m rephraser.app
```

An "R" icon appears in the system tray. Select text anywhere and press
`Ctrl+Alt+R`.

## Configuration

Right-click the tray icon:

- **Enabled** — master on/off toggle for the hotkey.
- **Mode** — switch between rephrasing modes:
  - `formal` — professional tone
  - `concise` — compress while preserving meaning
  - `grammar` — fix grammar/spelling only, keep the style
  - `casual` — relax the tone
- **Settings…** — provider, models, API key, hotkey, run on startup.
- **Quit**

Settings are stored as JSON in `%APPDATA%\Rephraser\config.json`.

### Providers

| Provider    | Default model      | Notes                                        |
|-------------|--------------------|----------------------------------------------|
| `ollama`    | `llama3.2`         | Default. Local & offline (`ollama serve`).   |
| `anthropic` | `claude-opus-4-8`  | Needs an API key.                            |

The Anthropic API key is stored in the **Windows Credential Manager** via
`keyring` (service `rephraser`) — it is never written to the JSON config or
any other plaintext file.

### Hotkey format

The hotkey uses pynput syntax, e.g. `<ctrl>+<alt>+r`, `<ctrl>+<shift>+<f9>`.
It is validated when you save.

### Run on Windows startup

The "Start with Windows" checkbox in Settings writes/removes a value under
`HKCU\Software\Microsoft\Windows\CurrentVersion\Run` pointing at
`pythonw.exe -m rephraser.app`.

## Development

```powershell
.venv\Scripts\pip install -r requirements-dev.txt
.venv\Scripts\python -m pytest -v
```

Tests run headless (`QT_QPA_PLATFORM=offscreen`); clipboard tests use Qt's
in-process offscreen clipboard and key simulation is stubbed out.

### Manual test checklist

Hotkey/paste round-trips need a real desktop session, so verify by hand:

1. Select text in Notepad → hotkey → result streams → `Enter` → text replaced,
   previous clipboard content restored.
2. Hotkey with the popup already open → second press is ignored.
3. `Esc` (or clicking another window) during streaming → nothing pasted,
   clipboard restored.
4. Hotkey with no selection → tray notification "No text selected".
5. Stop Ollama → hotkey → tray notification, no crash.
6. Switch provider to `anthropic` without a key → tray notification pointing
   to Settings.

## Limitations

- Only **text** clipboard content is backed up and restored. If you had an
  image on the clipboard, it is lost after a rephrase.
- Elevated (admin) windows don't accept simulated input from a non-elevated
  process (Windows UIPI) — run Rephraser elevated if you need it there.
- Apps with non-standard copy shortcuts (some terminals use
  `Ctrl+Shift+C`) won't respond to the simulated `Ctrl+C`.
- The hotkey chord is observed, **not swallowed** (pynput cannot suppress a
  single combination), so it still reaches the focused app. Windows treats
  `Ctrl+Alt` as `AltGr`: on layouts where `AltGr+R` produces a character
  (e.g. `®` on US-International), the default hotkey types that character
  over your selection. If your layout does this, pick a different hotkey in
  Settings (e.g. `<ctrl>+<shift>+<f9>`).
- The "Start with Windows" entry embeds the path of this checkout. If you
  move the folder, re-toggle the checkbox in Settings.

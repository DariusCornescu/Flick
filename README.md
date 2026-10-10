# Flick

**Rewrite text in any Windows app with one hotkey.** Select text anywhere, press `Ctrl+Alt+R`, watch the rewrite stream into a small popup next to your cursor, edit it if you like, and press `Enter` to replace your selection. Your clipboard is restored afterwards.

It runs fully offline with a local [Ollama](https://ollama.com) model, or with the Anthropic API. It handles Romanian and English natively.

## What it does

- **Works everywhere**: any app where you can select text and paste.
- **Streams the result** into a frameless popup you can edit before accepting (`Enter` inserts, `Shift+Enter` adds a newline, `Esc` cancels).
- **Several modes**: `formal`, `concise`, `grammar` (fix errors only), `casual`, `prompt` (turn a rough note into a clear instruction for an AI assistant), and **Translate** into English, Romanian, German, French, Spanish or Italian.
- **Compose window**: open it without selecting anything, add an optional context line (who the reader is, what you're working on), and rephrase pasted or typed text.
- **Private by default**: with Ollama, your text never leaves your machine. The Anthropic API key is stored in Windows Credential Manager, not in a config file.
- **Opt-in training data**: it can save the rewrites you accept, locally, as JSONL for fine-tuning a model on your own style. It is off by default and never uploaded.

## How it works

1. The hotkey fires and your clipboard is backed up.
2. The app simulates `Ctrl+C` and polls the clipboard for the selection, with no fixed sleeps.
3. The text and the active mode's prompt stream through the configured provider.
4. The popup shows the result as it is generated.
5. On confirm, the result is pasted over your selection and your original clipboard is restored.

Rewrites run at low temperature for stable, faithful results, and an output that echoes the input or refuses is retried once at a lower temperature. Each mode is steered with built-in English and Romanian examples so the rewrite keeps the input's language.

## Tech

Python 3.11, PySide6 (Qt) for the tray and popup, `pynput` for global hotkeys, `keyring` for credentials, Ollama and the Anthropic SDK as providers, and a headless pytest suite.

| Provider | Default model | Notes |
|---|---|---|
| `ollama` | `gemma3:12b` | Local and offline. Multilingual, including Romanian. |
| `anthropic` | `claude-sonnet-5` | Needs an API key. Highest quality. |

## Run it

Requires Windows 10/11 and Python 3.11+.

```powershell
git clone https://github.com/DariusCornescu/Flick.git
cd Flick
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
ollama pull gemma3:12b          # for the local provider
.venv\Scripts\python -m rephraser.app
```

A tray icon appears. Select text anywhere and press `Ctrl+Alt+R`. If your machine is tight on memory, `gemma3:4b` is a lighter multilingual model; switch models in Settings.

Settings (provider, models, default context, hotkey, start with Windows) are in the tray menu. They are stored in `%APPDATA%\Rephraser\config.json`.

## Development

```powershell
.venv\Scripts\pip install -r requirements-dev.txt
.venv\Scripts\python -m pytest -v
```

Tests run headless with `QT_QPA_PLATFORM=offscreen`. Hotkey and paste round trips need a real desktop session, so they are covered by a manual checklist.

## Known limitations

- Only text clipboard content is backed up. An image on the clipboard is lost after a rephrase.
- Admin windows don't accept simulated input from a non-elevated process (Windows UIPI).
- Apps with a non-standard copy shortcut (some terminals use `Ctrl+Shift+C`) won't respond to the simulated `Ctrl+C`.
- The hotkey isn't swallowed, so it still reaches the focused app. Windows treats `Ctrl+Alt` as `AltGr`, which on some layouts types a character over your selection. If yours does, pick another hotkey in Settings, such as `<ctrl>+<shift>+<f9>`.

## License

See [LICENSE](LICENSE).

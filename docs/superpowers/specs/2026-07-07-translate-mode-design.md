# Translate mode — design

**Date:** 2026-07-07
**Status:** implemented

## Goal

Translate the selection (or composed text) into a chosen target language,
picked from a tray submenu: **Mode → Translate → English / Romanian / German
/ French / Spanish / Italian**.

## Design

**Parametrized mode key, not new `MODES` entries.** The mode string is
`translate:<Language>` (e.g. `translate:German`):

- Every entry in `MODES` shares the `_OUTPUT_ONLY` suffix whose
  same-language / "Never translate" rules exist precisely so the other five
  modes never drift languages (a4aae6a). Translation is the one mode that
  must break that rule, so it gets its own prompt builder and output
  contract (`_translate_prompt`), and `system_prompt()` recognizes the
  `translate:` prefix before the `MODES` lookup. The `MODES` dict — and all
  loop-based invariant tests over it — stay untouched.
- The parametrized key flows through the existing plumbing for free: the
  tray emits it via `mode_selected`, config persists it as a plain string,
  and providers pass it to `system_prompt()` unchanged.
- `mode_label()` prettifies it for the popup title
  ("translate → German"); the raw key is never shown.
- The prompt tells the model to return text already entirely in the target
  language unchanged (deliberately different from `_OUTPUT_ONLY`'s
  "always apply the change").
- Targets are a curated tuple (`TRANSLATE_LANGUAGES`); `system_prompt()`
  accepts any non-empty target, so extending the list is a one-line change.

## Found along the way

Referencing the Mode submenu only through addMenu() locals let PySide6
garbage-collect the QMenu wrappers; under pytest the C++ objects were
reported deleted when resolved via `menuAction().menu()`. Submenus are now
anchored on the TrayIcon instance (`_mode_menu`, `_translate_menu`), and the
tray tests use those stable handles instead of transient wrapper lookups.

## Testing

- `test_modes.py`: target-language prompt content, no leakage of the
  "Never translate" rule, already-in-target tolerance, `translate:` with no
  target raises `KeyError`, curated targets all resolve, `mode_label`.
- `test_tray.py`: Translate submenu lists all targets under Mode, selecting
  a language emits `translate:<Language>`, persisted translate mode is
  checked on startup.
- `test_ollama.py`: the parametrized mode's system prompt reaches the
  provider payload.
- `test_compose_session.py`: compose window shows the pretty label.
- Live on `gemma3:4b` (2-run stability, all stable): RO→EN and EN→RO
  correct with proper diacritics; already-English input returned unchanged.
  Known 4B limit: occasional lexical slips on less-trained pairs (RO→DE
  rendered "maine" as "nächste Woche"); quality scales with model size as
  documented in the README.

# Movable popup + compose mode — design

**Date:** 2026-07-07
**Status:** implemented

## Goal

Two popup improvements requested together:

1. The result window can be dragged (it is frameless and used to be pinned
   where it appeared, often covering the text being rephrased).
2. The window can be opened *without* a selection ("compose"): type or paste
   text into it directly, rephrase with the active mode, and take the result
   away on the clipboard.

## Design

### Dragging

Standard frameless-window drag: `mousePressEvent` records the offset between
the global cursor and the window's top-left, `mouseMoveEvent` moves the
window while the left button is held, release ends the drag. Clicks inside
the editor are consumed by it, so the drag surface is the title strip, status
line, and margins; the title shows a move cursor as the affordance. Dragging
never deactivates the window, so it does not interact with click-away
cancellation.

### Compose sessions

- Tray gains **Compose…** (`compose_requested` signal). It works even while
  the hotkey is disabled - "Enabled" gates only the hotkey.
- `ResultPopup.begin_compose(mode)`: opens empty and editable. Enter inserts
  newlines (multi-line input); **Ctrl+Enter** submits. On submit the popup
  clears the editor, flips itself into the usual streaming state, and emits
  `compose_submitted(text)`; the app starts the same `RephraseWorker` used by
  hotkey sessions.
- **Accept copies instead of pasting.** A compose session has no target
  selection to replace, so on Enter the app puts the result on the clipboard
  (`ClipboardCapture.copy` - no simulated `Ctrl+V`) and the hint reads
  "Enter: copy". `RephraserApp` tracks this with `_manual_session`.
- **No clipboard backup/restore.** Manual sessions never touch the clipboard
  until accept, and restoring the empty backup would wipe it (or wipe the
  just-copied result). `_finish_session` skips restore for manual sessions.
- **Click-away does not cancel compose windows** - they hold user-typed text
  and are opened deliberately, so only Esc closes them. Hotkey sessions keep
  the existing transient behavior (click elsewhere cancels).
- Re-entrancy: `_busy` covers compose sessions too, so the hotkey and a
  second Compose are blocked while one session is open.

## Testing

- `tests/test_popup.py`: drag math (press/move/release), compose lifecycle
  (editable-empty, Ctrl+Enter submit payload + state flip, plain Enter =
  newline, empty submit ignored, result accept), click-away rules for both
  session kinds and their reset, Esc in compose.
- `tests/test_tray.py`: Compose… action present, emits `compose_requested`.
- `tests/test_compose_session.py`: app-level manual sessions - open/busy
  gating, accept copies (never pastes/restores), cancel leaves the clipboard
  alone, selection sessions still restore, submit starts the worker with the
  typed text, provider errors finish the session.
- `tests/test_capture.py`: `copy()` sets the clipboard and never simulates a
  keystroke.
- Offscreen runtime drive of the real popup: type → submit → stream →
  accept; verified payloads, hints, clipboard content, and state screenshots.

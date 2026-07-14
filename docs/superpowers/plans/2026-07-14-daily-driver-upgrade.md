# Rephraser Daily-Driver Upgrade Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

## Context

Flick (`rephraser`) is a Windows tray app that rewrites selected text via a global hotkey and streams the rewrite into a popup near the cursor. The owner uses it daily on **local Ollama** (does not want to pay for an API) and wants to (a) remove daily-driver friction, (b) improve rewrite quality — especially `prompt` mode, which is weak on the small local model — and (c) lay training-data groundwork for a future local fine-tune (their showcase piece).

Four decisions were made up front and drive this plan:

1. **Scope** = friction fix + rewrite quality + opt-in training-data logging. **No** training pipeline (that is a deferred follow-up).
2. **Popup** is **Esc-only**: it must never auto-cancel on focus loss (the current "closes while generating" bug), and gains a visible **×** close affordance.
3. **Prompt context** = an optional user "context" string (a persistent default in Settings applied to all rephrases, **plus** a per-session field in Compose), fenced off from the text to rewrite, **plus** built-in few-shot examples.
4. **Local model** default becomes **`gemma3:12b`** (owner's machine can run it, ~8 GB), prompts/examples tuned for it; the Anthropic model default is aligned with the provider constant.

**Goal:** Turn the hotkey rephraser into a comfortable daily driver on local Ollama and make the collected data training-ready for a future local fine-tune.

**Architecture:** Unchanged pipeline — pynput listener thread → Qt Signal → main thread does all clipboard/UI work; the LLM call streams from a `RephraseWorker` QThread via signals; providers implement `RephraseProvider.rephrase(text, mode, context="", strict=False) -> Iterator[str]`. New pieces: `rephraser/core/quality.py` (pure output-cleanup + retry heuristic) and `rephraser/core/dataset.py` (best-effort local JSONL append). Config stays a flat dataclass persisted to `%APPDATA%/Rephraser/config.json`; new fields are scalars so `Config.load`'s type-whitelist round-trips them for free.

**Tech Stack:** Python 3.11+, PySide6, pynput, keyring, requests (Ollama), anthropic SDK, pytest + pytest-qt (offscreen). No new runtime dependencies — dataset logging uses stdlib `json` + `pathlib`.

**Environment note:** run tests with `QT_QPA_PLATFORM=offscreen` (set in `tests/conftest.py`). Full suite: `.venv\Scripts\python -m pytest -q`.

---

## Dependency & sequencing note

Recommended order **1 → 2 → 3 → 4 → 5 → 6**, because several tasks touch the same seams:

- **Task 1 (popup Esc-only)** is fully independent (only `ui/popup.py` + `tests/test_popup.py`). Do it first for a quick daily-driver win.
- **Task 2 (few-shot + models)** changes the provider *message layout* (system → examples → user). Land it before Task 3 so context-fencing builds on a settled layout and provider-test message assertions are rewritten once.
- **Task 3 (context)** adds `context=""` to `rephrase` / `_stream_*` / `RephraseWorker` / both call sites and a shared `build_user_message()` in `base.py`. It updates every test stub's `rephrase` signature.
- **Task 4 (quality guard + retry)** extends `RephraseWorker.run`, adds `strict=False` to the provider signature (adjacent to `context` from Task 3 to avoid a second stub churn), and adds a `retrying` signal + popup retry state. Depends on Task 3's provider signature.
- **Task 5 (dataset logging)** depends on `RephraseWorker.finished_ok` still carrying the full text (currently dropped at `app.py:248-250`) and on session-stashing `original/mode/context/raw`. Independent of Task 4's internals but shares `app.py` teardown, so land it after 4.
- **Task 6** is verification & review.

Config gains exactly two new scalar fields: `default_context: str = ""` (Task 3) and `log_pairs: bool = False` (Task 5). Both round-trip through `Config.load`'s existing whitelist (`config.py:37-63`) with no loader change.

---

### Task 1: Popup Esc-only + visible × close

**Root cause (verified):** `ResultPopup.event()` (`rephraser/ui/popup.py:177-188`) cancels on **any** `WindowDeactivate` while visible and not `_closing_silently` and not `_composing`. It has no `_done` guard, so a selection/hotkey popup (`_composing=False`, set in `begin()` `popup.py:64-76`) is torn down by the spurious `WindowDeactivate` that arrives right after the app simulates Ctrl+C and fights the target app for foreground: `_cancel()` (`popup.py:205-208`) → `cancelled` → `RephraserApp._on_cancelled` (`app.py:281-284`) → `_finish_session` mid-stream. Compose is immune only via the `and not self._composing` clause. Decision 2: remove the focus-loss cancel for **all** sessions; only Esc (and the new ×) dismiss.

**Files:**
- Modify: `rephraser/ui/popup.py`
- Test: `tests/test_popup.py`

- [ ] **Step 1: Rewrite the two tests that encode the bug (verify they now fail).**
  - Replace `test_selection_session_still_cancels_on_click_away` (`test_popup.py:152-159`) with `test_selection_session_survives_click_away`: `popup.begin("formal")`, connect `cancelled` to a `fired` list, `popup.event(QEvent(QEvent.Type.WindowDeactivate))`, assert `fired == []` and `popup.isVisible()`.
  - Replace `test_begin_after_compose_resets_click_away_rule` (`:162-171`) with `test_selection_survives_deactivate_after_prior_compose`: `begin_compose("prompt")` → `dismiss()` → `begin("formal")` → deactivate → assert not cancelled, still visible.
  - Keep `test_compose_survives_click_away` (`:141-149`) and `test_escape_in_compose_cancels` (`:174-182`) as-is.
- [ ] **Step 2: Add coverage for the two regressions the fix must prevent.**
  - `test_streaming_selection_survives_deactivate`: `begin("formal")`, `append_chunk("partial")` (no `finish_stream` → `_done=False`), deactivate → not cancelled, visible.
  - `test_done_selection_survives_deactivate`: `begin("formal")`, `append_chunk("Result")`, `finish_stream()` (`_done=True`), deactivate → not cancelled, visible.
  - `test_close_button_cancels`: `begin("formal")`, connect `cancelled`, `popup._close_btn.click()`, assert `cancelled` fired once and `not popup.isVisible()`.
- [ ] **Step 3: Run to verify failure** — `pytest tests/test_popup.py -q`.
- [ ] **Step 4: Remove the focus-loss cancel.** Delete the `WindowDeactivate` branch in `event()` (`popup.py:177-188`); since the override existed only for this, drop the whole `event()` method (Qt default handling remains). Leave `closeEvent` (`:190-193`) so Alt+F4 still routes through `_cancel`. Keep the `_composing` flag (still used by Enter-handling in `eventFilter` and `finish_stream`); it just no longer gates a click-away rule.
- [ ] **Step 5: Add the × affordance.** In `__init__` (`popup.py:44-56`) wrap the title in a row: import `QPushButton`; create `self._close_btn = QPushButton("×")` (object name `"close"`, `PointingHand` cursor, `setFixedSize(20,20)`, `setFocusPolicy(Qt.NoFocus)` so it never steals editor focus); build a `QHBoxLayout` with `self._title` (stretch 1) + `self._close_btn`; add that row to the existing `QVBoxLayout` in place of the bare `self._title`. `self._close_btn.clicked.connect(self._cancel)`. Add a `QPushButton#close` rule to `_STYLE` (`:8-24`) matching the dark theme. The button is a child widget, so its clicks are consumed by it and do not start a window drag (`mousePressEvent` `:155`).
- [ ] **Step 6: Run tests** — `pytest tests/test_popup.py -q` → PASS; full suite → PASS.
- [ ] **Step 7: Commit** — `fix(popup): make popup Esc-only and add visible close affordance`

---

### Task 2: Few-shot examples + gemma3:12b default + Anthropic alignment

**Terrain (verified):** `MODES` (`base.py:17-53`) concatenates a per-mode lead with shared `_OUTPUT_ONLY` (`base.py:7-15`); `system_prompt(mode)` (`:56-58`) returns `MODES[mode]`. No few-shot exists; both providers send exactly `[system, user]` (`ollama.py:63-66`, `anthropic.py:62`). The prompt-mode spec (`docs/superpowers/specs/2026-07-07-prompt-mode-design.md`) documents that small gemma3 **regresses** when the system string grows (echoes input, answers questions) — so add few-shot as real alternating message turns, not more system text. Working tree already sets `AnthropicProvider.DEFAULT_MODEL="claude-sonnet-5"` (`anthropic.py:12`) while `Config.anthropic_model` defaults to `"claude-opus-4-8"` (`config.py:26`); align **Config to the provider constant** (`claude-sonnet-5`), matching the intentional edit. (If `claude-sonnet-5` is not the intended id, change both constants together and adjust the alignment test.)

**Files:**
- Modify: `rephraser/core/llm/base.py`, `rephraser/core/llm/ollama.py`, `rephraser/core/llm/anthropic.py`, `rephraser/config.py`, `README.md`
- Test: `tests/test_modes.py`, `tests/test_ollama.py`, `tests/test_anthropic.py`, `tests/test_config.py`

**Part A — model defaults (isolated commit):**

- [ ] **Step 1: Aligning tests.**
  - `tests/test_config.py::test_defaults_when_no_file`: add `assert cfg.ollama_model == "gemma3:12b"` and `assert cfg.anthropic_model == "claude-sonnet-5"`.
  - `tests/test_anthropic.py`: add `test_config_default_matches_provider_default` asserting `Config().anthropic_model == anthropic_module.DEFAULT_MODEL`. (Existing tests pass explicit `model="claude-opus-4-8"` via `_provider`, so they're unaffected.)
- [ ] **Step 2: Run to verify failure.**
- [ ] **Step 3: Implement.** `config.py:25` → `ollama_model: str = "gemma3:12b"` (update comment: 12B is default, ~8 GB, better nuance; 4B/`llama3.2` lighter fallbacks). `config.py:26` → `anthropic_model: str = "claude-sonnet-5"`. Leave `anthropic.py:12` as `claude-sonnet-5`.
- [ ] **Step 4: README.** Update providers table (`README.md:89-92`) to `gemma3:12b` / `claude-sonnet-5`; update install/quality prose (`:41-55`) so `ollama pull gemma3:12b` is primary.
- [ ] **Step 5: Commit** — `feat(config): default to gemma3:12b and align Anthropic model default`

**Part B — few-shot examples:**

- [ ] **Step 6: Failing tests.**
  - `tests/test_modes.py`: `test_example_messages_alternate_user_assistant` — for each mode with examples, `example_messages(mode)` is non-empty with roles alternating strictly `user, assistant, ...` and non-empty contents. `test_prompt_mode_has_bilingual_examples` — the user contents of `example_messages("prompt")` include an English item and a Romanian item (assert a diacritic `ă/ș/ț` in one, plain-ASCII English in another). Decide the unknown-mode contract (recommend `example_messages` returns `[]`; `system_prompt` still raises `KeyError`).
  - `tests/test_ollama.py::test_streams_chunks`: change assertions (`:103-104`) to layout-robust — `msgs = captured["payload"]["messages"]`; `assert msgs[0]["role"] == "system"`; `assert msgs[-1] == {"role": "user", "content": "hi"}`; assert middle turns alternate user/assistant. Add `assert captured["payload"]["options"]["num_ctx"] >= 8192`.
  - `tests/test_anthropic.py::test_streams_chunks`: change `:54` to `assert fake.kwargs["messages"][-1] == {"role": "user", "content": "gm"}` and assert earlier messages are alternating example turns.
- [ ] **Step 7: Run to verify failure.**
- [ ] **Step 8: Implement in `base.py`.** Add `EXAMPLES: dict[str, list[tuple[str, str]]]` (1 EN + 1 RO per mode; 2+ for `prompt` incl. complaint→imperative and question→"find the cause and fix it" traps; outputs clean, no quotes/fences). Add `def example_messages(mode) -> list[dict]` returning alternating `{"role":"user"...}, {"role":"assistant"...}` for `EXAMPLES.get(mode, [])`. Illustrative `prompt` examples:
  - EN `"you forgot to add validation on the login form and the error messages don't show"` → `"Add validation to the login form and make sure the error messages display correctly."`
  - RO `"nu mi-ai pus validare pe login și nu apar mesajele de eroare"` → `"Adaugă validare pe formularul de login și asigură-te că mesajele de eroare apar."`
  - Question trap EN `"why does the app crash when I open settings?"` → `"Find the cause of the crash that happens when opening settings and fix it."`
- [ ] **Step 9: Splice into providers.** Ollama `_stream_chat` (`ollama.py:56-67`): `messages = [system] + example_messages(mode) + [user]`; tune `options={"temperature": 0.3, "num_ctx": 8192}` (headroom for system + few-shot + context + text on 12B). Anthropic `_stream_text` (`anthropic.py:56-63`): `messages=[*example_messages(mode), {"role":"user",...}]`, `system` unchanged. Import `example_messages` in both.
- [ ] **Step 10: Run tests** → PASS.
- [ ] **Step 11: README** — note bilingual few-shot ships for every mode.
- [ ] **Step 12: Commit** — `feat(llm): add bilingual few-shot examples and tune Ollama for gemma3:12b`

---

### Task 3: Optional prompt context (persistent default + per-session)

**Decision 3:** optional context reachable from the hotkey flow (persistent `default_context` in Settings applied to all rephrases) and from Compose (per-session field), fenced off from the text-to-rewrite. Few-shot example turns stay clean; only the live final user turn carries fenced context.

**Files:**
- Modify: `rephraser/core/llm/base.py`, `rephraser/core/llm/ollama.py`, `rephraser/core/llm/anthropic.py`, `rephraser/app.py`, `rephraser/ui/popup.py`, `rephraser/ui/settings.py`, `rephraser/config.py`
- Test: `tests/test_config.py`, `tests/test_ollama.py`, `tests/test_anthropic.py`, `tests/test_popup.py`, `tests/test_compose_session.py`, `tests/test_cancel.py`

- [ ] **Step 1: Failing tests.**
  - `tests/test_config.py`: `test_default_context_round_trips` and `Config().default_context == ""`.
  - `tests/test_ollama.py` / `tests/test_anthropic.py`: `test_context_is_fenced_into_user_message` — `rephrase("hi","formal",context="Reader is a child")`; final user content contains `"hi"`, contains the context, and a fence marker (`"do not rewrite"` / `"Text to rewrite"`). `test_no_context_leaves_user_message_plain` — `context=""` → final user content is exactly `"hi"`.
  - `tests/test_popup.py`: `test_ctrl_enter_submits_compose_text` (`:74-87`) — `compose_submitted` now 2 args; `blocker.args == ["fa asta mai clar", ""]`; add `test_compose_submits_session_context`.
  - `tests/test_compose_session.py`: `RecordingBlockingProvider.rephrase(self, text, mode, context="")` (`:57`) records `(text, mode, context)`; `test_compose_submit_starts_worker_with_typed_text` (`:136-153`) drives `app._on_compose_submitted("textul meu", "ctx")` → `provider.calls == [("textul meu","formal","ctx")]`.
  - `tests/test_cancel.py`: add `context=""` to the three stub `rephrase` signatures (`:22`, `:66`, `:104`).
- [ ] **Step 2: Run to verify failure.**
- [ ] **Step 3: Shared builder in `base.py`.** `def build_user_message(text, context="") -> str:` — empty context → return `text` unchanged; else return a fenced block:
  ```
  Context (reference only — do not rewrite or answer this):
  <context>

  Text to rewrite:
  <text>
  ```
- [ ] **Step 4: Thread `context` through providers.** `base.py:71` abstract → `rephrase(self, text, mode, context="")`; Ollama/Anthropic `rephrase` → `_stream_*(text, mode, context)`; `_stream_*` build the final user content via `build_user_message(text, context)`.
- [ ] **Step 5: Thread through worker + call sites.** `RephraseWorker.__init__(..., context="")` (`app.py:31`) stores `self._context`; `run()` calls `provider.rephrase(self._text, self._mode, self._context)` (`app.py:48`). Hotkey site (`app.py:188`) passes `context=self._config.default_context`; compose site (`app.py:221`) passes `context=self._compose_context`.
- [ ] **Step 6: Config field.** Add `default_context: str = ""` (`config.py:20-30`); scalar round-trips.
- [ ] **Step 7: Compose per-session context in the popup.** Widen `compose_submitted = Signal(str, str)`. Add `self._context_input = QLineEdit()` above the editor, `setVisible(False)` by default; `begin()` hides it, `begin_compose()` clears + shows it. `_submit_compose()` (`popup.py:145-152`) reads `self._context_input.text().strip()` and emits `(text, context)`. App `_on_compose_submitted(self, text, context)` sets effective `self._compose_context = context or self._config.default_context` (per-session overrides default — document this).
- [ ] **Step 8: Settings field.** Add `self._default_context = QLineEdit(cfg.default_context)` + form row; in `_save()` write `self._cfg.default_context = self._default_context.text().strip()` — **do not** use the `... or self._cfg....` idiom (an empty field must clear the stored context).
- [ ] **Step 9: Run full suite** → PASS.
- [ ] **Step 10: README** — document both context inputs and that context is never rewritten.
- [ ] **Step 11: Commit** — `feat(context): optional fenced context for hotkey and compose flows`

---

### Task 4: Quality guard + single corrective retry

**Streaming tension (resolved):** chunks stream to the popup live via `chunk → _on_chunk → append_chunk` *before* the full text exists, so a full-output guard can only run *after* the stream. Resolution: guard in `RephraseWorker.run` after each attempt; on failure emit a new `retrying` signal so the popup clears and shows "Refining…", then run one bounded second attempt with a stricter corrective re-prompt and lower temperature; always `clean_output` the final text (replacing the current `"".join(parts).strip()` + empty-check at `app.py:63-67`).

**Files:**
- Create: `rephraser/core/quality.py`
- Modify: `rephraser/app.py` (`RephraseWorker`), `rephraser/core/llm/base.py`, `rephraser/core/llm/ollama.py`, `rephraser/core/llm/anthropic.py`, `rephraser/ui/popup.py`
- Test: `tests/test_quality.py` (new), `tests/test_retry.py` (new), `tests/test_ollama.py`, `tests/test_anthropic.py`, stub updates in `tests/test_cancel.py` / `tests/test_compose_session.py`

- [ ] **Step 1: Failing unit tests** — `tests/test_quality.py`: `clean_output` strips a fully-wrapping `"..."`/`“...”`, ` ```lang ... ``` ` fences, and a leading preamble line (`"Here is the rewritten text:"`, `"Sure,"`, `"Rezultat:"`); leaves internal quotes untouched; trims whitespace. `needs_retry(text, result, mode)`: `True` for empty; `True` for exact echo (casefold + collapsed-whitespace equal) in every mode **except** `grammar`; `True` for refusal patterns EN + RO (`"I can't"`, `"I cannot"`, `"as an AI"`, `"I'm sorry"`, `"Îmi pare rău"`, `"nu pot"`); `False` for a normal changed rewrite.
- [ ] **Step 2: Run to verify failure.**
- [ ] **Step 3: Implement `rephraser/core/quality.py`** — two pure functions (only `re`). Small curated refusal list; `clean_output` strips only when the *entire* output is wrapped.
- [ ] **Step 4: Failing worker/provider tests.**
  - `tests/test_retry.py`: stub provider `rephrase(self, text, mode, context="", strict=False)` yields the input verbatim (echo) on first call and a good rewrite when `strict=True`. Drive a real `RephraseWorker` (offscreen, `DirectConnection` signals like `tests/test_cancel.py`): `retrying` fires exactly once; `finished_ok` carries the cleaned good rewrite; control case (good first output) → `finished_ok` immediately, **no** `retrying`; "echo on both attempts" → one retry only, then `finished_ok` emits the cleaned second attempt (bounded — pin this contract).
  - `tests/test_ollama.py`: `test_strict_lowers_temperature_and_adds_corrective` — `payload["options"]["temperature"] <= 0.1` and final user content contains `"previous attempt"`.
  - `tests/test_anthropic.py`: `test_strict_sets_low_temperature` — `fake.kwargs.get("temperature", 1.0) <= 0.2` and corrective phrase present.
- [ ] **Step 5: Run to verify failure.**
- [ ] **Step 6: Add `strict` to the provider signature** (adjacent to Task 3's `context`). `base.py:71` → `rephrase(self, text, mode, context="", strict=False)`. Ollama `_stream_chat`: when `strict`, `options["temperature"]=0.1` and append a corrective sentence to the final user message. Anthropic `_stream_text`: when `strict`, pass `temperature=0.2` (currently none set, `anthropic.py:56-63`) and the same corrective suffix. Update the three `tests/test_cancel.py` stubs and the `tests/test_compose_session.py` stub to `rephrase(self, text, mode, context="", strict=False)`.
- [ ] **Step 7: Rework `RephraseWorker.run` (`app.py:45-67`).** Add `retrying = Signal()`. Factor the loop into `_attempt(self, strict) -> str | None` (emits `chunk`, returns raw joined string, or `None` on interruption / after emitting `failed`; preserve the interruption + late-failure suppression from `app.py:49-62`). Then:
  ```python
  def run(self):
      raw = self._attempt(strict=False)
      if raw is None:
          return
      if not self.isInterruptionRequested() and needs_retry(self._text, raw, self._mode):
          self.retrying.emit()
          retry = self._attempt(strict=True)
          if retry is None:
              return
          raw = retry
      final = clean_output(raw)
      if final:
          self.finished_ok.emit(final)
      else:
          self.failed.emit("The model returned an empty response.")
  ```
  The retry reuses the same (uncancelled) provider instance — safe, since `_stream_*` builds a fresh request each call.
- [ ] **Step 8: Popup retry state.** Add `clear_for_retry(self)` — `_done=False`, editor read-only + cleared, status `"Refining…"`. Connect `self._worker.retrying.connect(self._on_retrying)` at both worker sites (`app.py:189-192`, `:222-225`); `_on_retrying` guards `sender() is self._worker` then calls `popup.clear_for_retry()`. Existing `finished_ok → _on_stream_done → finish_stream()` re-enables editing after the retry.
- [ ] **Step 9: Run full suite** → PASS.
- [ ] **Step 10: Commit** — `feat(quality): clean model output and retry once on echo/refusal`

---

### Task 5: Opt-in training-data logging (JSONL, training-ready)

**Decision 1C:** opt-in local JSONL logging; **no** training pipeline. The full model output is discarded today — `finished_ok` carries it (`app.py:63-65`), `_on_stream_done` receives `_full_text` and drops it (`app.py:248-250`). Write point: `_on_accepted`/`_paste_and_restore` (`app.py:260-279`) where original + mode + context + raw + final are all knowable — but those currently live as locals and must be stashed on the session (like `self._backup`). Storage dir: `Config.path().parent`. No new dependency.

**Files:**
- Create: `rephraser/core/dataset.py`
- Modify: `rephraser/config.py`, `rephraser/app.py`, `rephraser/ui/settings.py`, `rephraser/ui/tray.py` (optional toggle), `README.md`
- Test: `tests/test_dataset.py` (new), `tests/test_config.py`, app-level gate test

- [ ] **Step 1: Failing tests.**
  - `tests/test_config.py`: `Config().log_pairs is False`; round-trips `True`.
  - `tests/test_dataset.py` (mirror `test_config.py`'s `monkeypatch.setenv("APPDATA", str(tmp_path))`): `log_rephrase({...})` appends one line to `Config.path().parent / "training_data.jsonl"`; the line is valid JSON with expected keys; a second call appends a second line (JSONL, not overwrite); Romanian diacritics survive (`ensure_ascii=False`); a write to an unwritable dir is swallowed (best-effort, no raise).
  - App gate test (extend `tests/test_compose_session.py`'s `_StubApp`): monkeypatch `rephraser.core.dataset.log_rephrase` to record calls; config `log_pairs=True`; drive `_on_stream_done("RAW")` then `_on_accepted("FINAL")` (manual session) → one record with `input`/`mode`/`context`/`output=="RAW"`/`final=="FINAL"`. `log_pairs=False` → zero calls.
- [ ] **Step 2: Run to verify failure.**
- [ ] **Step 3: Implement `rephraser/core/dataset.py`.** `log_path()` → `Config.path().parent / "training_data.jsonl"`; `log_rephrase(record)` → create parent dir, append `json.dumps(record, ensure_ascii=False)` + `"\n"`, wrap whole write in `try/except OSError` (never break a paste); `open_log_folder()` → `os.startfile(log_path().parent)` best-effort. Record schema (fine-tune pair is `input`→`final`, conditioned on `mode`/`context`; `output` kept for edit-delta):
  ```json
  {"ts":"2026-07-14T..Z","provider":"ollama","model":"gemma3:12b","mode":"formal",
   "context":"","input":"...","output":"...raw...","final":"...accepted...",
   "edited":true,"app_version":"0.1.0"}
  ```
- [ ] **Step 4: Config field.** Add `log_pairs: bool = False` (`config.py:20-30`); scalar bool round-trips (`config.py:54-55`).
- [ ] **Step 5: Stash session data + retain the dropped full text (`app.py`).** Stash `self._log_input/_log_mode/_log_context/_log_provider/_log_model` in `_on_hotkey` (`:187`) and `_on_compose_submitted` (`:207`). In `_on_stream_done` (`:248-250`), keep `self._log_raw = full_text` (rename the param). At accept, in `_on_accepted` manual branch (`:261-268`) and `_paste_and_restore` (`:272-279`), only if `self._config.log_pairs`, build the record and call `dataset.log_rephrase(...)` in a `try/except` (`final` = accepted `text`, `edited = final != self._log_raw`). Reset all `self._log_*` in `_finish_session` (`:303-314`).
- [ ] **Step 6: Settings checkbox.** Mirror `self._startup` (`settings.py:43-47`, `:94-100`): `QCheckBox("Log rephrases locally for training")` + row; in `_save()` set `self._cfg.log_pairs = self._log_pairs.isChecked()`. Optionally a `QPushButton("Open data folder")` → `dataset.open_log_folder`.
- [ ] **Step 7: (Optional) Tray toggle.** Mirror `_enabled_action` (`tray.py:49-53`): checkable `"Log rephrases"` action + `log_toggled = Signal(bool)`; connect in `app.py` (mirror `_on_enabled_toggled` `:106-108`) to write config + `save()`; keep in sync with the Settings checkbox.
- [ ] **Step 8: README + privacy note.** "Training-data logging" section: opt-in, **local only** (`%APPDATA%\Rephraser\training_data.jsonl`), never uploaded, one JSON object per line, safe to delete; brief schema.
- [ ] **Step 9: Run full suite** → PASS.
- [ ] **Step 10: Commit** — `feat(dataset): opt-in local JSONL logging of rephrase pairs`

---

### Task 6: Verification & review

- [ ] **Step 1: Full suite** — `.venv\Scripts\python -m pytest -q` → all green.
- [ ] **Step 2: Offscreen import smoke** — `QT_QPA_PLATFORM=offscreen .venv\Scripts\python -c "import rephraser.app"`.
- [ ] **Step 3: Lint** — no lint config ships today; run `ruff`/`flake8` only if added.
- [ ] **Step 4: Manual end-to-end checklist** (hotkey/paste needs a real desktop; verify against `gemma3:12b`):
  1. Notepad → select → hotkey → stream → **click another window while streaming** → popup **stays open** (the friction fix) → `Enter` → text replaced, clipboard restored.
  2. Click away **after** the stream finishes → still open; only `Esc` or the **×** dismisses (× visible, restores clipboard).
  3. Set a Settings **Default context** → hotkey rephrase reflects it; the context text is never inserted into the document.
  4. **Compose** with a per-session context → `Ctrl+Enter` reflects the session context (overrides default) → `Enter` copies.
  5. Trigger a likely echo (short input) → popup clears + shows **"Refining…"**, second cleaned attempt; final has no wrapping quotes/fences.
  6. Enable **Log rephrases** → accept → `training_data.jsonl` gains one valid line (`input`/`output`/`final`/`context`/`mode`, diacritics intact); disable → no new lines.
  7. Re-entry ignored while popup open; Ollama stopped → tray notice, no crash; `anthropic` without a key → tray notice.
- [ ] **Step 5: Adversarial code review** — threading/Qt correctness (retry re-entrancy, `sender() is self._worker` guards, no off-main-thread UI), spec compliance with the four decisions, Windows specifics, logging truly best-effort. Fix confirmed findings.
- [ ] **Step 6: Push branch, open PR** — `feat/daily-driver-upgrade`, title `feat: daily-driver upgrade (Esc-only popup, few-shot, context, quality retry, training logging)`.

---

## Deferred to a follow-up plan (explicitly out of scope)

The actual local-model fine-tune is a separate future plan and is **not** part of this work: dataset curation/cleaning from `training_data.jsonl`, train/val/test splitting, prompt/response formatting for the target base model, LoRA/QLoRA training config and runs, an evaluation harness (echo rate, faithfulness, diacritic correctness, per-mode quality), and packaging/serving the fine-tuned model back through the Ollama provider. This plan only makes the **data collection training-ready** (schema, JSONL, opt-in, local-only).

## Two judgment calls to confirm

- **Anthropic model string (Task 2):** the plan aligns `Config.anthropic_model` to the provider's already-edited `DEFAULT_MODEL="claude-sonnet-5"`. If that string is a placeholder rather than the real production id, change both `config.py:26` and `anthropic.py:12` together and keep the new alignment test as the guard.
- **"Echo persists after retry" contract (Task 4):** the plan emits the cleaned second attempt (bounded, never loops) rather than failing, because a genuine grammar-clean echo can be a valid answer. Pinned as a test so the behavior is explicit either way.

"""Opt-in local logging of rephrase pairs, to seed a future fine-tune.

When enabled, one JSON object per accepted rephrase is appended to a local
JSONL file next to the config. It is never uploaded anywhere. Writing is
best-effort: a failure must never break the paste/copy flow.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from rephraser.config import Config

FILENAME = "training_data.jsonl"


def log_path() -> Path:
    """Path of the JSONL log, alongside the config in %APPDATA%/Rephraser/."""
    return Config.path().parent / FILENAME


def log_rephrase(record: dict) -> None:
    """Append *record* as one JSONL line. Best-effort - never raises."""
    try:
        path = log_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError:
        pass


def open_log_folder() -> None:
    """Open the log's folder in the OS file browser. Best-effort."""
    try:
        folder = log_path().parent
        folder.mkdir(parents=True, exist_ok=True)
        os.startfile(folder)  # noqa: S606 - Windows-only, user-initiated
    except (OSError, AttributeError):  # AttributeError: startfile is Windows-only
        pass

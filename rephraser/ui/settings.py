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
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
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
        self._cfg.ollama_model = (
            self._ollama_model.text().strip() or self._cfg.ollama_model
        )
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
                QMessageBox.warning(
                    self, "Startup", f"Could not update startup entry: {exc}"
                )

        self.accept()

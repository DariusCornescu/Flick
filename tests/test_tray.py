"""Tests for the tray menu (offscreen)."""
from rephraser.ui.tray import TrayIcon


def test_tray_menu_has_compose_action(qapp):
    tray = TrayIcon(True, "formal")
    assert any(a.text() == "Compose..." for a in tray._menu.actions())


def test_compose_action_emits_signal(qapp, qtbot):
    tray = TrayIcon(True, "formal")
    action = next(a for a in tray._menu.actions() if a.text() == "Compose...")

    with qtbot.waitSignal(tray.compose_requested, timeout=1000):
        action.trigger()

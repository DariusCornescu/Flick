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


def test_tray_log_toggle_reflects_initial_state(qapp):
    tray = TrayIcon(True, "formal", log_pairs=True)
    action = next(a for a in tray._menu.actions() if a.text() == "Log rephrases")
    assert action.isCheckable()
    assert action.isChecked()


def test_log_toggle_emits_signal(qapp, qtbot):
    tray = TrayIcon(True, "formal")
    action = next(a for a in tray._menu.actions() if a.text() == "Log rephrases")

    with qtbot.waitSignal(tray.log_toggled, timeout=1000):
        action.trigger()


def test_set_log_enabled_updates_check_without_signal(qapp):
    tray = TrayIcon(True, "formal", log_pairs=False)
    fired = []
    tray.log_toggled.connect(lambda v: fired.append(v))

    tray.set_log_enabled(True)

    action = next(a for a in tray._menu.actions() if a.text() == "Log rephrases")
    assert action.isChecked()
    assert fired == []  # programmatic sync must not re-emit

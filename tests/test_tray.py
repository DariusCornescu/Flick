"""Tests for the tray menu (offscreen)."""
from rephraser.core.llm.base import TRANSLATE_LANGUAGES
from rephraser.ui.tray import TrayIcon


def _translate_menu(tray):
    # Use the stable instance handle: resolving submenus transiently via
    # menuAction().menu() under pytest trips a PySide6 wrapper-ownership bug
    # that reports the C++ QMenu as already deleted.
    return tray._translate_menu


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


def test_mode_menu_has_translate_submenu_with_languages(qapp):
    tray = TrayIcon(True, "formal")
    labels = [a.text() for a in _translate_menu(tray).actions()]
    assert labels == list(TRANSLATE_LANGUAGES)
    # and the submenu hangs off the Mode menu
    assert _translate_menu(tray).menuAction() in tray._mode_menu.actions()


def test_selecting_translate_language_emits_parametrized_mode(qapp, qtbot):
    tray = TrayIcon(True, "formal")
    german = next(
        a for a in _translate_menu(tray).actions() if a.text() == "German"
    )

    with qtbot.waitSignal(tray.mode_selected, timeout=1000) as blocker:
        german.trigger()

    assert blocker.args == ["translate:German"]


def test_translate_mode_checked_on_startup(qapp):
    tray = TrayIcon(True, "translate:French")
    french = next(
        a for a in _translate_menu(tray).actions() if a.text() == "French"
    )
    assert french.isChecked()

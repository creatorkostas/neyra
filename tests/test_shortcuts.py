import json
import unittest
from unittest.mock import Mock, patch
from pynput import keyboard
from neyra.hotkeys import Hotkeys
from neyra.shortcuts import DEFAULT_SHORTCUTS, load_bindings, validate_bindings, shortcut_warnings


class ShortcutTests(unittest.TestCase):
    def test_aliases_duplicates_and_partial_chords(self):
        custom = {**DEFAULT_SHORTCUTS, "dictation": "control+option+d"}
        self.assertEqual(validate_bindings(custom)["dictation"], "Ctrl+Alt+D")
        for value in ("Ctrl+Alt+A", "Ctrl+Alt", "A", "Ctrl+Ctrl+D", "Ctrl+???", "Ctrl+Alt+A+B"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_bindings({**DEFAULT_SHORTCUTS, "dictation": value})
        self.assertTrue(shortcut_warnings({**DEFAULT_SHORTCUTS, "dictation": "Ctrl+C"}))

    def test_corrupt_saved_preferences_use_defaults(self):
        settings = Mock()
        for raw in ('{', json.dumps({}), json.dumps({**DEFAULT_SHORTCUTS, "dictation": "Ctrl+Alt"})):
            settings.value.return_value = raw
            self.assertEqual(load_bindings(settings), DEFAULT_SHORTCUTS)

    def callbacks(self, bindings):
        with patch("neyra.hotkeys.keyboard.Listener") as listener:
            hotkeys = Hotkeys(bindings)
            hotkeys.start()
        self.addCleanup(hotkeys.stop)
        return hotkeys, listener.call_args.kwargs["on_press"], listener.call_args.kwargs["on_release"]

    def test_custom_hold_repeats_and_release_with_control_character(self):
        hotkeys, down, up = self.callbacks({**DEFAULT_SHORTCUTS, "dictation": "Ctrl+Alt+D"})
        started, stopped = Mock(), Mock()
        hotkeys.hold_start.connect(started)
        hotkeys.hold_stop.connect(stopped)
        for key in (keyboard.Key.ctrl_l, keyboard.Key.alt_l, keyboard.KeyCode.from_char("\x04")):
            down(key)
        down(keyboard.KeyCode.from_char("\x04"))
        started.assert_called_once()
        up(keyboard.KeyCode.from_char("d"))
        stopped.assert_called_once()
        self.assertFalse(hotkeys.holding)
        up(keyboard.Key.ctrl_l)
        up(keyboard.Key.alt_l)
        self.assertFalse(hotkeys.pressed)
        hotkeys.set_bindings(DEFAULT_SHORTCUTS)

    def test_function_key_toggle_latches_and_reconfiguration_waits_for_release(self):
        hotkeys, down, up = self.callbacks({**DEFAULT_SHORTCUTS, "toggle": "Alt+F8"})
        toggle = Mock()
        hotkeys.toggle.connect(toggle)
        down(keyboard.Key.alt_l)
        down(keyboard.Key.f8)
        down(keyboard.Key.f8)
        toggle.assert_called_once()
        with self.assertRaises(ValueError):
            hotkeys.set_bindings(DEFAULT_SHORTCUTS)
        up(keyboard.Key.f8)
        down(keyboard.Key.f8)
        self.assertEqual(toggle.call_count, 2)
        hotkeys.stop()
        down(keyboard.Key.ctrl_l)
        self.assertFalse(hotkeys.pressed)

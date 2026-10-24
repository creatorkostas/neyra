"""Speaker mute tests never touch the host audio system."""
from contextlib import contextmanager
import ctypes
import threading
import unittest
from unittest.mock import Mock, call, patch

from neyra import speaker_mute as mute


class SpeakerMuteTests(unittest.TestCase):
    def helper(self, backend, errors=None):
        patcher = patch.object(mute, "_output", return_value=backend)
        patcher.start()
        self.addCleanup(patcher.stop)
        helper = mute.SpeakerMute(errors)

        def finish():
            helper.close()
            helper._thread.join(2)
            self.assertFalse(helper._thread.is_alive())

        self.addCleanup(finish)
        return helper

    def flush(self, helper):
        helper._queue.join()

    def test_begin_and_end_are_idempotent_and_restore_original_target(self):
        backend = Mock()
        backend.snapshot.return_value = ("original-output", False)
        helper = self.helper(backend)
        helper.begin()
        helper.begin()
        helper.end()
        helper.end()
        self.flush(helper)
        backend.snapshot.assert_called_once()
        self.assertEqual(backend.set_muted.call_args_list,
                         [call("original-output", True), call("original-output", False)])

    def test_already_muted_output_is_never_unmuted(self):
        backend = Mock()
        backend.snapshot.return_value = ("speaker", True)
        helper = self.helper(backend)
        helper.begin()
        self.flush(helper)
        backend.set_muted.assert_not_called()
        helper.end()
        self.flush(helper)
        backend.set_muted.assert_called_once_with("speaker", True)

    def test_close_restores_and_ignores_later_requests(self):
        backend = Mock()
        backend.snapshot.return_value = ("speaker", False)
        helper = self.helper(backend)
        helper.begin()
        helper.close()
        helper.begin()
        helper.end()
        helper.close()
        helper._thread.join(2)
        self.assertFalse(helper._thread.is_alive())
        self.assertEqual(backend.set_muted.call_args_list,
                         [call("speaker", True), call("speaker", False)])
        self.assertFalse(helper._thread.daemon)

    def test_slow_os_call_does_not_block_begin_end_or_close(self):
        entered, release = threading.Event(), threading.Event()
        backend = Mock()

        def snapshot():
            entered.set()
            release.wait(2)
            return "speaker", False

        backend.snapshot.side_effect = snapshot
        helper = self.helper(backend)
        try:
            helper.begin()
            self.assertTrue(entered.wait(1))
            helper.end()
            helper.close()
            self.assertFalse(release.is_set())
        finally:
            release.set()
        helper._thread.join(2)
        self.assertEqual(backend.set_muted.call_args_list,
                         [call("speaker", True), call("speaker", False)])

    def test_failed_muting_still_attempts_restore(self):
        backend, errors = Mock(), Mock()
        backend.snapshot.return_value = ("speaker", False)
        backend.set_muted.side_effect = [OSError("mute failed"), None]
        helper = self.helper(backend, errors)
        helper.begin()
        self.flush(helper)
        self.assertEqual(backend.set_muted.call_args_list,
                         [call("speaker", True), call("speaker", False)])
        self.assertIn("mute failed", errors.call_args.args[0])

    def test_failed_restore_is_retried_and_retained_until_close(self):
        backend, errors = Mock(), Mock()
        backend.snapshot.return_value = ("speaker", False)
        backend.set_muted.side_effect = [None, OSError("offline"), OSError("offline"), None]
        helper = self.helper(backend, errors)
        helper.begin()
        helper.end()
        self.flush(helper)
        helper.close()
        helper._thread.join(2)
        self.assertEqual(backend.set_muted.call_args_list,
                         [call("speaker", True)] + [call("speaker", False)] * 3)
        self.assertEqual(errors.call_count, 2)

    def test_snapshot_failure_does_not_write_and_next_begin_can_retry(self):
        backend = Mock()
        backend.snapshot.side_effect = [OSError("unavailable"), ("speaker", False)]
        helper = self.helper(backend, Mock(side_effect=ValueError("callback failed")))
        helper.begin()
        self.flush(helper)
        backend.set_muted.assert_not_called()
        helper.begin()
        helper.end()
        self.flush(helper)
        self.assertEqual(backend.snapshot.call_count, 2)
        self.assertEqual(backend.set_muted.call_args_list,
                         [call("speaker", True), call("speaker", False)])

    def test_each_recording_captures_a_fresh_state(self):
        backend = Mock()
        backend.snapshot.side_effect = [("first", False), ("second", True)]
        helper = self.helper(backend)
        helper.begin()
        helper.end()
        helper.begin()
        helper.end()
        self.flush(helper)
        self.assertEqual(backend.set_muted.call_args_list,
                         [call("first", True), call("first", False), call("second", True)])


class PlatformMuteTests(unittest.TestCase):
    def test_pactl_preserves_explicit_sink_and_state(self):
        backend = mute._LinuxOutput()
        with patch.object(mute.shutil, "which", return_value="pactl"), patch.object(
            mute, "_run", side_effect=["alsa_output.usb", "Mute: yes", ""]
        ) as run:
            target, state = backend.snapshot()
            self.assertTrue(state)
            backend.set_muted(target, False)
        self.assertEqual(run.call_args_list, [call("pactl", "get-default-sink"),
                         call("pactl", "get-sink-mute", "alsa_output.usb"),
                         call("pactl", "set-sink-mute", "alsa_output.usb", "0")])

    def test_wpctl_resolves_default_once_and_keeps_numeric_sink(self):
        backend = mute._LinuxOutput()
        for volume, expected in (("Volume: 0.50", False), ("Volume: 0.50 [MUTED]", True)):
            with self.subTest(volume=volume), patch.object(
                mute.shutil, "which", side_effect=lambda tool: tool if tool == "wpctl" else None
            ), patch.object(mute, "_run", side_effect=['id 42, type PipeWire:Interface:Node\n', volume, ""]) as run:
                target, state = backend.snapshot()
                self.assertEqual(state, expected)
                backend.set_muted(target, True)
                run.assert_called_with("wpctl", "set-mute", "42", "1")

    def test_pactl_failure_falls_back_before_any_mutation(self):
        with patch.object(mute.shutil, "which", return_value="tool"), patch.object(
            mute, "_run", side_effect=[OSError("no PulseAudio"), "id 7, type Node", "Volume: 1.00"]
        ) as run:
            self.assertEqual(mute._LinuxOutput().snapshot(), (("wpctl", "7"), False))
            self.assertFalse(any("set" in str(c) for c in run.call_args_list))

    def test_unrecognized_state_and_missing_tools_fail_without_mutation(self):
        with patch.object(mute.shutil, "which", return_value=None), patch.object(mute, "_run") as run:
            with self.assertRaises(RuntimeError):
                mute._LinuxOutput().snapshot()
            run.assert_not_called()
        with patch.object(mute.shutil, "which", side_effect=lambda tool: tool if tool == "pactl" else None), patch.object(
            mute, "_run", side_effect=["sink", "unknown"]
        ):
            with self.assertRaises(RuntimeError):
                mute._LinuxOutput().snapshot()

    def test_mac_uses_only_output_mute_and_validates_state(self):
        backend = mute._MacOutput()
        with patch.object(mute, "_run", side_effect=["true", ""]) as run:
            target, state = backend.snapshot()
            self.assertTrue(state)
            backend.set_muted(target, False)
            run.assert_called_with("osascript", "-e", "set volume output muted false")
        with patch.object(mute, "_run", return_value="unknown"):
            with self.assertRaises(RuntimeError):
                backend.snapshot()

    def test_windows_snapshot_and_set_use_endpoint_identity_and_correct_methods(self):
        backend = mute._WindowsOutput()
        targets = []

        @contextmanager
        def endpoint(target=None):
            targets.append(target)
            yield "saved-endpoint", 123

        def com_call(pointer, index, argtypes=(), args=()):
            if index == 15:
                ctypes.cast(args[0], ctypes.POINTER(ctypes.c_int))[0] = 1
            return 0

        with patch.object(backend, "_endpoint", endpoint), patch.object(mute, "_com_call", side_effect=com_call) as com:
            target, state = backend.snapshot()
            self.assertEqual((target, state), ("saved-endpoint", True))
            backend.set_muted(target, False)
            self.assertEqual(targets, [None, "saved-endpoint"])
            self.assertEqual([c.args[1] for c in com.call_args_list], [15, 14])
            self.assertEqual(com.call_args.args[3], (0, None))

    def test_subprocess_has_timeout_and_no_shell(self):
        with patch.object(mute.subprocess, "run", return_value=Mock(stdout="false\n")) as run:
            self.assertEqual(mute._run("osascript", "-e", "script"), "false")
        self.assertEqual(run.call_args.args, (("osascript", "-e", "script"),))
        self.assertEqual(run.call_args.kwargs["timeout"], 3)
        self.assertTrue(run.call_args.kwargs["check"])
        self.assertNotIn("shell", run.call_args.kwargs)


if __name__ == "__main__":
    unittest.main()

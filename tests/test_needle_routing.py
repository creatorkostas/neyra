import json
import threading
import unittest
from unittest.mock import Mock, patch
from neyra.intent import NeedleRouter


class RoutingTests(unittest.TestCase):
    def route(self, response, text='make the music quieter'):
        agent = Mock()
        agent.complete.return_value = response
        with patch('needle.Needle', return_value=agent), patch('neyra.bundled.configure_bundled_runtime'):
            return NeedleRouter().route(text, ('firefox',), threading.Event())

    def test_valid_local_call_without_assistant(self):
        result = self.route({'function_calls': [{'name': 'media', 'arguments': {'action': 'volume down'}}], 'confidence': .95})
        self.assertEqual(json.loads(result), {'command': 'volume down'})

    def test_conversation_returns_no_tool(self):
        self.assertIsNone(self.route({'function_calls': [{'name': 'ask_assistant', 'arguments': {}}]}, 'What is gravity?'))
        self.assertIsNone(self.route({'function_calls': []}))

    def test_uncertain_ungrounded_and_multiple_calls_do_not_execute(self):
        call = {'name': 'open_app', 'arguments': {'name': 'firefox'}}
        for result in [dict(function_calls=[call], confidence=.2), dict(function_calls=[call, call], confidence=1), dict(function_calls=[call], confidence=1, validation={'ungrounded': ['open_app.name']})]:
            self.assertIn('clarification', json.loads(self.route(result)))

    def test_unregistered_app_is_rejected(self):
        with self.assertRaises(ValueError):
            NeedleRouter.canonical('open_app', {'name': 'powershell'}, ('firefox',))

    def test_cancel_before_loading(self):
        cancel = threading.Event(); cancel.set()
        with patch('needle.Needle') as load:
            with self.assertRaises(RuntimeError):
                NeedleRouter().route('hello', (), cancel)
            load.assert_not_called()

import json
import threading
import unittest
from unittest.mock import Mock, patch
from neyra.providers import AssistantProvider, endpoint


class ProviderTests(unittest.TestCase):
    def test_local_protocol_and_no_tool_execution(self):
        p = AssistantProvider('local', 'http://127.0.0.1:11434/v1', 'test')
        p._json = Mock(return_value={'choices': [{'message': {'content': 'Hello'}}]})
        delta = Mock()
        self.assertEqual(p.respond('system', 'hello', threading.Event(), delta), 'Hello')
        path, body = p._json.call_args.args
        self.assertEqual(path, '/chat/completions')
        self.assertEqual(body['model'], 'test')
        self.assertNotIn('tools', body)
        delta.assert_called_once_with('Hello')

    def test_opencode_session_disallows_actions_and_is_deleted(self):
        p = AssistantProvider('opencode_api', 'http://localhost:4096', 'provider/model')
        p._json = Mock(side_effect=[{'id': 'session1'}, {'parts': [{'type': 'text', 'text': 'Reply'}]}, True])
        self.assertEqual(p.respond('system', 'hello', threading.Event(), Mock()), 'Reply')
        calls = p._json.call_args_list
        self.assertEqual(calls[0].args[1]['permission'], [{'permission': '*', 'pattern': '*', 'action': 'deny'}])
        self.assertEqual(calls[1].args[1]['model'], {'providerID': 'provider', 'modelID': 'model'})
        self.assertEqual(calls[-1].kwargs['method'], 'DELETE')

    def test_cli_uses_stdin_and_cleans_up(self):
        process = Mock(returncode=0)
        process.communicate.return_value = (json.dumps({'type': 'text', 'part': {'text': 'Hi'}}), '')
        process.poll.return_value = 0
        p = AssistantProvider('opencode_cli', model='provider/model')
        with patch('neyra.providers.subprocess.Popen', return_value=process) as launch:
            self.assertEqual(p.respond('rules', 'hello; arbitrary shell syntax', threading.Event(), Mock()), 'Hi')
        args = launch.call_args.args[0]
        self.assertNotIn('hello; arbitrary shell syntax', args)
        self.assertNotIn('shell', launch.call_args.kwargs)
        config = json.loads(launch.call_args.kwargs['env']['OPENCODE_CONFIG_CONTENT'])
        self.assertEqual(config['permission'], {'*': 'deny'})
        self.assertEqual(process.communicate.call_args.args[0], 'hello; arbitrary shell syntax')

    def test_cancelled_request_does_not_send(self):
        p = AssistantProvider('local', model='test')
        p._json = Mock()
        cancel = threading.Event(); cancel.set()
        with self.assertRaisesRegex(RuntimeError, 'Cancelled'):
            p.respond('', '', cancel, Mock())
        p._json.assert_not_called()

    def test_config_identity_and_url_validation(self):
        self.assertNotEqual(AssistantProvider('local', model='a').active_id, AssistantProvider('local', model='b').active_id)
        for value in ['file:///tmp/a', 'http://remote.example', 'https://secret@example.com', 'https://example.com?key=secret']:
            with self.assertRaises(ValueError):
                endpoint(value)
        self.assertEqual(endpoint('http://localhost:8080/v1/'), 'http://localhost:8080/v1')

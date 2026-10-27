"""Text-only assistant transports; desktop actions are owned by Needle and Neyra."""
import base64
import hashlib
import json
import os
import subprocess
import tempfile
import threading
import time
from urllib.parse import urlsplit, quote
from urllib.request import Request, build_opener, HTTPRedirectHandler


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args):
        return None


def endpoint(value):
    parts = urlsplit(value)
    if parts.scheme not in ('http', 'https') or not parts.hostname or parts.username or parts.password or parts.query or parts.fragment:
        raise ValueError('Enter an HTTP(S) server URL without credentials, query, or fragment.')
    if parts.scheme == 'http' and parts.hostname not in ('localhost', '127.0.0.1', '::1'):
        raise ValueError('Use HTTPS for a remote provider, or HTTP on localhost.')
    return value.rstrip('/')


class AssistantProvider:
    def __init__(self, kind, url='', model='', executable='opencode'):
        self.kind, self.url, self.model, self.executable = kind, url, model, executable
        identity = json.dumps([kind, url, model, executable])
        self.active_id = 'provider:' + hashlib.sha256(identity.encode()).hexdigest()[:24]

    def accounts(self):
        return [{'id': self.active_id, 'label': self.kind, 'connected': self.kind != 'none'}]

    def _json(self, path, body=None, method=None):
        headers = {'Content-Type': 'application/json'}
        if self.kind == 'opencode_api':
            password = os.environ.get('OPENCODE_SERVER_PASSWORD')
            if password:
                user = os.environ.get('OPENCODE_SERVER_USERNAME', 'opencode')
                headers['Authorization'] = 'Basic ' + base64.b64encode(f'{user}:{password}'.encode()).decode()
        elif os.environ.get('NEYRA_ASSISTANT_API_KEY'):
            headers['Authorization'] = 'Bearer ' + os.environ['NEYRA_ASSISTANT_API_KEY']
        request = Request(endpoint(self.url) + path, data=None if body is None else json.dumps(body).encode(), headers=headers, method=method)
        with build_opener(NoRedirect()).open(request, timeout=90) as response:
            data = response.read(8_000_001)
        if len(data) > 8_000_000:
            raise ValueError('Provider response is too large.')
        return json.loads(data) if data else None

    def respond(self, instructions, input_text, cancel, on_delta, *, max_output_tokens=4096, image_data_url=None):
        if cancel.is_set():
            raise RuntimeError('Cancelled.')
        if self.kind == 'none':
            raise ValueError('Choose an assistant provider in Voice settings for conversational answers. Local tools work without one.')
        if image_data_url is not None:
            raise ValueError('Screen questions currently require the ChatGPT provider.')
        if self.kind == 'opencode_cli':
            answer = self._cli(instructions, input_text, cancel)
        elif self.kind == 'opencode_api':
            answer = self._opencode(instructions, input_text, cancel)
        else:
            if not self.model:
                raise ValueError('Enter the local server model name in Voice settings.')
            result = self._json('/chat/completions', {'model': self.model, 'messages': [
                {'role': 'system', 'content': instructions}, {'role': 'user', 'content': input_text}],
                'max_tokens': max_output_tokens, 'stream': False})
            answer = result['choices'][0]['message'].get('content')
        if cancel.is_set():
            raise RuntimeError('Cancelled.')
        if not isinstance(answer, str) or not answer.strip():
            raise ValueError('The assistant provider returned no text.')
        on_delta(answer)
        return answer

    def _opencode(self, instructions, text, cancel):
        session = self._json('/session', {'title': 'Neyra', 'permission': [{'permission': '*', 'pattern': '*', 'action': 'deny'}]})['id']
        path = '/session/' + quote(session, safe='')
        finished = threading.Event()
        def abort():
            while not finished.wait(.1):
                if cancel.is_set():
                    try:
                        self._json(path + '/abort', {})
                    except Exception:
                        pass
                    return
        watcher = threading.Thread(target=abort, daemon=True)
        watcher.start()
        try:
            body = {'system': instructions, 'parts': [{'type': 'text', 'text': text}]}
            if self.model:
                provider, separator, model = self.model.partition('/')
                if not separator or not model:
                    raise ValueError('OpenCode models use provider/model format.')
                body['model'] = {'providerID': provider, 'modelID': model}
            result = self._json(path + '/message', body)
            if result.get('info', {}).get('error'):
                raise RuntimeError('OpenCode could not complete the response. Check its provider configuration.')
            return '\n'.join(p['text'] for p in result.get('parts', []) if p.get('type') == 'text' and isinstance(p.get('text'), str))
        finally:
            finished.set()
            try:
                self._json(path, method='DELETE')
            except Exception:
                pass

    def _cli(self, instructions, text, cancel):
        # A dedicated empty cwd prevents accidentally exposing a user's project.
        env = os.environ.copy()
        env['OPENCODE_CONFIG_CONTENT'] = json.dumps({'permission': {'*': 'deny'}, 'agent': {
            'neyra': {'mode': 'primary', 'prompt': instructions, 'permission': {'*': 'deny'}}}})
        args = [self.executable, 'run', '--format', 'json', '--agent', 'neyra']
        if self.model:
            args += ['--model', self.model]
        with tempfile.TemporaryDirectory(prefix='neyra-assistant-') as folder:
            process = subprocess.Popen(args, cwd=folder, env=env, stdin=subprocess.PIPE,
                                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                       encoding='utf-8', creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            deadline = time.monotonic() + 180
            try:
                prompt = text
                while True:
                    if cancel.is_set() or time.monotonic() > deadline:
                        raise RuntimeError('Cancelled.' if cancel.is_set() else 'OpenCode timed out.')
                    try:
                        stdout, stderr = process.communicate(prompt, timeout=.2)
                        break
                    except subprocess.TimeoutExpired:
                        prompt = None
                if process.returncode:
                    raise RuntimeError('OpenCode failed. Check opencode auth and model settings.')
                parts = []
                for line in stdout.splitlines():
                    try:
                        event = json.loads(line)
                    except ValueError:
                        continue
                    if event.get('type') == 'error':
                        raise RuntimeError('OpenCode reported an error.')
                    if event.get('type') == 'text':
                        parts.append(event.get('part', {}).get('text', ''))
                return ''.join(parts)
            finally:
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.communicate(timeout=2)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.communicate()


def configured_provider(settings):
    kind = settings.value('assistant_provider', 'chatgpt')
    if kind == 'chatgpt':
        return None
    if kind not in ('none', 'local', 'opencode_api', 'opencode_cli'):
        raise ValueError('Unknown assistant provider.')
    default = 'http://127.0.0.1:4096' if kind == 'opencode_api' else 'http://127.0.0.1:11434/v1'
    return AssistantProvider(kind, settings.value(kind + '_url', default),
                             settings.value(kind + '_model', ''), settings.value('opencode_executable', 'opencode'))

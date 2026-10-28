"""Bounded phone transcription and conversation jobs; results never dispatch tools."""
import base64
from collections import OrderedDict
import json
import queue
import threading
import time
import uuid
import numpy as np
from PySide6.QtCore import QObject, Signal
from .conversation import ConversationMemory
from .stt import Transcriber


class CompanionJobs(QObject):
    completed = Signal(str, str, str)

    def __init__(self, owner):
        super().__init__(owner)
        self.owner = owner
        self.jobs = OrderedDict()
        self.memories = {}
        self.lock = threading.RLock()
        self.audio_job = None
        self.transcriber = None
        self.completed.connect(self.finish)

    def create(self, kind, body):
        scope = body.get('_peer', '')
        with self.lock:
            active = [j for j in self.jobs.values() if j['status'] == 'running']
            if len(active) >= 2:
                raise ValueError('Companion is busy. Try again shortly.')
            for key in list(self.jobs):
                if time.monotonic() - self.jobs[key]['created'] > 600 and self.jobs[key]['status'] != 'running':
                    del self.jobs[key]
            while len(self.jobs) >= 32:
                removable = next((k for k, j in self.jobs.items() if j['status'] != 'running'), None)
                if removable is None:
                    raise ValueError('Companion is busy.')
                del self.jobs[removable]
        identifier = uuid.uuid4().hex
        cancel = threading.Event()
        job = {'status': 'running', 'text': '', 'error': '', 'scope': scope,
               'cancel': cancel, 'created': time.monotonic(), 'kind': kind}
        if kind == 'transcribe':
            if self.audio_job or self.owner.recording or self.owner.processing or self.owner.notetaker_active:
                raise ValueError('Finish desktop recording or transcription first.')
            try:
                audio = base64.b64decode(body.get('pcm', ''), validate=True)
            except (ValueError, TypeError):
                raise ValueError('Invalid PCM audio.') from None
            if not 3200 <= len(audio) <= 1_920_000 or len(audio) % 2:
                raise ValueError('Record between 0.1 and 60 seconds of 16 kHz mono PCM16 audio.')
            with self.lock:
                self.jobs[identifier] = job
            if self.transcriber is None:
                self.transcriber = Transcriber()
                self.transcriber.finished.connect(self.audio_finished)
                self.transcriber.failed.connect(self.audio_failed)
            chunks = queue.Queue()
            samples = np.frombuffer(audio, dtype='<i2').astype(np.float32) / 32768
            for start in range(0, len(samples), 4000):
                chunks.put(samples[start:start + 4000])
            chunks.put(None)
            self.audio_job = identifier
            self.owner.processing = True
            self.owner.update_controls('Transcribing phone recording…')
            try:
                self.transcriber.run(chunks, model=self.owner.history.engine_choice.currentData())
            except Exception:
                self.audio_failed('Could not start the desktop speech engine.')
                raise
        elif kind == 'chat':
            text = body.get('text')
            if not isinstance(text, str) or not 1 <= len(text.strip()) <= 8000:
                raise ValueError('Enter between 1 and 8,000 characters.')
            client = self.owner.assistant_features.get_assistant_provider()
            account = client.active_id
            if callable(account):
                account = account()
            if scope not in self.memories and len(self.memories) >= 16:
                self.memories.pop(next(iter(self.memories)))
            memory = self.memories.setdefault(scope, ConversationMemory())
            context = memory.context(account)
            with self.lock:
                if any(j['scope'] == scope and j['kind'] == 'chat' and j['status'] == 'running' for j in active):
                    raise ValueError('Stop the current phone answer first.')
                self.jobs[identifier] = job
            job.update(account=account, request=text, memory=memory)
            instructions = ('You are Neyra, answering on the user\'s Android phone. Reply in concise natural spoken prose. '
                            'Use the bounded prior conversation only as context. Do not claim to execute actions or access '
                            'desktop screen, clipboard, files, or notes. You cannot run tools in this conversation. '
                            'If an action is requested, explain how to use Capture or Reminders instead.')
            prompt = json.dumps({'recentConversation': context, 'request': text}, ensure_ascii=False)
            def delta(value):
                with self.lock:
                    if not cancel.is_set():
                        job['text'] = (job['text'] + value)[:16000]
            def worker():
                try:
                    answer = client.respond(instructions, prompt, cancel, delta, max_output_tokens=2048)
                    if not cancel.is_set():
                        self.completed.emit(identifier, answer[:16000], '')
                except Exception as exc:
                    if not cancel.is_set():
                        self.completed.emit(identifier, '', str(exc)[:1000])
            threading.Thread(target=worker, daemon=True, name='companion-chat').start()
        else:
            raise ValueError('Unknown job kind.')
        return {'jobId': identifier}

    def audio_finished(self, text):
        self._audio_result(text, '')

    def audio_failed(self, error):
        self._audio_result('', error)

    def _audio_result(self, text, error):
        identifier, self.audio_job = self.audio_job, None
        if identifier:
            self.owner.processing = False
            if not self.owner.closing:
                self.owner.update_controls()
            self.finish(identifier, text, error)

    def finish(self, identifier, text, error):
        with self.lock:
            job = self.jobs.get(identifier)
            if not job or job['cancel'].is_set():
                return
            job.update(status='failed' if error else 'done', text=text, error=error)
            if not error and job['kind'] == 'chat':
                job['memory'].remember(job['account'], job['request'], text)

    def status(self, body):
        with self.lock:
            job = self.jobs.get(body.get('jobId'))
            if not job or job['scope'] != body.get('_peer', ''):
                raise ValueError('Job expired or belongs to another phone. Start again.')
            if body.get('action') == 'cancel':
                job['cancel'].set()
                job.update(status='cancelled', text='')
            return {key: job[key] for key in ('status', 'text', 'error')}

    def forget(self, scope):
        with self.lock:
            self.memories.pop(scope, None)
            for job in self.jobs.values():
                if job['scope'] == scope:
                    job['cancel'].set()
                    job.update(status='cancelled', text='')
        return {'message': 'Phone conversation cleared.'}

    def close(self):
        with self.lock:
            for job in self.jobs.values():
                job['cancel'].set()
            self.memories.clear()
        if self.transcriber:
            threading.Thread(target=self.transcriber.close, daemon=True).start()

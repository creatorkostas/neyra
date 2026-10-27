"""Local Needle 3 routing. Only validated calls become bounded Neyra commands."""
import json
import os
import re
import threading
from .assistant_tools import parse_command


def tool(name, description, properties):
    return {'name': name, 'description': description, 'parameters': {
        'type': 'object', 'properties': properties, 'required': list(properties), 'additionalProperties': False}}


def string(description):
    return {'type': 'string', 'description': description}


class NeedleRouter:
    def __init__(self):
        self._lock = threading.Lock()
        self._agent = None
        self._apps = None
        self._tool_key = None
        self._closed = False

    def route(self, text, apps, cancel):
        while not self._lock.acquire(timeout=.1):
            if cancel.is_set() or self._closed:
                raise RuntimeError('Cancelled.')
        try:
            if cancel.is_set() or self._closed:
                raise RuntimeError('Cancelled.')
            names = tuple(sorted(apps))
            lowered = text.casefold()
            if re.search(r"music|song|track|volume|sound|quieter|louder|mute|playback", lowered):
                group = ('media',)
            elif re.search(r"remind|remember|timer|countdown", lowered):
                group = ('reminder', 'timer', 'schedule_task')
            elif re.search(r"highlight|select|clipboard|translat", lowered):
                group = ('selection', 'local_action')
            elif re.search(r"note|meeting|follow.up|task", lowered):
                group = ('search_notes', 'local_action', 'schedule_task')
            elif re.search(r"agenda|plan|today|my day|briefing", lowered):
                group = ('local_action', 'plan', 'remove_plan')
            elif re.search(r"open|launch|start", lowered):
                group = ('open_app', 'timer', 'media')
            elif re.search(r'forget|stop speaking|stop reading', lowered):
                group = ('local_action',)
            else:
                return None
            if self._agent is None or names != self._apps or group != self._tool_key:
                from .bundled import configure_bundled_runtime
                configure_bundled_runtime()
                import needle
                tools = [
                    tool('media', 'Control music playback or speaker volume.', {'action': {'type': 'string', 'enum': ['volume up', 'volume down', 'mute', 'unmute', 'play music', 'next track', 'previous track']}}),
                    tool('reminder', 'Remind the user to do a task after a relative duration explicitly stated in the request. Never invent a time.', {'duration': string('Relative duration, e.g. five minutes'), 'task': string('Task to remember, copied from the request')}),
                    tool('timer', 'Start a countdown timer for the stated duration.', {'duration': string('Relative duration, e.g. ten minutes')}),
                    tool('search_notes', 'Find saved notes about a topic or question.', {'query': string('Search topic or question')}),
                    tool('selection', 'Explain, summarize, or translate selected text or clipboard.', {'mode': {'type': 'string', 'enum': ['explain', 'summarize', 'translate']}, 'source': {'type': 'string', 'enum': ['selected text', 'clipboard']}, 'language': string('Target language, English unless specified')}),
                    tool('local_action', 'Read the daily briefing, show plans, stop speaking, clear conversation, or find meeting tasks.', {'command': {'type': 'string', 'enum': ['daily briefing', 'show today', 'stop reading', 'forget our conversation', 'follow-ups for the latest meeting', 'find tasks', 'send this text', 'answer from these notes']}}),
                    tool('plan', 'Add a plan after a relative duration explicitly requested.', {'duration': string('Relative duration'), 'task': string('Plan text from the request')}),
                    tool('remove_plan', 'Remove a numbered plan explicitly requested.', {'number': {'type': 'integer', 'minimum': 1}}),
                    tool('schedule_task', 'Schedule a numbered extracted task after the requested relative duration.', {'number': {'type': 'integer', 'minimum': 1}, 'duration': string('Relative duration')}),
                ]
                if names:
                    tools.append(tool('open_app', 'Open one of the saved applications.', {'name': {'type': 'string', 'enum': list(names)}}))
                tools = [item for item in tools if item['name'] in group]
                tools.append(tool('ask_assistant', 'Answer an ordinary question or have a conversation when no device action was requested.', {}))
                if self._agent is not None:
                    self._agent.close()
                self._agent = needle.Needle(tools=tools, generation=3, weights=os.environ.get("NEYRA_NEEDLE_WEIGHTS"))
                self._apps = names
                self._tool_key = group
            # Do not let a cancelled turn or previous action authorize a new call.
            self._agent.reset()
            from .reminders import _number
            def normalized(match):
                try:
                    amount = _number(match[1])
                    return f"{amount:g} {match[2]}"
                except ValueError:
                    return match[0]
            number_words = r"(?:a|an|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety|hundred|and)"
            grounded_text = re.sub(r"\b(" + number_words + r"(?:[ -]" + number_words + r")*) (seconds?|minutes?|hours?|days?|weeks?)\b", normalized, text, flags=re.I)
            result = self._agent.complete(grounded_text)
            if cancel.is_set() or self._closed:
                raise RuntimeError('Cancelled.')
            calls = result.get('function_calls', [])
            if len(calls) == 1 and calls[0].get('name') == 'ask_assistant':
                return None
            if (result.get('validation') or {}).get('ungrounded') or (result.get('validation') or {}).get('negation') or result.get('suppressed_calls'):
                return json.dumps({'clarification': 'Please repeat the action with its specific details and time, if needed.'})
            if not calls:
                return None
            confidence = result.get('confidence')
            call = calls[0]
            threshold = .7
            if call.get('name') == 'media':
                threshold = .5
            if call.get('name') == 'local_action' and call.get('arguments', {}).get('command') in ('show today', 'daily briefing', 'stop reading'):
                threshold = .2
            if len(calls) != 1 or not isinstance(confidence, (float, int)) or confidence < threshold:
                return json.dumps({'clarification': 'Please ask for one action with its specific details.'})
            call = calls[0]
            name, args = call['name'], call['arguments']
            command = self.canonical(name, args, names)
            parse_command(command)
            return json.dumps({'command': command})
        finally:
            self._lock.release()

    def close(self):
        self._closed = True
        def release():
            with self._lock:
                if self._agent is not None:
                    self._agent.close()
                    self._agent = None
        threading.Thread(target=release, daemon=True).start()

    @staticmethod
    def canonical(name, args, apps):
        if name == 'open_app' and args.get('name') in apps:
            return 'open ' + args['name']
        if name == 'media' and args.get('action') in ('volume up', 'volume down', 'mute', 'unmute', 'play music', 'next track', 'previous track'):
            return args['action']
        if name == 'local_action' and args.get('command') in ('daily briefing', 'show today', 'stop reading', 'forget our conversation', 'follow-ups for the latest meeting', 'find tasks', 'send this text', 'answer from these notes'):
            return args['command']
        if name in ('reminder', 'plan'):
            prefix = 'remind me' if name == 'reminder' else 'add a plan'
            return f"{prefix} in {args['duration']} to {args['task']}"
        if name == 'timer':
            return 'set a timer for ' + args['duration']
        if name == 'search_notes':
            return 'ask my notes ' + args['query']
        if name == 'selection' and args.get('mode') in ('explain', 'summarize', 'translate') and args.get('source') in ('selected text', 'clipboard'):
            return f"{args['mode']} {args['source']}" + (f" into {args['language']}" if args['mode'] == 'translate' else '')
        if name in ('remove_plan', 'schedule_task') and type(args.get('number')) is int and args['number'] > 0:
            return f"remove plan {args['number']}" if name == 'remove_plan' else f"schedule task {args['number']} in {args['duration']}"
        raise ValueError('Needle returned an unsupported action.')

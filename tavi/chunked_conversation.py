"""Experimental completion-guarded, ordered sentence audio delivery.

Shares engagement/identity/token policy with Conversation. Text is completely
validated before any audio is published. At most two WAVs are queued; one worker
may prepare the next one. Each ACK names both response and sequence.
"""
import asyncio
from collections import deque
from contextlib import aclosing
from copy import deepcopy

from .conversation import Conversation
from .conversation_providers import PaidText
from .contracts import Event, Kind
from .sentence_chunks import SentenceChunks


class ChunkedConversation(Conversation):
    def __init__(self, *args, context_revision=None, sentence_minimum=32, **kwargs):
        if type(sentence_minimum) is not int or not 1 <= sentence_minimum <= 32:
            raise ValueError('Invalid sentence coalescing minimum')
        self.sentence_minimum = sentence_minimum
        # Optional trusted local scope/version, never inferred from model text.
        self.context_revision = context_revision
        self.response_context = None
        # History outlives a response token; _cancel runs at every new input.
        # Keep its authorization boundary separately so no browser poll is
        # required to retire a previous speaker/audience's conversation.
        self.history_context = None
        self.chunks = deque()
        self.space = asyncio.Event()
        self.response_done = False
        self.completed_response_id = None
        self.spoken_message = None
        super().__init__(*args, **kwargs)

    def _cancel(self, reason):
        super()._cancel(reason)
        self.chunks.clear()
        self.space.set()
        self.response_done = False
        self.completed_response_id = None
        self.spoken_message = None
        self.response_context = None

    def _reply_current(self, token):
        if token is None or token != self.controller.token:
            return False
        if self.context_revision is not None and self.response_context is not None:
            try:
                current = self.context_revision() == self.response_context[1]
            except Exception:
                current = False
            if not current:
                # Audience/identity/source revocation also retires old history.
                self._end('Context changed · say Paprika to begin again')
                return False
        return True

    def _end(self, reason):
        super()._end(reason)
        self.history_context = None

    @staticmethod
    def _history_key(scope):
        value = deepcopy(scope)
        if isinstance(value, dict) and isinstance(value.get('task'), dict):
            # A turn's event time changes without changing its permitted
            # conversation. All other trusted scope fields remain bound.
            value['task'].pop('conversation_at', None)
        return value

    def _schedule_reply(self, token, local_reply):
        # Capture synchronously at input acceptance, before the event loop can
        # run an audience/source update or attribute old words to a new speaker.
        if self.context_revision is not None:
            try:
                scope = deepcopy(self.context_revision())
                key = self._history_key(scope)
                if self.history_context is not None and key != self.history_context:
                    # Conversation has just appended THIS accepted human input.
                    # Keep it, but do not pass any old private history forward.
                    self.history = self.history[-1:] if self.history and self.history[-1]['role']=='user' else []
                    self._metric('history_scope_retired', response_id=token.response_id)
                self.history_context = key
                self.response_context = (token, scope)
            except Exception:
                self._end('Context unavailable · please try again')
                return
        super()._schedule_reply(token, local_reply)

    async def _respond(self, token, local_reply):
        start = self.clock()
        texts = asyncio.Queue(maxsize=480)  # At most480 characters/chunks; never block the terminal barrier.
        validated = asyncio.Event()
        component = None
        total_duration = 0
        sequence = 0

        async def produce():
            nonlocal component
            if local_reply is not None:
                text = local_reply
                await texts.put(text)
            else:
                self.paid_turns += 1
                if self.provider is None:
                    self.provider = await asyncio.to_thread(PaidText, self.store)
                splitter = SentenceChunks(minimum=self.sentence_minimum); text = ''
                async with aclosing(self.provider.stream_reply(deepcopy(self.history))) as deltas:
                    async for delta in deltas:
                        text += delta
                        if len(text)>480:raise ValueError('Reply exceeds text bound')
                        for part in splitter.feed(delta): await texts.put(part)
                for part in splitter.finish(): await texts.put(part)
            if not self._reply_current(token): return
            self.last_reply = text
            self._metric('text_completed', response_id=token.response_id,
                         elapsed_ms=(self.clock()-start)*1000)
            validated.set()
            await texts.put(None)

        async def consume():
            nonlocal component, total_duration, sequence
            while (text := await texts.get()) is not None:
                if not self._reply_current(token): return
                audio = await self.speech.synthesize(text)
                total_duration += audio.duration_ms
                if total_duration > 30000: raise ValueError('Response exceeds total audio bound')
                await validated.wait()
                while len(self.chunks)>=2:
                    self.space.clear()
                    await self.space.wait()
                if not self._reply_current(token) or self.lease is None: return
                if not self.controller.apply(Event.make(Kind.AUDIO, token, sequence=sequence,
                                                        duration_ms=audio.duration_ms, text=text)):
                    return
                chunk = {'id':token.response_id, 'sequence':sequence, 'wav':audio.wav,
                         'text':text, 'duration_ms':audio.duration_ms,
                         'ready_at':self.clock(), 'started_at':None}
                self.chunks.append(chunk)
                self.audio = self.chunks[0]
                self.notice = 'Talking' if self.audio['started_at'] is not None else 'Reply ready'
                self._metric('chunk_ready', response_id=token.response_id, sequence=sequence,
                             elapsed_ms=(self.clock()-start)*1000, duration_ms=audio.duration_ms)
                sequence += 1

        async def tagged(coro, stage):
            nonlocal component
            try: return await coro
            except Exception:
                if component is None: component = stage
                raise

        try:
            if not self._reply_current(token): return
            async with asyncio.TaskGroup() as group:
                group.create_task(tagged(produce(), 'reasoning'))
                group.create_task(tagged(consume(), 'speech'))
            if not self._reply_current(token): return
            self.response_done = True
            self.controller.apply(Event.make(Kind.DONE, token))
            if not self.chunks: self._finished(token.response_id)
        except asyncio.CancelledError:
            return
        except Exception as error:
            # TaskGroup may wrap a provider/voice exception. Never retry a paid
            # request or play remaining queued audio after either stage fails.
            errors = list(error.exceptions) if isinstance(error, ExceptionGroup) else [error]
            code = next((getattr(e,'code',None) for e in errors if getattr(e,'code',None)), None)
            if code=='memory_worker_unavailable':
                # Retiring the failed store changes its incarnation. Preserve
                # the actionable fault even though that invalidates context;
                # never attach it to a newer human turn or publish old text.
                if token is None or token!=self.controller.token:return
                self._end('Memory is unavailable')
            else:
                if not self._reply_current(token): return
                self._cancel('reply pipeline failed')
            stage = component or 'reasoning'
            self.controller.error = ('Memory is unavailable' if stage=='reasoning' and code=='memory_worker_unavailable'
                                     else 'Local voice unavailable' if stage=='speech' else 'Online reply unavailable')
            self.failure = {'component':stage, 'code':code or 'pipeline_failed', 'response_id':token.response_id,
                            'sequence':sequence}
            self.notice = (self.controller.error+'. Stop and save this attempt before trying again.'
                           if code=='memory_worker_unavailable' else self.controller.error+'; please try again')
            self._metric('pipeline_failed', response_id=token.response_id, component=stage,
                         failure_code=self.failure['code'], sequence=sequence)

    def _finished(self, response_id):
        closing = self.close_after_playback
        self.audio = None
        self.last_activity = self.clock()
        self.wait_seconds = 60 if self.last_reply.rstrip().endswith('?') else 20
        self.notice = 'Listening for your next words'
        self._metric('playback_completed', response_id=response_id)
        if closing: self._end('Chat ended · listening for Paprika')
        self.completed_response_id = response_id
        self.controller._touch()

    def command(self, lease, command, body):
        if lease == self.lease:
            self._reply_current(self.controller.token)
        if command not in ('started','played'): return super().command(lease, command, body)
        if lease != self.lease or lease is None: raise ValueError('Conversation lease expired')
        audio = self.audio; token = self.controller.token
        if (audio is None or token is None or body.get('response_id')!=token.response_id
                or type(body.get('sequence')) is not int or body['sequence']!=audio['sequence']):
            return False
        kind = Kind.STARTED if command=='started' else Kind.PLAYED
        if not self.controller.apply(Event.make(kind, token, sequence=audio['sequence'])): return False
        if command=='started':
            audio['started_at'] = self.clock(); self.notice = 'Talking'
            self._metric('playback_started', response_id=token.response_id, sequence=audio['sequence'])
        else:
            if self.spoken_message is None:
                self.spoken_message = {'role':'assistant','content':''}
                self.history.append(self.spoken_message); self.history = self.history[-12:]
            self.spoken_message['content'] += audio['text']
            self.chunks.popleft(); self.audio = self.chunks[0] if self.chunks else None
            if self.audio is not None: self.audio['ready_at'] = self.clock()
            self.space.set()
            if not self.chunks and self.response_done: self._finished(token.response_id)
        return True

    def audio_bytes(self, lease, response_id, sequence=None):
        self._reply_current(self.controller.token)
        if (lease!=self.lease or lease is None or self.controller.token is None
                or self.controller.token.response_id!=response_id or type(sequence) is not int):
            raise ValueError('Reply chunk expired')
        for chunk in self.chunks:
            if chunk['sequence']==sequence:
                if chunk is not self.audio and self._pending_input():
                    raise ValueError('New speech is being checked')
                return chunk['wav']
        raise ValueError('Reply chunk expired')

    def snapshot(self, *, diagnostics=False):
        self._reply_current(self.controller.token)
        state = super().snapshot(diagnostics=diagnostics)
        state.update(reply_delivery='sentences', completed_response_id=self.completed_response_id, prefetch_audio=None)
        if state['audio'] is not None:
            state['audio']['sequence'] = self.audio['sequence']
            if len(self.chunks)>1:
                state['prefetch_audio']={k:self.chunks[1][k] for k in ('id','sequence','duration_ms')}
        return state

"""Event-loop-owned controlled conversation, using the shared token reducer."""
import asyncio
from collections import deque
import re
import time

from .contracts import Event, Kind
from .runtime import Controller
from .conversation_providers import MacSpeech, PaidText, MODEL, LOCAL_REPLIES
from .addressing import ADDRESS
from .listen_only import listen_only
from .conversation_intents import GOODBYE, is_goodbye
from .storage import APPROVED_BUDGET_MICRO_USD

STOP = re.compile(r'^(?:stop|stop talking|be quiet|wait|hold on|pause)[.!?\s]*$', re.I)


class Conversation:
    def __init__(self, store, *, provider=None, speech=None, clock=time.monotonic, identity_resolver=None):
        self.store, self.clock = store, clock
        self.identity_resolver = identity_resolver
        self.controller = Controller(store, max_queue_ms=30000, simulation=False,
                                     record_sources=False, require_playback_start=True)
        self.provider, self.speech = provider, speech or MacSpeech()
        self.lease = None
        self.task = None
        self.tasks = set()
        self.audio = None
        self.history = []
        self.captures = {}
        self.metrics = deque(maxlen=200)
        self.last_heard = self.last_reply = ''
        self.accepted_utterance = None
        self.accepted_response_id = None
        self.accepted_recognition_id = None
        self.notice = 'Microphone off'
        self.online = True
        self.last_frame = self.last_activity = self.session_started = clock()
        self.wait_seconds = 20
        self.paid_turns = 0
        self.close_after_playback = False
        self.failure = None
        self.input_rejection = None
        self.confirmed_engagement = False

    @property
    def engaged(self):
        return self.controller.engagement == 'active'

    def _metric(self, kind, **data):
        self.metrics.append({'kind': kind, 'at': self.clock(), **data})

    def _cancel(self, reason):
        if self.task:
            self.task.cancel()
            self.task = None
        self.controller.cancel(reason)
        self.audio = None
        self.close_after_playback = False
        self._metric('cancelled', reason=reason)

    def _end(self, reason):
        self._cancel(reason)
        self.controller.end()
        self.confirmed_engagement = False
        self.history.clear()
        self.captures.clear()
        self.last_heard = self.last_reply = ''
        self.accepted_utterance = None
        self.accepted_response_id = None
        self.accepted_recognition_id = None
        self.notice = reason

    def start(self, lease, online=True):
        self.stop()
        self.failure=None
        self.input_rejection=None
        self.controller.error=None
        self.lease, self.online = lease, online
        self.controller.mute(False)
        self.controller.connectivity = 'ready'
        self.last_frame = self.clock()
        self.notice = 'Listening locally for Paprika'
        self._metric('capture_started', online=online)
        return self.snapshot()

    def stop(self, lease=None):
        if lease is not None and lease != self.lease:
            return
        self._end('Microphone off')
        self.controller.mute(True)
        self.lease = None

    def _open(self):
        self.controller.engagement = 'active'
        self.confirmed_engagement = False
        self.session_started = self.last_activity = self.clock()
        self.paid_turns = 0
        self.wait_seconds = 20
        self.history.clear()
        self._metric('engaged')

    def _begin_input(self, capture):
        previous = self.controller.token
        self._cancel('new human speech')
        self.failure=None
        capture['token'] = self.controller.begin()
        if capture.get('deferred'):
            # Later candidates are ordered behind this completed input. A new
            # accepted input advances their base; an unrelated cancel does not.
            for pending in self.captures.values():
                if (pending['utterance'] > capture['utterance'] and pending.get('deferred')
                        and pending['base_token'] == previous):
                    pending['base_token'] = capture['token']
        self.last_reply = ''
        self.notice = 'Listening to your request'

    def _pending_input(self):
        return any(c.get('deferred') and c['token'] is None
                   and c['base_token'] == self.controller.token
                   and (not self.close_after_playback or c.get('address_evidence'))
                   for c in self.captures.values())

    def feed(self, lease, result):
        if lease != self.lease:
            raise ValueError('Conversation lease expired')
        self.last_frame = self.clock()
        for event in result['events']:
            number = event['utterance']
            if event['type'] == 'speech_started':
                self.input_rejection = None
                if len(self.captures) >= 8:
                    self._end('Too many unfinished turns; say Paprika to begin again')
                unfinished_input = any(c['token'] is not None and c['token'] == self.controller.token
                                       for c in self.captures.values())
                capture = {'token': None, 'followup': self.confirmed_engagement, 'wake_candidate': False,
                           'address_evidence': None,
                           'during_playback': self.controller.output == 'playing', 'utterance': number,
                           'base_token': self.controller.token,
                           'deferred': self.engaged and (unfinished_input or self.controller.output in ('generating', 'ready'))}
                self.captures[number] = capture
                self._metric('speech_started', utterance=number,
                             during_playback=capture['during_playback'],
                             response_id=self.controller.token.response_id if self.controller.token else None,
                             speech_onset_sample=event.get('speech_onset_sample'))
                if capture['deferred']:
                    # VAD alone cannot replace an input still being decoded or
                    # a reply being prepared. Resolve candidates by final text.
                    # Touch the revision so older HTTP snapshots cannot unhold audio.
                    self.controller._touch()
                    self._metric('replacement_pending', utterance=number)
                elif self.engaged and not capture['during_playback']:
                    self._begin_input(capture)
            capture = self.captures.get(number)
            if capture is None:
                continue
            if event['type'] == 'recognition':
                # The partial name gate and final request recognizer have
                # distinct roles. Preserve an anchored address from THIS
                # utterance even if the final decoder omits the name. A name
                # merely mentioned elsewhere is never sufficient evidence.
                addressed = bool(ADDRESS.match(event['text']))
                if addressed and not event['final'] and capture['address_evidence'] is None:
                    capture['address_evidence'] = {
                        'recognition_id': event.get('recognition_id'),
                        'asr_run_id': event.get('asr_run_id'),
                        'utterance': number,
                    }
                    self._metric('address_prefix_detected', **capture['address_evidence'])
                if addressed and not self.engaged:
                    self._open()
                    capture['wake_candidate'] = True
                    self._begin_input(capture)
                    self.notice = 'Heard Paprika · keep speaking'
                if event['final']:
                    capture['recognition_id'] = event.get('recognition_id')
                    capture['address_verification'] = event.get('address_verification')
                    self._metric('recognition_final', utterance=number,
                                 asr_run_id=event.get('asr_run_id'),
                                 recognition_id=event.get('recognition_id'),
                                 confidence=event.get('confidence'),
                                 worker_timing=event.get('worker_timing'),
                                 address_at_start=addressed,
                                 name_present=bool(re.search(r'\bpaprika\b',event['text'],re.I)),
                                 address_verification=event.get('address_verification'),
                                 characters=len(event['text']), decode_ms=event.get('decode_ms'),
                                 job_age_ms=event.get('job_age_ms'),
                                 deadline_remaining_ms=event.get('deadline_remaining_ms'),
                                 queue_wait_ms=event.get('queue_wait_ms'))
                    self._resolve_final(capture, event['text'])
                    if (capture.get('deferred') and capture['base_token'] == self.controller.token
                            and not self._pending_input() and self.audio is not None
                            and self.audio['started_at'] is None):
                        # The endpoint gets its full start-ACK window after a hold.
                        self.audio['ready_at'] = self.clock()
                    self.controller._touch()
            elif event['type'] == 'speech_ended':
                self._metric('speech_ended', utterance=number,
                             speech_end_sample=event.get('speech_end_sample'))
                if capture['token'] == self.controller.token and capture['token'] is not None:
                    self.notice = 'Finishing local speech recognition'

    def _resolve_final(self, capture, text):
        """Resolve overlapping VAD candidates without guessing what a sound is.

        A newer candidate holds ordinary older text until it resolves. If the
        newer candidate is empty, use the latest completed older input. A fully
        recognized goodbye is terminal and may close before background speech.
        """
        number = capture['utterance']
        capture['final_text'] = text
        match = ADDRESS.match(text)
        closing = bool(GOODBYE.fullmatch(text[match.end():] if match else text.strip()))
        later = any(n > number for n in self.captures)
        if later and text.strip() and not closing:
            self._metric('transcript_waiting_for_later_candidate', utterance=number)
            return
        self._final(capture, text)
        self.captures.pop(number, None)
        if later:
            return
        completed = [c for n,c in self.captures.items() if n < number and 'final_text' in c]
        if not text.strip() and completed:
            previous = max(completed, key=lambda c:c['utterance'])
            self._final(previous, previous['final_text'])
        for previous in completed:
            self.captures.pop(previous['utterance'], None)

    def _final(self, capture, text):
        text = text.strip()
        if capture['during_playback'] and capture['token'] is None:
            self._metric('ignored_possible_echo', utterance=capture['utterance'])
            return
        if capture.get('deferred') and capture['token'] is None and capture['base_token'] != self.controller.token:
            self._metric('stale_transcript_rejected', utterance=capture['utterance'])
            return
        if capture['token'] is not None and capture['token'] != self.controller.token:
            self._metric('stale_transcript_rejected', utterance=capture['utterance'])
            return
        if not text or len(text) > 2000:
            self._metric('unusable_transcript_ignored', utterance=capture['utterance'],
                         reason='empty' if not text else 'oversized')
            if capture['token'] is not None and capture['token'] == self.controller.token:
                later = any(c['utterance'] > capture['utterance'] and c.get('deferred')
                            and c['base_token'] == self.controller.token for c in self.captures.values())
                if capture['wake_candidate'] and not capture['followup']:
                    self._end('No usable request · listening locally')
                elif not later:
                    self._cancel('Empty or oversized transcript')
            elif (capture.get('deferred') and capture['base_token'] == self.controller.token
                  and self.task is None and not any(c is not capture for c in self.captures.values())):
                self._cancel('No usable transcript in pending input')
            return
        match = ADDRESS.match(text)
        name_present = bool(re.search(r'\bpaprika\b', text, re.I))
        prior_address = (bool(capture.get('address_evidence')) and not name_present
                         and (capture.get('address_verification') or {}).get('confirmed') is True)
        if (self.close_after_playback and capture.get('deferred') and not match and not prior_address
                and not STOP.fullmatch(text)):
            # A confirmed goodbye ends ordinary follow-ups. Background speech
            # already queued behind it cannot hold or replace the local bye.
            # An explicit stop or addressed new request can reopen the turn;
            # endpoint-confirmed barge-in uses the existing cancellation path.
            self._metric('closing_speech_ignored', utterance=capture['utterance'])
            return
        if not capture['followup'] and not match and not prior_address:
            if capture['wake_candidate']:
                self._end('Could not confirm an addressed request · listening locally')
            reason = 'name_not_at_start' if name_present else 'name_missing'
            self.input_rejection = {'utterance':capture['utterance'],
                                    'recognition_id':capture.get('recognition_id'), 'reason':reason}
            self._metric('idle_speech_ignored', **self.input_rejection)
            return
        if not self.engaged:
            if not match and not prior_address:
                return
            self._open()
        if capture['token'] is None:
            self._begin_input(capture)
        token = capture['token']
        if token != self.controller.token:
            self._metric('stale_transcript_rejected')
            return
        remainder = text[match.end():].strip() if match else text
        local_reply = None
        closing = is_goodbye(remainder)
        if closing:
            local_reply = LOCAL_REPLIES['goodbye']
        elif not remainder:
            local_reply = LOCAL_REPLIES['greeting']
        elif STOP.fullmatch(remainder):
            local_reply = LOCAL_REPLIES['stop']
        elif listen_only(remainder):
            local_reply = LOCAL_REPLIES['listen']
        elif not self.online:
            local_reply = LOCAL_REPLIES['offline']
        elif self.paid_turns >= 12:
            local_reply = LOCAL_REPLIES['limit']
            closing = True
        c = self.controller
        speaker='unknown'
        if self.identity_resolver:
            try:speaker=self.identity_resolver(self.lease,capture['utterance'],token)
            except Exception:speaker='unknown'
        if speaker not in ('unknown','adultone','adulttwo','childtwo','childone'):speaker='unknown'
        c.apply(Event.make(Kind.IDENTITY, token, speaker=speaker))
        if not c.apply(Event.make(Kind.TRANSCRIPT, token, text=text)):
            return
        self.last_heard = text
        self.confirmed_engagement = True
        self.accepted_utterance = capture['utterance']
        self.accepted_response_id = token.response_id
        self.accepted_recognition_id = capture.get('recognition_id')
        self.last_activity = self.clock()
        self.history.append({'role': 'user', 'content': text})
        self.history = self.history[-12:]
        self.close_after_playback = closing
        self.notice = 'Thinking' if local_reply is None else 'Preparing a local reply'
        self._metric('accepted_turn', response_id=token.response_id,
                     utterance=capture['utterance'], recognition_id=capture.get('recognition_id'),
                     address_source='final_prefix' if match else 'partial_prefix' if prior_address else 'followup',
                     address_evidence=capture.get('address_evidence'),
                     cloud=local_reply is None)
        self._schedule_reply(token, local_reply)

    def _schedule_reply(self, token, local_reply):
        self.task = asyncio.create_task(self._respond(token, local_reply))
        self.tasks.add(self.task)
        self.task.add_done_callback(self.tasks.discard)

    async def _respond(self, token, local_reply):
        started = self.clock()
        try:
            if local_reply is None:
                self.paid_turns += 1
                try:
                    if self.provider is None:
                        self.provider = await asyncio.to_thread(PaidText, self.store)
                    text = await self.provider.reply(list(self.history))
                    if token == self.controller.token:
                        self.controller.connectivity = 'ready'
                except asyncio.CancelledError:
                    raise
                except Exception as error:
                    if token != self.controller.token:
                        return
                    self.controller.connectivity = 'degraded'
                    self.controller.error = 'Online reply unavailable (' + type(error).__name__ + ')'
                    self.failure={'component':'reasoning','code':'provider_unavailable','response_id':token.response_id}
                    self._metric('provider_failed', error_type=type(error).__name__)
                    text = LOCAL_REPLIES['failure']
            else:
                text = local_reply
            if token != self.controller.token:
                return
            provider_done = self.clock()
            audio = await self.speech.synthesize(text)
            if token != self.controller.token or self.lease is None:
                return
            if not self.controller.apply(Event.make(Kind.AUDIO, token, sequence=0,
                                                     duration_ms=audio.duration_ms, text=text)):
                return
            self.controller.apply(Event.make(Kind.DONE, token))
            self.audio = {'id': token.response_id, 'wav': audio.wav, 'text': text,
                          'duration_ms': audio.duration_ms, 'ready_at': self.clock(), 'started_at': None}
            self.last_reply = text
            self.notice = 'Reply ready'
            self._metric('reply_ready', response_id=token.response_id,
                         provider_ms=(provider_done-started)*1000,
                         synthesis_ms=(self.clock()-provider_done)*1000)
        except asyncio.CancelledError:
            return
        except Exception as error:
            if token == self.controller.token:
                self.controller.apply(Event.make(Kind.FAILURE, token))
                self.controller.error='Local voice unavailable'
                self.failure={'component':'speech','code':getattr(error,'code','synthesis_failed'),'response_id':token.response_id}
                self.audio = None
                self.notice = 'Local voice unavailable; please try again'
                self._metric('voice_failed', error_type=type(error).__name__,failure_code=self.failure['code'],response_id=token.response_id)

    def command(self, lease, command, body):
        if lease != self.lease or lease is None:
            raise ValueError('Conversation lease expired')
        if command == 'end':
            self._end('Chat ended · listening for Paprika')
            return True
        if command == 'online':
            if type(body.get('enabled')) is not bool:
                raise ValueError('Expected an online toggle')
            self.online = body['enabled']
            self._end('Online replies on' if self.online else 'Online replies off')
            return True
        audio = self.audio
        response_id = body.get('response_id')
        if self.controller.token is None or response_id != self.controller.token.response_id:
            return False
        if command == 'interrupt':
            capture = self.captures.get(body.get('utterance'))
            self._cancel('endpoint interruption')
            if capture is not None:
                capture['during_playback'] = False
                self._begin_input(capture)
            self.notice = 'Interrupted · listening'
            self.last_activity = self.clock()
            self._metric('interrupted', response_id=response_id)
            return True
        if audio is None or audio['id'] != response_id:
            return False
        token = self.controller.token
        if command == 'started':
            accepted = self.controller.apply(Event.make(Kind.STARTED, token, sequence=0))
            if accepted:
                audio['started_at'] = self.clock()
                self.notice = 'Talking'
                self._metric('playback_started', response_id=response_id)
            return accepted
        if command == 'played':
            accepted = self.controller.apply(Event.make(Kind.PLAYED, token, sequence=0))
            if accepted:
                self.history.append({'role': 'assistant', 'content': audio['text']})
                self.history = self.history[-12:]
                self.audio = None
                self.last_activity = self.clock()
                self.wait_seconds = 60 if audio['text'].rstrip().endswith('?') else 20
                self.notice = 'Listening for your next words'
                self._metric('playback_completed', response_id=response_id)
                if self.close_after_playback:
                    self._end('Chat ended · listening for Paprika')
            return accepted
        raise ValueError('Unknown conversation command')

    def audio_bytes(self, lease, response_id):
        if lease != self.lease or self.audio is None or self.audio['id'] != response_id:
            raise ValueError('Reply audio expired')
        return self.audio['wav']

    def expire(self):
        if self.lease is None:
            return
        now = self.clock()
        if now - self.last_frame > 2:
            self.stop()
            return
        if self.engaged and now - self.session_started > 300:
            self._end('Five-minute chat limit · say Paprika to start again')
        elif self.audio is not None:
            if self.audio['started_at'] is None and self._pending_input():
                return  # Local ASR retains its own bounded utterance/worker deadlines.
            start = self.audio['started_at'] or self.audio['ready_at']
            limit = self.audio['duration_ms']/1000 + 5 if self.audio['started_at'] else 5
            if now - start > limit:
                self._cancel('Playback acknowledgement timed out')
                self.notice = 'Playback stopped · please try again'
        elif self.engaged and self.controller.output == 'silent' and not self.captures and now - self.last_activity > self.wait_seconds:
            self._end('Chat finished · listening for Paprika')

    def snapshot(self, *, diagnostics=False):
        return {**self.controller.snapshot(), 'lease_active': self.lease is not None,
                'notice': self.notice, 'online_replies': self.online, 'model': getattr(self.provider,'model',MODEL),
                'voice': getattr(self.speech, 'name', 'Mac Samantha (local)'),
                'heard': self.last_heard, 'reply': self.last_reply,
                'accepted_utterance': self.accepted_utterance,
                'accepted_response_id': self.accepted_response_id,
                'accepted_recognition_id': self.accepted_recognition_id,
                'remaining_session_seconds': max(0, round(300-(self.clock()-self.session_started))) if self.engaged else None,
                'spent_or_reserved_usd': self.store.used_micro_usd()/1e6, 'budget_usd': APPROVED_BUDGET_MICRO_USD/1e6,
                'pending_input': self._pending_input(), 'failure':self.failure,
                'closing_after_playback': self.close_after_playback,
                'input_rejection':self.input_rejection,
                'audio': {k:v for k,v in self.audio.items() if k in ('id','duration_ms')} if self.audio and not self._pending_input() else None,
                'metrics_count': len(self.metrics), 'memory_enabled': bool(getattr(self.provider,'memory_enabled',False)),
                **({'metrics': list(self.metrics)} if diagnostics else {})}

    async def close(self):
        tasks = list(self.tasks)
        self.stop()
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        if self.provider is not None:
            await self.provider.close()
        if hasattr(self.speech, 'close'):
            await self.speech.close()

"""Bounded experimental native-audio reference, not a live provider selection.

No microphone, filesystem recording import or playback. Caller supplies only
synthetic input for this preflight. Local suppression happens before network
cancellation. A human endpoint would need its own consent and playback clock.
"""
import asyncio
import base64
import json
import math
import time
from uuid import uuid4

from .conversation_providers import runtime_key
from .storage import APPROVED_BUDGET_MICRO_USD

MODEL = 'gpt-realtime-2.1'
VOICE = 'marin'
MAX_OUTPUT_TOKENS = 768
RESERVATION = 1_000_000
INSTRUCTIONS = ('You are Paprika, a friendly imaginative toy. Speak only English. '
    'Answer the current request directly in one or two complete sentences. '
    'Do not introduce yourself or announce your name unless asked who you are. '
    'If your name is needed, pronounce Paprika puh-PREE-kuh; the pronunciation is a reference, not a greeting to repeat. '
    'Continue the same conversation across follow-ups without repeating an introduction. '
    'Follow changes of topic. When someone says goodbye, say one brief goodbye and stop. '
    'Do not claim to remember anyone or take physical actions. Do not use tools.')


def session_config():
    return {'type': 'realtime', 'model': MODEL, 'output_modalities': ['audio'],
        'instructions': INSTRUCTIONS, 'tools': [], 'tool_choice': 'none',
        'max_output_tokens': MAX_OUTPUT_TOKENS, 'reasoning': {'effort': 'minimal'},
        'truncation': 'disabled', 'audio': {
            'input': {'format': {'type': 'audio/pcm', 'rate': 24000}, 'turn_detection': None},
            'output': {'format': {'type': 'audio/pcm', 'rate': 24000}, 'voice': VOICE}}}


def charge_usage(usage):
    """Conservative all-token audio rate, ignoring discounts. Unknown stays reserved."""
    if not isinstance(usage, dict): return None
    counts = [usage.get('input_tokens'), usage.get('output_tokens')]
    if any(type(v) is not int or not 0 <= v <= 128000 for v in counts): return None
    # Official rates checked 4 Nov 2026: audio $32/$64 per million.
    return counts[0] * 32 + counts[1] * 64


class OutputGate:
    """Suppress late deltas locally; zero heard frames in the silent preflight."""
    def __init__(self):
        self.blocked = False
        self.received_frames = self.admitted_frames = self.dropped_frames = 0

    def accept(self, pcm):
        if not isinstance(pcm, bytes) or len(pcm) % 2: raise ValueError('Invalid output PCM')
        frames = len(pcm) // 2
        self.received_frames += frames
        if self.blocked:
            self.dropped_frames += frames
            return False
        self.admitted_frames += frames
        return True

    def stop(self):
        # A real endpoint must stop its sources/queue here, before contacting API.
        self.blocked = True
        return {'audio_end_ms': 0, 'heard_frames': 0, 'physical_playback': False}


class RealtimeReference:
    def __init__(self, store, *, connector=None):
        self.store = store
        self.connector = connector
        self.ws = None
        self.turns = 0
        self.total_input_seconds = 0
        self.events = []
        self.session = None

    async def connect(self):
        if self.connector is None:
            from websockets.asyncio.client import connect
            # Fixed destination; no environment-configured proxy or reconnect.
            self.ws = await connect('wss://api.openai.com/v1/realtime?model=' + MODEL,
                additional_headers={'Authorization': 'Bearer ' + runtime_key()},
                proxy=None, open_timeout=15, close_timeout=3, max_size=2_000_000,
                max_queue=16)
        else:
            self.ws = await self.connector()
        async with asyncio.timeout(20):
            first = await self.receive()
            if first['type'] != 'session.created': raise ValueError('Missing session receipt')
            await self.send('session.update', session=session_config())
            while True:
                event = await self.receive()
                if event['type'] == 'session.updated':
                    self.session = event['session']
                    if self.session.get('model') != MODEL: raise ValueError('Wrong realtime model')
                    expected = session_config()
                    for key in ('max_output_tokens', 'output_modalities', 'reasoning', 'truncation'):
                        if self.session.get(key) != expected[key]: raise ValueError('Session configuration mismatch: ' + key)
                    audio = self.session.get('audio', {})
                    if audio.get('input', {}).get('turn_detection') is not None:
                        raise ValueError('Automatic generation must be disabled')
                    if audio.get('output', {}).get('voice') != VOICE: raise ValueError('Wrong voice')
                    break

    async def send(self, kind, **fields):
        await self.ws.send(json.dumps({'type': kind, 'event_id': uuid4().hex, **fields}))

    async def receive(self):
        event = json.loads(await self.ws.recv())
        if not isinstance(event, dict) or not isinstance(event.get('type'), str):
            raise ValueError('Invalid realtime event')
        self.events.append({'type': event['type'], 'at_monotonic': time.monotonic()})
        if len(self.events) > 3000: raise ValueError('Event bound exceeded')
        if event['type'] == 'error':
            # No credentials, request bodies, headers or arbitrary error text.
            error = event.get('error', {})
            raise ValueError('Realtime protocol error: ' + str(error.get('code'))[:80])
        return event

    async def turn(self, pcm, *, source_kind, interrupt=False):
        if source_kind != 'synthetic': raise ValueError('This preflight accepts synthetic speech only')
        if not isinstance(pcm, bytes) or len(pcm) % 2 or not 4800 <= len(pcm) <= 12 * 48000:
            raise ValueError('Expected bounded mono 24kHz PCM16')
        duration = len(pcm) / 48000
        if self.ws is None or self.turns >= 3 or self.total_input_seconds + duration > 16:
            raise ValueError('Preflight session bound exceeded')
        reservation = 'realtime:' + uuid4().hex
        self.store.reserve(reservation, RESERVATION, APPROVED_BUDGET_MICRO_USD)
        self.turns += 1
        self.total_input_seconds += duration
        gate = OutputGate()
        start = time.monotonic()
        # Input pacing happens while no automatic response can be generated.
        # Control ack events are drained after commit; no cloud VAD is measured.
        for offset in range(0, len(pcm), 4800):
            await self.send('input_audio_buffer.append', audio=base64.b64encode(pcm[offset:offset+4800]).decode())
            await asyncio.sleep(max(0, start + min(offset + 4800, len(pcm)) / 48000 - time.monotonic()))
        commit = time.monotonic()
        await self.send('input_audio_buffer.commit')
        await self.send('response.create')
        result = {'input_seconds': duration, 'input_pacing_elapsed_ms': (commit-start)*1000,
                  'first_audio_after_commit_ms': None, 'first_audio_after_input_start_ms': None,
                  'output_transcript': '', 'interrupt_requested': interrupt, 'truncated_ack': False,
                  'usage_settled': False, 'model': MODEL, 'voice': VOICE,
                  'physical_playback': False, 'terminal_status': None}
        response_id = item_id = None
        requested_truncation = False
        terminal = False
        async with asyncio.timeout(25):
            while not terminal or (interrupt and not result['truncated_ack']):
                event = await self.receive()
                kind = event['type']
                if kind == 'response.created':
                    if response_id: raise ValueError('Unexpected additional response')
                    response_id = event['response']['id']
                elif kind == 'response.output_item.added':
                    item_id = event['item']['id']
                elif kind == 'response.output_audio.delta':
                    if event.get('response_id') != response_id: raise ValueError('Unbound audio response')
                    pcm_out = base64.b64decode(event['delta'], validate=True)
                    if gate.received_frames + len(pcm_out)//2 > 30*24000: raise ValueError('Output audio bound exceeded')
                    gate.accept(pcm_out)
                    if result['first_audio_after_commit_ms'] is None:
                        now = time.monotonic()
                        result['first_audio_after_commit_ms'] = (now-commit)*1000
                        result['first_audio_after_input_start_ms'] = (now-start)*1000
                    if interrupt and not requested_truncation:
                        if not item_id or event.get('item_id') != item_id: raise ValueError('Unbound assistant item')
                        before = time.monotonic()
                        result['local_stop'] = gate.stop()  # Before any network await.
                        result['local_gate_stop_work_ms'] = (time.monotonic()-before)*1000
                        requested_truncation = True
                        await self.send('response.cancel', response_id=response_id)
                        await self.send('conversation.item.truncate', item_id=item_id,
                                        content_index=event.get('content_index', 0), audio_end_ms=0)
                elif kind == 'response.output_audio_transcript.delta':
                    result['output_transcript'] += event['delta']
                    if len(result['output_transcript']) > 5000: raise ValueError('Transcript bound exceeded')
                elif kind == 'conversation.item.truncated':
                    if not requested_truncation or event.get('item_id') != item_id or event.get('audio_end_ms') != 0:
                        raise ValueError('Truncation acknowledgement mismatch')
                    result['truncated_ack'] = True
                elif kind == 'response.done':
                    response = event['response']
                    if response.get('id') != response_id: raise ValueError('Unbound terminal response')
                    if terminal: raise ValueError('Duplicate terminal response')
                    terminal = True
                    result['terminal_status'] = response['status']
                    result['usage'] = response.get('usage')
                    charge = charge_usage(response.get('usage'))
                    if charge is not None:
                        self.store.settle(reservation, charge)
                        result['usage_settled'] = True
                    result['terminal_after_commit_ms'] = (time.monotonic()-commit)*1000
                    expected = 'cancelled' if interrupt else 'completed'
                    if response['status'] != expected: raise ValueError('Unexpected terminal status: ' + response['status'])
        if not gate.received_frames: raise ValueError('Empty audio response')
        result['output_frames_received'] = gate.received_frames
        result['output_frames_dropped_after_stop'] = gate.dropped_frames
        result['output_frames_admitted_before_stop'] = gate.admitted_frames
        return result

    async def close(self):
        if self.ws is not None:
            await self.ws.close()
            self.ws = None

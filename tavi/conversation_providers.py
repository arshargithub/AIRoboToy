"""Bounded text-only cloud reasoning and replaceable local speech synthesis."""
import asyncio
from dataclasses import dataclass
from io import BytesIO
import hashlib
import json
import math
import os
from pathlib import Path
import re
import tempfile
from uuid import uuid4
import wave

from .storage import APPROVED_BUDGET_MICRO_USD

MODEL = 'gpt-5.4-mini-2026-03-17'
MAX_OUTPUT_TOKENS = 384
REQUEST_RESERVATION = 50_000  # $0.05, including uncertain/cancelled requests
MAX_INPUT_BYTES = 16_384
LOCAL_REPLIES = {
    'greeting': 'Hi! What shall we play?',
    'goodbye': 'Bye for now! Call Paprika when you want to play again.',
    'offline': 'I can hear you, but my online brain is switched off right now.',
    'limit': 'Let’s take a little break. Call Paprika to start a new chat.',
    'failure': 'My online brain is unavailable right now. Please try again in a moment.',
    'stop': 'Okay.',
    'listen': "I'm here with you, listening.",
}
INSTRUCTIONS = (
    'You are Paprika, a warm, playful stuffed-toy companion speaking English to a family. '
    'Reply in one to three short spoken sentences, normally under 45 words. '
    'Use plain speech without Markdown, emoji, lists, or stage directions. '
    'Stay suitable for children ages seven and ten. Be curious without asking personal or identifying questions. '
    'You are an AI toy: do not claim to be human, see the room, recognize voices, move, or remember past chats. '
    'Only the current conversation is available. Do not invent personal memories or family identities. '
    'Do not keep every turn going with a question; allow a natural ending. '
    'For a story, tell a short vivid story rather than an introduction. No tools or outside actions are available.'
)


def runtime_key():
    key = os.environ.get('OPENAI_API_KEY', '').strip()
    if not key:
        path = Path('.env')
        if path.exists():
            for line in path.read_text().splitlines():
                match = re.match(r'^\s*(?:export\s+)?OPENAI_API_KEY\s*=\s*(.*)$', line)
                if match:
                    key = match[1].strip()
                    if key[:1] in ('"', "'") and key[-1:] == key[:1]:
                        key = key[1:-1]
                    break
    if not key or any(v in key.lower() for v in ('your-api-key', 'your_openai', 'sk-...')):
        raise ValueError('Set OPENAI_API_KEY locally before using online replies')
    return key


def bounded_input(history):
    messages = [dict(role=m['role'], content=m['content']) for m in history[-12:]]
    while len(messages) > 1 and len(json.dumps(messages, ensure_ascii=False).encode()) > 11000:
        messages.pop(0)
    size = len(json.dumps({'instructions': INSTRUCTIONS, 'input': messages}, ensure_ascii=False).encode())
    if not messages or size > MAX_INPUT_BYTES:
        raise ValueError('Conversation context exceeds the prototype limit')
    return messages


class PaidText:
    def __init__(self, store, client=None, *, drain_stream=False):
        self.store = store
        self.drain_stream = drain_stream
        self.started = self.completed = 0
        if client is None:
            from openai import AsyncOpenAI
            # Ignore alternative base-URL environment settings: credentials/text
            # are authorized for OpenAI, not a silently substituted proxy.
            client = AsyncOpenAI(api_key=runtime_key(), base_url='https://api.openai.com/v1',
                                 max_retries=0, timeout=18)
        self.client = client
        # Resolve the SDK's lazy response resource during startup, before PCM
        # capture begins. Importing it on the first spoken turn stalls the loop.
        self.responses = client.responses

    async def reply(self, history):
        messages = bounded_input(history)
        request_id = 'conversation:' + uuid4().hex
        # Reserve before network transmission. Context bytes + 4096 overhead,
        # priced as input tokens, plus the output ceiling cost < $0.05.
        bound = math.ceil((MAX_INPUT_BYTES + 4096) * .75 + MAX_OUTPUT_TOKENS * 4.5)
        if bound > REQUEST_RESERVATION:
            raise ValueError('Pricing bound exceeds the configured reservation')
        self.store.reserve(request_id, REQUEST_RESERVATION, APPROVED_BUDGET_MICRO_USD)
        self.started += 1
        # Cancellation, transport failure and ambiguous outcomes retain the full
        # reservation. No automatic retry can duplicate a paid request.
        async with asyncio.timeout(20):
            response = await self.responses.create(
                model=MODEL, instructions=INSTRUCTIONS, input=messages,
                reasoning={'effort': 'none'}, max_output_tokens=MAX_OUTPUT_TOKENS,
                store=False, service_tier='default', tools=[], stream=False)
        usage = response.usage
        if usage is not None:
            # Cached inputs charged at the full input rate here: conservative
            # usage-based estimate, not an assertion about the final invoice.
            charge = math.ceil(usage.input_tokens * .75 + usage.output_tokens * 4.5)
            self.store.settle(request_id, charge)
        self.completed += 1
        if response.status != 'completed' or not response.output_text.strip():
            raise ValueError('The text response was incomplete or empty')
        text = response.output_text.strip()
        if len(text) > 480:
            # Keep the local voice bounded and prefer a complete sentence.
            short = text[:480]
            end = max(short.rfind('. '), short.rfind('? '), short.rfind('! '))
            text = short[:end + 1] if end > 120 else short.rsplit(' ', 1)[0] + '.'
        return text

    async def stream_reply(self, history):
        """Experimental deltas; successful exhaustion validates completion.

        Consumers must not equate an available prefix with a complete answer.
        Cancellation or an ambiguous terminal outcome keeps the reservation.
        This path is not selected by the live conversation controller.
        """
        messages = bounded_input(history)
        request_id = 'conversation:' + uuid4().hex
        bound = math.ceil((MAX_INPUT_BYTES + 4096) * .75 + MAX_OUTPUT_TOKENS * 4.5)
        if bound > REQUEST_RESERVATION:
            raise ValueError('Pricing bound exceeds the configured reservation')
        self.store.reserve(request_id, REQUEST_RESERVATION, APPROVED_BUDGET_MICRO_USD)
        self.started += 1
        stream = None
        text = ''
        completed = False
        try:
            async with asyncio.timeout(20):
                stream = await self.responses.create(
                    model=MODEL, instructions=INSTRUCTIONS, input=messages,
                    reasoning={'effort': 'none'}, max_output_tokens=MAX_OUTPUT_TOKENS,
                    store=False, service_tier='default', tools=[], stream=True)
                async for event in stream:
                    if completed:
                        raise ValueError('Unexpected event after completed response')
                    if event.type == 'response.output_text.delta':
                        text += event.delta
                        if len(text) > 480:
                            raise ValueError('Streamed reply exceeds the local voice bound')
                        yield event.delta
                    elif event.type == 'response.completed':
                        response = event.response
                        if response.usage is not None:
                            charge = math.ceil(response.usage.input_tokens * .75 + response.usage.output_tokens * 4.5)
                            self.store.settle(request_id, charge)
                        if response.status != 'completed' or not text.strip() or response.output_text != text:
                            raise ValueError('Streamed response did not match completed text')
                        completed = True
                        if not self.drain_stream:
                            break
                    elif event.type in ('error', 'response.failed', 'response.incomplete', 'response.refusal.delta'):
                        raise ValueError('Streamed response was not a complete spoken answer')
                if not completed:
                    raise ValueError('Stream ended without completion')
                self.completed += 1
        finally:
            if stream is not None:
                await stream.close()

    async def close(self):
        await self.client.close()


@dataclass(frozen=True)
class Speech:
    wav: bytes
    duration_ms: int


class MacSpeech:
    """Temporary Mac voice; dynamic audio is ephemeral, fixed replies may be cached."""
    @staticmethod
    def cache_path(text):
        if text not in LOCAL_REPLIES.values():
            return None
        digest = hashlib.sha256(('Samantha|190|16000|'+text).encode()).hexdigest()[:24]
        return Path('.tavi/audio') / ('local-'+digest+'.wav')

    @staticmethod
    def validate_audio(data):
        if len(data) > 1_000_000:
            raise ValueError('Local voice audio exceeds its memory bound')
        with wave.open(BytesIO(data)) as audio:
            if (audio.getframerate(), audio.getnchannels(), audio.getsampwidth()) != (16000, 1, 2):
                raise ValueError('Unexpected local voice format')
            duration = math.ceil(audio.getnframes() / 16)
            if not 0 < duration <= 30000:
                raise ValueError('Local voice exceeds the thirty-second playback limit')
        return Speech(data, duration)
    async def _run(self, *args, text=None):
        process = await asyncio.create_subprocess_exec(
            *args, stdin=asyncio.subprocess.PIPE if text is not None else asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE)
        try:
            async with asyncio.timeout(8):
                _, _ = await process.communicate(text.encode() if text is not None else None)
            if process.returncode:
                raise ValueError('Local voice synthesis failed')
        except BaseException:
            if process.returncode is None:
                process.kill()
            await process.wait()
            raise

    async def synthesize(self, text, *, cache=True):
        if not isinstance(text, str) or not 0 < len(text) <= 480:
            raise ValueError('Reply exceeds the local voice limit')
        path = self.cache_path(text)
        if cache and path and path.exists():
            if path.stat().st_size > 1_000_000:
                raise ValueError('Cached local voice exceeds its memory bound')
            return self.validate_audio(path.read_bytes())
        with tempfile.TemporaryDirectory(prefix='paprika-voice-') as folder:
            root = Path(folder)
            aiff, wav = root / 'speech.aiff', root / 'speech.wav'
            # Speech uses stdin, not shell interpolation or process arguments.
            await self._run('/usr/bin/say', '-v', 'Samantha', '-r', '190', '-o', str(aiff), text=text)
            await self._run('/usr/bin/afconvert', '-f', 'WAVE', '-d', 'LEI16@16000', '-c', '1', str(aiff), str(wav))
            if wav.stat().st_size > 1_000_000:
                raise ValueError('Local voice audio exceeds its memory bound')
            return self.validate_audio(wav.read_bytes())

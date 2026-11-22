import asyncio
import unittest
from types import SimpleNamespace
from experiments.memory.decision_contract_v2 import snapshot
from experiments.memory.voice_queue import chunks


class Voice:
    def __init__(self): self.calls=[]; self.closed=False
    async def synthesize(self,text):
        self.calls.append(text)
        return SimpleNamespace(duration_ms=1000, wav=b'fake')
    async def close(self): self.closed=True


class VoiceQueueTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.task={'people':{'a':'A'},'actual_speaker_id':'a','audience_ids':['a'],'catalogue':[]}
        self.evidence={'facts':[],'source_headers':{}}
        self.value={'text':'Here is a complete first sentence for you. Here is another one.', 'memory_uses':[], 'catalogue_choices':[]}
        self.sha=snapshot(self.task,self.evidence)
        self.voice=Voice()
    def stream(self,sha=None):
        return chunks(self.voice,self.value,self.task,self.evidence,issued_snapshot=self.sha,current_snapshot=sha or self.sha)
    async def test_invalid_or_stale_reply_never_reaches_voice(self):
        with self.assertRaises(ValueError):
            async for _ in self.stream('stale'): pass
        self.value['memory_uses']=[{'fact_index':0,'subject_id':'a'}]
        with self.assertRaises(ValueError):
            async for _ in self.stream(): pass
        self.assertEqual(self.voice.calls,[])
    async def test_exact_order_and_complete_text_preserved(self):
        result=[r async for r in self.stream()]
        self.assertEqual(''.join(r['text'] for r in result),self.value['text'])
        self.assertEqual([r['index'] for r in result],[0,1])
    async def test_close_after_first_chunk_stops_future_synthesis(self):
        stream=self.stream();await anext(stream);await stream.aclose()
        self.assertEqual(len(self.voice.calls),1);self.assertTrue(self.voice.closed)
    async def test_cancellation_during_synthesis_closes_worker(self):
        entered=asyncio.Event()
        async def wait(text): entered.set();await asyncio.Event().wait()
        self.voice.synthesize=wait
        stream=self.stream();job=asyncio.create_task(anext(stream));await entered.wait();job.cancel()
        with self.assertRaises(asyncio.CancelledError):await job
        self.assertTrue(self.voice.closed)

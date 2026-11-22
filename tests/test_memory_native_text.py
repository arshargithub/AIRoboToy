import unittest
from types import SimpleNamespace
from experiments.memory.native_text import NativeTextReference,speak_completed
from experiments.memory.decision_contract_v2 import snapshot
from tavi.storage import Store


class NativeTextTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.task={'actual_speaker_id':'a','people':{'a':'A'},'audience_ids':['a']};self.evidence={'facts':[]}
    async def test_terminal_text_must_match_before_return(self):
        store=Store();ref=NativeTextReference(store);sent=[]
        async def send(*a,**kw):sent.append(kw)
        ref.send=send
        events=iter([{'type':'response.created','response':{'id':'r','metadata':{'case_id':'c'}}},
                     {'type':'response.output_text.delta','response_id':'r','delta':'Complete thought.'},
                     {'type':'response.done','response':{'id':'r','status':'completed','usage':{'input_tokens':1,'output_tokens':1},'output':[{'content':[{'type':'output_text','text':'Different thought.'}]}]}}])
        async def receive():return next(events)
        ref.receive=receive
        with self.assertRaises(ValueError):await ref.reply(self.task,self.evidence,'c')
        self.assertEqual(sent[0]['response']['output_modalities'],['text']);store.close()
    async def test_incomplete_stale_or_overlong_text_never_reaches_voice(self):
        calls=[]
        async def synthesize(text):calls.append(text);return SimpleNamespace(duration_ms=1000)
        voice=SimpleNamespace(synthesize=synthesize)
        sha=snapshot(self.task,self.evidence)
        for result,current in [({'status':'cancelled','text':'A prefix.'},sha),({'status':'completed','text':'Old reply.'},'stale'),({'status':'completed','text':'x'*481},sha)]:
            with self.assertRaises(ValueError):
                async for _ in speak_completed(voice,result,self.task,self.evidence,issued_snapshot=sha,current_snapshot=current):pass
        self.assertEqual(calls,[])

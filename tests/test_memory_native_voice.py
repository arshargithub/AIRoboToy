import asyncio
import base64
import unittest
from experiments.memory.native_voice import NativeMemoryReference,response_options
from tavi.storage import Store


class NativeVoiceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.task={'actual_speaker_id':'a','people':{'a':'A'},'audience_ids':['a'],'question':'An idea?'}
        self.evidence={'facts':[],'source_headers':{}}
    def test_independent_explicit_input_and_no_tools(self):
        r=response_options(self.task,self.evidence,'c')
        self.assertEqual(r['conversation'],'none');self.assertEqual(r['input'][0]['content'][0]['type'],'input_text')
        self.assertNotIn('response_format',r)
        with self.assertRaises(ValueError):response_options({**self.task,'actual_speaker_id':'unknown'},self.evidence,'c')
    async def test_response_binding_and_conservative_usage(self):
        store=Store();ref=NativeMemoryReference(store);sent=[]
        async def send(kind,**kw):sent.append((kind,kw))
        ref.send=send
        events=iter([{'type':'response.created','response':{'id':'r','metadata':{'case_id':'c'}}},
                     {'type':'response.output_audio.delta','response_id':'r','delta':base64.b64encode(bytes(4800)).decode()},
                     {'type':'response.output_audio_transcript.delta','response_id':'r','delta':'A useful idea.'},
                     {'type':'response.done','response':{'id':'r','status':'completed','usage':{'input_tokens':2,'output_tokens':3}}}])
        async def receive():return next(events)
        ref.receive=receive
        result,audio=await ref.reply(self.task,self.evidence,'c')
        self.assertEqual(len(audio),4800);self.assertTrue(result['usage_settled']);self.assertEqual(store.used_micro_usd(),256)
        store.close()
    async def test_mismatched_output_rejected_keeps_reservation(self):
        store=Store();ref=NativeMemoryReference(store)
        async def send(*a,**kw):pass
        async def receive():return {'type':'response.output_audio.delta','response_id':'wrong','delta':'AAA='}
        ref.send=send;ref.receive=receive
        with self.assertRaises(ValueError):await ref.reply(self.task,self.evidence,'c')
        self.assertEqual(store.used_micro_usd(),1000000);store.close()

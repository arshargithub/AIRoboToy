import asyncio
from types import SimpleNamespace
import unittest
from tavi.conversation import Conversation
from tavi.conversation_providers import PaidText, Speech
from tavi.storage import Store, APPROVED_BUDGET_MICRO_USD


class Voice:
    async def synthesize(self, text): return Speech(b'synthetic-test-wave', 1000)


class Brain:
    def __init__(self): self.calls=[]
    async def reply(self, history):
        self.calls.append(history)
        return 'Let’s sail a tiny boat to the moon.'
    async def close(self): pass


class ConversationTests(unittest.IsolatedAsyncioTestCase):
    async def test_later_vad_cannot_discard_a_goodbye_still_being_decoded(self):
        self.utterance('Paprika',1);self.play(await self.ready())
        self.feed(self.event('speech_started',2),self.event('speech_started',3))
        self.feed(self.event('recognition',2,text='Goodbye, Paprika.',final=True))
        rid=await self.ready()
        self.assertTrue(self.c.close_after_playback)
        self.assertFalse(self.c.snapshot()['pending_input'],'Queued non-addressed sound must not hold goodbye audio')
        self.feed(self.event('recognition',3,text='you',final=True))
        self.assertEqual(self.c.snapshot()['audio']['id'],rid)
        self.assertEqual(self.brain.calls,[])
        self.play(rid)
        self.assertFalse(self.c.engaged)

    async def test_empty_candidate_does_not_discard_later_real_input_already_started(self):
        self.utterance('Paprika',1);self.play(await self.ready())
        self.feed(self.event('speech_started',2),self.event('speech_started',3))
        self.feed(self.event('recognition',2,text='',final=True))
        self.feed(self.event('recognition',3,text='How can we build a castle?',final=True))
        await self.ready()
        self.assertEqual(self.c.last_heard,'How can we build a castle?')
        self.assertEqual(len(self.brain.calls),1)

    async def test_explicit_address_can_replace_goodbye_while_unaddressed_followup_cannot(self):
        self.utterance('Paprika',1);self.play(await self.ready())
        self.feed(self.event('speech_started',2),self.event('speech_started',3))
        self.feed(self.event('recognition',2,text='Goodbye, Paprika.',final=True))
        await self.c.task
        self.feed(self.event('recognition',3,text='Paprika.',final=False))
        self.assertTrue(self.c.snapshot()['pending_input'])
        self.feed(self.event('recognition',3,text='Paprika, one more story.',final=True))
        rid=await self.ready()
        self.assertFalse(self.c.close_after_playback)
        self.assertEqual(self.c.last_heard,'Paprika, one more story.')
        self.play(rid);self.assertTrue(self.c.engaged)

    async def test_ordered_later_candidates_survive_acceptance_of_a_preceding_candidate(self):
        self.utterance('Paprika',1);self.play(await self.ready())
        self.feed(self.event('speech_started',2),self.event('speech_started',3),self.event('speech_started',4))
        self.feed(self.event('recognition',2,text='',final=True))
        self.feed(self.event('recognition',3,text='Tell me about a fox.',final=True))
        self.feed(self.event('recognition',4,text='Actually, tell me about a dragon.',final=True))
        await self.ready()
        self.assertEqual(self.c.last_heard,'Actually, tell me about a dragon.')

    async def test_earlier_candidate_text_does_not_call_cloud_before_later_candidate_resolves(self):
        self.utterance('Paprika',1);self.play(await self.ready())
        self.feed(self.event('speech_started',2),self.event('speech_started',3))
        self.feed(self.event('recognition',2,text='Thank you.',final=True))
        await asyncio.sleep(0)
        self.assertEqual(self.brain.calls,[])
        self.feed(self.event('recognition',3,text='How can we build a castle?',final=True))
        await self.ready()
        self.assertEqual(len(self.brain.calls),1)
        self.assertEqual(self.c.last_heard,'How can we build a castle?')

    async def test_earlier_completed_input_is_used_if_later_candidate_is_empty(self):
        self.utterance('Paprika',1);self.play(await self.ready())
        self.feed(self.event('speech_started',2),self.event('speech_started',3))
        self.feed(self.event('recognition',2,text='Tell me about a fox.',final=True))
        self.assertIsNone(self.c.task)
        self.feed(self.event('recognition',3,text='',final=True))
        await self.ready()
        self.assertEqual(self.c.last_heard,'Tell me about a fox.')
        self.assertEqual(len(self.brain.calls),1)

    async def test_two_empty_candidates_leave_no_stuck_input_or_provider_task(self):
        self.utterance('Paprika',1);self.play(await self.ready())
        self.feed(self.event('speech_started',2),self.event('speech_started',3))
        self.feed(self.event('recognition',2,text='',final=True),self.event('recognition',3,text='',final=True))
        self.assertEqual(self.brain.calls,[])
        self.assertFalse(self.c.captures)
        self.assertIsNone(self.c.controller.token)

    async def test_partial_wake_does_not_authorize_anonymous_later_candidate(self):
        self.feed(self.event('speech_started',1),self.event('recognition',1,text='Paprika.',final=False))
        self.feed(self.event('speech_started',2))
        self.feed(self.event('recognition',2,text='Tell me a story.',final=True))
        await asyncio.sleep(0)
        self.assertEqual(self.brain.calls,[])
        self.assertFalse(self.c.confirmed_engagement)

    async def test_explicit_stop_can_cancel_goodbye_without_cloud(self):
        self.utterance('Paprika',1);self.play(await self.ready())
        self.feed(self.event('speech_started',2),self.event('speech_started',3))
        self.feed(self.event('recognition',2,text='Goodbye, Paprika.',final=True))
        self.feed(self.event('recognition',3,text='Stop.',final=True))
        await self.ready()
        self.assertFalse(self.c.close_after_playback)
        self.assertEqual(self.c.last_heard,'Stop.')
        self.assertEqual(self.brain.calls,[])

    async def test_local_speech_failure_has_correct_component_and_response(self):
        from tavi.speech_errors import SpeechWorkerError
        class Broken:
            async def synthesize(self,text):raise SpeechWorkerError('unsupported_phoneme')
        self.c.speech=Broken()
        self.utterance('Paprika, tell me a story',matched=True)
        rid=self.c.accepted_response_id
        await self.c.task
        state=self.c.snapshot()
        self.assertEqual(state['error'],'Local voice unavailable')
        self.assertEqual(state['failure'],{'component':'speech','code':'unsupported_phoneme','response_id':rid})
        self.assertFalse(any(m['kind']=='provider_failed' for m in self.c.metrics))
        self.assertEqual(len(self.brain.calls),1,'Never retry a paid request on voice failure')
        self.c.start('fresh')
        self.assertIsNone(self.c.snapshot()['failure']);self.assertIsNone(self.c.snapshot()['error'])

    async def asyncSetUp(self):
        self.store=Store();self.addCleanup(self.store.close)
        self.brain=Brain();self.now=[0.0]
        self.c=Conversation(self.store,provider=self.brain,speech=Voice(),clock=lambda:self.now[0])
        self.c.start('lease')
        self.addAsyncCleanup(self.c.close)

    def event(self, kind, utterance=1, **data):
        return {'type':kind,'utterance':utterance,**data}

    def feed(self,*events): self.c.feed('lease',{'events':events})

    def utterance(self,text,number=1,matched=False):
        self.feed(self.event('speech_started',number))
        self.feed(self.event('recognition',number,text=text,first_detection=matched,final=True))

    async def ready(self):
        if self.c.task: await self.c.task
        return self.c.snapshot()['audio']['id']

    def play(self, response_id):
        self.assertTrue(self.c.command('lease','started',{'response_id':response_id}))
        self.assertTrue(self.c.command('lease','played',{'response_id':response_id}))

    async def test_idle_speech_and_name_mentions_never_call_cloud(self):
        self.utterance('Tell me a story')
        self.assertFalse(self.c.engaged);self.assertEqual(self.brain.calls,[])
        self.utterance('I heard someone say Paprika',2,matched=True)
        await asyncio.sleep(0)
        self.assertFalse(self.c.engaged);self.assertEqual(self.brain.calls,[])
        self.assertEqual(self.store.sources(),[])

    async def test_partial_prefix_authorizes_same_utterance_when_final_omits_name(self):
        self.feed(self.event('speech_started'))
        self.feed(self.event('recognition',text='Paprika.',first_detection=True,final=False,
                             recognition_id='prefix-1',asr_run_id='asr-1'))
        self.assertTrue(self.c.engaged)
        self.assertEqual(self.brain.calls,[],'An incomplete request must not call reasoning')
        self.feed(self.event('recognition',text='What could we build with three cushions?',
                             first_detection=False,final=True,recognition_id='final-1',
                             address_verification={'confirmed':True}))
        await self.ready()
        self.assertEqual(self.brain.calls[0][-1]['content'],'What could we build with three cushions?')
        accepted=next(m for m in self.c.metrics if m['kind']=='accepted_turn')
        self.assertEqual(accepted['address_source'],'partial_prefix')
        self.assertEqual(accepted['address_evidence']['recognition_id'],'prefix-1')

    async def test_partial_prefix_alone_or_failed_full_verification_never_authorizes_request(self):
        for number,verification in enumerate((None,{'confirmed':False}),1):
            self.c.start('lease')
            self.feed(self.event('speech_started',number))
            self.feed(self.event('recognition',number,text='Paprika.',first_detection=True,final=False))
            self.feed(self.event('recognition',number,text='Paper cup.',first_detection=False,final=True,
                                 address_verification=verification))
            await asyncio.sleep(0)
            self.assertEqual(self.brain.calls,[])
            self.assertFalse(self.c.engaged)

    async def test_mid_sentence_partial_name_does_not_open_a_session(self):
        self.feed(self.event('speech_started'))
        self.feed(self.event('recognition',text='We bought paprika.',first_detection=True,final=False))
        self.assertFalse(self.c.engaged)
        self.feed(self.event('recognition',text='What could we build with three cushions?',first_detection=False,final=True))
        await asyncio.sleep(0)
        self.assertEqual(self.brain.calls,[])
        self.assertEqual(self.c.snapshot()['input_rejection']['reason'],'name_missing')

    async def test_final_name_mention_overrides_ambiguous_partial_prefix(self):
        self.feed(self.event('speech_started'))
        self.feed(self.event('recognition',text='Paprika.',first_detection=True,final=False))
        self.feed(self.event('recognition',text='We bought paprika for dinner.',first_detection=False,final=True))
        self.assertFalse(self.c.engaged)
        self.assertEqual(self.brain.calls,[])
        self.assertEqual(self.c.input_rejection['reason'],'name_not_at_start')

    async def test_empty_final_cannot_carry_prefix_evidence_into_another_turn(self):
        self.feed(self.event('speech_started'))
        self.feed(self.event('recognition',text='Paprika.',first_detection=True,final=False))
        self.feed(self.event('recognition',text='',first_detection=False,final=True))
        self.assertFalse(self.c.engaged)
        self.utterance('What could we build with three cushions?',2)
        await asyncio.sleep(0)
        self.assertEqual(self.brain.calls,[])

    async def test_stale_final_cannot_end_a_newer_addressed_turn(self):
        self.feed(self.event('speech_started'))
        self.feed(self.event('recognition',text='Paprika.',first_detection=True,final=False))
        self.utterance('Paprika, a new request.',2)
        rid=await self.ready()
        self.feed(self.event('recognition',text='We bought paprika for dinner.',first_detection=False,final=True))
        self.assertEqual(self.c.controller.token.response_id,rid)
        self.assertTrue(self.c.engaged)
        self.assertEqual(len(self.brain.calls),1)

    async def test_wake_then_followup_without_name_and_only_played_history(self):
        self.utterance('Paprika, tell me a story',matched=True)
        rid=await self.ready()
        self.assertEqual(self.c.controller.output,'ready')
        self.assertFalse(any(m['role']=='assistant' for m in self.c.history))
        self.play(rid)
        self.assertEqual(self.c.controller.output,'silent')
        self.utterance('Make the boat purple',2)
        await self.ready()
        self.assertEqual(len(self.brain.calls),2)
        self.assertEqual(self.brain.calls[1][-1]['content'],'Make the boat purple')
        self.assertTrue(any(m['role']=='assistant' for m in self.brain.calls[1]))
        self.assertEqual(self.store.sources(),[])
        self.assertEqual(self.store.pending(),[])
        self.assertFalse(self.c.snapshot()['simulation'])

    async def test_name_only_and_offline_are_local(self):
        self.utterance('Paprika',matched=True);rid=await self.ready();self.play(rid)
        self.assertEqual(self.brain.calls,[])
        self.c.command('lease','online',{'enabled':False})
        self.utterance('Paprika, what is the moon?',2,matched=True)
        await self.ready();self.assertIn('switched off',self.c.last_reply)
        self.assertEqual(self.brain.calls,[])

    async def test_recognition_confidence_can_be_joined_to_accepted_response_without_text_leak(self):
        self.feed(self.event('speech_started'))
        self.feed(self.event('recognition',text='Paprika, tell me a story',first_detection=True,final=True,
                             recognition_id='recognition-a',asr_run_id='asr-a',
                             confidence={'min_avg_logprob':-1.6,'segments':[]}))
        rid=await self.ready()
        final=next(m for m in self.c.metrics if m['kind']=='recognition_final')
        accepted=next(m for m in self.c.metrics if m['kind']=='accepted_turn')
        self.assertEqual(final['recognition_id'],accepted['recognition_id'])
        self.assertEqual(accepted['response_id'],rid)
        self.assertEqual(self.c.snapshot()['accepted_recognition_id'],'recognition-a')
        self.assertEqual(final['confidence']['min_avg_logprob'],-1.6)
        self.assertNotIn('text',final);self.assertEqual(self.store.sources(),[])

    async def test_played_requires_real_start_and_duplicate_is_rejected(self):
        self.utterance('Paprika',matched=True);rid=await self.ready()
        self.assertFalse(self.c.command('lease','played',{'response_id':rid}))
        self.play(rid)
        self.assertFalse(self.c.command('lease','played',{'response_id':rid}))
        self.assertEqual(len([m for m in self.c.history if m['role']=='assistant']),1)

    async def test_possible_echo_requires_endpoint_interruption_before_new_cloud_turn(self):
        self.utterance('Paprika, tell me a story',matched=True);rid=await self.ready()
        self.c.command('lease','started',{'response_id':rid})
        self.utterance('This is possible echo',2)
        await asyncio.sleep(0)
        self.assertEqual(len(self.brain.calls),1)
        self.assertEqual(self.c.controller.output,'playing')
        ignored=[m for m in self.c.metrics if m['kind']=='ignored_possible_echo']
        self.assertEqual(ignored[-1]['utterance'],2)
        onsets=[m for m in self.c.metrics if m['kind']=='speech_started']
        self.assertTrue(onsets[-1]['during_playback'])
        self.assertEqual(onsets[-1]['response_id'],rid)
        self.assertFalse(any('text' in m for m in self.c.metrics))
        self.feed(self.event('speech_started',3))
        self.assertTrue(self.c.command('lease','interrupt',{'response_id':rid,'utterance':3}))
        self.feed(self.event('recognition',3,text='Tell me about a dragon instead',first_detection=False,final=True))
        new_rid=await self.ready()
        self.assertNotEqual(new_rid,rid)
        self.assertFalse(self.c.command('lease','played',{'response_id':rid}))
        self.assertFalse(any(m['role']=='assistant' for m in self.c.history))
        self.assertEqual(len(self.brain.calls),2)

    async def test_uncancellable_old_generation_cannot_publish_audio(self):
        entered,release=asyncio.Event(),asyncio.Event()
        class SlowBrain(Brain):
            async def reply(self, history):
                entered.set()
                try: await release.wait()
                except asyncio.CancelledError: await release.wait()
                return 'Late obsolete speech.'
        self.c.provider=SlowBrain()
        self.utterance('Paprika, tell me a story',matched=True)
        await entered.wait()
        self.c.stop('lease');self.c.start('new-lease')
        release.set();await asyncio.sleep(0);await asyncio.sleep(0)
        self.assertIsNone(self.c.audio)
        self.assertEqual(self.c.history,[])
        self.assertEqual(self.store.sources(),[])

    async def test_empty_vad_candidate_preserves_generation_and_holds_ready_audio(self):
        entered,release=asyncio.Event(),asyncio.Event()
        class WaitingBrain(Brain):
            async def reply(inner,history):
                inner.calls.append(history);entered.set();await release.wait()
                return 'The blue dragon explores a distant planet.'
        self.c.provider=WaitingBrain()
        self.utterance('Paprika, tell me a story',matched=True)
        await entered.wait();original=self.c.task;token=self.c.controller.token
        self.feed(self.event('speech_started',2))
        self.assertIs(self.c.task,original)
        self.assertTrue(self.c.snapshot()['pending_input'])
        release.set();await original
        self.assertIsNotNone(self.c.audio)
        self.assertIsNone(self.c.snapshot()['audio'],'do not start ready audio over unresolved speech')
        self.now[0]=6;self.c.last_frame=6;self.c.expire()
        self.assertEqual(self.c.controller.token,token,'held audio must not hit the ready timeout')
        self.feed(self.event('recognition',2,text='',first_detection=False,final=True))
        self.assertFalse(self.c.snapshot()['pending_input'])
        self.assertEqual(self.c.snapshot()['audio']['id'],token.response_id)
        self.c.expire()
        self.assertEqual(self.c.controller.token,token,'released audio gets a fresh start window')
        self.assertEqual(self.c.last_heard,'Paprika, tell me a story')
        self.assertEqual(len(self.c.provider.calls),1)
        self.play(token.response_id)

    async def test_real_replacement_waits_for_text_then_cancels_old_generation(self):
        entered=asyncio.Event();cancelled=[]
        class WaitingBrain(Brain):
            async def reply(inner,history):
                inner.calls.append(history)
                if len(inner.calls)==1:
                    entered.set()
                    try: await asyncio.Future()
                    except asyncio.CancelledError: cancelled.append(True);raise
                return 'A space adventure begins.'
        self.c.provider=WaitingBrain()
        self.utterance('Paprika, tell me a story',matched=True);await entered.wait()
        old_token=self.c.controller.token
        self.feed(self.event('speech_started',2))
        self.assertEqual(cancelled,[])
        self.feed(self.event('recognition',2,text='Make it a space adventure instead',first_detection=False,final=True))
        new_rid=await self.ready();await asyncio.sleep(0)
        self.assertNotEqual(new_rid,old_token.response_id)
        self.assertEqual(cancelled,[True])
        self.assertEqual(len(self.c.provider.calls),2)
        self.assertEqual(self.c.last_heard,'Make it a space adventure instead')

    async def test_late_deferred_transcript_cannot_replace_a_newer_turn(self):
        self.utterance('Paprika, tell me a story',matched=True);await self.ready()
        self.feed(self.event('speech_started',2),self.event('speech_started',3))
        self.feed(self.event('recognition',3,text='Make it a space adventure',first_detection=False,final=True))
        rid=await self.ready()
        self.feed(self.event('recognition',2,text='Older replacement',first_detection=False,final=True))
        self.assertEqual(self.c.controller.token.response_id,rid)
        self.assertEqual(self.c.last_heard,'Make it a space adventure')
        self.assertFalse(self.c.snapshot()['pending_input'])

    async def test_goodbye_closes_after_playback_and_timeout_returns_to_wake(self):
        self.utterance('Paprika',matched=True);rid=await self.ready();self.play(rid)
        self.utterance('Goodbye Paprika',2);rid=await self.ready()
        self.assertTrue(self.c.engaged);self.play(rid)
        self.assertFalse(self.c.engaged);self.assertEqual(self.c.history,[])
        self.utterance('Paprika',3,matched=True);rid=await self.ready();self.play(rid)
        self.now[0]=61;self.c.last_frame=61;self.c.expire()
        self.assertFalse(self.c.engaged)
        self.assertEqual(self.brain.calls,[])

    async def test_goodbye_spelling_variants_close_without_a_paid_call(self):
        for i,text in enumerate(['Good bye Paprika.','Good-bye, Paprika!','Bye-bye Paprika.','Goodbye, Paprika.']):
            self.c.start('lease');self.utterance('Paprika',i*2+1,matched=True);self.play(await self.ready())
            self.utterance(text,i*2+2);rid=await self.ready();self.assertTrue(self.c.close_after_playback)
            self.play(rid);self.assertFalse(self.c.engaged)
        self.assertEqual(self.brain.calls,[])
        from tavi.conversation import GOODBYE
        self.assertIsNone(GOODBYE.fullmatch('Goodbye is what the dragon said.'))

    async def test_natural_farewells_wait_for_playback_then_require_name_again(self):
        for i,text in enumerate(['Okay, bye.', 'Thanks, goodbye.', 'See you later, Paprika.', 'That’s all for now.']):
            self.c.start('lease');self.utterance('Paprika',i*3+1,matched=True);self.play(await self.ready())
            self.utterance(text,i*3+2);rid=await self.ready()
            self.assertTrue(self.c.snapshot()['closing_after_playback']);self.assertTrue(self.c.engaged)
            self.play(rid);self.assertFalse(self.c.engaged);self.assertEqual(self.c.history,[])
            self.assertIsNotNone(self.c.lease,'Goodbye ends the chat, not local name listening')
            self.utterance('Tell me another story.',i*3+3)
            self.assertFalse(self.c.engaged);self.assertEqual(self.brain.calls,[])

    async def test_thank_you_alone_does_not_close_the_chat(self):
        self.utterance('Paprika',1,matched=True);self.play(await self.ready())
        self.utterance('Thank you.',2);await self.ready()
        self.assertFalse(self.c.close_after_playback);self.assertTrue(self.c.engaged);self.assertEqual(len(self.brain.calls),1)

    async def test_disconnect_revokes_audio_and_session(self):
        self.utterance('Paprika',matched=True);rid=await self.ready()
        self.now[0]=2.1;self.c.expire()
        with self.assertRaises(ValueError): self.c.audio_bytes('lease',rid)
        self.assertIsNone(self.c.lease)
        self.assertEqual(self.c.history,[])


class PaidBudgetTests(unittest.IsolatedAsyncioTestCase):
    async def test_request_reserves_before_send_and_uses_bounded_text_only_api(self):
        store=Store();self.addCleanup(store.close)
        seen=[]
        async def create(**kwargs):
            self.assertEqual(store.used_micro_usd(),50000)
            self.assertEqual(kwargs['store'],False)
            self.assertEqual(kwargs['tools'],[])
            self.assertEqual(kwargs['max_output_tokens'],384)
            self.assertEqual(kwargs['reasoning'],{'effort':'none'})
            seen.append(kwargs)
            return SimpleNamespace(usage=SimpleNamespace(input_tokens=100,output_tokens=20),status='completed',output_text='Hello, brave explorer!')
        provider=PaidText(store,SimpleNamespace(responses=SimpleNamespace(create=create)))
        self.assertEqual(await provider.reply([{'role':'user','content':'Hello'}]),'Hello, brave explorer!')
        self.assertEqual(store.used_micro_usd(),165)
        self.assertEqual(len(seen),1)
        self.assertEqual(store.sources(),[])

    async def test_ambiguous_network_failure_retains_reservation_without_retry(self):
        store=Store();self.addCleanup(store.close);calls=[]
        async def fail(**kwargs): calls.append(1);raise ConnectionError('synthetic')
        provider=PaidText(store,SimpleNamespace(responses=SimpleNamespace(create=fail)))
        with self.assertRaises(ConnectionError):await provider.reply([{'role':'user','content':'Hello'}])
        self.assertEqual(len(calls),1)
        self.assertEqual(store.used_micro_usd(),50000)

    async def test_exhausted_budget_never_sends_a_request(self):
        store=Store();self.addCleanup(store.close)
        store.reserve('earlier',APPROVED_BUDGET_MICRO_USD,APPROVED_BUDGET_MICRO_USD)
        async def forbidden(**kwargs): self.fail('Network request must not happen')
        provider=PaidText(store,SimpleNamespace(responses=SimpleNamespace(create=forbidden)))
        with self.assertRaises(ValueError): await provider.reply([{'role':'user','content':'Hello'}])


class CaptureIsolationTests(unittest.IsolatedAsyncioTestCase):
    async def test_pcm_acknowledgement_does_not_wait_for_conversation_loop(self):
        import threading,time
        from http.client import HTTPConnection
        import json
        from tavi.service import LocalHTTPServer,Demo,handler_for
        class Live:
            def start(self,mode): return {'stream_id':'fixture-lease','sample_rate':16000}
            def feed(self,lease,sequence,pcm):
                return {'sequence':sequence,'probability':0,'events':[]}
            def stop(self,lease): return {'stopped':True}
            def expire(self): pass
            def close(self): pass
        store=Store();demo=Demo(store);loop=asyncio.get_running_loop()
        server=LocalHTTPServer(('127.0.0.1',0),lambda *a:None);port=server.server_port
        server.RequestHandlerClass=handler_for(demo,loop,port,live_factory=Live)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        def request(path,data,headers):
            conn=HTTPConnection('127.0.0.1',port,timeout=2)
            try:
                conn.request('POST',path,body=data,headers=headers)
                response=conn.getresponse();value=json.loads(response.read())
                self.assertEqual(response.status,200,value);return value
            finally:conn.close()
        entered=threading.Event()
        def blocked_loop(): entered.set();time.sleep(.35)
        def capture():
            self.assertTrue(entered.wait(1));start=time.perf_counter()
            result=request('/api/conversation/frame',bytes(1024),{'Content-Type':'application/octet-stream','X-Audio-Stream':'fixture-lease','X-Audio-Sequence':'0'})
            return time.perf_counter()-start,result
        try:
            await asyncio.to_thread(request,'/api/conversation/start',json.dumps({'online':False}),{'Content-Type':'application/json'})
            task=asyncio.create_task(asyncio.to_thread(capture))
            await asyncio.sleep(0)
            loop.call_soon(blocked_loop)
            duration,result=await task
            self.assertLess(duration,.15,'Capture ACK must not inherit a blocked conversation loop')
            self.assertEqual(result['sequence'],0)
        finally:
            await server.RequestHandlerClass.close_conversation()
            server.RequestHandlerClass.close_live()
            await asyncio.to_thread(server.shutdown);server.server_close();store.close()

import asyncio
import json
from pathlib import Path
import tempfile
import threading
import unittest
from http.client import HTTPConnection

from tavi.audio import Frame, PreRoll
from tavi.contracts import Event, Kind
from tavi.memory import FakeMemory, drain_outbox
from tavi.runtime import Controller
from tavi.service import Demo, LocalHTTPServer, handler_for
from tavi.storage import Store, APPROVED_BUDGET_MICRO_USD

class ControllerTests(unittest.TestCase):
    def setUp(self):
        self.store = Store()
        self.addCleanup(self.store.close)
        self.c = Controller(self.store)
        self.token = self.c.begin()

    def event(self, kind, token=None, **payload):
        return Event.make(kind, token or self.token, **payload)

    def ready(self):
        self.c.apply(self.event(Kind.TRANSCRIPT, text="Let's build a spaceship"))
        self.c.apply(self.event(Kind.IDENTITY, speaker="childone"))

    def audio(self, seq=0, duration=500):
        return self.event(Kind.AUDIO, sequence=seq, duration_ms=duration, text="A completed chunk")

    def test_identity_and_transcript_barrier_in_either_order(self):
        for first in (Kind.IDENTITY, Kind.TRANSCRIPT):
            self.token = self.c.begin()
            a=self.event(Kind.IDENTITY,speaker="childone")
            b=self.event(Kind.TRANSCRIPT,text="Spaceship")
            ordered=(a,b) if first == Kind.IDENTITY else (b,a)
            self.c.apply(ordered[0])
            self.assertEqual(self.c.output,"silent")
            self.c.apply(ordered[1])
            self.assertEqual(self.c.output,"generating")
        self.assertEqual(len(self.store.pending()),2)

    def test_delayed_identity_cannot_contaminate_next_turn(self):
        old=self.token
        self.token=self.c.begin()
        self.assertFalse(self.c.apply(self.event(Kind.IDENTITY,old,speaker="childtwo")))
        self.ready()
        self.assertEqual(self.store.pending()[0]["body"]["speaker"],"childone")

    def test_duplicate_event_does_not_repeat_memory_work(self):
        self.ready()
        self.assertFalse(self.c.apply(self.event(Kind.TRANSCRIPT,text="duplicate")))
        self.assertEqual(len(self.store.pending()),1)

    def test_audio_before_context_is_rejected(self):
        self.assertFalse(self.c.apply(self.audio()))
        self.assertEqual(self.c.snapshot()["queued_ms"],0)

    def test_interrupt_flushes_audio_and_rejects_all_late_callbacks(self):
        self.ready(); self.c.apply(self.audio()); self.c.cancel()
        for kind,payload in ((Kind.AUDIO,dict(sequence=1,duration_ms=500,text="late")),(Kind.PLAYED,dict(sequence=0)),(Kind.DONE,{})):
            self.assertFalse(self.c.apply(self.event(kind,**payload)))
        self.assertEqual(self.c.output,"silent")
        self.assertFalse(any(x["kind"] == "assistant_played" for x in self.store.sources()))

    def test_only_played_chunks_enter_history(self):
        self.ready(); self.c.apply(self.audio()); self.c.apply(self.audio(1))
        self.c.apply(self.event(Kind.PLAYED,sequence=0)); self.c.cancel()
        played=[x for x in self.store.sources() if x["kind"] == "assistant_played"]
        self.assertEqual(len(played),1)

    def test_out_of_order_and_duplicate_acknowledgements(self):
        self.ready(); self.c.apply(self.audio()); self.c.apply(self.audio(1))
        self.assertFalse(self.c.apply(self.event(Kind.PLAYED,sequence=1)))
        event=self.event(Kind.PLAYED,sequence=0)
        self.assertTrue(self.c.apply(event)); self.assertFalse(self.c.apply(event))
        self.assertEqual(self.c.snapshot()["queued_ms"],500)

    def test_done_before_playback_does_not_show_silent(self):
        self.ready(); self.c.apply(self.audio()); self.c.apply(self.event(Kind.DONE))
        self.assertEqual(self.c.output,"playing")
        self.c.apply(self.event(Kind.PLAYED,sequence=0))
        self.assertEqual(self.c.output,"silent")
        self.assertFalse(self.c.apply(self.audio(1)))

    def test_overflow_cancels_instead_of_silently_dropping(self):
        self.ready(); self.c.apply(self.audio(duration=1500))
        self.assertFalse(self.c.apply(self.audio(1,1500)))
        self.assertEqual(self.c.snapshot()["queued_ms"],0)
        self.assertIn("overflow",self.c.error)

    def test_mute_blocks_turns_until_explicit_unmute(self):
        self.c.mute(True)
        with self.assertRaises(ValueError): self.c.begin()
        self.c.connected(True)
        with self.assertRaises(ValueError): self.c.begin()
        self.c.mute(False); self.c.begin()

    def test_unknown_speaker_does_not_queue_personal_memory(self):
        self.c.apply(self.event(Kind.TRANSCRIPT,text="Unknown child"))
        self.c.apply(self.event(Kind.IDENTITY,speaker="unknown"))
        self.assertEqual(self.store.pending(),[])
        self.assertEqual(self.c.output,"generating")

    def test_failure_clears_playback(self):
        self.ready(); self.c.apply(self.audio()); self.c.apply(self.event(Kind.FAILURE))
        self.assertEqual(self.c.connectivity,"degraded")
        self.assertEqual(self.c.snapshot()["queued_ms"],0)

class PersistenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/"runtime.sqlite3"

    def test_restart_recovers_pending_job_but_no_live_turn(self):
        s=Store(self.path);c=Controller(s);token=c.begin()
        c.apply(Event.make(Kind.TRANSCRIPT,token,text="Test event"))
        c.apply(Event.make(Kind.IDENTITY,token,speaker="childone"));s.close()
        s=Store(self.path);self.addCleanup(s.close);c=Controller(s)
        self.assertEqual(len(s.pending()),1)
        self.assertIsNone(c.token)
        self.assertFalse(c.apply(Event.make(Kind.AUDIO,token,sequence=0,duration_ms=100,text="old")))

    def test_failed_job_retries_without_duplicate_projection(self):
        s=Store(self.path);self.addCleanup(s.close)
        s.record("source",{"text":"fictional"},memory=True)
        class Flaky(FakeMemory):
            def ingest(self, source_id, body):
                super().ingest(source_id,body)
                raise RuntimeError("Crash after ingest before acknowledgement")
        self.assertEqual(drain_outbox(s,Flaky(s))["failures"],1)
        self.assertEqual(s.pending()[0]["attempts"],1)
        self.assertEqual(drain_outbox(s,FakeMemory(s))["successes"],1)
        self.assertEqual(len(s.sources()),2)
        self.assertEqual(s.pending(),[])

    def test_budget_is_persistent_and_conservative_across_connections(self):
        a=Store(self.path);b=Store(self.path);self.addCleanup(a.close);self.addCleanup(b.close)
        a.reserve("first",20_000_000,25_000_000)
        with self.assertRaises(ValueError): b.reserve("second",6_000_000,25_000_000)
        a.settle("first",10_000_000)
        b.reserve("second",15_000_000,25_000_000)
        self.assertEqual(b.used_micro_usd(),25_000_000)

    def test_budget_cannot_be_raised_or_use_fractional_money(self):
        s=Store(self.path);self.addCleanup(s.close)
        for amount,cap in ((1,50_000_000),(1.5,25_000_000),(True,25_000_000)):
            with self.assertRaises(ValueError):s.reserve("forbidden",amount,cap)
        self.assertEqual(s.used_micro_usd(),0)

    def test_overage_is_recorded_and_freezes_future_requests(self):
        s=Store(self.path);self.addCleanup(s.close);s.reserve("a",100,25_000_000)
        with self.assertRaises(ValueError): s.settle("a",101)
        self.assertEqual(s.used_micro_usd(),101)
        with self.assertRaises(ValueError): s.reserve("b",100,25_000_000)

class AudioTests(unittest.TestCase):
    def test_idle_preroll_bound_and_drain(self):
        buffer=PreRoll(seconds=.02)
        for seq in range(1000): buffer.append(Frame(seq,b'\x00\x00'*160))
        self.assertEqual(buffer.samples,320)
        self.assertEqual([x.sequence for x in buffer.drain()],[998,999])
        self.assertEqual(buffer.samples,0)

    def test_bad_audio_is_rejected(self):
        buffer=PreRoll(); buffer.append(Frame(1,b'\x00\x00'))
        for frame in (Frame(0,b'\x00\x00'),Frame(2,b'\x00'),Frame(2,b'\x00\x00',24000)):
            with self.assertRaises(ValueError):buffer.append(frame)

class ServiceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.store=Store();self.demo=Demo(self.store, pace=.1)
    async def asyncTearDown(self):
        await self.demo.close();self.store.close()

    async def test_second_turn_cancels_first_provider_task(self):
        await self.demo.command("say",{"text":"first","speaker":"childtwo"})
        old=tuple(self.demo.tasks)[0]
        await self.demo.command("say",{"text":"second","speaker":"childone"})
        await asyncio.sleep(.01)
        self.assertTrue(old.done())
        await asyncio.sleep(.45)
        self.assertEqual(self.store.pending()[0]["body"]["text"],"second")
        self.assertEqual(self.store.pending()[0]["body"]["speaker"],"childone")

    async def test_offline_and_mute_cannot_be_bypassed_by_say(self):
        for command in ("offline","mute"):
            await self.demo.command(command,{})
            with self.assertRaises(ValueError):await self.demo.command("say",{"text":"blocked"})
            await self.demo.command("online",{})

    async def test_http_page_state_and_local_origin_boundary(self):
        loop=asyncio.get_running_loop()
        # Reserve a free loopback port before constructing host checks.
        server=LocalHTTPServer(("127.0.0.1",0),lambda *a:None)
        port=server.server_port
        server.RequestHandlerClass=handler_for(self.demo,loop,port)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        base=f"http://127.0.0.1:{port}"
        def request(path,body=None,origin=None):
            headers={"Content-Type":"application/json"}
            if origin:headers["Origin"]=origin
            connection=HTTPConnection("127.0.0.1",port,timeout=2)
            try:
                connection.request("POST" if body else "GET",path,body=json.dumps(body) if body else None,headers=headers)
                response=connection.getresponse()
                return response.status,response.read()
            finally:
                connection.close()
        def persistent_requests():
            connection=HTTPConnection("127.0.0.1",port,timeout=2)
            try:
                connection.request("GET","/api/state")
                response=connection.getresponse();response.read()
                self.assertFalse(response.will_close)
                first_socket=connection.sock
                connection.request("GET","/api/state")
                response=connection.getresponse();response.read()
                self.assertEqual(response.status,200)
                self.assertIs(connection.sock,first_socket)
            finally:
                connection.close()
        def microphone_page_policy():
            connection=HTTPConnection('127.0.0.1',port,timeout=2)
            try:
                connection.request('GET','/mic-check')
                response=connection.getresponse();body=response.read()
                self.assertEqual(response.status,200)
                self.assertIn(b'Start recording on this Mac',body)
                policy=response.getheader('Content-Security-Policy')
                self.assertIn("media-src 'self' blob:",policy)
                self.assertIn("connect-src 'self'",policy)
                self.assertIn("default-src 'self'",policy)
            finally:
                connection.close()
        try:
            await asyncio.to_thread(persistent_requests)
            await asyncio.to_thread(microphone_page_policy)
            self.assertIn(b"Offline simulator",(await asyncio.to_thread(request,"/"))[1])
            self.assertIn(b"Start listening",(await asyncio.to_thread(request,"/live-wake"))[1])
            self.assertIn(b"Start Paprika",(await asyncio.to_thread(request,"/conversation"))[1])
            self.assertEqual((await asyncio.to_thread(request,"/conversation?retest=phonemes"))[0],200)
            self.assertEqual((await asyncio.to_thread(request,"/not-an-asset?retest=phonemes"))[0],404)
            from unittest.mock import patch
            from tavi.saved_tests import save_test
            saved={'schema_version':1,'kind':'paprika_controlled_conversation_diagnostics',
                   'local_save_consent':{'destination':'project_private_local','explicit_save':True},
                   'runs':[{'ended_at':'2026-11-02T00:00:00Z'}],'audio_included':False,'transcripts_included':False}
            with tempfile.TemporaryDirectory() as folder, patch('tavi.saved_tests.save_test',lambda raw:save_test(raw,Path(folder))):
                status,body=await asyncio.to_thread(request,'/api/conversation/save-test',saved)
                self.assertEqual(status,200);filename=json.loads(body)['filename']
                self.assertTrue((Path(folder)/filename).is_file())
                status,_=await asyncio.to_thread(request,'/api/conversation/save-test',saved,'https://example.com')
                self.assertEqual(status,403)
                self.assertEqual((await asyncio.to_thread(request,'/private-conversation-results/'+filename))[0],404)
            status,_=await asyncio.to_thread(request,"/api/conversation/start",{"online":True},"https://example.com")
            self.assertEqual(status,403)
            status,_=await asyncio.to_thread(request,"/api/conversation/start",{"online":"yes"})
            self.assertEqual(status,400)
            self.assertIn(b"paprika_live_whisper",(await asyncio.to_thread(request,"/live-wake.js"))[1])
            status,_=await asyncio.to_thread(request,"/api/live-wake/start",{"mode":"hinted"},"https://example.com")
            self.assertEqual(status,403)
            status,_=await asyncio.to_thread(request,"/api/live-wake/start",{"mode":"remote"})
            self.assertEqual(status,400)
            state=json.loads((await asyncio.to_thread(request,"/api/state"))[1])
            self.assertFalse(state["paid_apis_enabled"])
            self.assertEqual(state["budget_usd"],APPROVED_BUDGET_MICRO_USD/1e6)
            status,_=await asyncio.to_thread(request,"/api/command",{"command":"say","text":"unwanted"},"https://example.com")
            self.assertEqual(status,403)
            state=json.loads((await asyncio.to_thread(request,"/api/command",{"command":"mute"}))[1])
            self.assertEqual(state["input"],"muted")
        finally:
            await asyncio.to_thread(server.shutdown);server.server_close()

if __name__ == "__main__":
    unittest.main()

import threading
import time
import unittest
from tavi.live_wake import LiveWake
from tavi.asr_confidence import DecodedSpeech

SPEECH = b'\x01\x00' * 512
QUIET = bytes(1024)


class Detector:
    def reset(self): pass
    def probability(self, pcm): return .99 if pcm[0] else 0


class Decoder:
    def __init__(self, blocked=False):
        self.entered = threading.Event()
        self.release = threading.Event()
        self.calls = []
        if not blocked: self.release.set()

    def decode(self, pcm, prompt):
        self.calls.append((pcm, prompt))
        self.entered.set()
        if not self.release.wait(2): raise RuntimeError('Test decoder timed out')
        return 'Paprika, tell me a story.'


class LiveWakeTests(unittest.TestCase):
    def test_model_warmup_does_not_expire_the_new_microphone_lease(self):
        now=[10.0]
        self.make(clock=lambda:now[0])
        self.decoder.prepare=lambda:now.__setitem__(0,now[0]+5)
        self.lease=self.engine.start('hinted')['stream_id'];self.seq=0
        self.assertEqual(self.feed(QUIET)['sequence'],0)

    def test_final_adapter_receives_absolute_queue_age_deadline(self):
        self.make();deadlines=[]
        def final(pcm,prompt,deadline,valid):
            self.assertTrue(valid())
            deadlines.append(deadline)
            return 'Paprika, hello.'
        self.decoder.decode_final_job=final
        self.feed(count=22);self.settled();self.feed(QUIET,25);self.settled();self.feed(QUIET)
        event=next(e for e in self.events if e['type']=='recognition' and e['final'])
        self.assertEqual(len(deadlines),1)
        self.assertLess(event['job_age_ms'],3000)
        self.assertAlmostEqual(event['deadline_remaining_ms']+event['job_age_ms'],3000)

    def test_full_address_check_only_for_missing_final_name_after_anchored_partial(self):
        for partial,final,expected in [('Paprika.','What could we build?',1),
                                        ('We bought paprika.','What could we build?',0),
                                        ('Paprika.','We bought paprika.',0),
                                        ('Hello.','What could we build?',0)]:
            self.make();calls=[]
            self.decoder.decode=lambda pcm,prompt:partial
            self.decoder.decode_final=lambda pcm,prompt:final
            def verify(pcm,text,prompt):calls.append((pcm,text,prompt));return {'confirmed':True}
            self.decoder.verify_address=verify
            self.feed(QUIET,10);self.feed(count=22);self.settled();self.feed(QUIET,25);self.settled()
            result=self.feed(QUIET)
            self.assertEqual(len(calls),expected)
            events=[e for e in result['events'] if e['type']=='recognition' and e['final']]
            self.assertEqual(len(events),1)
            self.assertEqual(events[0]['address_verification'],{'confirmed':True} if expected else None)

    def test_partials_and_finals_use_distinct_decoder_paths(self):
        self.make();final_calls=[]
        def final(pcm,prompt):
            final_calls.append((pcm,prompt));return DecodedSpeech('Good bye, Paprika.',{'decoder':{'model':'base.en'}})
        self.decoder.decode_final=final
        self.feed(QUIET,10);self.feed(count=22);self.settled();self.feed(QUIET,25);self.settled();self.feed(QUIET)
        self.assertTrue(self.decoder.calls,'Name search still uses the lightweight partial decoder')
        self.assertEqual(len(final_calls),1)
        e=next(e for e in self.events if e['type']=='recognition' and e['final'])
        self.assertEqual(e['text'],'Good bye, Paprika.');self.assertEqual(e['confidence']['decoder']['model'],'base.en')

    def make(self, blocked=False, clock=time.monotonic):
        decoder = Decoder(blocked)
        engine = LiveWake(Detector(), decoder, clock)
        self.addCleanup(lambda: (decoder.release.set(), engine.close()))
        self.engine, self.decoder = engine, decoder
        self.lease = engine.start('hinted')['stream_id']
        self.seq = 0
        self.events = []
        return engine

    def feed(self, pcm=SPEECH, count=1):
        for _ in range(count):
            result = self.engine.feed(self.lease, self.seq, pcm)
            self.seq += 1
            self.events.extend(result['events'])
        return result

    def settled(self):
        with self.engine.condition:
            self.assertTrue(self.engine.condition.wait_for(lambda: self.engine.pending is None and self.engine.running is None, timeout=2))

    def test_incremental_name_detection_and_whole_turn_final(self):
        self.make()
        self.feed(QUIET, 10)
        self.feed(count=22)
        self.settled()
        result = self.feed()
        self.assertTrue(result['speech'])
        self.assertTrue(any(e.get('first_detection') for e in self.events))
        # Distinct later words remain in the final, not just the wake prefix.
        marker = b'\x02\x00' * 512
        self.feed(marker, 20)
        self.feed(QUIET, 25)
        self.settled()
        self.feed(QUIET)
        final = [e for e in self.events if e['type'] == 'recognition' and e['final']]
        self.assertEqual(len(final), 1)
        self.assertEqual(sum(bool(e.get('first_detection')) for e in self.events), 1)
        self.assertIn(SPEECH, self.decoder.calls[-1][0])
        self.assertIn(marker, self.decoder.calls[-1][0])
        self.assertTrue(final[0]['heard_name_any'])

    def test_confidence_and_decode_ids_survive_the_worker_to_final_event(self):
        self.make()
        self.decoder.decode=lambda pcm,prompt:DecodedSpeech('Paprika, hello.',{'min_avg_logprob':-1.7,'segments':[]},
                                                            {'worker_transcribe_ms':123})
        self.feed(QUIET,10);self.feed(count=22);self.settled();self.feed(QUIET,25);self.settled();self.feed(QUIET)
        final=next(e for e in self.events if e['type']=='recognition' and e['final'])
        self.assertEqual(final['confidence']['min_avg_logprob'],-1.7)
        self.assertEqual(final['worker_timing']['worker_transcribe_ms'],123)
        self.assertTrue(final['recognition_id']);self.assertTrue(final['asr_run_id'])
        self.assertEqual(final['audio_samples'],final['snapshot_end_sample']-final['audio_start_sample'])

    def test_blocked_decoder_does_not_block_frames_and_queue_is_bounded(self):
        engine = self.make(blocked=True)
        self.feed(count=22)
        self.assertTrue(self.decoder.entered.wait(1))
        self.feed(count=100)
        self.assertIsNotNone(engine.running)
        self.assertIsNotNone(engine.pending)
        self.assertGreater(engine.replaced, 0)
        self.assertLessEqual(len(engine.segment) * 512, 320000)
        self.feed(QUIET, 25)
        self.assertTrue(engine.pending.final)

    def test_muting_and_new_lease_discard_late_results(self):
        engine = self.make(blocked=True)
        old = self.lease
        self.feed(count=22)
        self.assertTrue(self.decoder.entered.wait(1))
        engine.stop(old)
        self.assertIsNone(engine.segment)
        self.lease = engine.start('unhinted')['stream_id']
        self.seq = 0
        engine.stop(old)  # Late stop cannot mute the new capture.
        self.decoder.release.set()
        self.settled()
        self.assertEqual(self.feed(QUIET)['events'], [])
        self.assertEqual(engine.stream_id, self.lease)
        self.assertIsNone(engine.pending)

    def test_gaps_and_expired_leases_clear_audio(self):
        now = [10.0]
        engine = self.make(clock=lambda: now[0])
        self.feed(count=3)
        with self.assertRaises(ValueError): engine.feed(self.lease, 99, SPEECH)
        self.assertIsNone(engine.stream_id)
        self.assertIsNone(engine.segment)
        self.lease = engine.start('hinted')['stream_id']
        now[0] += 2.1
        engine.expire()
        self.assertIsNone(engine.stream_id)
        with self.assertRaises(ValueError): engine.feed(self.lease, 0, QUIET)

    def test_pending_final_cannot_be_silently_overwritten(self):
        engine = self.make(blocked=True)
        self.feed(count=22)
        self.assertTrue(self.decoder.entered.wait(1))
        self.feed(QUIET, 25)
        self.assertTrue(engine.pending.final)
        self.feed(count=22)
        with self.assertRaisesRegex(ValueError, 'final request'):
            self.feed(QUIET, 25)
        self.assertIsNone(engine.stream_id)
        self.assertIsNone(engine.segment)

    def test_long_speech_is_bounded_and_fails_visibly(self):
        engine = self.make()
        with self.assertRaisesRegex(ValueError, '20-second'):
            self.feed(count=650)
        self.assertIsNone(engine.stream_id)
        self.assertIsNone(engine.segment)

    def test_slow_result_does_not_publish_a_stale_name_detection(self):
        now = [0.0]
        engine = self.make(blocked=True, clock=lambda: now[0])
        self.feed(count=22)
        self.assertTrue(self.decoder.entered.wait(1))
        now[0] = 3.1
        self.decoder.release.set()
        self.settled()
        with self.assertRaisesRegex(ValueError, 'three-second'):
            self.feed(QUIET)
        self.assertIsNone(engine.stream_id)
        self.assertFalse(engine.events)

    def test_invalid_mode_does_not_start_or_replace_capture(self):
        engine = self.make()
        old = engine.stream_id
        with self.assertRaises(ValueError): engine.start('remote')
        self.assertEqual(engine.stream_id, old)

    def test_capture_times_out_even_if_the_decoder_never_returns(self):
        now = [0.0]
        engine = self.make(blocked=True, clock=lambda: now[0])
        self.feed(count=22)
        self.assertTrue(self.decoder.entered.wait(1))
        now[0] = 3.1
        with self.assertRaisesRegex(ValueError, 'three-second'):
            self.feed(QUIET)
        self.assertIsNone(engine.stream_id)
        self.assertIsNone(engine.segment)
        with self.assertRaisesRegex(ValueError, 'still busy'):
            engine.start('hinted')


if __name__ == '__main__': unittest.main()

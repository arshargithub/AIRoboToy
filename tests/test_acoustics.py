import unittest
from tavi.acoustics import AcousticSession

class Detector:
    def __init__(self):self.resets=0;self.value=.9
    def reset(self):self.resets+=1
    def probability(self,pcm):return self.value

class AcousticTests(unittest.TestCase):
    def setUp(self):
        self.detector=Detector();self.now=10
        self.audio=AcousticSession(self.detector,lambda:self.now)
        self.lease=self.audio.start()['stream_id']

    def test_two_frames_confirm_speech_and_silence_resets_confirmation(self):
        self.assertFalse(self.audio.feed(self.lease,0,bytes(1024))['speech'])
        self.assertTrue(self.audio.feed(self.lease,1,bytes(1024))['speech'])
        self.detector.value=.1
        self.assertFalse(self.audio.feed(self.lease,2,bytes(1024))['speech'])
        self.detector.value=.9
        self.assertFalse(self.audio.feed(self.lease,3,bytes(1024))['speech'])

    def test_preroll_is_bounded_during_long_idle_stream(self):
        for i in range(1000):result=self.audio.feed(self.lease,i,bytes(1024))
        self.assertLessEqual(result['preroll_samples'],32000)

    def test_missing_frame_invalidates_stream_and_clears_buffer(self):
        self.audio.feed(self.lease,0,bytes(1024))
        with self.assertRaises(ValueError):self.audio.feed(self.lease,2,bytes(1024))
        self.assertEqual(self.audio.buffer.samples,0)
        self.assertIsNone(self.audio.stream_id)

    def test_new_endpoint_invalidates_old_lease(self):
        new=self.audio.start()['stream_id']
        with self.assertRaises(ValueError):self.audio.feed(self.lease,0,bytes(1024))
        self.assertEqual(self.audio.feed(new,0,bytes(1024))['frames'],1)

    def test_stop_erases_transient_input(self):
        self.audio.feed(self.lease,0,bytes(1024));self.audio.stop()
        with self.assertRaises(ValueError):self.audio.feed(self.lease,1,bytes(1024))
        self.assertEqual(self.audio.buffer.samples,0)

    def test_stale_or_wrong_size_frames_fail_closed(self):
        self.now=13
        with self.assertRaises(ValueError):self.audio.feed(self.lease,0,bytes(1024))
        self.lease=self.audio.start()['stream_id']
        with self.assertRaises(ValueError):self.audio.feed(self.lease,0,bytes(100))

    def test_disconnected_endpoint_expires_without_another_frame(self):
        self.audio.feed(self.lease,0,bytes(1024))
        self.now=13
        self.audio.expire()
        self.assertIsNone(self.audio.stream_id)
        self.assertEqual(self.audio.buffer.samples,0)

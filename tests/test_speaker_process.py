from io import BytesIO
import unittest
from unittest.mock import patch
from tavi.speaker_process import SpeakerProcess
class FakeProcess:
 def __init__(self):self.stdin=BytesIO();self.stdout=BytesIO();self.killed=False
 def poll(self):return None
 def kill(self):self.killed=True
 def wait(self,timeout):return 0
class ProcessBoundsTests(unittest.TestCase):
 def test_timeout_kills_owned_worker_and_never_returns_a_late_embedding(self):
  w=SpeakerProcess();p=FakeProcess();w.process=p
  with patch.object(w,'prepare'),patch.object(w,'_read',side_effect=TimeoutError('controlled timeout')):
   with self.assertRaises(TimeoutError):w.encode(b'pcm')
  self.assertTrue(p.killed);self.assertTrue(p.stdin.closed);self.assertIsNone(w.process)
 def test_unbound_reply_is_rejected_and_owned_worker_stopped(self):
  w=SpeakerProcess();p=FakeProcess();w.process=p
  with patch.object(w,'prepare'),patch.object(w,'_read',return_value={'id':'different-request','ok':True,'result':{'embedding':[1,0]}}):
   with self.assertRaises(ValueError):w.encode(b'pcm')
  self.assertTrue(p.killed);self.assertIsNone(w.process)

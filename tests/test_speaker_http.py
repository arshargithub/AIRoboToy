import json,tempfile,threading,unittest,urllib.request,urllib.error
from pathlib import Path
from http.server import ThreadingHTTPServer
from unittest.mock import patch
from tavi.speaker_profile import Enrollment
from tavi.speaker_setup import handler
from tests.test_speaker_profile import FakeEncoder
class SpeakerHTTPTests(unittest.TestCase):
 def test_loopback_requires_consent_session_origin_and_small_recording(self):
  with tempfile.TemporaryDirectory() as d:
   bound=[];e=Enrollment(Path(d)/'private',encoder=FakeEncoder(),guard=lambda:None,bind=lambda body:bound.append(body))
   server=ThreadingHTTPServer(('127.0.0.1',0),lambda *_:None);server.RequestHandlerClass=handler(e,server.server_port);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
   def post(path,body,**headers):
    req=urllib.request.Request(f'http://127.0.0.1:{server.server_port}'+path,data=json.dumps(body).encode(),headers={'Content-Type':'application/json',**headers})
    try:
     with urllib.request.urlopen(req,timeout=2) as r:return r.status,json.load(r)
    except urllib.error.HTTPError as r:return r.code,json.load(r)
   try:
    self.assertEqual(post('/api/begin',{})[0],400);self.assertFalse(e.root.exists());self.assertEqual(bound,[])
    self.assertEqual(post('/api/finish',{})[0],400)
    self.assertEqual(post('/api/begin',{},Origin='https://unrelated.example')[0],403)
    self.assertEqual(post('/api/begin',{},Host='unrelated.example')[0],403)
   finally:server.shutdown();server.server_close();thread.join()

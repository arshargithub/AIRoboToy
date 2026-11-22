import json
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from tavi.adventure_preview import handler


class AdventureHTTPTests(unittest.TestCase):
    def test_static_preview_denies_recording_profiles_and_external_host(self):
        server = ThreadingHTTPServer(('127.0.0.1', 0), lambda *_: None)
        server.RequestHandlerClass = handler(server.server_port)
        thread = threading.Thread(target=server.serve_forever, daemon=True);thread.start()
        base = f'http://127.0.0.1:{server.server_port}'
        try:
            for path in ('/', '/adventure-preview.css', '/adventure-state.js', '/adventure-preview.js'):
                with urllib.request.urlopen(base+path, timeout=2) as response:
                    self.assertEqual(response.status, 200)
                    self.assertIn('microphone=()', response.headers['Permissions-Policy'])
                    self.assertIn("connect-src 'none'", response.headers['Content-Security-Policy'])
                    self.assertTrue(response.read())
            with urllib.request.urlopen(base+'/api/health', timeout=2) as response:
                self.assertEqual(json.load(response), {'preview': True, 'microphone': False, 'models': False, 'cloud': False, 'real_profiles': False})
            for path, method, headers, status in [('/api/record', 'POST', {}, 405),('/api/begin','POST',{},405),('/../speaker_profile.py','GET',{},404),('/','GET',{'Host':'external.example'},403)]:
                req = urllib.request.Request(base+path, data=b'{}' if method=='POST' else None, headers=headers, method=method)
                with self.assertRaises(urllib.error.HTTPError) as raised:urllib.request.urlopen(req, timeout=2)
                self.assertEqual(raised.exception.code, status)
        finally:server.shutdown();server.server_close();thread.join()

"""Loopback-only isolated guided native voice reference."""
import argparse
import asyncio
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import signal
import threading
from urllib.parse import urlsplit

from .realtime_lab import NativeLab
from .storage import Store


def handler(lab, loop, port):
    allowed={f'http://127.0.0.1:{port}',f'http://localhost:{port}'}
    web=Path(__file__).with_name('web')
    assets={'/':('realtime.html','text/html; charset=utf-8'),
            '/engagement':('realtime.html','text/html; charset=utf-8'),'/realtime.js':('realtime.js','text/javascript'),
            '/native-playback.js':('native-playback.js','text/javascript'),'/interruption.js':('interruption.js','text/javascript'),
            '/capture.js':('capture.js','text/javascript'),
            '/parent-setup':('parent-setup.html','text/html; charset=utf-8'),
            '/parent-setup.js':('parent-setup.js','text/javascript'),
            '/playback-check':('playback-check.html','text/html; charset=utf-8'),
            '/playback-check.js':('playback-check.js','text/javascript'),
            '/playback-v1.js':('../../tests/fixtures/native-playback-v1.js','text/javascript')}
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def valid(self):return 'http://'+self.headers.get('Host','') in allowed
        def reply(self,status,data,kind='application/json'):
            raw=data if isinstance(data,bytes) else json.dumps(data,allow_nan=False).encode()
            self.send_response(status);self.send_header('Content-Type',kind)
            self.send_header('Content-Length',str(len(raw)));self.send_header('Cache-Control','no-store')
            self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; connect-src 'self'; media-src 'self' blob:; frame-ancestors 'none'; object-src 'none'")
            self.end_headers()
            try:self.wfile.write(raw)
            except (BrokenPipeError,ConnectionResetError):pass
        def do_GET(self):
            if not self.valid():return self.reply(403,{'error':'Localhost only'})
            asset=assets.get(urlsplit(self.path).path)
            if not asset:return self.reply(404,{'error':'Not found'})
            name,kind=asset;return self.reply(200,(web/name).read_bytes(),kind)
        def do_POST(self):
            if not self.valid() or self.headers.get('Origin') not in allowed:return self.reply(403,{'error':'Same-origin test action required'})
            if self.path not in ('/prepare','/frame','/interrupt','/played','/stop','/save','/readiness'):
                return self.reply(404,{'error':'Not found'})
            future=None
            try:
                n=int(self.headers.get('Content-Length','0'))
                if not 0<n<=80000:raise ValueError('Bounded test action required')
                body=json.loads(self.rfile.read(n))
                if not isinstance(body,dict):raise ValueError('Expected test action')
                future=asyncio.run_coroutine_threadsafe(lab.action(self.path,body),loop)
                result=future.result(timeout=35 if self.path=='/prepare' else 6)
                return self.reply(200,result)
            except TimeoutError:
                if future:future.cancel()
                return self.reply(503,{'error':'Test action timed out. Stop and save this attempt.'})
            except Exception as exc:
                message=str(exc) if isinstance(exc,ValueError) else 'Test action failed. Stop and save this attempt.'
                return self.reply(400,{'error':message})
    return Handler


async def serve(port):
    store=Store('.tavi/simulation/simulation.sqlite3');lab=NativeLab(store)
    loop=asyncio.get_running_loop();server=ThreadingHTTPServer(('127.0.0.1',port),handler(lab,loop,port))
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    watchdog=asyncio.create_task(lab.watchdog());done=asyncio.Event()
    for sig in (signal.SIGINT,signal.SIGTERM):loop.add_signal_handler(sig,done.set)
    print(f'Adult native reference: http://127.0.0.1:{port}/ · microphone off',flush=True)
    try:await done.wait()
    finally:
        watchdog.cancel();await asyncio.gather(watchdog,return_exceptions=True)
        for session in lab.sessions.values():await session.stop()
        await asyncio.to_thread(server.shutdown);server.server_close();store.close()


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--port',type=int,default=8768)
    asyncio.run(serve(parser.parse_args().port))

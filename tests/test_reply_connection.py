"""Exercise real SDK/HTTP EOF semantics on loopback, without a paid provider."""
import asyncio
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading
import unittest

import httpx
from openai import AsyncOpenAI, DefaultAsyncHttpxClient

from tavi.conversation_providers import PaidText
from tavi.storage import Store


class ConnectionTests(unittest.IsolatedAsyncioTestCase):
    async def test_drained_sdk_stream_reuses_socket_and_keeps_completion_guard(self):
        peers=[]
        class Handler(BaseHTTPRequestHandler):
            protocol_version='HTTP/1.1'
            def log_message(self,*args):pass
            def do_POST(self):
                self.rfile.read(int(self.headers['Content-Length']))
                peers.append(self.client_address)
                text='A little rocket.'
                events=[{'type':'response.output_text.delta','delta':text},
                    {'type':'response.completed','response':{'id':'test-response','status':'completed',
                    'output':[{'type':'message','id':'test-message','role':'assistant','content':[
                        {'type':'output_text','text':text,'annotations':[]}]}],
                    'usage':{'input_tokens':100,'output_tokens':20,'total_tokens':120}}}]
                body=''.join('event: '+e['type']+'\ndata: '+json.dumps(e)+'\n\n' for e in events).encode()
                self.send_response(200);self.send_header('Content-Type','text/event-stream')
                self.send_header('Content-Length',str(len(body)));self.end_headers()
                self.wfile.write(body);self.wfile.flush()
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        store=Store()
        transport=DefaultAsyncHttpxClient(limits=httpx.Limits(keepalive_expiry=120),trust_env=False)
        client=AsyncOpenAI(api_key='local-test-only',base_url=f'http://127.0.0.1:{server.server_port}/v1',
                           max_retries=0,timeout=2,http_client=transport)
        provider=PaidText(store,client,drain_stream=True)
        try:
            for _ in range(2):
                text=''.join([part async for part in provider.stream_reply([{'role':'user','content':'A story'}])])
                self.assertEqual(text,'A little rocket.')
            self.assertEqual(len(peers),2)
            self.assertEqual(peers[0],peers[1],'SDK must consume HTTP EOF to release a reusable socket')
            self.assertEqual(provider.completed,2)
            self.assertEqual(store.used_micro_usd(),330)
        finally:
            await provider.close();store.close()
            await asyncio.to_thread(server.shutdown);server.server_close();thread.join(1)

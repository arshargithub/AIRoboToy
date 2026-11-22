"""Static microphone-free design preview. No profile, model or cloud imports."""
import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

WEB = Path(__file__).parent/'web'
ASSETS = {'/': ('adventure-preview.html', 'text/html; charset=utf-8'),
          '/adventure-preview.css': ('adventure-preview.css', 'text/css'),
          '/adventure-state.js': ('adventure-state.js', 'text/javascript'),
          '/adventure-preview.js': ('adventure-preview.js', 'text/javascript')}


def handler(port):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):pass
        def reply(self, status, raw, mime='application/json'):
            self.send_response(status)
            for name, value in {'Content-Type': mime, 'Content-Length': str(len(raw)),
                'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff',
                'Permissions-Policy': 'microphone=(), camera=(), geolocation=()',
                'Content-Security-Policy': "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'none'; media-src 'none'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'none'"}.items():
                self.send_header(name, value)
            self.end_headers();self.wfile.write(raw)
        def do_GET(self):
            if self.headers.get('Host') not in {f'127.0.0.1:{port}', f'localhost:{port}'}:
                return self.reply(403, b'{"error":"Local preview only"}')
            if self.path == '/api/health':
                return self.reply(200, json.dumps({'preview': True, 'microphone': False,
                    'models': False, 'cloud': False, 'real_profiles': False}).encode())
            if self.path not in ASSETS:return self.reply(404, b'{"error":"Not found"}')
            file, mime = ASSETS[self.path]
            self.reply(200, (WEB/file).read_bytes(), mime)
        def do_POST(self):self.reply(405, b'{"error":"This preview cannot accept recordings or profiles"}')
        do_PUT = do_DELETE = do_POST
    return Handler


def main():
    parser = argparse.ArgumentParser();parser.add_argument('--port', type=int, default=8781)
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:parser.error('Invalid port')
    server = ThreadingHTTPServer(('127.0.0.1', args.port), handler(args.port))
    print(f'Microphone-free adventure preview: http://127.0.0.1:{args.port}/', flush=True)
    try:server.serve_forever()
    finally:server.server_close()


if __name__ == '__main__':main()

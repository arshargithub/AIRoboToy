"""Loopback-only owner review of frozen fictional memory reply wording.

No microphone, model, voice profile or cloud API. This records product feedback,
not a scored semantic experiment or memory-engine acceptance.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import tempfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from experiments.memory.runtime import ROOT, SSD, require_ssd
from tavi.experiment_workflow import digest

EXAMPLES = ROOT/'experiments/memory/owner-style-examples-v1.json'
WEB = ROOT/'tavi/web'
RATINGS = {'natural', 'stiff', 'unclear'}
DECISIONS = {'acceptable', 'warmer', 'unsure'}


def validate_review(body, examples):
    required = {'id', 'ratings', 'notes', 'decision', 'examples_sha256'}
    if not isinstance(body, dict) or not required <= set(body) or set(body) - required - {'comments'}:
        raise ValueError('The review could not be read. Please try saving again.')
    if not isinstance(body['id'], str) or not re.fullmatch(r'[a-f0-9-]{36}', body['id']):
        raise ValueError('Invalid review session.')
    if body['examples_sha256'] != digest(EXAMPLES):
        raise ValueError('The examples changed. Reload this page before reviewing them.')
    keys = {e['id'] for e in examples['examples']}
    ratings = {'A','B','C','none','tie'} if examples.get('review_kind') == 'companion' else RATINGS
    if (not isinstance(body['ratings'], dict) or not set(body['ratings']) <= keys
            or any(v not in ratings for v in body['ratings'].values())):
        raise ValueError('Choose one response for each example.')
    comments = body.get('comments', {})
    if (not isinstance(comments, dict) or not set(comments) <= keys
            or any(not isinstance(v, str) or len(v) > 2000 for v in comments.values())):
        raise ValueError('Keep each example response below 2,000 characters.')
    answered = set(body['ratings']) | {k for k, v in comments.items() if v.strip()}
    if not isinstance(body['notes'], str) or len(body['notes']) > 4000:
        raise ValueError('Please keep your note below 4,000 characters.')
    if body['decision'] not in DECISIONS | {None}:
        raise ValueError('Choose one overall response.')
    if body['decision'] and answered != keys:
        raise ValueError('Please finish every example first.')
    return bool(body['decision'])


def save_review(body, examples, directory):
    complete = validate_review(body, examples)
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    if directory.is_symlink():raise ValueError('Review folder must be local storage.')
    record = {**body, 'complete': complete, 'review_kind': examples.get('review_kind','owner_style_feedback'),
              'scope': examples['scope'], 'source_run': examples['source_run'],
              'source_observations_sha256': examples['observations_sha256'],
              'implementation_sha256': {str(p.relative_to(ROOT)): digest(p) for p in
                  [ROOT/'tavi/memory_review.py', WEB/'memory-review.html', WEB/'memory-review.js']}}
    encoded = json.dumps(record, indent=2).encode()
    sha = hashlib.sha256(encoded).hexdigest()
    target = directory/(body['id']+'-'+sha[:16]+'.json')
    # Each revision is retained; a retry with identical content is idempotent.
    if not target.exists():
        fd, name = tempfile.mkstemp(dir=directory, prefix='.pending-')
        try:
            with os.fdopen(fd, 'wb') as stream:
                stream.write(encoded);stream.flush();os.fsync(stream.fileno())
            os.replace(name, target)
        finally:
            if os.path.exists(name):os.unlink(name)
    return {'saved': True, 'complete': complete, 'id': body['id'], 'revision': sha}


def serve(port=8769, *, qa=False, examples_path=None):
    global EXAMPLES
    if examples_path is not None:
        EXAMPLES = Path(examples_path).resolve()
        EXAMPLES.relative_to(ROOT/'experiments/memory')
    require_ssd()
    examples = json.loads(EXAMPLES.read_text())
    if digest(Path(examples['source_run'])/'observations.json') != examples['observations_sha256']:
        raise ValueError('Source evidence changed')
    kind = 'companion-style' if examples.get('review_kind') == 'companion' else 'memory-style'
    directory = ROOT/'.tavi/qa'/kind if qa else SSD/'owner-reviews'/kind
    token = secrets.token_urlsafe(32)
    allowed_hosts = {f'127.0.0.1:{port}', f'localhost:{port}'}
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):pass
        def send(self, status, content, kind='application/json'):
            raw = json.dumps(content).encode() if kind == 'application/json' else content
            self.send_response(status);self.send_header('Content-Type', kind+'; charset=utf-8')
            self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff')
            self.send_header('Content-Security-Policy',"default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'")
            self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
        def valid_host(self):return self.headers.get('Host') in allowed_hosts
        def do_GET(self):
            if not self.valid_host():self.send(403,{'error':'Use the local review page.'});return
            path=self.path.split('?')[0]
            if path == '/api/examples':
                self.send(200,{**examples,'token':token,'examples_sha256':digest(EXAMPLES)});return
            files={'/':'memory-review.html','/memory-review.js':'memory-review.js'}
            if path not in files:self.send(404,{'error':'Page not found.'});return
            self.send(200,(WEB/files[path]).read_bytes(),'text/html' if path=='/' else 'text/javascript')
        def do_POST(self):
            if (not self.valid_host() or self.path != '/api/review'
                    or self.headers.get('X-Review-Token') != token
                    or self.headers.get('Origin') not in {f'http://{h}' for h in allowed_hosts}):
                self.send(403,{'error':'Reload the local review page and try again.'});return
            try:
                require_ssd()
                size=int(self.headers.get('Content-Length','0'))
                if not 0<size<=80000:raise ValueError('Review is too large.')
                result=save_review(json.loads(self.rfile.read(size)),examples,directory)
                self.send(200,result)
            except (ValueError, OSError, RuntimeError) as exc:
                self.send(400,{'error':str(exc)+' Your choices are still on this page. Reconnect the external drive if needed, then retry.'})
    print(json.dumps({'ready':True,'url':f'http://127.0.0.1:{port}/','microphone':False,'cloud':False}),flush=True)
    ThreadingHTTPServer(('127.0.0.1',port),Handler).serve_forever()


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--port',type=int,default=8769)
    parser.add_argument('--qa',action='store_true')
    parser.add_argument('--examples')
    args=parser.parse_args();serve(args.port,qa=args.qa,examples_path=args.examples)

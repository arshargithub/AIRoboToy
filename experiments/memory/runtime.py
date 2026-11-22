"""External-drive memory qualification utilities; never operates on AWS.

This is experiment infrastructure, not Paprika's production memory interface.
Only the broker receives the real inference credential. Engines receive a
run-specific loopback token. Embeddings are always computed locally.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
SSD = Path('/Volumes/MovieFactorySSD/PaprikaMemory')
MODEL = 'gpt-5.4-mini-2026-03-17'
CAPACITY_MODEL = 'gpt-5.4-2026-03-05'
# USD per million tokens = micro-USD per token; cached discounts ignored.
MODEL_RATES = {MODEL: (.75, 4.5), CAPACITY_MODEL: (2.5, 15.)}
EMBEDDING = 'BAAI/bge-small-en-v1.5'


def require_ssd():
    # A missing volume must never create a lookalike internal-drive folder.
    if not Path('/Volumes/MovieFactorySSD').is_mount() or not SSD.is_dir():
        raise RuntimeError('Mount MovieFactorySSD before starting memory services')
    return SSD


def engine_environment():
    """A fresh environment, excluding cloud credentials and URL overrides."""
    env = {key: os.environ[key] for key in ('PATH', 'HOME', 'USER', 'TMPDIR', 'LANG') if key in os.environ}
    env.update(HF_HOME=str(SSD/'models/huggingface'), HF_HUB_DISABLE_TELEMETRY='1',
               HF_HUB_DISABLE_IMPLICIT_TOKEN='1', MEM0_TELEMETRY='false',
               HF_HUB_OFFLINE='1',
               GRAPHITI_TELEMETRY_ENABLED='false', TOKENIZERS_PARALLELISM='false',
               PYTHONPATH=str(ROOT), PYTHONUNBUFFERED='1',
               XDG_CACHE_HOME=str(SSD/'cache'))
    return env


class Broker:
    """Fail-closed paid text gateway and free local embedding server.

    Calls are serialized so the global ledger and run limit are checked before
    every upstream send. Failed/ambiguous calls keep their full reservation.
    SDK retries remain metered individually, including engine background work.
    """
    def __init__(self, directory, *, paid=False, maximum_usd=0, maximum_calls=0, capacity_comparison=False, reasoning_comparison=False, project_ceiling_micro_usd=None):
        from tavi.storage import APPROVED_BUDGET_MICRO_USD
        if (project_ceiling_micro_usd is not None and (type(project_ceiling_micro_usd) is not int
                or not 0<=project_ceiling_micro_usd<=APPROVED_BUDGET_MICRO_USD)):
            raise ValueError('Invalid project ceiling')
        self.project_ceiling_micro_usd=project_ceiling_micro_usd
        require_ssd()
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=False, mode=0o700)
        self.token = secrets.token_urlsafe(24)
        self.paid = paid
        if reasoning_comparison and not capacity_comparison:
            raise ValueError("Reasoning comparison requires the full-model allowance")
        self.reasoning_comparison = reasoning_comparison
        self.allowed_models = (MODEL, CAPACITY_MODEL) if capacity_comparison else (MODEL,)
        self.maximum = round(maximum_usd * 1_000_000)
        if not 0 <= self.maximum <= 4_000_000 or not 0 <= maximum_calls <= 1500:
            raise ValueError('Memory qualification exceeds its additional spending/call bounds')
        self.maximum_calls = maximum_calls
        self.calls = 0
        self.lock = threading.Lock()
        self.embedding_lock = threading.Lock()
        self.started = time.monotonic()
        self.events = []
        from fastembed import TextEmbedding
        self.embedding = TextEmbedding(EMBEDDING, cache_dir=str(SSD/'models/fastembed'), threads=2)
        import sys
        sys.path.insert(0, str(ROOT))
        from tavi.storage import Store
        ledger = ROOT/'.tavi/simulation/simulation.sqlite3'
        if not ledger.is_file():
            raise RuntimeError('Existing project-wide spend ledger is required')
        store = Store(ledger)
        self.initial_used = store.used_micro_usd()
        store.close()
        self.prefix = 'memory:' + uuid4().hex + ':'
        # Credentials are resolved only with the explicit paid mode.
        self.key = None
        if paid:
            from tavi.conversation_providers import runtime_key
            self.key = runtime_key()

    def embedding_response(self, body):
        if body.get('model') != EMBEDDING:
            raise ValueError('Only the frozen local embedding model is allowed')
        texts = body['input']
        if isinstance(texts, str):
            texts = [texts]
        if not isinstance(texts, list) or len(texts) > 128 or not all(isinstance(t, str) for t in texts):
            raise ValueError('Embedding input must be bounded text')
        if sum(len(t.encode()) for t in texts) > 250_000:
            raise ValueError('Embedding batch too large')
        with self.embedding_lock:
            vectors = list(self.embedding.embed(texts))
        return {'object': 'list', 'model': EMBEDDING, 'data': [
            {'object': 'embedding', 'index': i, 'embedding': vector.tolist()}
            for i, vector in enumerate(vectors)], 'usage': {'prompt_tokens': 0, 'total_tokens': 0}}

    def completion(self, engine, body):
        if not self.paid:
            raise PermissionError('Paid inference is disabled for dependency qualification')
        if body.get('model') not in self.allowed_models or body.get('stream', False):
            raise ValueError('Unexpected model or streaming request')
        effort = body.get('reasoning_effort', 'none')
        if effort != 'none':
            if not (getattr(self, 'reasoning_comparison', False) and engine == 'evaluator'
                    and body['model'] == CAPACITY_MODEL and effort == 'low'):
                raise ValueError('Reasoning profile is outside the explicit evaluator-only comparison')
            if any(k in body for k in ('temperature', 'top_p')):
                raise ValueError('Sampling overrides are unavailable in this reasoning profile')
        input_rate, output_rate = MODEL_RATES[body['model']]
        allowed = {'model', 'messages', 'temperature', 'top_p', 'max_tokens', 'max_completion_tokens',
                   'response_format', 'reasoning_effort', 'store', 'stream', 'seed',
                   'frequency_penalty', 'presence_penalty', 'tools', 'tool_choice', 'parallel_tool_calls'}
        if body.keys() - allowed:
            raise ValueError('Unreviewed inference parameters: ' + ','.join(sorted(body.keys()-allowed)))
        request = dict(body)
        limit = request.pop('max_tokens', request.get('max_completion_tokens', 8192))
        if type(limit) is not int or not 1 <= limit <= 16384:
            raise ValueError('Output ceiling exceeds the frozen envelope')
        request.update(max_completion_tokens=limit, reasoning_effort=effort, store=False)
        raw = json.dumps(request, ensure_ascii=False).encode()
        if len(raw) > 160_000:
            raise ValueError('Input exceeds the frozen envelope')
        # Treat UTF-8 bytes plus framing as tokens: conservative upper bound.
        reservation = math.ceil((len(raw)+8192)*input_rate + limit*output_rate)
        with self.lock:
            if not self.paid:
                raise PermissionError('Paid inference has been disabled')
            if self.calls >= self.maximum_calls or time.monotonic()-self.started > 7200:
                raise PermissionError('Pilot call/time bound exhausted')
            from tavi.storage import Store, APPROVED_BUDGET_MICRO_USD
            store = Store(ROOT/'.tavi/simulation/simulation.sqlite3')
            rows = store.db.execute('SELECT COALESCE(SUM(COALESCE(actual,reserved)),0) FROM spending WHERE id LIKE ?',
                                    (self.prefix+'%',)).fetchone()
            if rows[0]+reservation > self.maximum:
                store.close()
                raise PermissionError('Pilot additional spending bound exhausted')
            request_id = self.prefix + str(self.calls)
            ceiling=getattr(self,'project_ceiling_micro_usd',None)
            try:store.reserve(request_id, reservation, min(APPROVED_BUDGET_MICRO_USD,ceiling if ceiling is not None else APPROVED_BUDGET_MICRO_USD))
            except BaseException:store.close();raise
            self.calls += 1
            event = {'id': request_id, 'engine': engine, 'model': body['model'], 'rates_micro_usd': [input_rate, output_rate], 'reserved_micro_usd': reservation,
                     'request_sha256': hashlib.sha256(raw).hexdigest(), 'started_monotonic': time.monotonic()}
            (self.directory/f'{self.calls:04d}-request.json').write_bytes(raw)
            try:
                import httpx
                # No proxy, redirects, alternative host, upload, audio or retry.
                with httpx.Client(timeout=90, trust_env=False, follow_redirects=False) as client:
                    response = client.post('https://api.openai.com/v1/chat/completions',
                        headers={'Authorization': 'Bearer '+self.key, 'Content-Type':'application/json'}, content=raw,
                        extensions={}, )
                result = response.json()
                event['http_status'] = response.status_code
                usage = result.get('usage')
                if usage and 'prompt_tokens' in usage and 'completion_tokens' in usage:
                    amount = math.ceil(usage['prompt_tokens']*input_rate+usage['completion_tokens']*output_rate)
                    store.settle(request_id, amount)
                    event.update(usage=usage, actual_micro_usd=amount)
                (self.directory/f'{self.calls:04d}-response.json').write_text(json.dumps(result))
                if response.status_code != 200:
                    raise RuntimeError('Upstream inference returned HTTP '+str(response.status_code))
                return result
            finally:
                event['elapsed_ms'] = round((time.monotonic()-event['started_monotonic'])*1000)
                self.events.append(event)
                (self.directory/'calls.json').write_text(json.dumps(self.events, indent=2))
                store.close()

    def serve(self, port=8790):
        broker = self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass
            def do_GET(self):
                if self.path == '/health':
                    self.respond(200, {'local': True, 'paid_enabled': broker.paid,
                                       'project_ceiling_micro_usd':getattr(broker,'project_ceiling_micro_usd',None),
                                       'maximum_usd':broker.maximum/1e6,'maximum_calls':broker.maximum_calls,
                                       'embedding': EMBEDDING, 'dimensions':384, 'calls':broker.calls, 'allowed_models':broker.allowed_models})
                else:
                    self.respond(404, {'error': {'message': 'Unknown route'}})
            def respond(self, status, body):
                content = json.dumps(body).encode()
                self.send_response(status)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(content)))
                self.end_headers()
                self.wfile.write(content)
            def do_POST(self):
                try:
                    if self.headers.get('Authorization') != 'Bearer '+broker.token:
                        raise PermissionError('Invalid local experiment token')
                    if self.path == '/control/disable-paid':
                        with broker.lock:
                            broker.paid=False
                            self.respond(200,{'disabled':True,'calls':broker.events})
                        return
                    size = int(self.headers.get('Content-Length', '0'))
                    if not 0 < size <= 200_000:
                        raise ValueError('Invalid request size')
                    body = json.loads(self.rfile.read(size))
                    parts = self.path.strip('/').split('/')
                    if len(parts) < 3 or parts[0] not in ('hindsight','graphiti','mem0','sqlite','evaluator') or parts[1] != 'v1':
                        raise ValueError('Unexpected route')
                    if parts[2:] == ['embeddings']:
                        value = broker.embedding_response(body)
                    elif parts[2:] == ['chat','completions']:
                        value = broker.completion(parts[0],body)
                    else:
                        raise ValueError('Unexpected route')
                    self.respond(200, value)
                except Exception as exc:
                    self.respond(400, {'error': {'message': str(exc), 'type': type(exc).__name__}})
        server = ThreadingHTTPServer(('127.0.0.1',port),Handler)
        config = {'base_url':f'http://127.0.0.1:{port}', 'token':self.token,
                  'pid':os.getpid(), 'paid':self.paid, 'allowed_models':self.allowed_models, 'directory':str(self.directory)}
        path = SSD/'private-config/broker.json'
        path.write_text(json.dumps(config));path.chmod(0o600)
        print(json.dumps({'ready':True,'local_embedding':EMBEDDING,'paid':self.paid,'port':port}),flush=True)
        server.serve_forever()


def hindsight_server():
    require_ssd()
    broker = json.loads((SSD/'private-config/broker.json').read_text())
    db = json.loads((SSD/'private-config/postgres.json').read_text())
    os.environ.update({
        # Background workers also read config directly; bind them to the same
        # explicit SSD database as the API engine, rather than default pg0.
        'HINDSIGHT_API_DATABASE_URL':db['uri'],
        'HINDSIGHT_API_SKIP_LLM_VERIFICATION':'true',
        'HINDSIGHT_API_EMBEDDINGS_PROVIDER':'openai',
        'HINDSIGHT_API_EMBEDDINGS_OPENAI_API_KEY':broker['token'],
        'HINDSIGHT_API_EMBEDDINGS_OPENAI_MODEL':EMBEDDING,
        'HINDSIGHT_API_EMBEDDINGS_OPENAI_BASE_URL':broker['base_url']+'/hindsight/v1',
        'HINDSIGHT_API_EMBEDDINGS_OPENAI_DIMENSIONS':'384',
        'HINDSIGHT_API_RERANKER_PROVIDER':'onnx',
        'HINDSIGHT_API_LLM_MAX_RETRIES':'0',
        'HINDSIGHT_API_LLM_REASONING_EFFORT':'none',
        'HINDSIGHT_API_RETAIN_MAX_COMPLETION_TOKENS':'8192',
        'HINDSIGHT_API_OTEL_TRACES_ENABLED':'false',
        'HINDSIGHT_API_LLM_TRACE_ENABLED':'false',
        'HINDSIGHT_API_AUDIT_LOG_ENABLED':'false',
    })
    # Use the API library directly. The slim meta-package deliberately omits
    # the legacy `hindsight.Server` convenience wrapper and its heavy extras.
    from hindsight_api import MemoryEngine
    from hindsight_api.api import create_app
    import uvicorn
    memory = MemoryEngine(db_url=db['uri'],memory_llm_provider='openai',
        memory_llm_api_key=broker['token'],memory_llm_model=MODEL,
        memory_llm_base_url=broker['base_url']+'/hindsight/v1')
    app = create_app(memory=memory,mcp_api_enabled=False,initialize_memory=True)
    uvicorn.run(app,host='127.0.0.1',port=8791,log_level='warning')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('role',choices=['broker','hindsight'])
    parser.add_argument('--directory')
    parser.add_argument('--paid',action='store_true')
    parser.add_argument('--maximum-usd',type=float,default=0)
    parser.add_argument('--maximum-calls',type=int,default=0)
    parser.add_argument('--capacity-comparison', action='store_true')
    parser.add_argument('--reasoning-comparison', action='store_true')
    args = parser.parse_args()
    if args.role == 'broker':
        Broker(args.directory,paid=args.paid,maximum_usd=args.maximum_usd,
               maximum_calls=args.maximum_calls, capacity_comparison=args.capacity_comparison,
               reasoning_comparison=args.reasoning_comparison).serve()
    else:
        hindsight_server()

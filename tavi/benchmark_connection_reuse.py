"""Synthetic text-only network reuse screen; never capture or upload audio."""
import argparse
import asyncio
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import time

import httpx
from openai import AsyncOpenAI, DefaultAsyncHttpxClient

from .benchmark_reply_overlap import PROMPTS
from .conversation_providers import MODEL, PaidText, REQUEST_RESERVATION, runtime_key
from .storage import Store


async def run(drain=False):
    protocol=Path('experiments/asr-mlx/connection-drain-protocol.json' if drain else 'experiments/asr-mlx/connection-protocol.json')
    plan=json.loads(protocol.read_text()); assert plan['model']==MODEL
    folder=Path('.tavi/connection-reuse')/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    folder.mkdir(parents=True)
    store=Store('.tavi/simulation/simulation.sqlite3')
    initial=store.used_micro_usd(); ceiling=initial+12*REQUEST_RESERVATION
    report={'protocol':plan,'protocol_sha256':hashlib.sha256(protocol.read_bytes()).hexdigest(),
            'initial_spent_reserved_usd':initial/1e6,'rows':[],'completed':False}
    active={}
    def hook_for(variant):
        async def hook(request):
            row=active[variant]
            async def trace(name, info):
                if name.startswith(('connection.connect_tcp.','connection.start_tls.')):
                    row['connection_events'].append({'name':name,'at_ms':(time.perf_counter()-row['_start'])*1000})
            request.extensions['trace']=trace
        return hook
    providers={}
    for variant,expiry in [('baseline',5),('reuse',120)]:
        http=DefaultAsyncHttpxClient(limits=httpx.Limits(max_connections=4,max_keepalive_connections=2,keepalive_expiry=expiry),
                                    event_hooks={'request':[hook_for(variant)]})
        client=AsyncOpenAI(api_key=runtime_key(),base_url='https://api.openai.com/v1',max_retries=0,timeout=18,http_client=http)
        providers[variant]=PaidText(store,client,drain_stream=drain and variant=='reuse')
    def save():
        report['final_spent_reserved_usd']=store.used_micro_usd()/1e6
        (folder/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    try:
        for n,(case,prompt) in enumerate(PROMPTS):
            if n: await asyncio.sleep(7)
            for variant in (('baseline','reuse') if n%2==0 else ('reuse','baseline')):
                if store.used_micro_usd()+REQUEST_RESERVATION>ceiling:raise ValueError('Pilot budget exhausted')
                row={'pair':n,'cold_control':n==0,'case':case,'variant':variant,'text':'','deltas':[],
                     'connection_events':[],'_start':time.perf_counter()}
                active[variant]=row
                async for delta in providers[variant].stream_reply([{'role':'user','content':prompt}]):
                    row['text']+=delta
                    row['deltas'].append({'at_ms':(time.perf_counter()-row['_start'])*1000,'characters':len(delta)})
                row['text_completed_ms']=(time.perf_counter()-row.pop('_start'))*1000
                report['rows'].append(row);save()
                print(n,variant,'first',round(row['deltas'][0]['at_ms']),'complete',round(row['text_completed_ms']),
                      'connect',len(row['connection_events']),flush=True)
        report['completed']=True
    finally:
        save()
        for provider in providers.values():await provider.close()
        store.close()
    print(str(folder/'report.json'),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--drain',action='store_true')
    asyncio.run(run(parser.parse_args().drain))

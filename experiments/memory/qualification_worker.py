"""Four-engine qualification adapter with common recoverable publication.

Never silently upgrades the pilot's old databases. All generation directories
are newly created under this run. Native summaries are exposed separately and
not blended into the controlled fact-retrieval track.
"""
import asyncio
import fcntl
import json
import os
from pathlib import Path
import sys
import time
from uuid import uuid4

from experiments.memory.recovery import Journal
from experiments.memory.worker import Worker
from experiments.memory.structured import StructuredFacts
from experiments.memory.runtime import require_ssd


class Coordinator:
    def __init__(self,engine,directory):
        require_ssd()
        self.engine=engine;self.directory=Path(directory);self.directory.mkdir(parents=True,exist_ok=True)
        self.lock=open(self.directory/'owner.lock','a')
        fcntl.flock(self.lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        self.journal=Journal(self.directory);self.workers={}

    async def worker(self,scope,generation):
        key=(scope,generation)
        if key not in self.workers:
            worker=Worker(self.engine,self.directory/(scope+'-'+generation))
            worker.observation_scopes='shared'  # Still one audience per bank.
            await worker.initialize()
            if self.engine=='sqlite':
                worker.structured=StructuredFacts(worker.db,worker.embed,worker.base,worker.token)
            self.workers[key]=worker
        return self.workers[key]

    async def rebuild(self,scope,people,crash=None):
        previous=self.journal.generation(scope)[0]
        generation='g'+uuid4().hex
        worker=await self.worker(scope,generation)
        results=[]
        for episode in self.journal.sources(scope):
            results.append(await worker.ingest(episode,people))
        if crash=='before_publish':os._exit(78)
        self.journal.publish(scope,generation)
        old=self.workers.pop((scope,previous),None)
        if old:await old.close()
        elif self.engine=='graphiti':
            # After a hard parent crash the Unix-socket child may survive.
            # Verify its actual configured directory before stopping it.
            retire_graph(self.directory/(scope+'-'+previous))
        return {'generation':generation,'replayed':len(results),'results':results,
                'quarantined_generations_retained':True}

    async def ingest(self,episode,people,crash=None):
        intent=self.journal.prepare(episode)
        if intent['duplicate']:
            # A replay after a crash may be duplicate in the canonical journal
            # while its native write is unresolved. Do not return false success.
            if self.journal.generation(intent['scope'])[1]:
                return {'duplicate_source':True,'recovery':await self.rebuild(intent['scope'],people,crash)}
            return intent
        if crash=='before_dispatch':os._exit(78)
        if intent['requires_rebuild']:
            return {'recovery':await self.rebuild(intent['scope'],people,crash)}
        generation,_=self.journal.generation(intent['scope'])
        worker=await self.worker(intent['scope'],generation)
        result=await worker.ingest(episode,people)
        if crash in ('after_native','before_publish'):os._exit(78)
        self.journal.publish(intent['scope'],generation)
        return result

    async def recover(self,people):
        results=[]
        for scope in self.journal.pending():results.append(await self.rebuild(scope,people))
        return {'recovered':results}

    async def delete(self,sid,people,crash=None):
        intent=self.journal.tombstone(sid)
        if crash=='after_tombstone':os._exit(78)
        if not self.journal.generation(intent['scope'])[1]:return intent
        return await self.rebuild(intent['scope'],people,crash)

    async def query(self,question,people):
        start=time.monotonic();native=[];scopes=[]
        for scope,generation in self.journal.readable(question['audience_ids']):
            worker=await self.worker(scope,generation)
            result=await worker.query(question,people)
            native.extend(result['native_context']);scopes.append(scope)
        return {'native_context':native,'scopes_searched':scopes,
                'retrieval_ms':(time.monotonic()-start)*1000}

    async def profiles(self,question,people):
        began=time.monotonic();blocks=[]
        for scope,generation in self.journal.readable(question['audience_ids']):
            w=await self.worker(scope,generation);namespace=w.namespace(scope.split('-'))
            if self.engine=='hindsight':
                result=await w.client.arecall(bank_id=namespace,query=question['text'],types=['observation'],
                    max_tokens=1500,budget='low',include_source_facts=True,max_source_facts_tokens=1500,
                    query_timestamp=question['at'])
                block={'representation':'native_observations','value':result.model_dump(mode='json')}
            elif self.engine=='graphiti':
                from graphiti_core.nodes import EntityNode
                nodes=await EntityNode.get_by_group_ids(w.client.driver.clone(database=namespace),[namespace],limit=1000)
                block={'representation':'native_entity_summaries','value':[
                    {'id':n.uuid,'name':n.name,'summary':n.summary} for n in nodes],
                    'limitation':'Entity summaries do not expose full per-claim episode lineage'}
            elif self.engine=='mem0':
                value=await asyncio.to_thread(w.mem0(scope).get_all,filters={'user_id':namespace},top_k=1000)
                block={'representation':'native_memory_records_no_separate_OSS_profile','value':value,
                    'limitation':'Latest metadata is not a complete support set'}
            else:
                block={'representation':'deterministic_three_session_choices','value':w.structured.profiles()}
            blocks.append({'scope':scope,**block})
        return {'blocks':blocks,'elapsed_ms':(time.monotonic()-began)*1000}

    async def close(self):
        for worker in self.workers.values():await worker.close()
        self.journal.close();self.lock.close()


async def main():
    coordinator=Coordinator(sys.argv[1],sys.argv[2])
    for line in sys.stdin:
        try:
            r=json.loads(line);op=r['op']
            if op=='initialize':value={'ready':True,'pending_scopes':coordinator.journal.pending()}
            elif op=='ingest':value=await coordinator.ingest(r['episode'],r['people'],r.get('crash'))
            elif op=='recover':value=await coordinator.recover(r['people'])
            elif op=='query':value=await coordinator.query(r['question'],r['people'])
            elif op=='profiles':value=await coordinator.profiles(r['question'],r['people'])
            elif op=='delete':value=await coordinator.delete(r['source_id'],r['people'],r.get('crash'))
            elif op=='close':
                await coordinator.close();print(json.dumps({'ok':True,'result':{'closed':True}}),flush=True);return
            else:raise ValueError('Unknown operation')
            print(json.dumps({'ok':True,'result':value},default=str),flush=True)
        except Exception as exc:
            import traceback
            traceback.print_exc(file=sys.stderr)
            print(json.dumps({'ok':False,'error':type(exc).__name__+': '+str(exc)}),flush=True)


def retire_graph(directory):
    settings=Path(directory)/'falkor.rdb.settings'
    if not settings.exists():return False
    config=json.loads(settings.read_text())
    if Path(config['dbdir']).resolve()!=Path(directory).resolve():
        raise RuntimeError('Refusing to stop an unrelated graph directory')
    import redis
    client=redis.Redis(unix_socket_path=config['unixsocket'],socket_timeout=2)
    try:
        client.ping()
    except redis.ConnectionError:return False
    actual=client.config_get('dir').get('dir')
    if isinstance(actual,bytes):actual=actual.decode()
    if actual is None:actual=client.config_get('dir').get(b'dir',b'').decode()
    if Path(actual).resolve()!=Path(directory).resolve():raise RuntimeError('Graph socket now belongs to another database')
    client.shutdown(save=True);client.close();return True


if __name__=='__main__':asyncio.run(main())

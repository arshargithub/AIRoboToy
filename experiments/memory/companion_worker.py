"""Persistent native workers for a bounded companion-usefulness comparison."""
import asyncio,json,sys,time
from experiments.memory.worker import Worker
from experiments.memory.companion_contract import MISSION,reflection_scope


async def main():
    worker=Worker(sys.argv[1],sys.argv[2]);worker.observation_scopes='shared'
    initialized_banks=set()
    for line in sys.stdin:
        try:
            r=json.loads(line);op=r['op']
            if op=='initialize':value=await worker.initialize()
            elif op=='ingest':
                if worker.engine=='hindsight':
                    bank=worker.namespace(r['episode']['audience_ids'])
                    if bank not in initialized_banks:
                        await worker.client.acreate_bank(bank_id=bank,reflect_mission=MISSION)
                        initialized_banks.add(bank)
                value=await worker.ingest(r['episode'],r['people'])
            elif op=='query':value=await worker.query(r['question'],r['people'])
            elif op=='reflect':
                bank=reflection_scope(worker,r['question'],r['people'])
                if bank is None:raise ValueError('Unknown identity cannot reflect personal memory')
                started=time.monotonic()
                result=await worker.client.areflect(bank_id=bank,
                    query=r['question']['text'],context=json.dumps(r['task']),budget='low',
                    max_tokens=512,include_facts=True,include_tool_calls=True,
                    reflect_search_observations_max_tokens=1500,
                    reflect_search_mental_models_max_tokens=1500)
                value={'native':result.model_dump(mode='json'),'elapsed_ms':(time.monotonic()-started)*1000}
            elif op=='close':
                await worker.close();print(json.dumps({'ok':True,'result':{'closed':True}}),flush=True);return
            else:raise ValueError('Unknown operation')
            print(json.dumps({'ok':True,'result':value},default=str),flush=True)
        except Exception as exc:
            import traceback;traceback.print_exc(file=sys.stderr)
            print(json.dumps({'ok':False,'error':type(exc).__name__+': '+str(exc)}),flush=True)


if __name__=='__main__':asyncio.run(main())

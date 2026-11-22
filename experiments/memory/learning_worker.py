"""Native automatic-learning verification worker with explicit delete control."""
import asyncio,json,sys
from experiments.memory.guarded_worker import GuardedWorker
async def main():
    import argparse
    from tavi.memory_generation import validate_worker_realm
    parser=argparse.ArgumentParser();parser.add_argument('engine');parser.add_argument('directory');parser.add_argument('--source-realm',choices=['fixture','household'],default='fixture');args=parser.parse_args()
    validate_worker_realm(args.directory,args.source_realm)
    w=GuardedWorker(args.engine,args.directory);w.observation_scopes='shared';w.source_realm=args.source_realm
    for line in sys.stdin:
        try:
            r=json.loads(line);op=r['op']
            if op=='initialize':v=await w.initialize()
            elif op=='ingest':v=await w.ingest(r['episode'],r['people'])
            elif op=='query':v=await w.query(r['question'],r['people'])
            elif op=='delete':v=await w.delete(r['source_id'])
            elif op=='inventory':
                from tavi.memory_projection import verified_inventory
                v=await verified_inventory(w,r['people'])
            elif op=='close':
                await w.close();print(json.dumps({'ok':True,'result':{'closed':True}}),flush=True);return
            else:raise ValueError('Unknown operation')
            print(json.dumps({'ok':True,'result':v}),flush=True)
        except Exception as e:print(json.dumps({'ok':False,'error':type(e).__name__+': '+str(e)}),flush=True)
if __name__=='__main__':asyncio.run(main())

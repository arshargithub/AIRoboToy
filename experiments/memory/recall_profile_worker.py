"""Read-only per-query profile; fictional development bank, no ingestion."""
import asyncio,cProfile,io,json,pstats,sys,time
from experiments.memory.guarded_worker import GuardedWorker
async def main():
 w=GuardedWorker('hindsight',sys.argv[2]);w.observation_scopes='shared'
 for line in sys.stdin:
  try:
   r=json.loads(line)
   if r['op']=='initialize':value=await w.initialize()
   elif r['op']=='query':
    p=cProfile.Profile();start=time.monotonic();p.enable()
    try:value=await w.query(r['question'],r['people'])
    finally:p.disable()
    value['profiled_wall_ms']=(time.monotonic()-start)*1000
    output=io.StringIO();pstats.Stats(p,stream=output).strip_dirs().sort_stats('cumulative').print_stats(35)
    value['profile']=output.getvalue()
   elif r['op']=='close':
    await w.close();print(json.dumps({'ok':True,'result':{'closed':True}}),flush=True);return
   else:raise ValueError('Unknown operation')
   print(json.dumps({'ok':True,'result':value}),flush=True)
  except Exception as e:print(json.dumps({'ok':False,'error':type(e).__name__+': '+str(e)}),flush=True)
if __name__=='__main__':asyncio.run(main())

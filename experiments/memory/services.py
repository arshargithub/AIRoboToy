"""Launch only this experiment's explicitly recorded loopback services."""
import argparse
import json
import signal
import subprocess
import time
from datetime import datetime,timezone
from experiments.memory.runtime import SSD,ROOT,engine_environment,require_ssd

# Hindsight1.2.0 multiplies this base by0.5 at low budget. The final
# iteration synthesizes, so six permits observation search, recall, and reply.
REFLECT_BASE_ITERATIONS = 6

def start(maximum_usd,maximum_calls,capacity_comparison=False,reflect_capacity=False,reasoning_comparison=False):
    import httpx
    require_ssd()
    if reasoning_comparison and not capacity_comparison:
        raise ValueError('Reasoning comparison requires the full-model allowance')
    if reflect_capacity and not capacity_comparison:
        raise ValueError('Full reflection requires the explicit capacity gateway allowance')
    path=SSD/'private-config/services.json'
    old=json.loads(path.read_text()) if path.exists() else {}
    if isinstance(old,list):old={entry['role']:entry['pid'] for entry in old}
    for role,pid in old.items():
        if role not in ('broker','hindsight'):raise ValueError('Unrecognized managed service')
        result=subprocess.run(['ps','-p',str(pid),'-o','command='],capture_output=True,text=True)
        if result.returncode==0:
            if 'experiments/memory/runtime.py '+role not in result.stdout:
                raise RuntimeError('Recorded PID belongs to another process; refusing to signal')
            subprocess.run(['kill','-TERM',str(pid)],check=True)
    time.sleep(1)
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    directory=SSD/'runs/gateway'/stamp
    roles={}
    for role,env in [('broker','broker'),('hindsight','hindsight')]:
        args=[str(SSD/'venvs'/env/'bin/python'),str(ROOT/'experiments/memory/runtime.py'),role]
        if role=='broker':args += ['--directory',str(directory),'--paid','--maximum-usd',str(maximum_usd),'--maximum-calls',str(maximum_calls)]
        if role == 'broker' and capacity_comparison: args.append('--capacity-comparison')
        if role == 'broker' and reasoning_comparison: args.append('--reasoning-comparison')
        log=open(SSD/'logs'/(stamp+'-'+role+'.log'),'a')
        env_values=engine_environment()
        if role=='hindsight' and reflect_capacity:
            from experiments.memory.runtime import CAPACITY_MODEL
            env_values.update(HINDSIGHT_API_REFLECT_LLM_MODEL=CAPACITY_MODEL,
                HINDSIGHT_API_REFLECT_MAX_ITERATIONS=str(REFLECT_BASE_ITERATIONS),
                HINDSIGHT_API_REFLECT_MAX_CONTEXT_TOKENS='8192')
        child=subprocess.Popen(args,cwd=ROOT,env=env_values,stdout=log,stderr=log,start_new_session=True)
        roles[role]=child.pid;log.close()
        path.write_text(json.dumps(roles));path.chmod(0o600)
        ready=False
        for _ in range(60):
            if child.poll() is not None:raise RuntimeError(role+' exited during startup')
            try:
                r=httpx.get('http://127.0.0.1:'+('8790' if role=='broker' else '8791')+'/health',timeout=1)
                r.raise_for_status();ready=True;break
            except Exception:time.sleep(.5)
        if not ready:raise RuntimeError(role+' did not become ready')
    print(json.dumps({'ready':True,'roles':roles,'gateway_directory':str(directory),
                      'maximum_usd':maximum_usd,'maximum_calls':maximum_calls}),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--maximum-usd',type=float,required=True);p.add_argument('--maximum-calls',type=int,required=True)
    p.add_argument('--capacity-comparison', action='store_true')
    p.add_argument('--reflect-capacity', action='store_true')
    p.add_argument('--reasoning-comparison', action='store_true')
    a=p.parse_args();start(a.maximum_usd,a.maximum_calls,a.capacity_comparison,a.reflect_capacity,a.reasoning_comparison)

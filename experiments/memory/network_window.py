"""Bounded transport/clock screen; does not prove Wi-Fi or upstream constancy."""
import time


def clock():return {'utc_seconds':time.time(),'monotonic_seconds':time.monotonic()}


def probe():
    import httpx
    start=clock()
    try:
        r=httpx.get('https://api.openai.com/',timeout=3,trust_env=False,follow_redirects=False)
        end=clock();ms=(end['monotonic_seconds']-start['monotonic_seconds'])*1000
        return {'start':start,'end':end,'elapsed_ms':ms,'status':r.status_code,
                'ok':r.status_code<500 and ms<=2000,'authenticated':False}
    except Exception as exc:
        return {'start':start,'end':clock(),'ok':False,'error_type':type(exc).__name__,'authenticated':False}


def qualified(before,after,start,end):
    jump=abs((end['utc_seconds']-start['utc_seconds'])-(end['monotonic_seconds']-start['monotonic_seconds']))
    return {'qualified':bool(before.get('ok') and after.get('ok') and jump<=.5),
            'wall_monotonic_discrepancy_seconds':jump,
            'scope':'No observed boundary-probe failure or clock gap; not proof of stationary network or acoustic latency.'}

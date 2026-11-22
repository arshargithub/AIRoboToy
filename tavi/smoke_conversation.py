"""Synthetic loopback conversation smoke check with simulated endpoint ACKs.

Two bounded cloud text replies are expected. This does not test actual speakers,
AEC, human latency or audible interruption. No human microphone is used.
"""
import asyncio
import argparse
from http.client import HTTPConnection
from io import BytesIO
import json
from pathlib import Path
import time
import wave
from .conversation_providers import MacSpeech


def request(path, data=b'', headers=None, binary=False, method='POST'):
    connection=HTTPConnection('127.0.0.1',8765,timeout=25)
    try:
        connection.request(method,path,body=data,headers=headers or {})
        response=connection.getresponse();raw=response.read()
        if response.status!=200:
            raise ValueError('Local smoke request failed: '+str(response.status)+' '+raw[:200].decode(errors='replace'))
        return raw if binary else json.loads(raw)
    finally:connection.close()


async def fixtures():
    voice=MacSpeech();result={}
    for key,text in [('background','The coffee is on the table.'),('request','Paprika, tell me a short story about a tiny dragon.'),
                     ('followup','Make the dragon blue.'),('goodbye','Goodbye, Paprika.'),('offline','Paprika, are you there?')]:
        audio=await voice.synthesize(text)
        with wave.open(BytesIO(audio.wav)) as wav: result[key]=wav.readframes(wav.getnframes())
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--first-turn-only',action='store_true');args=parser.parse_args()
    clips=asyncio.run(fixtures())
    before=request('/api/conversation/diagnostics',method='GET')['spent_or_reserved_usd']
    started=request('/api/conversation/start',json.dumps({'online':True}),{'Content-Type':'application/json'})
    lease=started['stream_id'];seq=0;next_due=time.perf_counter();rtts=[];slow_frames=[];latest=started['conversation'];responses=[]
    def command(name,body=None):
        return request('/api/conversation/'+name,json.dumps(body or {}),{'Content-Type':'application/json','X-Audio-Stream':lease})
    def frame(pcm=bytes(1024)):
        nonlocal seq,next_due,latest
        wait=next_due-time.perf_counter()
        if wait>0:time.sleep(wait)
        now=time.perf_counter()
        result=request('/api/conversation/frame',pcm,{'Content-Type':'application/octet-stream','X-Audio-Stream':lease,'X-Audio-Sequence':str(seq)})
        elapsed=(time.perf_counter()-now)*1000;rtts.append(elapsed)
        if elapsed>50:slow_frames.append({'sequence':seq,'rtt_ms':elapsed,'notice':result['conversation']['notice']})
        seq+=1;next_due+=.032;latest=result['conversation']
        if latest['spent_or_reserved_usd']-before>.20:raise ValueError('Synthetic test spend exceeded its $0.20 guard')
    def silence(seconds):
        for _ in range(int(seconds/.032)+1):frame()
    def speak(key):
        raw=bytes(11200)+clips[key]+bytes(32000);raw+=bytes(-len(raw)%1024)
        for offset in range(0,len(raw),1024):frame(raw[offset:offset+1024])
    def await_reply():
        deadline=time.perf_counter()+22
        while not latest.get('audio') and time.perf_counter()<deadline:frame()
        assert latest.get('audio'), 'No bounded reply arrived'
        audio=latest['audio'];wave_bytes=request('/api/conversation/audio',headers={'X-Audio-Stream':lease,'X-Response-Id':audio['id']},binary=True,method='GET')
        with wave.open(BytesIO(wave_bytes)) as w:assert w.getnframes()>0
        responses.append({'recognized_synthetic_request':latest['heard'],'synthetic_reply':latest['reply'],'audio_duration_ms':audio['duration_ms']})
        command('started',{'response_id':audio['id']})
        # Simulate the elapsed playback duration, but never output speaker audio.
        silence(audio['duration_ms']/1000+.1)
        command('played',{'response_id':audio['id']})
        silence(.2)
    try:
        speak('background');silence(.5)
        assert latest['engagement']=='idle' and latest['spent_or_reserved_usd']==before, 'Idle speech must not call cloud'
        speak('request');await_reply()
        if not args.first_turn_only:
            speak('followup');await_reply()
            speak('goodbye');await_reply();assert latest['engagement']=='idle'
            online_cost=latest['spent_or_reserved_usd']
            command('online',{'enabled':False});speak('offline');await_reply()
            assert latest['spent_or_reserved_usd']==online_cost, 'Offline reply must not spend'
    finally:
        command('stop')
    final=request('/api/conversation/diagnostics',method='GET')
    result={'scope':'Synthetic inputs and simulated playback ACKs only; not human acoustic acceptance',
            'cloud_requests':sum(m['kind']=='accepted_turn' and m.get('cloud',False) for m in final['metrics']),
            'spent_or_reserved_usd':final['spent_or_reserved_usd'],'incremental_cost_usd':final['spent_or_reserved_usd']-before,
            'frames':seq,'max_rtt_ms':max(rtts),'slow_frames':slow_frames,'responses':responses,'metrics':final['metrics']}
    Path('.tavi/conversation-smoke-first-turn.json' if args.first_turn_only else '.tavi/conversation-smoke.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({k:v for k,v in result.items() if k!='metrics'},indent=2))


if __name__=='__main__':main()

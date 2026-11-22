"""Replay explicitly saved microphone PCM locally; never calls conversation/cloud."""
import argparse
import json
from pathlib import Path
import time
import wave

from .acoustics import Silero
from .live_wake import LiveWake,WhisperDecoder


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('manifest',type=Path)
    args=p.parse_args();manifest=json.loads(args.manifest.read_text());run=manifest['runs'][0]
    with wave.open(run['microphone_wav']) as w:
        if (w.getframerate(),w.getnchannels(),w.getsampwidth())!=(16000,1,2):raise ValueError('Expected saved mono PCM16')
        pcm=w.readframes(w.getnframes())
    engine=LiveWake(Silero(Path('.tavi/models/silero_vad.onnx'),wake_backend='off'),WhisperDecoder(final_model='base.en'))
    events=[];maximum=0;last=time.perf_counter();start=last
    lease=engine.start('hinted')['stream_id']
    try:
        # Pace input to exercise the real one-running/one-pending scheduling bound.
        for seq,offset in enumerate(range(0,len(pcm)+32000,1024)):
            due=start+seq*.032;delay=due-time.perf_counter()
            if delay>0:time.sleep(delay)
            frame=pcm[offset:offset+1024].ljust(1024,b'\0')
            before=time.perf_counter();result=engine.feed(lease,seq,frame);maximum=max(maximum,(time.perf_counter()-before)*1000)
            for e in result['events']:
                events.append(e)
                if e['type']=='recognition' and e['final']:print('Final',e['utterance'],round(e['decode_ms']),'ms:',e['text'],flush=True)
            if time.perf_counter()-last>25:print('Replayed',round(seq*.032),'seconds',flush=True);last=time.perf_counter()
        report={'scope':'Real-time local replay of one saved adult recording, not a fresh session or human acceptance',
                'source_sha256':manifest['source_sha256'],'models':engine.decoder.profiles,'events':events,
                'max_feed_ms':maximum,'fault':engine.fault,'api_spend_usd':0}
        output=args.manifest.with_name('base-final-streaming-replay.json');output.write_text(json.dumps(report,indent=2)+'\n')
        finals=[e for e in events if e['type']=='recognition' and e['final']]
        print('Completed:',len(finals),'finals; max frame work',round(maximum,2),'ms; fault',engine.fault,flush=True)
    finally:engine.stop(lease);engine.close()


if __name__=='__main__':main()

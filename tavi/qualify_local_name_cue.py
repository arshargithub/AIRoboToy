"""Local-only development screen for an early *visual* address candidate.

Uses existing frozen Tiny/LiveWake partials on three bound saved adult windows.
No microphone, speaker or provider; no production/address-gate change. Complete
Turbo confirmation remains the only gate in the integrated native prototype.
"""
import base64
import hashlib
import json
import time
import wave

from .acoustics import Silero
from .addressing import ADDRESS
from .experiment_workflow import ROOT, begin, finish, audit
from .live_wake import LiveWake, WhisperDecoder

MANIFEST='.tavi/local-name-cue-v1/manifest.json'


def run():
    folder,plan=begin('experiments/realtime/local-name-cue-v1.json')
    decoder=engine=None;rows=[];error=None
    try:
        decoder=WhisperDecoder(final_model='tiny.en')
        engine=LiveWake(Silero(ROOT/'.tavi/models/silero_vad.onnx',wake_backend='off'),decoder)
        manifest=json.loads((ROOT/MANIFEST).read_text())
        for case in manifest['cases']:
            with wave.open(str(ROOT/case['wav'])) as w:
                if (w.getframerate(),w.getnchannels(),w.getsampwidth())!=(16000,1,2):raise ValueError('Invalid local test PCM')
                pcm=w.readframes(w.getnframes())
            if hashlib.sha256(pcm).hexdigest()!=case['pcm16_sha256']:raise ValueError('Local input changed')
            # Half-second local silence before/after each exact retained window.
            prefix=16000;pcm=bytes(prefix)+pcm+bytes(32000)
            pcm+=bytes((-len(pcm))%1024)
            lease=engine.start('unhinted')['stream_id'];events=[];started=time.monotonic()
            for sequence,offset in enumerate(range(0,len(pcm),1024)):
                result=engine.feed(lease,sequence,pcm[offset:offset+1024])
                events.extend({**e,'observed_after_clip_start_ms':(time.monotonic()-started)*1000-prefix/32} for e in result['events'])
                time.sleep(max(0,started+(offset+1024)/32000-time.monotonic()))
            # Drain an outstanding final without lying about the source clock.
            deadline=time.monotonic()+3
            while not any(e.get('type')=='recognition' and e.get('final') for e in events):
                if time.monotonic()>deadline:raise ValueError('Local partial/final worker did not drain')
                sequence+=1
                result=engine.feed(lease,sequence,bytes(1024))
                events.extend({**e,'observed_after_clip_start_ms':(time.monotonic()-started)*1000-prefix/32} for e in result['events'])
                time.sleep(.032)
            partials=[e for e in events if e.get('type')=='recognition' and not e.get('final')]
            anchored=[e for e in partials if ADDRESS.match(e['text'])]
            early=[e for e in anchored if e['observed_after_clip_start_ms']<case['speech_end_ms']]
            row={'id':case['id'],'expected_address':case['expected_address'],
                 'partial_count':len(partials),'anchored_partial_count':len(anchored),
                 'anchored_before_speech_end':bool(early),
                 'first_anchored_after_clip_start_ms':anchored[0]['observed_after_clip_start_ms'] if anchored else None,
                 'speech_end_ms':case['speech_end_ms'],'name_end_ms':None,
                 'name_end_latency_500ms_gate':'unknown: no independent name-end label',
                 'events':events}
            rows.append(row)
            engine.stop(lease)
    except Exception as exc:
        error=type(exc).__name__
    finally:
        if engine:engine.close()
        elif decoder:decoder.close()
    metrics={'cases':len(rows),'errors':int(error is not None),
             'positive_with_early_candidate':sum(r['expected_address'] and r['anchored_before_speech_end'] for r in rows),
             'negative_with_candidate':sum(not r['expected_address'] and r['anchored_partial_count']>0 for r in rows)}
    path=folder/'results.json'
    path.write_text(json.dumps({'kind':'local_visual_cue_development_screen','rows':rows,'metrics':metrics,
        'error':error,'profile':getattr(decoder,'profile',None),'cloud_requests':0,
        'limitations':'Three reused windows, one adult/session; weak intent labels from guided task/human ratings, not exact word labels. No name-end label, p95 or false-wake-rate qualification. No live code changed.'},indent=2)+'\n')
    record=finish(folder,metrics,artifacts=[path],completed=error is None,error=error)
    print(json.dumps({'run':str(folder),'decision':record['decision'],'audit':audit(folder)},indent=2))


if __name__=='__main__':run()

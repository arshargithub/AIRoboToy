"""Create fixed synthetic K audio for a cloud API plumbing screen; no upload."""
import asyncio
import audioop
import hashlib
from io import BytesIO
import json
from pathlib import Path
import wave

from .local_speech import LocalSpeech

CASES=[
    ('bridge','Paprika, could we build a bridge for two toy cars?'),
    ('colour','Please make the little boat yellow, then stop.'),
    ('change','Wait, make it a space adventure instead.'),
    ('keys','Change the ending so the penguin finds three keys.'),
    ('pause','Paprika, I was thinking we could make a tiny house.'),
    ('close','Goodbye, Paprika.')]


async def run():
    root=Path('.tavi/synthetic-asr-v1');root.mkdir(parents=True,exist_ok=False)
    voice=LocalSpeech('kokoro-k-mlx');manifest={'origin':'synthetic_K_only','voice':'provisional K',
        'purpose':'Cloud API transport/cost screen; not human or household accuracy.',
        'resampler':'Python3.11 audioop.ratecv mono PCM16 24000 to16000, initial stateNone perclip',
        'cases':[],'files':[]}
    try:
        await voice.prepare()
        for key,text in CASES:
            result=await voice.synthesize(text)
            with wave.open(BytesIO(result.wav)) as w:pcm=w.readframes(w.getnframes())
            converted,_=audioop.ratecv(pcm,2,1,24000,16000,None)
            path=root/(key+'.wav')
            with wave.open(str(path),'wb') as w:
                w.setnchannels(1);w.setsampwidth(2);w.setframerate(16000);w.writeframes(converted)
            duration=len(converted)/32000
            if duration>12:raise ValueError('Synthetic clip exceeds adapter bound')
            manifest['cases'].append({'id':key,'expected':text,'wav':str(path),'duration_seconds':duration})
            manifest['files'].append({'path':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest()})
        (root/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    finally:await voice.close()
    print(json.dumps({'manifest':str(root/'manifest.json'),'clips':len(manifest['cases']),
                      'duration_seconds':sum(c['duration_seconds'] for c in manifest['cases']),'api_requests':0}))


if __name__=='__main__':asyncio.run(run())

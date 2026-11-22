"""Create new synthetic K inputs locally; never opens a microphone or uploads."""
import asyncio
import audioop
import hashlib
from io import BytesIO
import json
import wave

from .experiment_workflow import ROOT
from .local_speech import LocalSpeech

CASES=[('ambient','I wonder what we could build next.'),
       ('fort','Paprika, what is our pretend fort called?'),
       ('story','Tell me a longer story about that fort.'),
       ('change','Wait, make it a space adventure instead.'),
       ('fox',"What is our pretend fox's name?"),('close','Goodbye, Paprika.')]


async def run():
    folder=ROOT/'.tavi/engagement-synth-v1'
    if folder.exists() and any(folder.iterdir()):raise ValueError('Existing synthetic inputs preserved; do not overwrite')
    folder.mkdir(parents=True,exist_ok=True)
    voice=LocalSpeech(backend='kokoro-k-mlx')
    manifest={'origin':'synthetic_K_only','cases':[],'files':[]}
    try:
        await voice.prepare()
        for name,text in CASES:
            speech=await voice.synthesize(text)
            with wave.open(BytesIO(speech.wav)) as w:pcm=w.readframes(w.getnframes())
            pcm,_=audioop.ratecv(pcm,2,1,24000,16000,None)
            path=folder/(name+'.wav')
            with wave.open(str(path),'wb') as w:
                w.setnchannels(1);w.setsampwidth(2);w.setframerate(16000);w.writeframes(pcm)
            manifest['cases'].append({'id':name,'text':text,'wav':str(path.relative_to(ROOT)),
                                      'duration_seconds':len(pcm)/32000})
            manifest['files'].append({'path':str(path.relative_to(ROOT)),
                                       'sha256':hashlib.sha256(path.read_bytes()).hexdigest()})
        (folder/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    finally:await voice.close()
    print(json.dumps({'manifest':str(folder/'manifest.json'),'clips':len(manifest['cases']),'api_requests':0}))


if __name__=='__main__':asyncio.run(run())

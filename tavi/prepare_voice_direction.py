"""Prepare a retained 50% reference, new 35% blend, and voice-design auditions."""
import argparse
import hashlib
import json
from pathlib import Path
import time

from .neural_voice import verify_assets, pcm_wave
from .prepare_voice_audition import PASSAGES, level_match
from .prepare_voice_texture import blend_styles
from .voice_pronunciation import audition_phonemes, PRONUNCIATION, IPA

ROOT=Path('.tavi/voice-direction')


def prepare_blends():
    import numpy as np
    import sherpa_onnx as s
    from piper.phonemize_espeak import EspeakPhonemizer
    ROOT.mkdir(parents=True,exist_ok=True)
    old=json.loads(Path('tavi/web/voice-texture-range-protocol.json').read_text())
    source=verify_assets('kokoro')
    styles=np.fromfile(source/'voices.bin',dtype='<f4').reshape(54,510,256)
    style_path=ROOT/'direction-blends.bin';blend_styles(styles,(.35,.5)).astype('<f4').tofile(style_path)
    settings=s.OfflineTtsConfig(model=s.OfflineTtsModelConfig(kokoro=s.OfflineTtsKokoroModelConfig(
        model=str(source/'model.int8.onnx'),voices=str(style_path),tokens=str(source/'tokens.txt')),
        num_threads=2,provider='cpu'))
    if not settings.validate():raise ValueError('Invalid 35 percent voice configuration')
    engine=s.OfflineTts(settings);phonemizer=EspeakPhonemizer()
    tokens={line.rsplit(' ',1)[0] for line in (source/'tokens.txt').read_text().splitlines() if line}
    trials=[]
    for voice in ('I','K'):
        for case,text in PASSAGES.items():
            start=time.perf_counter()
            if voice=='I' and case=='short_story':
                ref=next(t for t in old['trials'] if t['voice']=='I' and t['case']==case)
                data=Path('.tavi/voice-texture-range',ref['src'].rsplit('/',1)[-1]).read_bytes()
                if hashlib.sha256(data).hexdigest()!=ref['sha256']:raise ValueError('Half-blend reference changed')
                gain=1
            else:
                phonemes=audition_phonemes(phonemizer,text)
                if any(c not in tokens for sent in phonemes for c in sent):raise ValueError('Unknown phoneme')
                config=s.GenerationConfig();config.sid=1 if voice=='I' else 0;config.silence_scale=1
                config.phoneme_codepoints=[[ord(c) for c in sent] for sent in phonemes]
                audio=engine.generate('',config);data,gain=level_match(pcm_wave(audio.samples,audio.sample_rate))
            index=len(trials)+1;path=ROOT/f'sample-{index}.wav';path.write_bytes(data)
            trials.append({'id':f'direction-{index}','voice':voice,'case':case,'text':text,
                'src':f'/voice-direction/sample-{index}.wav','sha256':hashlib.sha256(data).hexdigest(),
                'gain':gain,'original_reference_unchanged':voice=='I' and case=='short_story',
                'pronunciation_override':IPA if case=='greeting' else None,
                'preparation_ms':(time.perf_counter()-start)*1000})
            print(voice+' '+case+': ready',flush=True)
    (ROOT/'blends.json').write_text(json.dumps({'trials':trials,'derived_voices_sha256':hashlib.sha256(style_path.read_bytes()).hexdigest()},indent=2)+'\n')


def assemble():
    blends=json.loads((ROOT/'blends.json').read_text())
    design=json.loads((ROOT/'design.json').read_text())
    expected={(voice,case) for voice in ('L','M') for case in PASSAGES}
    if len(design['trials'])!=4 or {(r['voice'],r['case']) for r in design['trials']}!=expected:
        raise ValueError('Both designed voices need both passages')
    if any(r['text']!=PASSAGES[r['case']] for r in design['trials']):
        raise ValueError('Designed passages must match the blends')
    trials=blends['trials']
    for row in design['trials']:
        data=Path(row['wav']).read_bytes()
        if hashlib.sha256(data).hexdigest()!=row['sha256']:raise ValueError('Designed output changed')
        data,gain=level_match(data);index=len(trials)+1;path=ROOT/f'sample-{index}.wav';path.write_bytes(data)
        trials.append({**{k:v for k,v in row.items() if k not in ('wav','sha256')},
            'id':f'direction-{index}','src':f'/voice-direction/sample-{index}.wav',
            'sha256':hashlib.sha256(data).hexdigest(),'gain':gain})
    plan={'schema_version':1,'id':'paprika-voice-direction-v1','kind':'paprika_voice_character_check',
        'display_order':['I','K','L','M'],
        'voices':{'I':'Retained 50% af_heart / 50% af_nicole','K':'65% af_heart / 35% af_nicole',
                  'L':'Qwen VoiceDesign · youthful, warm and lightly husky',
                  'M':'Qwen VoiceDesign · youthful, confident and lightly raspy'},
        'passages':{'short_story':'Fox story','greeting':'Hello from Paprika'},
        'reference_feedback':{'voice':'I','viable_candidate':True,'accepted':False,
            'requested_change':'Keep the half blend, add 35% donor, and try naturally youthful slightly husky female voice.'},
        'method':'Two retained/derived Kokoro candidates versus natural-language voice design; no added distortion or pitch effects.',
        'design_model':design['model'],'design_settings':design['settings'],
        'pronunciation':{'name':'Paprika','target':PRONUNCIATION,'ipa':IPA,
            'method':'Explicit Kokoro phonemes; natural-language instruction for designed voices. Human listening still required.'},
        'trials':trials,'api_spend_usd':0,'microphone_used':False,
        'limitations':['Voice descriptions are targets, not independently verified vocal traits.',
            'Designed identity consistency across passages and live performance remain unqualified.']}
    Path('tavi/web/voice-direction-protocol.json').write_text(json.dumps(plan,indent=2)+'\n')
    print('Comparison assembled; half-blend story unchanged, greetings target puh-PREE-kuh; no live promotion.')


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--assemble',action='store_true')
    assemble() if p.parse_args().assemble else prepare_blends()


if __name__=='__main__':main()

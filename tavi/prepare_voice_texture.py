"""Audition small Kokoro style blends around the user's preferred voice C.

This explores texture; it does not claim measured raspiness or perceived age.
Uses only installed public presets and fixed synthetic text. Original C audio
and all pinned model assets remain unchanged. No audio postprocessing effect.
"""
import argparse
import hashlib
import json
from pathlib import Path
import time

from .neural_voice import verify_assets, pcm_wave
from .prepare_voice_audition import PASSAGES, level_match


def blend_styles(styles, strengths=(.10,.20)):
    import numpy as np
    if styles.shape != (54,510,256) or styles.dtype != np.dtype('float32') or not np.isfinite(styles).all():
        raise ValueError('Unexpected pinned Kokoro style table')
    if not 1<=len(strengths)<=3 or any(not np.isfinite(w) or not 0<=w<=1 for w in strengths):
        raise ValueError('Invalid blend strengths')
    derived=styles.copy()
    # The source table stays untouched. Two unused slots in this private copy
    # become derived presets; the protocol records their actual provenance.
    for slot,weight in enumerate(strengths):
        derived[slot]=(1-weight)*styles[3]+weight*styles[6]
    return derived


def add_previous_reference(plan,root):
    """Preserve the slightly preferred 20% trial without regenerating it."""
    previous=json.loads(Path('tavi/web/voice-texture-protocol.json').read_text())
    plan['voices']['G']=previous['voices']['G']+' · previous closest'
    plan['display_order']=['C','G','I','J','H']
    plan['reference_feedback'].update(voice='G',base_voice='C',
        previous_trial_feedback='10/20 percent blends barely distinguishable; G was closer, but barely')
    for case in ('short_story','greeting'):
        old=next(t for t in previous['trials'] if t['voice']=='G' and t['case']==case)
        data=Path('.tavi/voice-texture',old['src'].rsplit('/',1)[-1]).read_bytes()
        if hashlib.sha256(data).hexdigest()!=old['sha256']:raise ValueError('Previous G changed')
        index=len(plan['trials'])+1;path=root/f'sample-{index}.wav';path.write_bytes(data)
        plan['trials'].append({**old,'id':f'voice-texture-range-{index}',
             'src':f'/voice-texture-range/sample-{index}.wav',
             'original_reference_unchanged':True,'preparation_ms':0})


def main():
    import numpy as np
    import sherpa_onnx as s
    from piper.phonemize_espeak import EspeakPhonemizer
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--wide',action='store_true',help='Include donor alone and 50/75 percent blends')
    wide=parser.parse_args().wide
    prefix='voice-texture-range' if wide else 'voice-texture'
    source=verify_assets('kokoro');root=Path('.tavi')/prefix;root.mkdir(parents=True,exist_ok=True)
    styles=np.fromfile(source/'voices.bin',dtype='<f4').reshape(54,510,256)
    derived=blend_styles(styles,(.5,.75,1) if wide else (.1,.2));style_path=root/'heart-nicole-blends.bin';derived.astype('<f4').tofile(style_path)
    settings=s.OfflineTtsConfig(model=s.OfflineTtsModelConfig(kokoro=s.OfflineTtsKokoroModelConfig(
        model=str(source/'model.int8.onnx'),voices=str(style_path),tokens=str(source/'tokens.txt')),
        num_threads=2,provider='cpu'))
    if not settings.validate():raise ValueError('Invalid derived voice configuration')
    engine=s.OfflineTts(settings);phonemizer=EspeakPhonemizer()
    tokens={line.rsplit(' ',1)[0] for line in (source/'tokens.txt').read_text().splitlines() if line}
    previous=json.loads(Path('tavi/web/voice-audition-protocol.json').read_text())
    voices=({'C':'Original C · Kokoro af_heart','I':'50% af_heart + 50% af_nicole',
             'J':'25% af_heart + 75% af_nicole','H':'af_nicole alone · donor endpoint'} if wide else
            {'C':'Original C · Kokoro af_heart','F':'90% af_heart + 10% af_nicole','G':'80% af_heart + 20% af_nicole'})
    slots={'F':0,'G':1,'I':0,'J':1,'H':2}
    plan={'schema_version':1,'id':'paprika-voice-texture-range-v1' if wide else 'paprika-voice-texture-v1','kind':'paprika_voice_character_check',
          'display_order':list(voices),'voices':voices,'passages':previous['passages'],
          'reference_feedback':{'voice':'C','source':'user chat','best_so_far':True,'accepted':False,
                                'requested_change':'A little teenage-style raspiness / husky texture',
                                'previous_trial_feedback':'10/20 percent blends were barely distinguishable' if wide else None},
          'method':'Linear interpolation of installed public voice style embeddings; no DSP distortion or pitch shift. Texture/age not guaranteed.',
          'source_voices_sha256':hashlib.sha256((source/'voices.bin').read_bytes()).hexdigest(),
          'derived_voices_sha256':hashlib.sha256(style_path.read_bytes()).hexdigest(),
          'trials':[],'api_spend_usd':0,'microphone_used':False}
    for voice in voices:
        for case,text in PASSAGES.items():
            index=len(plan['trials'])+1;start=time.perf_counter()
            if voice=='C':
                old=next(t for t in previous['trials'] if t['voice']=='C' and t['case']==case)
                data=Path('.tavi/voice-audition',old['src'].rsplit('/',1)[-1]).read_bytes()
                if hashlib.sha256(data).hexdigest()!=old['sha256']:raise ValueError('Original C changed')
                gain=1
            else:
                phonemes=phonemizer.phonemize('en-us',text)
                if any(char not in tokens for sentence in phonemes for char in sentence):raise ValueError('Unsupported phoneme')
                config=s.GenerationConfig();config.sid=slots[voice];config.silence_scale=1
                config.phoneme_codepoints=[[ord(char) for char in sentence] for sentence in phonemes]
                audio=engine.generate('',config);data,gain=level_match(pcm_wave(audio.samples,audio.sample_rate))
            path=root/f'sample-{index}.wav';path.write_bytes(data)
            plan['trials'].append({'id':f'{prefix}-{index}','voice':voice,'case':case,'text':text,
                 'src':f'/{prefix}/sample-{index}.wav','sha256':hashlib.sha256(data).hexdigest(),
                 'gain':gain,'original_reference_unchanged':voice=='C',
                 'preparation_ms':(time.perf_counter()-start)*1000})
            print(f'{voice} {case}: ready; {plan["trials"][-1]["preparation_ms"]:.0f} ms',flush=True)
    if wide:add_previous_reference(plan,root)
    Path('tavi/web',prefix+'-protocol.json').write_text(json.dumps(plan,indent=2)+'\n')
    print(f'{len(plan["trials"])} local texture auditions ready; original C and pinned models unchanged. No live promotion.')


if __name__=='__main__':main()

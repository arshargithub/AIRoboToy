"""Local voice-character auditions; fixed text, no microphone/cloud/playback.

Retain the user's earlier B/fox sample exactly, then compare three genuinely
different female voice presets. External phonemes avoid the rejected lexicon-
only Kokoro configuration. This does not qualify live latency or voice fit.
"""
import hashlib
import json
from pathlib import Path
import time

from .neural_voice import create_engine, generate, pcm_wave
from .voice_audio import level_match

PASSAGES = {
    'short_story': 'A tiny fox found a silver key. It opened a door inside an old oak tree, where a sleepy owl was baking star-shaped cookies.',
    'greeting': "Hi, I'm Paprika. What should we explore today? I think we can handle a little adventure.",
}
VOICES = {'B': ('Piper LJ Speech medium · earlier reference', None),
          'C': ('Kokoro af_heart', 3), 'D': ('Kokoro af_bella', 2), 'E': ('Kokoro af_kore', 5)}




def main():
    import sherpa_onnx as s
    from piper.phonemize_espeak import EspeakPhonemizer
    root=Path('.tavi/voice-audition');root.mkdir(parents=True,exist_ok=True)
    # Keep the first round intact. Explicit revisioned protocol/paths distinguish
    # new character ratings from recognition/clarity ratings in old downloads.
    plan={'schema_version':1,'id':'paprika-voice-character-v1','kind':'paprika_voice_character_check',
          'display_order':list(VOICES),'voices':{key:value[0] for key,value in VOICES.items()},
          'passages':{'short_story':'Fox story','greeting':'Hello from Paprika'},
          'brief':'Youthful adult female voice; confident, warm, full sound with some texture and natural expression.',
          'reference_feedback':{'voice':'B','passage':'short_story','user_rating':'okay, still not what I want','accepted':False},
          'trials':[],'api_spend_usd':0,'microphone_used':False,
          'scope':'Prerecorded voice-character audition; not a live latency or intelligibility qualification.'}
    piper,pc=create_engine('piper');kokoro,kc=create_engine('kokoro');phonemizer=EspeakPhonemizer()
    tokens={line.rsplit(' ',1)[0] for line in Path('.tavi/models/kokoro-int8-multi-lang-v1_0/tokens.txt').read_text().splitlines() if line}
    for voice,(_,sid) in VOICES.items():
        for case,text in PASSAGES.items():
            index=len(plan['trials'])+1;started=time.perf_counter()
            if voice=='B' and case=='short_story':
                data=Path('.tavi/voice-check/sample-2.wav').read_bytes();gain=1
                reference=True
            else:
                reference=False
                if voice=='B':audio=generate(piper,pc,text)
                else:
                    phonemes=phonemizer.phonemize('en-us',text)
                    unknown={char for sentence in phonemes for char in sentence if char not in tokens}
                    if unknown:raise ValueError('Unsupported audition phonemes: '+repr(unknown))
                    config=s.GenerationConfig();config.sid=sid;config.silence_scale=1
                    config.phoneme_codepoints=[[ord(char) for char in sentence] for sentence in phonemes]
                    audio=kokoro.generate('',config)
                data,gain=level_match(pcm_wave(audio.samples,audio.sample_rate))
            path=root/f'sample-{index}.wav';path.write_bytes(data)
            plan['trials'].append({'id':f'audition-{index}','voice':voice,'case':case,'text':text,
                 'src':f'/voice-audition/sample-{index}.wav','sha256':hashlib.sha256(data).hexdigest(),
                 'gain':gain,'original_reference_unchanged':reference,
                 'preparation_ms':(time.perf_counter()-started)*1000,
                 'phonemizer':'piper bundled eSpeak en-us' if voice!='B' else 'Piper voice frontend'})
            print(f'{voice} {case}: prepared ({plan["trials"][-1]["preparation_ms"]:.0f} ms); synthetic only',flush=True)
    path=Path(__file__).with_name('web')/'voice-audition-protocol.json'
    path.write_text(json.dumps(plan,indent=2)+'\n')
    print('Eight character-audition samples ready; reference B/fox unchanged. No live default changed.')


if __name__=='__main__':main()

"""Keep K/M exactly, add N/O without assuming that prompt targets were achieved."""
import hashlib
import json
from pathlib import Path

from .prepare_voice_audition import PASSAGES, level_match

ROOT=Path('.tavi/voice-husky')


def main():
    previous=json.loads(Path('tavi/web/voice-direction-protocol.json').read_text())
    design=json.loads((ROOT/'design.json').read_text())
    expected={(voice,case) for voice in ('N','O') for case in PASSAGES}
    if len(design['trials'])!=4 or {(r['voice'],r['case']) for r in design['trials']}!=expected:
        raise ValueError('N/O both need both passages')
    trials=[]
    for voice in ('K','M','N','O'):
        for case,text in PASSAGES.items():
            retained=voice in ('K','M')
            row=next(r for r in (previous['trials'] if retained else design['trials']) if r['voice']==voice and r['case']==case)
            if row['text']!=text:raise ValueError('All voices must use matching words')
            source=Path('.tavi/voice-direction',row['src'].rsplit('/',1)[-1]) if retained else Path(row['wav'])
            data=source.read_bytes()
            if hashlib.sha256(data).hexdigest()!=row['sha256']:raise ValueError('Source audio changed')
            if not retained:data,gain=level_match(data)
            else:gain=1
            index=len(trials)+1;target=ROOT/f'sample-{index}.wav';target.write_bytes(data)
            trials.append({**{k:v for k,v in row.items() if k not in ('wav','src','id','sha256','gain')},
                'id':f'husky-{index}','src':f'/voice-husky/sample-{index}.wav',
                'sha256':hashlib.sha256(data).hexdigest(),'gain':gain,
                'retained_audio_unchanged':retained,'source_protocol_id':previous['id'] if retained else None})
    plan={'schema_version':1,'id':'paprika-voice-husky-v1','kind':'paprika_voice_character_check',
        'display_order':['K','M','N','O'],
        'voices':{'K':'Retained 35% donor blend · current favourite',
                  'M':'Retained Qwen design · human-sounding, not husky per user',
                  'N':'New Qwen design · low contralto / coarse grain target',
                  'O':'New Qwen design · smoky / hoarse texture target'},
        'passages':previous['passages'],'pronunciation':previous['pronunciation'],
        'reference_feedback':{'voice':'K','best_so_far':True,'accepted':False,'retain':['K','M'],
            'source':'User chat, 2 November 2026',
            'observations':{'K':'Favourite so far; I/K sound more AI-like.',
                'M':'Keep as a more human-sounding reference; high-pitched/chirpy, not husky.',
                'L':'High-pitched/chirpy, opposite of husky; more human-sounding.',
                'target_husky_voice_found':False}},
        'method':'Exact K/M references versus two newly generated lower-register/grain targets; no pitch shift or rasp effects.',
        'design_model':design['model'],'design_settings':design['settings'],
        'trials':trials,'api_spend_usd':0,'microphone_used':False,
        'limitations':['New prompts do not establish audible huskiness; the previous husky prompts failed human review.',
            'Lower pitch and humanlike delivery are separate from huskiness.',
            'Stable identity across passages and live performance remain unqualified.']}
    Path('tavi/web/voice-husky-protocol.json').write_text(json.dumps(plan,indent=2)+'\n')
    print('K/M copied exactly; N/O added as unjudged candidates. No live promotion.')


if __name__=='__main__':main()

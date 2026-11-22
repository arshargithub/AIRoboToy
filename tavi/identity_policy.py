"""Frozen score/margin policy, with independent held-out evidence required.

Similarity is not probability. A development fit can never authorize a person.
The live loader recomputes the sealed identity screen, rather than trusting a
model-written 'qualified' flag or an editable threshold by itself.
"""
from dataclasses import dataclass
import hashlib
import importlib.util
import json
import math
from pathlib import Path
from tavi.speaker_evidence import FAMILY


def rank(scores,threshold,margin,*,eligible):
    if not eligible or len(scores)<2:return 'unknown'
    values=sorted(scores,key=lambda x:(-x['cosine'],x['person_id']))
    if (len({x['person_id'] for x in values})!=len(values) or any(x['person_id'] not in FAMILY or type(x['cosine']) not in (int,float) or not math.isfinite(x['cosine']) or not -1<=x['cosine']<=1 for x in values)):
        raise ValueError('Invalid independent speaker scores')
    gap=values[0]['cosine']-values[1]['cosine']
    if values[0]['cosine']>=threshold and gap>0 and gap>=margin:return values[0]['person_id']
    return 'unknown'


def fit_development(rows,people):
    """One conservative global rule; no search on held-out labels."""
    if not rows or any(r.get('phase')!='development' for r in rows):raise ValueError('Development-only inputs required')
    sessions=set();audio=set()
    for r in rows:
        if r['pcm_sha256'] in audio:raise ValueError('Duplicate development audio')
        audio.add(r['pcm_sha256']);sessions.add(r['session_id'])
    known=[r for r in rows if r['label_kind']=='known' and r['eligible']]
    unknown=[r for r in rows if r['label_kind']=='unknown' and r['eligible']]
    if any(sum(r['person_id']==p for r in known)<12 for p in people) or len(unknown)<20:
        return {'status':'needs_evidence','recognition_enabled':False,'required_known_each':12,'required_unknown':20}
    pairs=[]
    for r in known+unknown:
        values=sorted(r['scores'],key=lambda x:-x['cosine'])
        if len(values)<2:return {'status':'needs_profiles','recognition_enabled':False}
        pairs.append((values[0]['cosine'],values[0]['cosine']-values[1]['cosine']))
    thresholds=sorted({x[0] for x in pairs}|{min(1.,max(x[0] for x in pairs)+1e-6)})
    margins=sorted({0.,*(x[1] for x in pairs)})
    best=None
    for threshold in thresholds:
        for margin in margins:
            predictions=[rank(r['scores'],threshold,margin,eligible=r['eligible']) for r in known+unknown]
            wrong=sum(p!='unknown' and (r['label_kind']=='unknown' or p!=r['person_id']) for r,p in zip(known+unknown,predictions))
            if wrong:continue
            correct=sum(p==r['person_id'] for r,p in zip(known,predictions[:len(known)]))
            candidate=(correct,threshold,margin)
            if best is None or candidate>best:best=candidate
    if best is None:return {'status':'not_separable','recognition_enabled':False}
    correct,threshold,margin=best
    predictions=[rank(r['scores'],threshold,margin,eligible=True) for r in known]
    if correct/len(known)<.9 or any(sum(p==r['person_id'] for r,p in zip(known,predictions) if r['person_id']==person)/sum(r['person_id']==person for r in known)<.85 for person in people):
        return {'status':'development_failed','correct':correct,'eligible_known':len(known),'recognition_enabled':False}
    return {'status':'development_candidate_only','threshold':threshold,'margin':margin,'correct':correct,'eligible_known':len(known),
            'development_sessions':sorted(sessions),'development_pcm_sha256':sorted(audio),'recognition_enabled':False,'authorizes_personal_memory':False}


@dataclass(frozen=True)
class QualifiedPolicy:
    threshold:float
    margin:float
    model_sha256:str
    profiles_revision:str
    certificate_sha256:str

    @classmethod
    def load(cls,path,catalog,model_sha256):
        path=Path(path)
        if not path.is_file():return None
        if path.is_symlink():raise ValueError('Policy must be a reviewed local artifact')
        raw=path.read_bytes();d=json.loads(raw)
        if d.get('issuer')!='paprika_identity_component_v1' or d.get('profiles_revision')!=catalog.revision or d.get('model_sha256')!=model_sha256:
            raise ValueError('Voice qualification no longer matches profiles/model')
        from tavi.experiment_workflow import audit,digest,ROOT
        result=audit(d['run'])
        if result['state']!='finished' or result['decision']!='pass':raise ValueError('Identity screen is not sealed/pass')
        record=json.loads((Path(d['run'])/'run.json').read_text())
        candidate_path=Path(d['development_policy_path'])
        candidate=json.loads(candidate_path.read_text())
        if (not record['experiment_id'].startswith('IDENTITY-HELDOUT-')
                or record.get('input_sha256',{}).get(str(candidate_path))!=digest(candidate_path)
                or candidate.get('decision_code_sha256')!=digest(ROOT/'tavi/identity_policy.py')
                or record.get('source_sha256',{}).get('tavi/identity_policy.py')!=candidate.get('decision_code_sha256')
                or record.get('source_sha256',{}).get('experiments/speaker-id/identity_metrics.py')!=digest(ROOT/'experiments/speaker-id/identity_metrics.py')
                or candidate.get('profiles_revision')!=catalog.revision or candidate.get('model_sha256')!=model_sha256
                or any(d[k]!=candidate[k] for k in ('threshold','margin','development_sessions','development_pcm_sha256'))):
            raise ValueError('Cutoffs must be frozen before the held-out run, not selected on its labels')
        rows_path=Path(d['rows_path'])
        if record.get('artifacts',{}).get(str(rows_path.resolve()))!=digest(rows_path):raise ValueError('Unbound held-out labels')
        spec=importlib.util.spec_from_file_location('paprika_identity_metrics',ROOT/'experiments/speaker-id/identity_metrics.py');module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        rows=json.loads(rows_path.read_text())
        if record.get('input_sha256',{}).get(str(rows_path))!=digest(rows_path) or any(r.get('phase')!='heldout' for r in rows):raise ValueError('Rows were not frozen as held-out inputs')
        if any(record.get('input_sha256',{}).get(str(e['path']))!=digest(e['path']) for e in catalog.entries.values()):raise ValueError('Profiles were not frozen before held-out decisions')
        predicted=[]
        for row in rows:
            value=rank(row['scores'],d['threshold'],d['margin'],eligible=row['eligible'])
            predicted.append({**row,'decision':value,'memory_authorized':value!='unknown'})
        report=module.evaluate(predicted,model_sha256=model_sha256,enrollment=catalog.enrollment(),development_sessions=d['development_sessions']+catalog.excluded_sessions())
        if report['identity_subscreen']!='pass':raise ValueError('Independent identity coverage/accuracy gates not met')
        if any(r['pcm_sha256'] in d['development_pcm_sha256'] for r in rows):raise ValueError('Held-out audio reused from development')
        if not -1<=d['threshold']<=1 or not 0<=d['margin']<=2:raise ValueError('Invalid voice cutoff')
        return cls(d['threshold'],d['margin'],model_sha256,catalog.revision,hashlib.sha256(raw).hexdigest())

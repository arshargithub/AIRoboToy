"""Fresh, labelled calibration visits. Never enrolls, transcribes or learns.

One visit is at most12attempts, reviewed before sealing. Several short visits
can build a development corpus. Held-out capture is locked until cutoff freeze.
"""
import hashlib
import json
import math
import os
from pathlib import Path
import re
import secrets
import threading
from uuid import uuid4
from tavi.identity_catalog import PEOPLE
from tavi.speaker_profile import VOICE,ROOT,require_drive,write_json,wave_bytes,stamp
from tavi.family_collection import PROMPTS,QUALITY_PREFIXES
from tavi.speaker_evidence import TurnKey,compare_shadow

CONSENT='fresh-local-voice-calibration-v1'
ROLES={**PEOPLE,'guest':{'name':'Guest adult','child':False},
       'short':{'name':'Very short answers','child':False,'control':True},
       'overlap':{'name':'Two voices together','child':True,'control':True}}


class VoiceCalibration:
    def __init__(self,catalog,encoder,*,root=VOICE/'calibration',guard=require_drive,bind=None,seal=None):
        self.catalog,self.encoder=catalog,encoder;self.root=Path(root);self.guard=guard;self.bind=bind;self.seal=seal;self.lock=threading.RLock()
        self.model=json.loads((ROOT/'experiments/speaker-id/model-manifest.json').read_text())['sha256']

    def drafts(self):
        self.guard();rows=[]
        for file in self.root.glob('*/visit.json'):
            if file.is_symlink() or file.parent.is_symlink():raise ValueError('Voice check files must be local')
            value=json.loads(file.read_text())
            rows.append(value)
        return rows

    def visits(self):
        rows=[]
        for value in self.drafts():
            if value.get('complete') and value.get('model_sha256')==self.model:
                if value.get('workflow_run'):
                    from tavi.experiment_workflow import audit
                    record=audit(value['workflow_run'])
                    if record['state']!='finished' or record.get('decision')!='pass':continue
                rows.append(value)
        return rows

    def progress(self):
        result={p:{'development':0,'heldout':0} for p in ROLES}
        policy=self.root/'development-policy.json';policy_sha=hashlib.sha256(policy.read_bytes()).hexdigest() if policy.exists() else None
        for visit in self.visits():
            if visit['phase']=='heldout' and visit.get('evaluation_policy_sha256')!=policy_sha:continue
            result[visit['person_id']][visit['phase']]+=sum(a['outcome'] in ('clear','short_control') and a['review']=='keep' for a in visit['attempts'])
        return result

    def status(self):
        self.guard();self.catalog.refresh();progress=self.progress()
        candidate=self.root/'development-policy.json'
        frozen=json.loads(candidate.read_text()) if candidate.exists() else None
        from tavi.experiment_workflow import digest
        locked=(not frozen or len(self.catalog.entries)!=4 or frozen.get('profiles_revision')!=self.catalog.revision
                or frozen.get('status')!='development_candidate_only' or frozen.get('model_sha256')!=self.model
                or frozen.get('decision_code_sha256')!=digest(ROOT/'tavi/identity_policy.py'))
        from tavi.identity_policy import QualifiedPolicy
        try:qualified=QualifiedPolicy.load(self.root.parent/'identity-policy.json',self.catalog,self.model) is not None
        except (ValueError,KeyError,OSError):qualified=False
        return {'people':[{**r,'development_target':12,'heldout_target':25,'progress':progress[r['person_id']]} for r in self.catalog.status()['people']]+[
            {'person_id':p,**ROLES[p],'enrolled':p=='guest' or not locked,'examples':0,'development_target':20 if p=='guest' else 0,'heldout_target':20 if p=='guest' else 10,'progress':progress[p]} for p in ('guest','short','overlap')],
            'profiles_revision':self.catalog.revision,'heldout_locked':locked,'recognition_enabled':False,
            'heldout_help':'First collect fresh development examples and a consenting guest adult. Cutoffs are frozen before a different held-out occasion.',
            'current_profiles':len(self.catalog.candidates),'required_profiles':4,'identity_qualified':qualified,'memory_qualified':False}

    def folder(self,token,person):
        if person not in ROLES or not isinstance(token,str) or not re.fullmatch('[a-f0-9]{32}\.[a-f0-9]{48}',token):raise ValueError('Start this person’s voice check first')
        folder=self.root/token[:32];visit=json.loads((folder/'visit.json').read_text())
        if visit['person_id']!=person or not secrets.compare_digest(visit['token_hash'],hashlib.sha256(token.encode()).hexdigest()):raise ValueError('This voice check belongs to a different person')
        return folder,visit

    def state(self,token,person):
        self.guard()
        with self.lock:
            folder,v=self.folder(token,person)
            attempts=[{k:x for k,x in a.items() if k not in ('embedding','reference_file')} for a in v['attempts']]
            prompt=PROMPTS[(v['prompt_offset']+len(attempts))%len(PROMPTS)]
            prompt=dict(prompt)
            if person=='short':prompt.update(question='Say just “Hi”.',help='One little word only. This checks that Paprika stays unsure about very short voices.',audio=False)
            if person=='overlap':prompt['help']='Two willing people: answer the question at the same time, with different answers. A grown-up supervises any child.'
            record=json.loads((Path(v['workflow_run'])/'run.json').read_text()) if v.get('workflow_run') else None
            sealed=record is None or (record['state']=='finished' and record.get('decision',{}).get('outcome')=='pass')
            return {'person_id':person,**ROLES[person],'session':token,'phase':v['phase'],'complete':v['complete'] and sealed,
                'retain_audio':v['retain_audio'],'attempts':attempts,'total':len(attempts),'batch_end':v['batch_end'],
                'kept':sum(a['review']=='keep' for a in attempts),'eligible':sum(a['outcome'] in ('clear','short_control') and a['review']!='exclude' for a in attempts),
                'next_prompt':prompt,'max_attempts':12,'recognition_enabled':False}

    def begin(self,body,token=None):
        self.guard();person=body.get('person_id');role=ROLES.get(person);phase=body.get('phase')
        if (not role or phase not in ('development','heldout') or body.get('consent')!=CONSENT or body.get('adult') is not True
            or body.get('subject_willing') is not True or body.get('local_only') is not True
            or (person!='overlap' and body.get('alone') is not True)
            or (person=='overlap' and (body.get('two_speakers_agree') is not True or body.get('alone') is not False))
            or type(body.get('retain_audio')) is not bool or (role['child'] and body.get('supervised') is not True)
            or (not role['child'] and body.get('own_voice') is not True)
            or (person=='guest' and body.get('outside_family') is not True)
            or (person in ('short','overlap') and phase!='heldout')
            or (phase=='heldout' and body.get('different_occasion') is not True)):
            raise ValueError('Choose adult supervision or own voice, willingness, one voice and local recording settings')
        with self.lock:
            status=self.status()
            if person in PEOPLE and person not in self.catalog.entries:raise ValueError('Save this person’s enrollment profile before the fresh check')
            if phase=='heldout' and status['heldout_locked']:raise ValueError('Held-out checking opens after development and cutoff freeze')
            if token:
                folder,v=self.folder(token,person)
                if v['phase']!=phase or v['retain_audio']!=body['retain_audio']:raise ValueError('Resume with the same phase and recording choice')
                existing=self.state(token,person)
                if not existing['complete']:return existing
            visits=self.drafts();count=sum(v['person_id']==person and v['phase']==phase for v in visits)
            if count>=(6 if phase=='heldout' else 4):raise ValueError('This check has reached its short-visit limit. Earlier examples are kept for review')
            if self.root.exists() and sum(p.stat().st_size for p in self.root.rglob('*') if p.is_file())>256_000_000:raise ValueError('Local voice-check storage is full. Earlier examples are kept')
            bound=self.bind(body) if self.bind else None
            token=uuid4().hex+'.'+secrets.token_hex(24);folder=self.root/token[:32]
            offset=sum(len(v['attempts']) for v in visits if v['person_id']==person)
            policy_path=self.root/'development-policy.json'
            write_json(folder/'visit.json',{'person_id':person,'phase':phase,'token_hash':hashlib.sha256(token.encode()).hexdigest(),
                'session_id':folder.name,'created_at':stamp(),'complete':False,'retain_audio':body['retain_audio'],'model_sha256':self.model,
                'profiles_revision':self.catalog.revision,'workflow_run':str(bound) if bound else None,'attempts':[],
                'batch_end':6,'prompt_offset':offset,'source':'fresh_supervised_or_own_voice','consent':CONSENT,
                'different_occasion':phase=='heldout','supervised':role['child'],'outside_family':person=='guest',
                'evaluation_policy_sha256':hashlib.sha256(policy_path.read_bytes()).hexdigest() if phase=='heldout' else None})
            return self.state(token,person)

    def attempt(self,token,person,attempt_id,prompt_id,pcm,*,capture_settings=None):
        self.guard()
        if not isinstance(attempt_id,str) or not re.fullmatch('[a-f0-9]{32}',attempt_id):raise ValueError('A stable recording ID is required')
        if not isinstance(pcm,bytes) or len(pcm)%2 or not 0<len(pcm)<=160000:raise ValueError('Record one short answer, up to five seconds')
        capture_settings=capture_settings or {}
        allowed={'sampleRate','channelCount','echoCancellation','noiseSuppression','autoGainControl'}
        if not isinstance(capture_settings,dict) or not set(capture_settings)<=allowed or any(type(v) not in (bool,int,float) or not math.isfinite(v) for v in capture_settings.values()):raise ValueError('Only microphone processing settings may be retained')
        sha=hashlib.sha256(pcm).hexdigest()
        with self.lock:
            folder,v=self.folder(token,person)
            old=next((a for a in v['attempts'] if a['id']==attempt_id),None)
            if old:
                if old['pcm_sha256']!=sha or old['prompt_id']!=prompt_id:raise ValueError('A saved voice check cannot be replaced')
                return self.state(token,person)
            n=len(v['attempts'])
            if v['complete'] or n>=v['batch_end'] or n>=12 or PROMPTS[(v['prompt_offset']+n)%len(PROMPTS)]['id']!=prompt_id:raise ValueError('This question is no longer current. Reopen saved progress')
            item={'id':attempt_id,'prompt_id':prompt_id,'number':n+1,'at':stamp(),'pcm_sha256':sha,
                'outcome':'short','review':'pending','duration_ms':round(len(pcm)/32),'quality':{},'eligible':False,'capture_settings':capture_settings}
            # Explicitly exclude enrollment and all previously seen calibration PCM.
            hashes={r['pcm_sha256'] for r in self.catalog.enrollment()}
            hashes.update(a['pcm_sha256'] for visit in self.drafts() for a in visit['attempts'])
            hashes.update(a['pcm_sha256'] for a in v['attempts'])
            if sha in hashes:item['outcome']='reused'
            elif person=='short' and 16000<=len(pcm)<=38400:
                item.update(outcome='short_control',eligible=False)
                if v['retain_audio']:
                    file=folder/(attempt_id+'.wav');raw=wave_bytes(pcm)
                    if file.is_symlink():raise ValueError('A listening copy cannot be linked')
                    if file.exists() and file.read_bytes()!=raw:raise ValueError('Listening copy differs')
                    if not file.exists():
                        with os.fdopen(os.open(file,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600),'wb') as out:out.write(raw);out.flush();os.fsync(out.fileno())
                    item['reference_file']=file.name
            elif len(pcm)>=64000:
                try:result=self.encoder.encode(pcm)
                except ValueError as error:
                    outcome=next((kind for prefix,kind in QUALITY_PREFIXES.items() if str(error).startswith(prefix)),None)
                    if outcome is None:raise
                    item['outcome']=outcome
                else:
                    vec=result['embedding'];norm=math.hypot(*vec) if isinstance(vec,list) and len(vec)==512 else 0
                    if (result['pcm_sha256']!=sha or result['model_sha256']!=self.model or result['dimension']!=512
                        or not norm or not math.isfinite(norm) or any(not math.isfinite(x) for x in vec)
                        or result['quality']['voiced_seconds']<2):raise ValueError('The local voice result did not match this recording')
                    item.update(outcome='clear',eligible=True,embedding=[x/norm for x in vec],quality=result['quality'])
                    if v['retain_audio']:
                        file=folder/(attempt_id+'.wav');self.guard()
                        raw=wave_bytes(pcm)
                        if file.is_symlink():raise ValueError('A listening copy cannot be a linked file')
                        if file.exists():
                            if file.read_bytes()!=raw:raise ValueError('Existing listening copy differs. Earlier samples are kept')
                        else:
                            with os.fdopen(os.open(file,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600),'wb') as out:out.write(raw);out.flush();os.fsync(out.fileno())
                        item['reference_file']=file.name
            v['attempts'].append(item);self.guard();write_json(folder/'visit.json',v);return self.state(token,person)

    def review(self,token,person,choices,attested,*,finish_visit=False):
        self.guard()
        if attested is not True or not isinstance(choices,dict):raise ValueError('A supervising adult or speaker must review the voice labels')
        with self.lock:
            folder,v=self.folder(token,person)
            if v['complete']:
                if self.seal:self.seal(folder,v)
                return self.state(token,person)
            discard=list(v.get('cleanup_pending',[]))
            receipt=hashlib.sha256(json.dumps(choices,sort_keys=True).encode()).hexdigest()
            if v.get('review_receipt')!=receipt:
                expected={a['id'] for a in v['attempts'] if a['outcome'] in ('clear','short_control') and a['review']!='exclude'}
                if set(choices)!=expected or any(value not in ('keep','exclude') for value in choices.values()):raise ValueError('Review every usable example without looking at similarity scores')
                for a in v['attempts']:
                    if a['id'] not in choices:continue
                    a['review']=choices[a['id']]
                    if a['review']=='exclude':
                        a.pop('embedding',None)
                        if 'reference_file' in a:discard.append(a.pop('reference_file'))
                v['review_receipt']=receipt
            v['cleanup_pending']=discard;write_json(folder/'visit.json',v)
            for name in list(discard):
                if not re.fullmatch('[a-f0-9]{32}\.wav',name) or (folder/name).is_symlink():raise ValueError('Unexpected listening copy path')
                (folder/name).unlink(missing_ok=True);v['cleanup_pending'].remove(name);write_json(folder/'visit.json',v)
            v['reviewed_at']=stamp()
            if finish_visit:v['complete']=True
            else:v['batch_end']=min(12,len(v['attempts'])+6)
            write_json(folder/'visit.json',v)
            if finish_visit and self.seal:self.seal(folder,v)
            return self.state(token,person)

    def corpus(self,phase):
        self.catalog.refresh();rows=[]
        for visit in self.visits():
            if visit['phase']!=phase:continue
            if phase=='heldout':
                policy_path=self.root/'development-policy.json'
                if not policy_path.exists() or visit.get('evaluation_policy_sha256')!=hashlib.sha256(policy_path.read_bytes()).hexdigest():continue
            for a in visit['attempts']:
                if a['review']=='exclude' or a['outcome'] in ('interrupted','reused'):continue
                scores=[]
                if a.get('embedding'):
                    evidence=compare_shadow(TurnKey(visit['session_id'],a['id'],a['pcm_sha256'],0),a['embedding'],self.model,self.catalog.candidates,quality_eligible=a['eligible'])
                    scores=[{'person_id':s.person_id,'cosine':s.cosine} for s in evidence.scores]
                kind={'guest':'unknown','short':'short','overlap':'overlap'}.get(visit['person_id'],'known')
                rows.append({'sample_id':a['id'],'session_id':visit['session_id'],'pcm_sha256':a['pcm_sha256'],'model_sha256':self.model,
                    'phase':phase,'label_kind':kind,'person_id':visit['person_id'] if kind=='known' else None,
                    'duration_ms':a['duration_ms'],'eligible':a['eligible'] and a['review']=='keep','scores':scores})
        return rows

    def audio(self,token,person,sample):
        self.guard()
        with self.lock:
            folder,v=self.folder(token,person)
            item=next((a for a in v['attempts'] if a['id']==sample),None)
            if not item or item['review']=='exclude' or not item.get('reference_file'):raise ValueError('No listening copy is available')
            path=folder/item['reference_file']
            if path.is_symlink() or path.name!=sample+'.wav':raise ValueError('Unexpected listening copy')
            return path.read_bytes()

    def skip(self,token,person,attempt_id,prompt_id):
        self.guard()
        if not isinstance(attempt_id,str) or not re.fullmatch('[a-f0-9]{32}',attempt_id):raise ValueError('Stable question ID required')
        with self.lock:
            folder,v=self.folder(token,person)
            if any(a['id']==attempt_id for a in v['attempts']):return self.state(token,person)
            n=len(v['attempts'])
            if v['complete'] or n>=v['batch_end'] or n>=12 or PROMPTS[(v['prompt_offset']+n)%len(PROMPTS)]['id']!=prompt_id:raise ValueError('Question no longer current')
            v['attempts'].append({'id':attempt_id,'prompt_id':prompt_id,'number':n+1,'at':stamp(),'pcm_sha256':hashlib.sha256(b'').hexdigest(),
                'outcome':'interrupted','review':'exclude','duration_ms':0,'quality':{},'eligible':False})
            write_json(folder/'visit.json',v);return self.state(token,person)

    def fit(self):
        self.guard();self.catalog.refresh()
        if set(self.catalog.entries)!=set(PEOPLE):return {'status':'needs_all_four_profiles','recognition_enabled':False}
        if (self.root/'development-policy.json').exists() and any(v['phase']=='heldout' for v in self.drafts()):
            return {'status':'cutoffs_frozen_heldout_started','recognition_enabled':False}
        from tavi.identity_policy import fit_development
        rows=self.corpus('development')
        result=fit_development([r for r in rows if r['eligible']],sorted(PEOPLE))
        if result['status']=='development_candidate_only':
            from tavi.experiment_workflow import digest
            result.update(model_sha256=self.model,profiles_revision=self.catalog.revision,created_at=stamp(),decision_code_sha256=digest(ROOT/'tavi/identity_policy.py'))
            write_json(self.root/'development-policy.json',result)
        return {k:v for k,v in result.items() if k not in ('threshold','margin','development_pcm_sha256')}

    def qualify(self):
        self.guard()
        from tavi.identity_qualification import qualify
        return qualify(self)

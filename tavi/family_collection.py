"""Explicit local family voice collection, separate from adult-only experiments.

Parent/self labels supply subject identity. Collection never establishes it.
No transcript, cloud inference, memory learning or live recognition is used.
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
import wave
from tavi.speaker_profile import ROOT,VOICE,require_drive,write_json,wave_bytes,stamp

PEOPLE={'childone':{'name':'Child One','child':True},'childtwo':{'name':'Child Two','child':True},'adulttwo':{'name':'Adult Two','child':False}}
CONSENT='supervised-family-local-voice-v1'
PROMPTS=json.loads((ROOT/'experiments/speaker-id/family-prompts-v1.json').read_text())['prompts']
QUALITY_PREFIXES={'Keep this recording between':'short','I need a little more clear speech':'short',
    'The recording is too quiet':'quiet','The recording is distorted':'clipped','Not enough clear voice':'short'}
SETTINGS={'audio_context_rate','requested_echo_cancellation','requested_noise_suppression','requested_auto_gain_control','actual_sampleRate','actual_channelCount','actual_echoCancellation','actual_noiseSuppression','actual_autoGainControl'}


def capture_settings(value):
    if not isinstance(value,dict) or not set(value)<=SETTINGS or any(type(v) not in (int,bool) and not (k=='actual_echoCancellation' and v in ('all','remote-only')) for k,v in value.items()):
        raise ValueError('Unexpected microphone settings; device identifiers are not saved.')
    return value


def consent_valid(body):
    person=body.get('person_id');role=PEOPLE.get(person)
    if (not role or body.get('consent')!=CONSENT or body.get('adult_confirmed') is not True
            or body.get('subject_willing') is not True or body.get('alone') is not True
            or body.get('processing')!='local-only' or type(body.get('retain_audio')) is not bool
            or (role['child'] and body.get('supervised') is not True)
            or (not role['child'] and body.get('own_voice') is not True)):
        raise ValueError('Choose adult supervision or own voice, willingness, local processing and recording retention before starting.')
    return role


class FamilyCollection:
    def __init__(self,*,root=VOICE/'family-enrollment',encoder,guard=require_drive,bind=None,model_sha256=None):
        self.root=Path(root);self.encoder=encoder;self.guard=guard;self.bind=bind;self.lock=threading.RLock()
        self.model_sha256=model_sha256 or json.loads((ROOT/'experiments/speaker-id/model-manifest.json').read_text())['sha256']

    def _write(self,path,value):
        # Recheck after potentially slow native work before creating paths.
        self.guard();write_json(path,value)

    @staticmethod
    def _reference(folder,name):
        if not isinstance(name,str) or not re.fullmatch(r'pending-[a-f0-9]{32}-[a-f0-9]{12}(?:-recovered-[a-f0-9]{32})?\.wav',name):
            raise ValueError('Unexpected temporary recording path. Keep the samples for local review.')
        path=folder/name
        if path.is_symlink():raise ValueError('A temporary recording cannot be a link to another file.')
        return path

    def folder(self,token,person):
        if person not in PEOPLE or not isinstance(token,str) or not re.fullmatch('[a-f0-9]{32}\\.[a-f0-9]{48}',token):
            raise ValueError('Start or resume this person’s collection first.')
        folder=self.root/token[:32];draft=json.loads((folder/'draft.json').read_text())
        if draft['person_id']!=person or not secrets.compare_digest(draft['token_hash'],hashlib.sha256(token.encode()).hexdigest()):
            raise ValueError('This link and saved collection belong to different people. Earlier samples are kept.')
        return folder,draft

    def state(self,token,person):
        self.guard()
        with self.lock:
            folder,draft=self.folder(token,person);attempts=draft['attempts']
            usable=[a for a in attempts if a['outcome']=='clear' and a['review']!='exclude']
            kept=[a for a in usable if a['review']=='keep']
            sealed=not draft.get('workflow_run') or json.loads((Path(draft['workflow_run'])/'run.json').read_text())['state']=='finished'
            return {'person_id':person,'name':PEOPLE[person]['name'],'child':PEOPLE[person]['child'],
                'retain_audio':draft['retain_audio'],'attempts':[{k:v for k,v in a.items() if k not in ('embedding','reference_file')} for a in attempts],
                'eligible':len(usable),'kept':len(kept),'target':6,'total':len(attempts),'segment_end':draft['segment_end'],
                'sitting_start':draft['sitting_start'],'paused':draft.get('paused',False),'reviewed':draft.get('reviewed',False),
                'next_prompt':PROMPTS[len(attempts)] if len(attempts)<len(PROMPTS) else None,
                'complete':(folder/'profile.json').is_file() and sealed,'profile_saved':(folder/'profile.json').is_file(),
                'recognition_enabled':False,'authorizes_personal_memory':False,'workflow_run_bound':bool(draft.get('workflow_run'))}

    def begin(self,body,token=None):
        role=consent_valid(body);self.guard();person=body['person_id']
        with self.lock:
            if token:
                folder,draft=self.folder(token,person)
                if draft['retain_audio']!=body['retain_audio']:raise ValueError('Resume with the original recording choice; earlier samples are kept.')
                if (folder/'profile.json').exists():return {'session':token,**self.state(token,person)}
                if draft.get('workflow_run'):
                    previous=json.loads((Path(draft['workflow_run'])/'run.json').read_text())
                    if previous['state']=='finished':
                        if (draft['attempts'] or previous.get('error')!='microphone_startup_processor_not_registered' or not self.bind):
                            raise ValueError('This collection needs local review before another recording. Earlier samples are kept.')
                        # Explicit fresh consent above binds corrected source; never rewrite the failed run.
                        replacement=self.bind(body)
                        if not replacement:raise ValueError('The repaired collection could not be prepared. Nothing is recording.')
                        draft.setdefault('previous_workflow_runs',[]).append(draft['workflow_run'])
                        draft['workflow_run']=str(replacement)
                        draft.setdefault('consent_resumes',[]).append(stamp())
                        self._write(folder/'draft.json',draft)
                if body.get('new_sitting') is True and len(draft['attempts'])<24 and (draft.get('paused') or len(draft['attempts'])>=draft['sitting_start']+12):
                    if draft.get('sittings',1)>=2:raise ValueError('This collection has reached its two-sitting limit. Earlier samples are kept for local review.')
                    draft['sitting_start']=len(draft['attempts']);draft['segment_end']=min(24,len(draft['attempts'])+max(2,6-sum(a['review']=='keep' for a in draft['attempts'])))
                    draft['sittings']=draft.get('sittings',1)+1
                    draft['paused']=False;draft['reviewed']=False;draft.setdefault('consent_resumes',[]).append(stamp());self._write(folder/'draft.json',draft)
                elif draft.get('paused'):
                    draft['paused']=False;self._write(folder/'draft.json',draft)
                return {'session':token,**self.state(token,person)}
            if self.root.exists() and sum(p.stat().st_size for p in self.root.rglob('*') if p.is_file())>256_000_000:
                raise ValueError('The local collection folder is full. Existing samples are kept; storage needs review.')
            bound=self.bind(body) if self.bind else None
            token=uuid4().hex+'.'+secrets.token_hex(24);folder=self.root/token[:32]
            self._write(folder/'draft.json',{'person_id':person,'token_hash':hashlib.sha256(token.encode()).hexdigest(),
                'consent':CONSENT,'created_at':stamp(),'retain_audio':body['retain_audio'],'adult_confirmed':True,
                'subject_willing':True,'alone':True,'supervised':role['child'],'own_voice':not role['child'],
                'processing':'local-only','workflow_run':str(bound) if bound else None,'attempts':[],
                'segment_end':6,'sitting_start':0,'sittings':1,'reviewed':False,'paused':False})
            return {'session':token,**self.state(token,person)}

    def attempt(self,token,person,attempt_id,prompt_id,pcm,settings):
        self.guard();capture_settings(settings)
        if not isinstance(attempt_id,str) or not re.fullmatch('[a-f0-9]{32}',attempt_id):raise ValueError('A stable recording ID is required.')
        if not isinstance(pcm,bytes) or len(pcm)>256000 or len(pcm)%2:raise ValueError('One short mono recording is required.')
        sha=hashlib.sha256(pcm).hexdigest()
        with self.lock:
            folder,draft=self.folder(token,person)
            old=next((a for a in draft['attempts'] if a['id']==attempt_id),None)
            if old:
                if old['pcm_sha256']!=sha or old['prompt_id']!=prompt_id:raise ValueError('A saved turn cannot be replaced by different audio.')
                return self.state(token,person)
            n=len(draft['attempts'])
            if (folder/'profile.json').exists() or draft.get('paused') or n>=draft['segment_end'] or n>=min(24,draft['sitting_start']+12) or PROMPTS[n]['id']!=prompt_id:
                raise ValueError('This turn is no longer current. Reopen the latest saved progress; earlier samples are kept.')
            item={'id':attempt_id,'prompt_id':prompt_id,'number':n+1,'pcm_sha256':sha,'at':stamp(),
                  'review':'pending','browser_reported_capture_settings':settings,'outcome':'short','quality':{'duration_seconds':len(pcm)/32000}}
            if len(pcm)>=32000:
                if any(a['pcm_sha256']==sha and a['outcome']=='clear' for a in draft['attempts']):item['outcome']='duplicate'
                else:
                    try:result=self.encoder.encode(pcm)
                    except ValueError as error:
                        kind=next((kind for prefix,kind in QUALITY_PREFIXES.items() if str(error).startswith(prefix)),None)
                        if kind is None:raise
                        item['outcome']=kind
                    else:
                        if not isinstance(result,dict) or set(result)!={'embedding','model_sha256','dimension','quality','pcm_sha256'}:raise ValueError('Unexpected local model result; keep this recording for local review.')
                        vec=result.get('embedding');norm=math.hypot(*vec) if isinstance(vec,list) and len(vec)==512 else 0
                        if (result.get('pcm_sha256')!=sha or result.get('model_sha256')!=self.model_sha256 or result.get('dimension')!=512
                                or not norm or not math.isfinite(norm) or any(not math.isfinite(x) for x in vec)
                                or result.get('quality',{}).get('voiced_seconds',0)<2):
                            raise ValueError('The local model result did not match this recording. Keep this page open and retry the check.')
                        item.update(result);item['embedding']=[x/norm for x in vec];item['outcome']='clear'
                        if draft['retain_audio']:
                            self.guard()
                            name=f'pending-{attempt_id}-{sha[:12]}.wav';file=folder/name;raw=wave_bytes(pcm)
                            if file.exists() and file.read_bytes()!=raw:
                                name=f'pending-{attempt_id}-{sha[:12]}-recovered-{uuid4().hex}.wav';file=folder/name
                            if not file.exists():
                                with os.fdopen(os.open(file,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600),'wb') as out:out.write(raw);out.flush();os.fsync(out.fileno())
                            item['reference_file']=name
            draft['attempts'].append(item);draft['reviewed']=False;self._write(folder/'draft.json',draft)
            return self.state(token,person)

    def skip(self,token,person,attempt_id,prompt_id,sha):
        self.guard()
        if not isinstance(attempt_id,str) or not re.fullmatch('[a-f0-9]{32}',attempt_id) or not isinstance(sha,str) or not re.fullmatch('[a-f0-9]{64}',sha):raise ValueError('A stable skipped-turn identity is required.')
        with self.lock:
            folder,draft=self.folder(token,person)
            old=next((a for a in draft['attempts'] if a['id']==attempt_id),None)
            if old:
                if old['pcm_sha256']!=sha:raise ValueError('The saved recording differs. Show the latest progress before continuing.')
                return self.state(token,person)
            n=len(draft['attempts'])
            if (folder/'profile.json').exists() or draft.get('paused') or n>=draft['segment_end'] or n>=min(24,draft['sitting_start']+12) or PROMPTS[n]['id']!=prompt_id:raise ValueError('This turn is no longer current. Show the latest progress.')
            draft['attempts'].append({'id':attempt_id,'prompt_id':prompt_id,'number':n+1,'pcm_sha256':sha,'at':stamp(),'outcome':'interrupted','review':'exclude','exclusion':'unfinished_turn','quality':{}})
            draft['reviewed']=False;self._write(folder/'draft.json',draft)
            return self.state(token,person)

    def review(self,token,person,choices,attested):
        self.guard()
        if attested is not True or not isinstance(choices,dict):raise ValueError('The supervising adult or speaker must review whose normal voice was recorded.')
        with self.lock:
            folder,draft=self.folder(token,person)
            if (folder/'profile.json').exists():return self.state(token,person)
            receipt=hashlib.sha256(json.dumps(choices,sort_keys=True).encode()).hexdigest()
            if draft.get('review_receipt')!=receipt:
                expected={a['id'] for a in draft['attempts'] if a['outcome']=='clear' and a['review']!='exclude'}
                if set(choices)!=expected or any(v not in ('keep','other_voice','silly_voice','skip') for v in choices.values()):raise ValueError('Review each useful sample once; no short or rejected sample can be promoted.')
                discard=list(draft.get('cleanup_pending',[]))
                for a in draft['attempts']:
                    if a['id'] not in choices:continue
                    choice=choices[a['id']];a['review']='keep' if choice=='keep' else 'exclude'
                    if choice!='keep':
                        a['exclusion']=choice;a.pop('embedding',None)
                        if 'reference_file' in a:
                            self._reference(folder,a['reference_file']);discard.append(a.pop('reference_file'))
                draft.update(review_receipt=receipt,cleanup_pending=discard,reviewed=False)
                self._write(folder/'draft.json',draft) # Exclusion precedes raw cleanup.
            for name in list(draft.get('cleanup_pending',[])):
                try:self._reference(folder,name).unlink(missing_ok=True)
                except OSError:raise ValueError('The sample is excluded, but its temporary recording could not be removed. Keep recording paused and retry this review for local cleanup.')
                draft['cleanup_pending'].remove(name);self._write(folder/'draft.json',draft)
            draft['reviewed']=True;draft['review_at']=stamp();draft['reviewer_role']='supervising_adult' if PEOPLE[person]['child'] else 'subject_adult';self._write(folder/'draft.json',draft)
            return self.state(token,person)

    def more(self,token,person):
        self.guard()
        with self.lock:
            folder,draft=self.folder(token,person);n=len(draft['attempts']);kept=sum(a['review']=='keep' for a in draft['attempts'])
            if not draft.get('reviewed') or kept>=6 or n>=min(24,draft['sitting_start']+12):raise ValueError('Finish this sitting for now. Useful samples are kept for a later session.')
            draft['segment_end']=min(24,draft['sitting_start']+12,n+max(2,6-kept));draft['reviewed']=False;self._write(folder/'draft.json',draft)
            return self.state(token,person)

    def pause(self,token,person):
        self.guard()
        with self.lock:
            folder,draft=self.folder(token,person)
            if (folder/'profile.json').exists():return self.state(token,person)
            draft['paused']=True;self._write(folder/'draft.json',draft)
            return self.state(token,person)

    def audio(self,token,person,attempt_id):
        self.guard()
        with self.lock:
            folder,draft=self.folder(token,person);a=next((a for a in draft['attempts'] if a['id']==attempt_id),None)
            if not a or a.get('review')=='exclude' or not a.get('reference_file'):raise ValueError('No retained listening copy for this sample.')
            file=self._reference(folder,a['reference_file']);raw=file.read_bytes()
            try:
                with wave.open(str(file),'rb') as w:
                    valid=(w.getnchannels(),w.getsampwidth(),w.getframerate())==(1,2,16000) and hashlib.sha256(w.readframes(w.getnframes())).hexdigest()==a['pcm_sha256']
            except (wave.Error,EOFError):valid=False
            if not valid:raise ValueError('The retained recording changed. Leave that sample out and use a fresh question; earlier samples are kept.')
            return raw

    def finish(self,token,person):
        self.guard()
        with self.lock:
            folder,draft=self.folder(token,person)
            if (folder/'profile.json').exists():return self.state(token,person)
            clips=[a for a in draft['attempts'] if a['outcome']=='clear' and a['review']=='keep']
            if not draft.get('reviewed') or len(clips)<6:raise ValueError('Keep at least six reviewed examples before saving a candidate profile. Earlier samples are kept.')
            if any(c['model_sha256']!=self.model_sha256 or c['dimension']!=512 for c in clips):raise ValueError('Candidate model changed; keep all samples for review.')
            for c in clips:
                if 'reference_file' in c:self.audio(token,person,c['id'])
            centroid=[sum(c['embedding'][i] for c in clips)/len(clips) for i in range(512)];norm=math.hypot(*centroid)
            if not norm or not math.isfinite(norm):raise ValueError('The candidate profile could not be combined; keep samples for review.')
            self._write(folder/'profile.json',{'schema_version':1,'profile_id':folder.name,'person_id':person,'display_name':PEOPLE[person]['name'],
                'created_at':stamp(),'status':'candidate_unqualified','recognition_enabled':False,'authorizes_personal_memory':False,
                'model_sha256':self.model_sha256,'dimension':512,'centroid':[x/norm for x in centroid],
                'clips':clips,'retain_audio':draft['retain_audio'],'consent':CONSENT,'local_only':True,
                'threshold':None,'unknown_speaker_qualified':False,'held_out_session_qualified':False,'workflow_run':draft.get('workflow_run')})
            return self.state(token,person)

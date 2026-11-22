"""Exact local candidate versions; collection is never recognition authority."""
import hashlib
import json
from pathlib import Path
from tavi.speaker_evidence import Candidate, FAMILY, profile_revision
from tavi.speaker_profile import VOICE, require_drive
from tavi.experiment_workflow import audit

PEOPLE={'adultone':{'name':'Adult One','child':False},'adulttwo':{'name':'Adult Two','child':False},
        'childtwo':{'name':'Child Two','child':True},'childone':{'name':'Child One','child':True}}


class ProfileCatalog:
    def __init__(self,root=VOICE,*,guard=require_drive,verify_run=audit):
        self.root=Path(root);self.guard=guard;self.verify_run=verify_run
        self.candidates=();self.entries={};self.issues={};self.revision=profile_revision(())
        self.inventory=();self.selection_stat=None

    def refresh(self):
        self.guard();found={p:[] for p in FAMILY};issues={}
        for directory in ('family-enrollment','enrollment','imported-enrollment'):
            for file in sorted((self.root/directory).glob('*/profile.json')):
                if file.is_symlink() or file.parent.is_symlink():raise ValueError('Voice profile must be a real local file')
                raw=file.read_bytes();profile=json.loads(raw);person=profile.get('person_id')
                if person not in FAMILY:continue
                try:
                    candidate=Candidate.from_bytes(raw)
                    if len(profile.get('clips',[]))<6:raise ValueError('Six reviewed examples required')
                    if profile.get('workflow_run'):
                        run=self.verify_run(profile['workflow_run'])
                        if run.get('state')!='finished' or run.get('decision')!='pass':raise ValueError('Collection not complete')
                    else:raise ValueError('Collection provenance unavailable')
                    found[person].append({'candidate':candidate,'path':file,'profile':profile,'stat':self._stat(file)})
                except (ValueError,KeyError,OSError):issues[person]='profile_needs_review'
        selected={}
        selection=self.root/'selected-profiles.json'
        if selection.exists():
            if selection.is_symlink():raise ValueError('Profile selection must be local')
            selected=json.loads(selection.read_text())
        entries={}
        for person,options in found.items():
            if len(options)==1:entries[person]=options[0]
            elif len(options)>1:
                matching=[o for o in options if o['candidate'].profile_sha256==selected.get(person)]
                if len(matching)==1:entries[person]=matching[0]
                else:issues[person]='choose_one_profile_version'
            else:issues.setdefault(person,'enrollment_needed')
        self.entries=entries;self.issues=issues;self.candidates=tuple(entries[p]['candidate'] for p in sorted(entries));self.revision=profile_revision(self.candidates)
        self.inventory=self._inventory();self.selection_stat=self._stat(selection) if selection.exists() else None
        return self.status()

    def _inventory(self):
        return tuple(sorted(str(p) for category in ('family-enrollment','enrollment','imported-enrollment') for p in (self.root/category).glob('*/profile.json')))

    @staticmethod
    def _stat(file):
        s=file.stat();return(s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns)

    def current(self):
        try:
            self.guard()
            selection=self.root/'selected-profiles.json'
            return (self._inventory()==self.inventory and (self._stat(selection) if selection.exists() else None)==self.selection_stat
                    and all(not e['path'].is_symlink() and self._stat(e['path'])==e['stat'] for e in self.entries.values()))
        except (OSError,ValueError):return False

    def status(self):
        return {'profiles_revision':self.revision,'people':[{'person_id':p,**PEOPLE[p],
            'enrolled':p in self.entries,'examples':len(self.entries[p]['profile']['clips']) if p in self.entries else 0,
            'issue':self.issues.get(p),'recognition_enabled':False} for p in PEOPLE],
            'selected_profiles':len(self.candidates),'recognition_enabled':False}

    def enrollment(self):
        rows=[]
        for person,e in self.entries.items():
            profile=e['profile']
            sessions=profile.get('excluded_from_heldout_sessions') or [profile.get('workflow_run') or profile['profile_id']]
            for clip in profile['clips']:
                rows.append({'person_id':person,'session_id':clip.get('session_id',sessions[0]),'pcm_sha256':clip['pcm_sha256']})
        return rows

    def excluded_sessions(self):
        return sorted({s for e in self.entries.values() for s in (e['profile'].get('excluded_from_heldout_sessions') or [e['profile'].get('workflow_run') or e['profile']['profile_id']])})

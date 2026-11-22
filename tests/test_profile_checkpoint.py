import hashlib
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from tavi.profile_checkpoint import checkpoint, verify, restore_offline
from tavi.speaker_evidence import Candidate, FAMILY, profile_revision


class ProfileCheckpointTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name).resolve()
        self.source=self.root/'source';self.source.mkdir();self.entries={}
        for i,person in enumerate(sorted(FAMILY)):
            file=self.source/(person+'.json');file.write_text(json.dumps({'schema_version':1,'profile_id':str(i+1)*32,
                'person_id':person,'model_sha256':'a'*64,'status':'candidate_unqualified','recognition_enabled':False,
                'authorizes_personal_memory':False,'threshold':None,'local_only':True,'dimension':512,'centroid':[1]+[0]*511}))
            self.entries[person]={'path':file,'candidate':Candidate.from_bytes(file.read_bytes())}
        self.catalogue=SimpleNamespace(entries=self.entries,revision=profile_revision(tuple(e['candidate'] for e in self.entries.values())),refresh=lambda:None)
    def test_exact_candidates_preserved_in_private_independent_copy(self):
        folder=checkpoint(self.catalogue,self.root);value=verify(folder)
        self.assertEqual(value['profiles_revision'],self.catalogue.revision)
        for person,e in self.entries.items():self.assertEqual((folder/(person+'.json')).read_bytes(),e['path'].read_bytes())
        self.assertEqual(folder.stat().st_mode&0o777,0o700)
        for f in folder.iterdir():self.assertEqual(f.stat().st_mode&0o777,0o600)
    def test_offline_restore_never_selects_or_qualifies_candidates(self):
        folder=checkpoint(self.catalogue,self.root);restored=restore_offline(folder,self.root)
        self.assertEqual(verify(restored)['profiles_revision'],self.catalogue.revision)
        m=json.loads((restored/'RESTORE_VOICE_OFFLINE_ONLY.json').read_text());self.assertFalse(m['automatic_selection_allowed'])
        self.assertFalse(m['recognition_enabled']);self.assertFalse(m['authorizes_personal_memory'])
        self.assertFalse((restored/'selected-profiles.json').exists())
    def test_raw_recordings_and_unrelated_files_are_not_copied(self):
        (self.source/'private.wav').write_bytes(b'not part of candidate checkpoint')
        folder=checkpoint(self.catalogue,self.root)
        self.assertEqual({p.name for p in folder.iterdir()},{'manifest.json',*(p+'.json' for p in FAMILY)})
    def test_corruption_blocks_restore_before_new_destination(self):
        folder=checkpoint(self.catalogue,self.root);next(folder.glob('adultone.json')).write_bytes(b'changed');before=set(self.root.iterdir())
        with self.assertRaises(ValueError):restore_offline(folder,self.root)
        self.assertEqual(set(self.root.iterdir()),before)
    def test_interrupted_restore_is_marked_offline_before_profile_copy(self):
        folder=checkpoint(self.catalogue,self.root)
        with patch('tavi.profile_checkpoint.copy_private',side_effect=OSError('full')):
            with self.assertRaises(OSError):restore_offline(folder,self.root)
        target=next(self.root.glob('voice-offline-restore-*'));self.assertTrue((target/'RESTORE_VOICE_OFFLINE_ONLY.json').is_file())
        self.assertFalse((target/'manifest.json').exists())
    def test_changed_candidate_blocks_complete_backup(self):
        self.entries['adultone']['path'].write_bytes(b'{"changed":true}')
        with self.assertRaises(ValueError):checkpoint(self.catalogue,self.root)
        self.assertFalse(any(p.exists() for p in self.root.glob('voice-checkpoint-*/manifest.json')))
    def test_symlink_profile_is_not_followed(self):
        file=self.entries['adultone']['path'];kept=self.source/'kept.json';file.rename(kept);file.symlink_to(kept)
        with self.assertRaises(ValueError):checkpoint(self.catalogue,self.root)
    def test_backup_never_overwrites_existing_candidate_copies(self):
        a=checkpoint(self.catalogue,self.root);sha=hashlib.sha256((a/'adultone.json').read_bytes()).hexdigest()
        b=checkpoint(self.catalogue,self.root);self.assertNotEqual(a,b)
        self.assertEqual(hashlib.sha256((a/'adultone.json').read_bytes()).hexdigest(),sha)

import hashlib,json,tempfile,unittest
from pathlib import Path
from tavi.speaker_profile import Enrollment,CONSENT

class FakeEncoder:
 def encode(self,pcm):return {'embedding':[1.,0.,0.],'dimension':3,'model_sha256':'pinned-test-model','pcm_sha256':hashlib.sha256(pcm).hexdigest(),'quality':{'voiced_seconds':3,'duration_seconds':8,'rms':.05,'clipped_fraction':0}}
class EnrollmentTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)/'enrollment';self.bound=[]
  self.e=Enrollment(self.root,encoder=FakeEncoder(),guard=lambda:None,bind=lambda body:self.bound.append(dict(body)))
  self.body={'consent':CONSENT,'adult_alone':True,'processing':'local-only','person_id':'adultone','retain_audio':False}
 def begin(self):return self.e.begin(self.body)['session']
 def clip(self,token,index):
  pcm=('fake-voice-'+str(index)).encode();result=self.e.preview(token,index,pcm);return self.e.use(token,index,result['pcm_sha256'])
 def test_choices_and_child_ids_rejected_before_binding_or_directory_creation(self):
  for body in [{},{**self.body,'adult_alone':False},{**self.body,'processing':'cloud'},{**self.body,'retain_audio':None},{**self.body,'person_id':'childone'},{**self.body,'person_id':'childtwo'}]:
   with self.assertRaises(ValueError):self.e.begin(body)
  self.assertEqual(self.bound,[]);self.assertFalse(self.root.exists())
 def test_six_reviewed_recordings_make_candidate_only_profile_without_raw_audio(self):
  token=self.begin()
  for i in range(6):state=self.clip(token,i)
  self.assertFalse(state['complete']);state=self.e.finish(token,'quiet room');self.assertTrue(state['complete'])
  folder,_=self.e._folder(token);p=json.loads((folder/'profile.json').read_text())
  self.assertFalse(p['recognition_enabled']);self.assertFalse(p['authorizes_personal_memory']);self.assertIsNone(p['threshold']);self.assertEqual(p['note'],'quiet room');self.assertEqual(len(p['clips']),6);self.assertEqual(list(folder.glob('*.wav')),[]);self.assertEqual(self.e.pending,{})
 def test_reference_audio_choice_and_private_permissions_preserved(self):
  self.body['retain_audio']=True;token=self.begin();self.clip(token,0);folder,_=self.e._folder(token)
  wav=next(folder.glob('*.wav'));self.assertTrue(wav.read_bytes().startswith(b'RIFF'));self.assertEqual(wav.stat().st_mode&0o777,0o600);self.assertEqual(self.root.stat().st_mode&0o777,0o700)
 def test_resume_keeps_progress_and_rejects_person_or_retention_change(self):
  token=self.begin();self.clip(token,0);e=Enrollment(self.root,encoder=FakeEncoder(),guard=lambda:None)
  self.assertEqual(e.begin(self.body,token)['saved_clips'],1)
  with self.assertRaises(ValueError):e.begin({**self.body,'person_id':'adulttwo'},token)
  with self.assertRaises(ValueError):e.begin({**self.body,'retain_audio':True},token)
 def test_token_tamper_and_path_escape_cannot_open_profile(self):
  token=self.begin()
  for value in ['../profile',token[:33]+'a'*48]:
   with self.assertRaises(ValueError):self.e.state(value)
 def test_stale_or_changed_clip_cannot_replace_reviewed_recording(self):
  token=self.begin();a=self.e.preview(token,0,b'first');b=self.e.preview(token,0,b'second')
  with self.assertRaises(ValueError):self.e.use(token,0,a['pcm_sha256'])
  self.e.use(token,0,b['pcm_sha256']);self.assertEqual(self.e.use(token,0,b['pcm_sha256'])['saved_clips'],1)
  with self.assertRaises(ValueError):self.e.use(token,0,a['pcm_sha256'])
 def test_model_version_mix_blocks_finalization(self):
  token=self.begin()
  for i in range(6):self.clip(token,i)
  folder,d=self.e._folder(token);d['clips'][0]['model_sha256']='another-model';(folder/'draft.json').write_text(json.dumps(d))
  with self.assertRaises(ValueError):self.e.finish(token)
  self.assertFalse((folder/'profile.json').exists())
 def test_new_profile_does_not_overwrite_existing_and_finish_is_idempotent(self):
  token=self.begin()
  for i in range(6):self.clip(token,i)
  self.e.finish(token);folder,_=self.e._folder(token);before=(folder/'profile.json').read_bytes();self.e.finish(token,'different retry note');self.assertEqual((folder/'profile.json').read_bytes(),before)
  second=self.begin();self.assertNotEqual(second,token);self.assertEqual(self.e.state(token)['saved_clips'],6)
 def test_missing_drive_stops_before_writing_or_encoding(self):
  def unavailable():raise ValueError('Drive unavailable')
  self.e.guard=unavailable
  with self.assertRaises(ValueError):self.begin()
  self.assertFalse(self.root.exists())
 def test_candidate_collection_seals_real_workflow_without_granting_identity(self):
  from tavi.experiment_workflow import begin,audit
  from tavi.speaker_setup import seal
  protocol=Path(self.temp.name)/'protocol.json'
  protocol.write_text(json.dumps({'experiment_id':'UNIT-SPEAKER-COLLECTION','work_item':'F1','hypothesis':'Synthetic unit fixture only','configuration':{'synthetic':True},'inputs':['experiments/speaker-id/model-manifest.json'],'source_paths':['tavi/speaker_profile.py'],'data_policy':'fictional_text_only','limits':{'maximum_additional_api_usd':0},'criteria':[{'metric':'recordings_reviewed','equals':6},{'metric':'candidate_only','equals':True}],'next_actions':dict.fromkeys(['pass','fail','error','needs_evidence'],'Unit fixture only')}))
  def bind(body):return begin(protocol,run_root=Path(self.temp.name)/'runs')[0]
  self.e.bind=bind;token=self.begin()
  for i in range(6):self.clip(token,i)
  self.assertFalse(self.e.finish(token)['complete']);seal(self.e,token);self.assertTrue(self.e.state(token)['complete'])
  _,draft=self.e._folder(token);record=json.loads((Path(draft['workflow_run'])/'run.json').read_text());self.assertFalse(record['integration_qualified']);self.assertFalse(record['product_accepted']);self.assertEqual(audit(draft['workflow_run'])['decision'],'pass')
 def test_incomplete_reference_file_is_preserved_and_saved_under_new_name(self):
  self.body['retain_audio']=True;token=self.begin();folder,_=self.e._folder(token);pcm=b'voice-00';result=self.e.preview(token,0,pcm)
  old=folder/f"clip-1-{result['pcm_sha256'][:12]}.wav";old.write_bytes(b'partial')
  self.e.use(token,0,result['pcm_sha256']);self.assertEqual(old.read_bytes(),b'partial');_,draft=self.e._folder(token)
  self.assertNotEqual(draft['clips'][0]['reference_file'],old.name);self.assertTrue((folder/draft['clips'][0]['reference_file']).read_bytes().startswith(b'RIFF'))
 def test_tampered_reference_blocks_profile_save_and_preserves_all_files(self):
  self.body['retain_audio']=True;token=self.begin()
  for i in range(6):self.clip(token,i)
  folder,_=self.e._folder(token);raw=next(folder.glob('*.wav'));raw.write_bytes(b'corrupted reference')
  with self.assertRaises(ValueError):self.e.finish(token)
  self.assertFalse((folder/'profile.json').exists());self.assertEqual(len(list(folder.glob('*.wav'))),6)
 def test_capture_settings_exclude_device_identifiers_and_keep_actual_processing_reports(self):
  token=self.begin();result=self.e.preview(token,0,b'voice-00')
  with self.assertRaises(ValueError):self.e.use(token,0,result['pcm_sha256'],{'deviceId':'private-device'})
  self.e.use(token,0,result['pcm_sha256'],{'audio_context_rate':16000,'actual_sampleRate':48000,'actual_echoCancellation':'all'})
  _,draft=self.e._folder(token);self.assertEqual(draft['clips'][0]['browser_reported_capture_settings']['actual_echoCancellation'],'all')
  self.assertNotIn('deviceId',json.dumps(draft))

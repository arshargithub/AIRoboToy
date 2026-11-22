from http.server import ThreadingHTTPServer
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
import urllib.request
import urllib.error
from tavi.family_collection import FamilyCollection,CONSENT
from tavi.family_capture import handler
from tests.test_family_collection import Encoder,MODEL


class FamilyHTTPTests(unittest.TestCase):
    def test_named_links_consent_person_token_and_local_origin_boundaries(self):
        with tempfile.TemporaryDirectory() as tmp:
            bound=[];collection=FamilyCollection(root=Path(tmp)/'family',encoder=Encoder(),guard=lambda:None,bind=lambda b:bound.append(b),model_sha256=MODEL)
            server=ThreadingHTTPServer(('127.0.0.1',0),lambda *_:None);server.RequestHandlerClass=handler(collection,server.server_port)
            thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start();base=f'http://127.0.0.1:{server.server_port}'
            def post(body,person='childone',token=None,origin=base):
                h={'Content-Type':'application/json','X-Person-ID':person,'Origin':origin}
                if token:h['X-Collection-Session']=token
                request=urllib.request.Request(base+'/api/begin',data=json.dumps(body).encode(),headers=h)
                try:
                    with urllib.request.urlopen(request,timeout=2) as r:return r.status,json.load(r)
                except urllib.error.HTTPError as r:return r.code,json.load(r)
            try:
                with patch('tavi.family_capture.ready'):
                    for person,name in [('childone','Child One'),('childtwo','Child Two'),('adulttwo','Adult Two')]:
                        with urllib.request.urlopen(base+'/'+person,timeout=2) as r:
                            page=r.read().decode();self.assertIn(f'data-person="{person}"',page);self.assertIn(name,page);self.assertNotIn('@@',page)
                        with urllib.request.urlopen(base+'/api/setup?person='+person,timeout=2) as r:
                            data=json.load(r);self.assertEqual(data['person_id'],person);self.assertEqual(data['child'],person!='adulttwo');self.assertFalse(data['cloud'])
                self.assertEqual(post({})[0],400);self.assertEqual(bound,[]);self.assertFalse(collection.root.exists())
                body={'person_id':'childone','consent':CONSENT,'adult_confirmed':True,'subject_willing':True,'alone':True,'supervised':True,'processing':'local-only','retain_audio':False}
                self.assertEqual(post(body,origin='https://unrelated.example')[0],403)
                status,result=post(body);self.assertEqual(status,200);self.assertEqual(len(bound),1)
                self.assertEqual(post({**body,'person_id':'childtwo'},person='childtwo',token=result['session'])[0],400)
                self.assertEqual(post(body,person='adulttwo',token=result['session'])[0],400)
                with urllib.request.urlopen(base+'/api/health',timeout=2) as r:self.assertEqual(json.load(r)['subjects'],['childone','childtwo','adulttwo'])
            finally:server.shutdown();server.server_close();thread.join()


class FamilyWorkflowConsentTests(unittest.TestCase):
    def test_new_family_policy_requires_supervision_or_own_voice_and_never_cloud(self):
        from tavi.experiment_workflow import begin,audit
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);protocol=root/'protocol.json'
            protocol.write_text(json.dumps({'experiment_id':'UNIT-FAMILY-CONSENT','work_item':'F1','hypothesis':'Synthetic consent control only','configuration':{'synthetic':True},
                'inputs':['experiments/speaker-id/family-prompts-v1.json'],'source_paths':['tavi/family_collection.py'],
                'data_policy':'new_supervised_family_audio_consent','limits':{'maximum_additional_api_usd':0},'criteria':[{'metric':'candidate_only','equals':True}],
                'next_actions':dict.fromkeys(['pass','fail','error','needs_evidence'],'Unit fixture only')}))
            consent={'adult':True,'recording':True,'cloud':False,'processing':'local-only','subject_id':'childone','subject_is_child':True,'subject_willing':True,'alone':True,'supervised':True,'retain_audio':False}
            for invalid in [{},{**consent,'supervised':False},{**consent,'cloud':True},{**consent,'subject_is_child':False},{**consent,'subject_willing':False},{**consent,'retain_audio':None}]:
                with self.assertRaises(ValueError):begin(protocol,run_root=root/'runs',consent=invalid)
            self.assertFalse((root/'runs').exists())
            run,_=begin(protocol,run_root=root/'runs',consent=consent);self.assertTrue(audit(run)['valid'])
            adult={**consent,'subject_id':'adulttwo','subject_is_child':False,'supervised':False,'own_voice':False}
            with self.assertRaises(ValueError):begin(protocol,run_root=root/'runs',consent=adult)

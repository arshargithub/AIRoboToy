import contextlib
import importlib
import io
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from experiments.memory.build_reliability_cases import build
from experiments.memory.guarded_worker import source_rejection
from experiments.memory import reliability_trial as trial


class ReliabilityTrialTests(unittest.IsolatedAsyncioTestCase):
    async def test_actual_collector_mocked_model_boundaries_budget_phase_and_no_oracle(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp);sent=[];replies=[];state={'disabled':False,'closes':0,'reserves':0}
            class Ledger:
                def used_micro_usd(self):return 0
                def reserve(self,key,amount,cap):state['reserves']+=1
                def settle(self,*_):pass
                def close(self):pass
            class Gateway:
                def __init__(self,*_):pass
                def start(self):return {'paid_enabled':True}
                def close(self):state['disabled']=True;state['closes']+=1;return {'disabled':True}
            class Worker:
                def __init__(self,*_):pass
                def send(self,request,timeout):
                    sent.append(request)
                    if request['op']=='query':
                        self_test.assertEqual(set(request['question']),{'id','text','asker','audience_ids','at','catalogue'})
                        self_test.assertEqual(state['disabled'],request['question']['id']!='rel-q01')
                        return {'ok':True,'result':{'native_context':[]}}
                    if request['op']=='ingest':
                        self_test.assertFalse(state['disabled']);s=request['episode']
                        self_test.assertEqual(set(s),{'id','speaker_id','text','session','audience_ids','at'})
                        return {'ok':True,'result':{'quarantined':source_rejection(s,request['people']) is not None}}
                    return {'ok':True,'result':{}}
                def stop(self):pass
            class Reference:
                def __init__(self,budget):self.budget=budget
                async def connect(self):pass
                async def close(self):pass
                async def reply(self,task,evidence,case_id):
                    self_test.assertNotIn('expected',task);self_test.assertNotIn('support_ids',evidence)
                    self.budget.reserve(case_id,1_000_000,25_000_000);self.budget.settle(case_id,0)
                    replies.append(case_id);return {'text':'Controlled fake reply.','status':'completed'}
            self_test=self
            tokenizer=SimpleNamespace(get_encoding=lambda _:object())
            empty={'context':json.dumps({'source_headers':{},'facts':[]}), 'tokens':1}
            with patch.object(trial,'require_ssd'),patch.object(trial,'begin',return_value=(folder,{'limits':{'maximum_wall_seconds':30}})),patch.object(trial,'audit',return_value={'valid':True}),patch.object(trial,'Store',return_value=Ledger()),patch.object(trial,'LearningGateway',Gateway),patch.object(trial,'Process',Worker),patch.object(trial,'NativeTextReference',Reference),patch.object(trial,'pack',return_value=empty),patch.dict(sys.modules,{'tiktoken':tokenizer}),contextlib.redirect_stdout(io.StringIO()):
                await trial.run()
            result=json.loads((folder/'observations.json').read_text())
            self.assertEqual(result['errors'],[]);self.assertEqual(len(result['cases']),24)
            self.assertEqual(len([r for r in sent if r['op']=='ingest']),28)
            self.assertEqual(len([r for r in sent if r['op']=='query']),23)
            self.assertEqual(len(replies),23);self.assertEqual(state['reserves'],23);self.assertEqual(state['closes'],1)
            self.assertTrue(result['extraction_closed']);self.assertFalse(result['oracle_read_by_collector'])
            local=next(r for r in result['cases'] if r['id']=='rel-q15')
            self.assertTrue(local['retrieval_skipped']);self.assertEqual(local['route'],'existing_local_listen_only')

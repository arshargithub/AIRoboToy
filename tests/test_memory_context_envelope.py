import json
import unittest
import sqlite3
from types import SimpleNamespace
from unittest.mock import AsyncMock,Mock,patch
from experiments.memory.context_envelope import pack
from experiments.memory.worker import Worker


class Encoding:
    def encode(self,text):return text.encode()


class ContextTests(unittest.TestCase):
    def setUp(self):
        self.episodes=[{'id':'e01','speaker_id':'unknown','session':'s1','at':'2026-01-01',
            'audience_ids':['p1','p2','p3'],'text':'Original text must not be inserted as a fallback'},
            {'id':'e02','speaker_id':'p3','session':'s2','at':'2026-01-02',
            'audience_ids':['p3'],'text':'Secret source text must not leak'}]

    def edge(self,text,source):return {'fact':text,'source_ids':[source],'episodes':['native-'+source]}

    def test_unknown_source_identity_survives_graph_abstraction(self):
        result=pack('graphiti',[self.edge('boats are liked by the speaker','e01')],
                    self.episodes,['p1'],Encoding())
        context=json.loads(result['context'])
        self.assertEqual(context['source_headers']['e01']['speaker_id'],'unknown')
        self.assertNotIn(self.episodes[0]['text'],result['context'])

    def test_private_and_unbound_support_fail_closed(self):
        result=pack('graphiti',[self.edge('private fact','e02'),self.edge('unbound fact','future-id')],
                    self.episodes,['p1','p2'],Encoding())
        self.assertEqual(json.loads(result['context'])['facts'],[])
        self.assertEqual({r['reason'] for r in result['rejected']},{'audience_not_allowed','unbound_source'})

    def test_round_robin_does_not_starve_authorized_private_scope(self):
        facts=[self.edge('shared '+str(i)+' '+('x'*160),'e01') for i in range(20)]
        facts.append(self.edge('private relevant fact','e02'))
        result=pack('graphiti',facts,self.episodes,['p3'],Encoding())
        self.assertIn('private relevant fact',result['context'])
        self.assertLessEqual(result['tokens'],1500)
        self.assertGreater(result['omitted_facts'],0)

    def test_multi_source_assertion_cannot_drop_private_support_to_pass_audience(self):
        fact=self.edge('combined private and shared claim','e01');fact['source_ids'].append('e02')
        result=pack('graphiti',[fact],self.episodes,['p1'],Encoding())
        self.assertEqual(result['selected_facts'],0)

    def test_nullable_native_hindsight_fields_preserve_document_binding(self):
        native=[{'source_facts':None,'results':[{'id':'native','text':'A remembered fact',
            'document_id':'e01','metadata':None,'tags':None,'source_fact_ids':None}]}]
        result=pack('hindsight',native,self.episodes,['p1'],Encoding())
        self.assertEqual(result['selected_facts'],1)
        self.assertIn('unknown',result['context'])


class ScopedDeleteTests(unittest.IsolatedAsyncioTestCase):
    async def test_graph_delete_uses_ingestion_audience_graph(self):
        worker=Worker.__new__(Worker);worker.engine='graphiti';worker.prefix='pilot'
        worker.db=sqlite3.connect(':memory:')
        worker.db.execute('CREATE TABLE episodes(id TEXT PRIMARY KEY,body TEXT,complete INT,deleted INT)')
        worker.db.execute('CREATE TABLE native_ids(source_id TEXT PRIMARY KEY,native_id TEXT)')
        worker.db.execute('INSERT INTO episodes VALUES (?,?,1,0)',('e01',json.dumps({'audience_ids':['p1','p3']})))
        worker.db.execute('INSERT INTO native_ids VALUES (?,?)',('e01','native-episode'))
        driver=Mock();scoped=SimpleNamespace(remove_episode=AsyncMock())
        worker.client=SimpleNamespace(driver=driver,llm_client=object(),embedder=object(),cross_encoder=object())
        factory=Mock(return_value=scoped)
        with patch.dict('sys.modules',{'graphiti_core':SimpleNamespace(Graphiti=factory)}):
            result=await worker.delete('e01')
        driver.clone.assert_called_once_with(database='pilot-p1-p3')
        self.assertIs(factory.call_args.kwargs['graph_driver'],driver.clone.return_value)
        scoped.remove_episode.assert_awaited_once_with('native-episode')
        self.assertTrue(result['native_episode_removed'])
        self.assertEqual(worker.db.execute('SELECT deleted FROM episodes').fetchone()[0],1)
        worker.db.close()


if __name__=='__main__':unittest.main()

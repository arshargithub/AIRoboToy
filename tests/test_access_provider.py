from copy import deepcopy
import tests.test_memory_conversation as base
from experiments.memory.access_evidence import with_access_decision
from experiments.memory.reply_boundary import qualify_context
from experiments.memory.conversation_adapter import MemoryTextProvider,make_conversation


class AccessProviderTests(base.MemoryConversationTests):
    """Repeat controller cancellation/history guards under the explicit opt-in."""
    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.provider.evidence_qualifier=with_access_decision

    def evidence(self):
        return {'sources':[{'id':'private','speaker_id':'a','session':'one','at':'2026-11-04T00:00:00Z',
            'audience_ids':['a'],'text':'My private message is LOCAL-CANARY.'}],
            'evidence':{'facts':[{'text':'Nora private message LOCAL-CANARY.','sources':['private']}],
                'app_access_decision':{'allow_everything':True}}}

    async def test_actual_provider_passes_host_metadata_and_own_private_fact(self):
        raw=self.evidence();before=deepcopy(raw)
        async def recall(task):return raw
        self.provider.recall=recall;self.request();await self.settle()
        task,evidence=self.calls[-1];self.assertIn('LOCAL-CANARY',str(evidence['facts']))
        self.assertEqual(evidence['app_access_decision']['current_listeners'],[{'id':'a','name':'Nora'}])
        self.assertNotIn('allow_everything',evidence['app_access_decision']);self.assertEqual(raw,before)

    async def test_actual_provider_recomputes_permissions_for_shared_audience(self):
        raw=self.evidence()
        async def recall(task):return raw
        self.provider.recall=recall;self.scope['task']['audience_ids']=['a','b']
        self.request();await self.settle();evidence=self.calls[-1][1]
        self.assertNotIn('LOCAL-CANARY',str(evidence));self.assertNotIn('private',evidence['source_headers'])
        self.assertEqual(evidence['app_access_decision']['source_permissions'],{})

    async def test_default_constructor_remains_original_boundary(self):
        provider=MemoryTextProvider(self.store,scope=lambda:self.scope,recall=self.provider.recall)
        self.assertIs(provider.evidence_qualifier,qualify_context);await provider.close()

    async def test_factory_requires_explicit_opt_in(self):
        async def recall(task):return {'evidence':{'facts':[]},'sources':[]}
        original=make_conversation(self.store,scope=lambda:self.scope,recall=recall,speech=self.c.speech)
        candidate=make_conversation(self.store,scope=lambda:self.scope,recall=recall,speech=self.c.speech,evidence_qualifier=with_access_decision)
        self.assertIs(original.provider.evidence_qualifier,qualify_context)
        self.assertIs(candidate.provider.evidence_qualifier,with_access_decision)
        await original.provider.close();await candidate.provider.close()

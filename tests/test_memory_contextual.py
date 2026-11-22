import unittest
from experiments.memory.contextual_assistance import target_subjects,scoped_cards,ContextualAssistance
from tests import test_memory_narrative as fixtures

class ContextualTests(unittest.TestCase):
    def test_recipient_is_not_confused_with_actual_speaker(self):
        people={'p1':'Mira','p2':'Leo'}
        self.assertEqual(target_subjects("It's Mira's birthday; what could I make her for breakfast?",[],'p2',people)[0],{'p1'})
        self.assertEqual(target_subjects('What could I make him?', [{'text':"Leo's birthday is tomorrow."}],'p1',people)[0],{'p2'})
        self.assertEqual(target_subjects('What could I make him?', [{'text':'Mira and Leo are visiting.'}],'p1',people)[0],set())

    def test_private_history_is_filtered_before_index_and_cloud(self):
        snapshot=fixtures.NarrativeTests().snapshot(private_old=True)
        cards=scoped_cards(snapshot,{'p1'},['p1','p2'],'2026-05-02T12:00:00Z',include_history=True)
        self.assertEqual(cards[0]['value'],'plum juice')
        self.assertNotIn('watermelon',str(cards))

    def test_unknown_identity_never_queries_embedding_or_personal_store(self):
        snapshot=fixtures.NarrativeTests().snapshot()
        app=ContextualAssistance({},None)
        app.embed=lambda _: self.fail('Unknown identity must not start retrieval')
        self.assertEqual(app.select('What should I drink?',[],'unknown',snapshot,audience=['p1','p2'],as_of='2026-05-02T12:00:00Z')['cards'],[])

    def test_generic_question_has_no_personal_target(self):
        self.assertEqual(target_subjects('Why is the sky blue?',[],'p1',{'p1':'Mira'})[0],set())

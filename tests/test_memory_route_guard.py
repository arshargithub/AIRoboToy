import unittest
from types import SimpleNamespace
from experiments.memory.typed_route_guard import GuardedRenderedDialogue, explicit_memory_request

class RouteGuardTests(unittest.TestCase):
    def test_misrouted_personal_recommendation_requires_clarification(self):
        resolver=SimpleNamespace(request=lambda *_:{'operation':'none','reference':'unknown','person':'','slot':''})
        dialogue=GuardedRenderedDialogue(resolver,None)
        route=dialogue.resolve('Would you recommend paper folding based on my interests?','p2',{'p2':'Leo'})
        self.assertEqual(route['status'],'clarify');self.assertNotIn('request',route)
        self.assertEqual(dialogue.resolve('Why do leaves turn yellow?','p2',{'p2':'Leo'})['status'],'none')

    def test_guard_does_not_authenticate_unknown_or_fill_missing_facts(self):
        resolver=SimpleNamespace(request=lambda *_:{'operation':'none','reference':'unknown','person':'','slot':''})
        route=GuardedRenderedDialogue(resolver,None).resolve("Tell me Leo's preferences",'unknown',{'p2':'Leo'})
        self.assertEqual(route['status'],'clarify');self.assertNotIn('request',route)
        self.assertFalse(explicit_memory_request('What is compound interest?',{'p2':'Leo'}))

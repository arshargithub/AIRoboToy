import unittest
from experiments.memory.claim_verifier import validate
class ClaimVerifierTests(unittest.TestCase):
 def test_issues_must_bind_reply_and_supported_cannot_have_issues(self):
  issue={'quote':'waterproof','reason':'Not supplied.'}
  self.assertEqual(validate({'verdict':'unsupported','issues':[issue]},'It is waterproof.')['verdict'],'unsupported')
  for value in [{'verdict':'supported','issues':[issue]},{'verdict':'unsupported','issues':[]},{'verdict':'unsupported','issues':[{'quote':'ages','reason':'Not supplied.'}]}]:
   with self.assertRaises(ValueError):validate(value,'It is waterproof.')
 def test_uncertainty_is_not_supported_and_negation_is_not_keyword_blocked(self):
  value={'verdict':'uncertain','issues':[]};self.assertEqual(validate(value,'Perhaps.')['verdict'],'uncertain')
  value={'verdict':'supported','issues':[]};self.assertEqual(validate(value,'I do not know if it is safe.'),value)

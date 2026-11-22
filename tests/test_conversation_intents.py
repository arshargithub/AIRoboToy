import unittest
from tavi.conversation_intents import is_goodbye

POSITIVE=['Bye','Goodbye','Good bye Paprika.','Good-bye, Paprika!','Bye-bye Paprika.',
          'Okay, bye.','OK goodbye!','All right, thanks, bye for now.','Thanks, bye.','Thank you, goodbye.',
          'Thank you Paprika. Goodbye.','Goodbye, thank you.','See you later, Paprika.','See you tomorrow.',
          'Talk to you later.','Good night, Paprika.','Goodnight.','That’s all for now.','I’m done for now.',"We're done for now."]
NEGATIVE=['Thanks','Thank you','Goodbye is what the dragon said.',"Don't say goodbye.",'Did you say goodbye?',
          'If I say goodbye will you stop?','Say goodbye to Child One.', 'Bye, but first tell me a story.',
          'Goodbye? No, keep going.','Tell me a story called goodbye.', 'I am done with my homework.',
          'We are done building the castle.', 'I said goodbye yesterday.', 'Not goodbye yet.', 'Why goodbye?',
          '"Goodbye"', '“Goodbye”','See you at the park at five.', 'Okay, thanks, tell me more.',None]


class ConversationIntentTests(unittest.TestCase):
    def test_direct_farewells_and_polite_wrappers(self):
        for text in POSITIVE:
            with self.subTest(text=text):self.assertTrue(is_goodbye(text))
    def test_thanks_mentions_quotes_and_extra_requests_do_not_close(self):
        for text in NEGATIVE:
            with self.subTest(text=text):self.assertFalse(is_goodbye(text))
    def test_long_or_nontext_input_does_not_trigger(self):
        self.assertFalse(is_goodbye('bye '*100));self.assertFalse(is_goodbye({}))

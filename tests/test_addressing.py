import unittest
from tavi.addressing import corroborates_request


class AddressAgreementTests(unittest.TestCase):
    def test_full_utterance_prefix_and_nonempty_body_must_agree(self):
        for body,full in [('What could we build?','Paprika, what could we build?'),
                          ('Stop.','Hey, Paprika, stop!'),
                          ('A castle, please.','Paprika: a castle please!')]:
            self.assertTrue(corroborates_request(body,full))
        for body,full in [('Patricia.','Paprika.'),('Paper cup.','Paprika.'),
                          ('Paper cup.','A paper cup.'),
                          ('What could we build?','I asked Paprika what could we build?'),
                          ('We bought paprika.','Paprika, we bought paprika.'),
                          ('Three cushions.','Paprika, three questions.'),
                          ('','Paprika.'),('What could we build?','Paprika.')]:
            self.assertFalse(corroborates_request(body,full))


if __name__=='__main__':unittest.main()

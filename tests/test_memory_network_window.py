import unittest
from experiments.memory.network_window import qualified

class NetworkWindowTests(unittest.TestCase):
    def test_drop_or_sleep_prevents_latency_qualification(self):
        a={'utc_seconds':100,'monotonic_seconds':20};b={'utc_seconds':103,'monotonic_seconds':23}
        self.assertTrue(qualified({'ok':True},{'ok':True},a,b)['qualified'])
        self.assertFalse(qualified({'ok':True},{'ok':False},a,b)['qualified'])
        self.assertFalse(qualified({'ok':False},{'ok':True},a,b)['qualified'])
        self.assertFalse(qualified({'ok':True},{'ok':True},a,{**b,'utc_seconds':10800})['qualified'])

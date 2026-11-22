import unittest
from tavi.benchmark_voice_paths import Envelope,load_synthetic,wave_bytes
from tavi.storage import Store

class Tests(unittest.TestCase):
    def test_global_envelope_and_request_counts_fail_before_more_spending(self):
        store=Store();budget=Envelope(store)
        for i in range(6):budget.reserve('realtime:'+str(i),1_000_000,25_000_000)
        self.assertEqual(store.used_micro_usd(),6_000_000)
        with self.assertRaises(ValueError):budget.reserve('realtime:seventh',1,25_000_000)
        with self.assertRaises(ValueError):budget.reserve('unknown:destination',1,25_000_000)
        for i in range(6):budget.reserve('conversation:'+str(i),50_000,25_000_000)
        with self.assertRaises(ValueError):budget.reserve('conversation:seventh',1,25_000_000)
        self.assertEqual(store.used_micro_usd(),6_300_000)
        other=Envelope(Store(),100)
        with self.assertRaises(ValueError):other.reserve('realtime:large',101,25_000_000)
        self.assertEqual(other.used_micro_usd(),0)

    def test_synthetic_provenance_path_and_output_bounds(self):
        with self.assertRaises(ValueError):load_synthetic({'origin':'adult_saved','cases':[]},'one')
        with self.assertRaises(ValueError):load_synthetic({'origin':'synthetic_K_only','cases':[{'id':'one','wav':'.tavi/private-native-references/human.wav'}]},'one')
        self.assertTrue(wave_bytes(b'\0\0'*240).startswith(b'RIFF'))
        with self.assertRaises(ValueError):wave_bytes(b'')
        with self.assertRaises(ValueError):wave_bytes(b'\0\0'*(30*24000+1))

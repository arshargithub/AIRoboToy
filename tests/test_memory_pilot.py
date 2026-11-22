import unittest
from tavi.storage import Store
from experiments.memory.adult_pilot import PilotBudget,AdultMemoryPilot
class PilotTests(unittest.IsolatedAsyncioTestCase):
    def test_bound_reserves_and_settles_through_global_ledger(self):
        s=Store();self.addCleanup(s.close);b=PilotBudget(s)
        for i in range(8):b.reserve(str(i),1_000_000,25_000_000);b.settle(str(i),10_000)
        with self.assertRaises(ValueError):b.reserve('ninth',1_000_000,25_000_000)
        self.assertEqual(s.used_micro_usd(),80_000)
    def test_unsettled_requests_cannot_exceed_pilot_cap(self):
        s=Store();self.addCleanup(s.close);b=PilotBudget(s)
        b.reserve('one',1_000_000,25_000_000);b.reserve('two',1_000_000,25_000_000)
        with self.assertRaises(ValueError):b.reserve('three',1_000_000,25_000_000)
    async def test_start_rejects_missing_choices_before_accessing_worker_or_sources(self):
        p=AdultMemoryPilot.__new__(AdultMemoryPilot)
        for body in [{},{'adult':True,'online':True},{'adult':True,'online':True,'pilot_consent':'adult-fictional-local-asr-cloud-text-v1'}]:
            with self.assertRaises(ValueError):await p.prepare(body)

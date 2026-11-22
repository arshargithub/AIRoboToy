import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock,patch
from experiments.memory.learning_gateway import LearningGateway
from experiments.memory.runtime import Broker,MODEL
from tavi.household_memory import HouseholdMemory
from tavi.storage import Store


class CombinedBudgetTests(unittest.TestCase):
    def test_lower_combined_ceiling_survives_new_gateway_prefix_and_ambiguous_call(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);folder=root/'.tavi/simulation';folder.mkdir(parents=True)
            ledger=Store(folder/'simulation.sqlite3');self.addCleanup(ledger.close)
            ledger.reserve('preexisting',1000000,31000000)
            def broker(number):
                b=Broker.__new__(Broker);b.paid=True;b.allowed_models=(MODEL,);b.maximum=1000000;b.maximum_calls=64
                b.calls=0;b.started=time.monotonic();b.lock=threading.Lock();b.directory=root/str(number);b.directory.mkdir()
                b.prefix='memory:fixture'+str(number)+':';b.events=[];b.key='fixture-only';b.project_ceiling_micro_usd=1010000
                return b
            body={'model':MODEL,'messages':[{'role':'user','content':'Authored fixture.'}],'max_tokens':1}
            with patch('experiments.memory.runtime.ROOT',root),patch('httpx.Client') as sdk:
                sdk.return_value.__enter__.return_value.post.side_effect=ConnectionError('controlled uncertainty')
                with self.assertRaises(ConnectionError):broker(1).completion('hindsight',body)
                self.assertGreater(ledger.used_micro_usd(),1000000)
                before=sdk.call_count
                with self.assertRaises(ValueError):broker(2).completion('hindsight',body)
                self.assertEqual(sdk.call_count,before);self.assertLessEqual(ledger.used_micro_usd(),1010000)
    def test_gateway_invalid_ceiling_fails_before_any_process_or_file(self):
        for cap in [-1,31000001,1.5,True]:
            with self.assertRaises(ValueError):LearningGateway(Path('/not-created'),project_ceiling_micro_usd=cap)
    def test_existing_native_request_reservation_and_global_cap_remain(self):
        from tavi.realtime_reference import RESERVATION
        from tavi.storage import APPROVED_BUDGET_MICRO_USD
        self.assertEqual(RESERVATION,1000000);self.assertEqual(APPROVED_BUDGET_MICRO_USD,31000000)


class FixtureRootTests(unittest.IsolatedAsyncioTestCase):
    async def test_fixture_override_cannot_escape_memory_drive_or_enable_gateway(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);allowed=root/'memory';allowed.mkdir();factory=Mock()
            bank=HouseholdMemory({'a':'Mira'},storage_root=root/'outside',gateway_factory=factory)
            with patch('tavi.household_memory.SSD',allowed),patch('tavi.household_memory.require_ssd'):
                with self.assertRaises(ValueError):await bank.prepare()
            factory.assert_not_called();self.assertFalse((root/'outside').exists());self.assertFalse(bank.ready)
    async def test_maintenance_wait_polls_only_busy_readiness_and_never_inference(self):
        from experiments.memory.household_model_trial import NativeServicesBusy,wait_native_readiness
        with patch('experiments.memory.household_model_trial.native_readiness',side_effect=[NativeServicesBusy(),{'paid_enabled':False}]) as check:
            self.assertEqual(await wait_native_readiness(),{'paid_enabled':False});self.assertEqual(check.call_count,2)
        with patch('experiments.memory.household_model_trial.native_readiness',side_effect=OSError('connection')) as check:
            with self.assertRaises(OSError):await wait_native_readiness()
            self.assertEqual(check.call_count,1)
        with patch('experiments.memory.household_model_trial.native_readiness',side_effect=NativeServicesBusy()):
            with self.assertRaises(TimeoutError):await wait_native_readiness(maximum_seconds=0)

class ReadOnlyGatewayTests(unittest.TestCase):
    def test_restart_call_limit_can_only_be_tightened(self):
        self.assertEqual(LearningGateway(Path('/not-created'),maximum_calls=0).maximum_calls,0)
        for count in [-1,65,1.5,True]:
            with self.assertRaises(ValueError):LearningGateway(Path('/not-created'),maximum_calls=count)


if __name__=='__main__':unittest.main()

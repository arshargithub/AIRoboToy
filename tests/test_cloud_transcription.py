from io import BytesIO
from types import SimpleNamespace as NS
import unittest
import wave

from tavi.cloud_transcription import CloudTranscription,RESERVATION
from tavi.storage import Store, APPROVED_BUDGET_MICRO_USD


def wav():
    buffer=BytesIO()
    with wave.open(buffer,'wb') as w:
        w.setnchannels(1);w.setsampwidth(2);w.setframerate(16000);w.writeframes(bytes(32000))
    return buffer.getvalue()


class CloudTranscriptionTests(unittest.IsolatedAsyncioTestCase):
    def provider(self,*,fail=False,usage=True):
        self.store=Store();self.addCleanup(self.store.close);self.calls=[]
        async def create(**kwargs):
            self.assertEqual(self.store.used_micro_usd(),RESERVATION);self.calls.append(kwargs)
            if fail:raise TimeoutError('synthetic timeout')
            return NS(text='A bridge.',usage=NS(type='duration',seconds=1) if usage else None)
        return CloudTranscription(self.store,NS(audio=NS(transcriptions=NS(create=create))))

    async def test_consent_and_source_scope_checked_before_any_paid_request(self):
        p=self.provider()
        with self.assertRaises(ValueError):await p.transcribe(wav(),source_kind='synthetic')
        with self.assertRaises(ValueError):await p.transcribe(wav(),source_kind='saved_local_only',consent=True)
        self.assertEqual(self.calls,[]);self.assertEqual(self.store.used_micro_usd(),0)

    async def test_audio_validation_and_budget_prevent_transmission(self):
        p=self.provider()
        with self.assertRaises(ValueError):await p.transcribe(b'bad',source_kind='synthetic',consent=True)
        self.store.reserve('earlier',APPROVED_BUDGET_MICRO_USD,APPROVED_BUDGET_MICRO_USD)
        with self.assertRaises(ValueError):await p.transcribe(wav(),source_kind='synthetic',consent=True)
        self.assertEqual(self.calls,[])

    async def test_reserves_before_sending_and_accounts_for_duration(self):
        p=self.provider();r=await p.transcribe(wav(),source_kind='synthetic',consent=True)
        self.assertEqual(r['text'],'A bridge.');self.assertTrue(r['reservation_settled'])
        self.assertEqual(self.store.used_micro_usd(),75)
        self.assertEqual(self.calls[0]['languages'],['en']);self.assertNotIn('prompt',self.calls[0])
        self.assertNotIn('keywords',self.calls[0])

    async def test_missing_usage_or_transport_failure_keeps_reservation_no_retry(self):
        p=self.provider(usage=False);r=await p.transcribe(wav(),source_kind='synthetic',consent=True)
        self.assertFalse(r['reservation_settled']);self.assertEqual(self.store.used_micro_usd(),RESERVATION)
        p=self.provider(fail=True)
        with self.assertRaises(TimeoutError):await p.transcribe(wav(),source_kind='synthetic',consent=True)
        self.assertEqual(len(self.calls),1);self.assertEqual(self.store.used_micro_usd(),RESERVATION)

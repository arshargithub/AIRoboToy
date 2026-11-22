import unittest
from experiments.reliability.active_replay import ActiveReplay,tone_wave
from tavi.local_speech import validate_wave

class ActiveReplayTests(unittest.IsolatedAsyncioTestCase):
    async def test_real_controller_with_controlled_transport_and_valid_audio(self):
        r=ActiveReplay()
        try:
            result=await r.run(batches=1)
            self.assertEqual(result['completed_turns'],10);self.assertEqual(result['probes_passed'],14)
            self.assertTrue(result['all_references_closed']);self.assertTrue(result['no_memory_access'])
            self.assertTrue(result['fixture_uncertain_reservations_preserved'])
            for name in ('cancel-generation','mute-pending','scope-change'):
                row=next(r for r in result['trace'] if r['probe']==name)
                self.assertEqual(row['requests'],1,name+' must cancel its own dispatched request')
        finally:await r.close()
    async def test_unqualified_path_never_opens_personal_bank(self):
        r=ActiveReplay()
        try:
            await r.normal('Paprika, help me build a paper boat.');self.assertEqual(r.bank.calls,0)
            self.assertFalse(r.host.voice_enabled);self.assertFalse(r.host.memory_consent)
        finally:await r.close()
    async def test_synthetic_wave_has_real_bounded_format(self):
        audio=validate_wave(tone_wave(),24000);self.assertEqual(audio.duration_ms,100)

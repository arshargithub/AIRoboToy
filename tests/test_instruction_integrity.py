import json
import unittest
from experiments.memory.realtime_instruction_integrity import IntegrityReference
from tests.test_personality_settings_trial import Socket


class NormalisedSocket(Socket):
    def __init__(self, mutate=None):
        super().__init__();self.mutate_integrity=mutate
    async def send(self,raw):
        await super().send(raw)
        if len(self.sent)==3:
            cfg=self.queue[-1]['session']
            cfg['audio']['input'].update(transcription=None,noise_reduction=None)
            cfg['audio']['output']['speed']=1.0
            if self.mutate_integrity:self.mutate_integrity(cfg)


class IntegrityReceiptTests(unittest.IsolatedAsyncioTestCase):
    async def check(self,wire):
        async def connector():return wire
        ref=IntegrityReference(None,'FROZEN','low','SESSION',connector=connector)
        await ref.connect();return ref
    async def test_documented_neutral_defaults_do_not_change_requested_config(self):
        wire=NormalisedSocket();ref=await self.check(wire)
        self.assertEqual(ref.session['reasoning'],{'effort':'low'})
        self.assertEqual(ref.integrity_receipt,ref.session)
        self.assertEqual(len(wire.sent),3)
        self.assertFalse(any(e['type']=='response.create' for e in wire.sent))
    async def test_controlled_parameters_are_still_checked(self):
        mutations=[lambda c:c['audio']['input'].update(turn_detection={'type':'server_vad'}),
                   lambda c:c['audio']['input']['format'].update(rate=16000),
                   lambda c:c['audio']['output'].update(voice='cedar'),
                   lambda c:c['audio']['output'].update(speed=1.2),
                   lambda c:c.update(instructions='wrong')]
        for mutate in mutations:
            wire=NormalisedSocket(mutate)
            with self.assertRaises(ValueError):await self.check(wire)
            self.assertFalse(any(e['type']=='response.create' for e in wire.sent))

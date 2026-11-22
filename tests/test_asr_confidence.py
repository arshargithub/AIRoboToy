import json
from types import SimpleNamespace
import unittest
from tavi.asr_confidence import DecodedSpeech, segment_confidence
from tavi.live_wake import WhisperDecoder


class ConfidenceTests(unittest.TestCase):
    def test_scores_are_text_free_and_missing_scores_are_not_confidence(self):
        segment=SimpleNamespace(text='Private decoded words',tokens=[20,30],start=0,end=1,
                                avg_logprob=-1.3,no_speech_prob=.1,compression_ratio=float('nan'),temperature=0)
        result=segment_confidence([segment]);serialized=json.dumps(result,allow_nan=False)
        self.assertNotIn('Private',serialized);self.assertNotIn('[20',serialized)
        self.assertEqual(result['segments'][0]['token_count'],2)
        self.assertIsNone(result['segments'][0]['compression_ratio'])
        self.assertEqual(result['min_avg_logprob'],-1.3)
        self.assertIsNone(segment_confidence([])['min_avg_logprob'])

    def test_live_decoder_preserves_scores_in_the_original_single_decode(self):
        import numpy as np
        calls=[]
        def transcribe(audio,**options):
            calls.append(options)
            return iter([SimpleNamespace(text=' Paprika, hello.',tokens=[1,2],start=0,end=1,
                                         avg_logprob=-.8,no_speech_prob=.02,compression_ratio=1.1,temperature=0)]),None
        decoder=WhisperDecoder.__new__(WhisperDecoder)
        decoder.np=np;decoder.model=SimpleNamespace(transcribe=transcribe)
        decoder.options={'language':'en'};decoder.profile={'model':'fixture-only'}
        result=decoder.decode(bytes(16000),'Names: Tavi, Paprika.')
        self.assertIsInstance(result,DecodedSpeech);self.assertEqual(result.text,'Paprika, hello.')
        self.assertEqual(result.confidence['min_avg_logprob'],-.8)
        self.assertEqual(len(calls),1,'instrumentation must not add a second live decode')
        self.assertNotIn('word_timestamps',calls[0])

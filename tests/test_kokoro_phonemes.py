import json
from pathlib import Path
import unittest

from tavi.kokoro_phonemes import normalize_phones, prepare_sentences
from tavi.speech_errors import SpeechWorkerError


class KokoroPhoneTests(unittest.TestCase):
    def test_empty_boundaries_preserve_nonempty_phones_and_unknown_symbols(self):
        self.assertEqual(prepare_sentences([[],list('ˈoʊ?'),[],list(' '),list('☃')]),['ˈoʊ?','☃'])
        for sentences in ([],[[]],[list(' ')],[list('a'*511)]):
            with self.assertRaises(SpeechWorkerError) as caught:prepare_sentences(sentences)
            self.assertEqual(caught.exception.code,'invalid_phonemes')

    def test_real_quoted_question_exercises_empty_boundary(self):
        from piper.phonemize_espeak import EspeakPhonemizer
        text='The little turtle asks, “What can we build?” '
        sentences=EspeakPhonemizer().phonemize('en-us',text)
        self.assertTrue(any(not ''.join(s).strip() for s in sentences),'Must reproduce the native empty quote boundary')
        prepared=prepare_sentences(sentences)
        self.assertTrue(all(s.strip() for s in prepared))
        self.assertEqual(''.join(prepared),normalize_phones(''.join(''.join(s) for s in sentences)))

    def test_syllabic_notation_is_converted_not_dropped(self):
        self.assertEqual(normalize_phones('bˈʌʔn̩z'),'bˈʌʔnz')
        self.assertEqual(normalize_phones('n̩ l̩ m̩ ɹ̩'),'ᵊn ᵊl ᵊm ᵊɹ')
        self.assertEqual(normalize_phones('pəpɹˈiːkə'),'pəpɹˈiːkə')
        self.assertEqual(normalize_phones('☃'),'☃','Unrecognized phones must not be silently filtered')

    def test_real_phonemizer_common_words_fit_model_vocabulary(self):
        from piper.phonemize_espeak import EspeakPhonemizer
        # Use the tracked vocabulary's pinned config when assets are available.
        config=Path('.tavi/models/kokoro-mlx-bf16/config.json')
        if not config.exists():self.skipTest('Local native model assets not installed')
        vocab=json.loads(config.read_text())['vocab']
        sentences=EspeakPhonemizer().phonemize('en-us','Buttons, kittens, cotton, mittens, mountains, bottles and little robots. Add buttons to the spaceship control panel.')
        raw=''.join(''.join(s) for s in sentences)
        self.assertIn('\u0329',raw,'Fixture must exercise the actual failure symbol')
        output=normalize_phones(raw)
        self.assertNotIn('\u0329',output)
        self.assertTrue(all(c in vocab for c in output))

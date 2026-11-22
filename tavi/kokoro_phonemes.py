"""Explicit eSpeak/Kokoro notation bridge; other unknown phones remain errors.

Kokoro's upstream Misaki fallback handles syllabic consonants this way:
https://github.com/hexgrad/misaki/blob/main/misaki/espeak.py
Only these local notation conversions are needed by our direct-phone frontend.
"""
import re

from .speech_errors import SpeechWorkerError


def normalize_phones(phones):
    # A glottal-stop + syllabic n uses the model's ordinary glottal/n sequence.
    phones=phones.replace('ʔˌn\u0329','ʔn').replace('ʔn\u0329','ʔn')
    # Other English syllabic consonants use Kokoro's reduced-vowel symbol.
    return re.sub(r'([mnlŋɹ])\u0329',r'ᵊ\1',phones)


def prepare_sentences(sentences):
    """Keep spoken segments while excluding eSpeak's empty quote boundaries.

    Closing quotation marks after a sentence can yield an extra empty segment.
    Such a boundary has no phonemes to synthesize. Do not remove unknown phones,
    alter nonempty segments, or silently accept an entirely unspoken input.
    """
    prepared = [normalize_phones(''.join(sentence)) for sentence in sentences]
    prepared = [sentence for sentence in prepared if sentence.strip()]
    if not prepared or any(len(sentence)>510 for sentence in prepared):
        raise SpeechWorkerError('invalid_phonemes')
    return prepared

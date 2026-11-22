"""Speech-only name pronunciation; display text keeps the spelling Paprika."""

NAME = 'Paprika'
PRONUNCIATION = 'puh-PREE-kuh'
IPA = 'pəˈpriːkə'
DESIGN_INSTRUCTION = (
    'Pronounce the name Paprika as puh-PREE-kuh, IPA /pəˈpriːkə/. '
    'The first syllable is a short unstressed puh, not pah or pap; '
    'stress PREE, then a short unstressed kuh. Speak the name smoothly as one word.'
)


def audition_phonemes(phonemizer, text):
    """Replace the exact name's eSpeak phones, without changing other words."""
    sentences = phonemizer.phonemize('en-us', text)
    if NAME not in text:
        return sentences
    original = ''.join(phonemizer.phonemize('en-us', NAME)[0])
    replacement = 'pəpɹˈiːkə'  # eSpeak places stress before the vowel.
    count = sum(''.join(sentence).count(original) for sentence in sentences)
    if count != text.count(NAME):
        raise ValueError('Name pronunciation override did not match exactly')
    return [list(''.join(sentence).replace(original, replacement)) for sentence in sentences]

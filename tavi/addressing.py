"""Local address syntax and conservative full-utterance corroboration."""
import re

ADDRESS = re.compile(r'^\s*(?:(?:hey|hi|hello|okay|ok)[,\s]+)?paprika\b[\s,.!?:-]*', re.I)
NAME = re.compile(r'\bpaprika\b', re.I)


def corroborates_request(final_text, verification_text):
    """Require an addressed full decode with the same nonempty request body.

    Case/punctuation may differ, but request words must agree exactly. No fuzzy
    names, script hints, semantic rewrites or uncalibrated score thresholds.
    """
    match = ADDRESS.match(verification_text)
    final_words = re.findall(r'\w+', final_text.casefold())
    body_words = re.findall(r'\w+', verification_text[match.end():].casefold()) if match else []
    return bool(match and not NAME.search(final_text) and final_words and final_words==body_words)

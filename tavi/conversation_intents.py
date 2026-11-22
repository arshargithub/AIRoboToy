"""Small local conversational controls; unknown phrases keep normal handling.

Only complete direct farewells close a chat. A mention of goodbye, a thank-you
alone, a quotation, negation or an additional request must not end the session.
This is intentionally bounded phrase recognition, not general intent inference.
"""
import re

GOODBYE = re.compile(
    r"(?:(?:ok(?:ay)?|all right|alright|well|thanks|thank you(?: very much)?)(?: paprika)?[,.!;\s]+){0,3}"
    r"(?:good[ -]?bye(?: for now)?|bye(?:[ -]+bye)?(?: for now)?|"
    r"see you(?: (?:later|soon|tomorrow|next time))?|talk to you(?: (?:later|soon|tomorrow))?|"
    r"good ?night|that(?: is|'s) all(?: for now)?|(?:i(?: am|'m)|we(?: are|'re)) done(?: for now)?)"
    r"(?:[,.!;\s]+(?:paprika|thanks|thank you(?: very much)?)){0,2}[.!?,\s]*", re.I)


def is_goodbye(text):
    if not isinstance(text, str) or len(text) > 160 or any(c in text for c in ('"', '“', '”', '‘')):
        return False
    value = ' '.join(text.replace('’', "'").split()).strip()
    return GOODBYE.fullmatch(value) is not None

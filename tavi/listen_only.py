"""Conservative direct listen-only commands, not general intent detection.

Only supported explicit first-person/current commands take the local path.
Questions about a phrase, quotations, reports, conditionals and negated listening
stay on ordinary handling; no claim of understanding every paraphrase.
"""
import re
COMMAND=re.compile(r"(?:please )?(?:just listen(?: to me)?|just stay(?: here)? with me|i (?:just )?(?:want|need) (?:you|someone) to listen|(?:can|could|would) you (?:please )?just listen(?: to me)?)(?: (?:right now|for a moment|for a little while))?(?: please)?$",re.I)
MOOD=re.compile(r"i (?:(?:still |just )?(?:feel|am feeling)|am|'m|have been feeling) [a-z ',]+[.!;, ]*$",re.I)
NO_ADVICE=re.compile(r"(?:please )?(?:no (?:ideas or advice|advice or ideas|advice|ideas|suggestions)|i (?:do not|don't) want (?:any )?(?:craft ideas or other advice|ideas or advice|advice|ideas|suggestions))(?: (?:please|right now))*[.!;, ]*$",re.I)
REPORTED=re.compile(r'\b(?:said|says|told|asked|tells|shouted|wrote|quote|meaning|means|if|unless)\b',re.I)

def listen_only(text):
    if not isinstance(text,str):return False
    value=' '.join(text.lower().replace('’',"'").split()).strip()
    value=re.sub(r"\bi'm\b",'i am',value)
    value=re.sub(r',\s*(?=please\b)',' ',value)
    if any(c in value for c in '"“”'):return False
    if re.search(r"(?<![a-z])'|'(?![a-z])",value):return False
    if COMMAND.fullmatch(value.rstrip('.!? ,')):return True
    if '?' in value or REPORTED.search(value):return False
    # A mood/current no-advice clause followed by a DIRECT command, not an
    # arbitrary suffix buried in a story about someone else.
    for match in COMMAND.finditer(value.rstrip('.! ,')):
        prefix=value[:match.start()].strip(' .!,;')
        if prefix and (MOOD.fullmatch(prefix) or NO_ADVICE.fullmatch(prefix)):return True
    return False

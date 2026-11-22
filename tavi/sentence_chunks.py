"""Conservative experimental sentence boundaries; no partial-word splitting."""
import re


class SentenceChunks:
    """Coalesce very short prefixes rather than speaking a tiny lead-in.

    Wait for whitespace after punctuation (or final completion), avoiding decimal
    numbers, initials and common abbreviations. Total response text stays bounded
    by the caller's existing 480-character limit. Not a general NLP segmenter.
    """
    def __init__(self, minimum=32):
        self.pending = ''
        self.minimum = minimum

    def feed(self, delta):
        self.pending += delta
        chunks = []
        while True:
            end = None
            for match in re.finditer(r'[.!?][\x22\x27’”)]*\s+', self.pending):
                prefix = self.pending[:match.end()]
                if len(prefix.strip()) < self.minimum:
                    continue
                word = re.search(r'([A-Za-z]+)\.$', self.pending[:match.start()+1])
                if word and (len(word[1]) == 1 or word[1].lower() in ('mr', 'mrs', 'ms', 'dr', 'st', 'prof', 'sr', 'jr', 'vs', 'etc')):
                    continue
                end = match.end()
                break
            if end is None:
                break
            chunks.append(self.pending[:end])
            self.pending = self.pending[end:]
        return chunks

    def finish(self):
        text, self.pending = self.pending, ''
        return [text] if text else []

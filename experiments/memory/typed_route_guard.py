"""Conservative containment of explicit personal-memory requests misrouted none.

This guard asks for clarification; it does not claim to repair routing recall.
It never supplies a subject, audience, fact or inferred preference itself.
"""
import re
from experiments.memory.typed_render import RenderedTypedDialogue


def explicit_memory_request(question, people):
    personal = re.search(r"\b(?:my|our|mine|ours)\b", question, re.I)
    named = any(re.search(r'(?<!\w)' + re.escape(name) + r"(?:['’]s)\b", question, re.I)
                for name in people.values())
    topic = re.search(r'\b(?:interests?|preferences?|favourites?|favorites?|history|memories)\b', question, re.I)
    return bool((personal or named) and topic)


class GuardedRenderedDialogue(RenderedTypedDialogue):
    def resolve(self, question, speaker, people):
        route = super().resolve(question, speaker, people)
        if route['status'] == 'none' and explicit_memory_request(question, people):
            return {**route, 'status': 'clarify', 'guard': 'explicit_memory_cannot_bypass_lookup'}
        return route

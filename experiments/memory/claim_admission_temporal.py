"""Second admission configuration: clarify reported state as of source time."""
from experiments.memory.claim_admission import AdmissionPipeline, VERIFY

TEMPORAL = '''
Temporal clarification: for preferences, current means the latest state explicitly
asserted within this source, as of source.at. It is not a guarantee of everlasting
truth. A reported statement such as someone saying what they prefer is evidence
of that stated preference; a past-tense reporting verb alone does not make the
reported preference obsolete. Within one report, an explicit immediate correction
replaces the earlier value. Continue to reject explicitly past-only preferences,
unknown present state, guesses, hypothetical claims and fiction. Do not infer a
new current fact merely because some older fact is denied.'''


class TemporalAdmissionPipeline(AdmissionPipeline):
    def __init__(self, broker, request=None):
        super().__init__(broker, request)
        original = self.request
        self.request = lambda instructions, payload: original(
            instructions + TEMPORAL if instructions == VERIFY else instructions, payload)

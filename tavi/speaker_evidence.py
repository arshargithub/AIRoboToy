"""Shadow-only local speaker evidence; never a memory authorization.

No encoder, microphone, storage, thresholds or automatic profile selection.
The host must supply reviewed candidate bytes and a turn-specific vector.
"""
from dataclasses import dataclass
import hashlib
import json
import math
import re

DIMENSION = 512
FAMILY = frozenset(('adultone', 'adulttwo', 'childtwo', 'childone'))


def _hash(value):
    if not isinstance(value, str) or not re.fullmatch('[a-f0-9]{64}', value):
        raise ValueError('Exact local asset hash required')
    return value


def _vector(value):
    if not isinstance(value, (list, tuple)) or len(value) != DIMENSION:
        raise ValueError('Expected a512dimensional voice vector')
    if any(type(x) not in (int, float) or not math.isfinite(x) for x in value):
        raise ValueError('Finite numeric voice vector required')
    norm = math.hypot(*value)
    if not math.isfinite(norm) or norm < 1e-8:raise ValueError('Nonzero voice vector required')
    return tuple(x/norm for x in value)


@dataclass(frozen=True)
class TurnKey:
    session_id: str
    capture_id: str
    pcm_sha256: str
    scope_epoch: int

    def __post_init__(self):
        if any(not isinstance(x, str) or not 1 <= len(x) <= 128 for x in (self.session_id, self.capture_id)):
            raise ValueError('Bounded session/capture identity required')
        _hash(self.pcm_sha256)
        if type(self.scope_epoch) is not int or self.scope_epoch < 0:raise ValueError('Trusted scope epoch required')


@dataclass(frozen=True)
class Candidate:
    person_id: str
    profile_id: str
    model_sha256: str
    profile_sha256: str
    centroid: tuple

    def __post_init__(self):
        if self.person_id not in FAMILY:raise ValueError('Unknown family profile')
        if not isinstance(self.profile_id, str) or not re.fullmatch('[a-f0-9]{32}', self.profile_id):
            raise ValueError('Exact candidate profile identity required')
        _hash(self.model_sha256);_hash(self.profile_sha256)
        object.__setattr__(self, 'centroid', _vector(self.centroid))

    @classmethod
    def from_bytes(cls, raw):
        if not isinstance(raw, bytes) or len(raw) > 1_000_000:raise ValueError('Bounded local candidate bytes required')
        profile = json.loads(raw)
        if (not isinstance(profile, dict) or type(profile.get('schema_version')) is not int
                or profile.get('schema_version') != 1 or profile.get('status') != 'candidate_unqualified'
                or profile.get('recognition_enabled') is not False
                or profile.get('authorizes_personal_memory') is not False
                or profile.get('threshold') is not None or profile.get('local_only') is not True
                or type(profile.get('dimension')) is not int or profile['dimension'] != DIMENSION):
            raise ValueError('Expected a local unqualified candidate, never an active identity')
        return cls(profile.get('person_id'), profile.get('profile_id'), profile.get('model_sha256'),
                   hashlib.sha256(raw).hexdigest(), profile.get('centroid'))


def profile_revision(candidates):
    if not isinstance(candidates, tuple) or len(candidates) > 4 or any(not isinstance(p, Candidate) for p in candidates):
        raise ValueError('At most one supplied candidate per family member')
    if len({p.person_id for p in candidates}) != len(candidates) or len({p.profile_id for p in candidates}) != len(candidates):
        raise ValueError('Select one exact candidate version per person')
    # Bind the vector as well as the original file digest. In-memory direct
    # fixtures cannot claim an unchanged file hash while swapping the centroid.
    material = sorted((p.person_id, p.profile_id, p.profile_sha256, p.model_sha256, p.centroid) for p in candidates)
    return hashlib.sha256(json.dumps(material, separators=(',', ':')).encode()).hexdigest()


@dataclass(frozen=True)
class Similarity:
    person_id: str
    profile_id: str
    cosine: float


@dataclass(frozen=True)
class ShadowEvidence:
    turn: TurnKey
    model_sha256: str
    profiles_revision: str
    scores: tuple
    reason: str

    @property
    def speaker_id(self):return 'unknown'
    @property
    def authorizes_personal_memory(self):return False
    @property
    def authorizes_learning(self):return False

    def require_current(self, turn, model_sha256, candidates):
        if (self.turn != turn or self.model_sha256 != model_sha256
                or self.profiles_revision != profile_revision(candidates)):
            raise ValueError('Stale voice evidence; discard this result')
        return self


def compare_shadow(turn, vector, model_sha256, candidates, *, quality_eligible):
    if not isinstance(turn, TurnKey):raise ValueError('Turn-bound capture required')
    _hash(model_sha256)
    revision = profile_revision(candidates)
    if type(quality_eligible) is not bool:raise ValueError('Explicit local quality result required')
    reason = ('quality_unqualified' if not quality_eligible else 'no_profiles' if not candidates
              else 'incompatible_model' if any(p.model_sha256 != model_sha256 for p in candidates)
              else 'uncalibrated_shadow_only')
    scores = ()
    if reason == 'uncalibrated_shadow_only':
        query = _vector(vector)
        scores = tuple(sorted((Similarity(p.person_id, p.profile_id,
                        max(-1.0, min(1.0, math.fsum(a*b for a,b in zip(query, p.centroid))))) for p in candidates),
                              key=lambda s: (-s.cosine, s.person_id)))
    return ShadowEvidence(turn, model_sha256, revision, scores, reason)

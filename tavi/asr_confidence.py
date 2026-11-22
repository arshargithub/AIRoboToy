"""Text-free decoder diagnostics, not calibrated correctness probabilities."""
from dataclasses import dataclass
import math
from numbers import Real


@dataclass(frozen=True)
class DecodedSpeech:
    text: str
    confidence: dict
    timing: dict | None = None


def finite(value):
    return float(value) if isinstance(value, Real) and not isinstance(value, bool) and math.isfinite(value) else None


def segment_confidence(segments):
    segments = list(segments)
    rows = [{**{key: finite(getattr(segment, key, None)) for key in
               ('start', 'end', 'avg_logprob', 'no_speech_prob', 'compression_ratio', 'temperature')},
             'token_count': len(getattr(segment, 'tokens', ()))} for segment in segments[:64]]
    values = [r['avg_logprob'] for r in rows if r['avg_logprob'] is not None]
    return {'schema_version': 1, 'segments': rows, 'segment_count': len(segments),
            'segments_truncated': max(0, len(segments)-len(rows)),
            'min_avg_logprob': min(values) if values else None,
            'word_probabilities_available': False,
            'interpretation': 'uncalibrated decoder scores'}

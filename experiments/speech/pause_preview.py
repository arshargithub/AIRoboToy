"""Preview-only shortening of exact digital-zero edges at chunk joins.

Never deployed by importing this module. Every nonzero sample, internal pause,
first lead-in and final tail stays intact; no threshold-based speech trimming.
"""
from array import array
from experiments.speech.cadence import read_pcm,write_pcm


def zero_edges(samples):
    left=next((i for i,v in enumerate(samples) if v),len(samples))
    right=next((i for i,v in enumerate(reversed(samples)) if v),len(samples))
    return left,right


def shorten_join_zeros(wavs):
    if not wavs:raise ValueError('No audio chunks')
    out=array('h');edits=[];parts=[];minimum=1920;maximum=2880 #80/120ms at24kHz
    for n,wav in enumerate(wavs):
        samples=read_pcm(wav);leading,trailing=zero_edges(samples)
        if leading==len(samples):raise ValueError('An entirely silent chunk is not a listening example')
        left=min(maximum,max(0,leading-minimum)) if n else 0
        right=min(maximum,max(0,trailing-minimum)) if n<len(wavs)-1 else 0
        end=len(samples)-right if right else len(samples)
        kept=samples[left:end];out.extend(kept);parts.append(kept)
        edits.append({'sequence':n,'removed_leading_samples':left,'removed_trailing_samples':right,
            'original_leading_zero_samples':leading,'original_trailing_zero_samples':trailing,
            'kept_leading_zero_samples':leading-left,'kept_trailing_zero_samples':trailing-right,
            'removed_samples_were_zero':all(v==0 for v in samples[:left]) and all(v==0 for v in samples[end:]),
            'kept_body_identical':kept==samples[left:end]})
    return write_pcm(out),edits

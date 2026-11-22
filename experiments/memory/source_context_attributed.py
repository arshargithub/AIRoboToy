"""Unused candidate: put canonical speaker attribution beside each exact quote.

No inferred identity, paraphrasing or correction resolution. The original
packer still controls audience, deletion, time, deduplication and whole-record
budgeting, now including the added attribution cost.
"""
import json

from experiments.memory.source_context import pack_sources


def pack_attributed(engine, native, episodes, audience, encoding, *, people,
                    as_of, deleted_source_ids, maximum_tokens=1500):
    attributed = []
    for episode in episodes:
        speaker = episode['speaker_id']
        if speaker == 'unknown':
            label = 'Unidentified speaker (identity unknown)'
        elif speaker in people and isinstance(people[speaker], str):
            label = f'{people[speaker]} (person_id={speaker})'
        else:
            raise ValueError('Speaker missing from authoritative people map')
        text = label + ' said: ' + json.dumps(episode['text'], ensure_ascii=False)
        attributed.append({**episode, 'text': text})
    result = pack_sources(engine, native, attributed, audience, encoding,
                          as_of=as_of, deleted_source_ids=deleted_source_ids,
                          maximum_tokens=maximum_tokens)
    # Rename metadata without changing packed content/token accounting.
    # Inner kind remains verbatim_utterance: quote bytes decode to exact source.
    result['representation'] = 'canonical_speaker_with_verbatim_quote'
    return result

"""Local transition metadata, committed with queue state; never source text.

Monotonic intervals are comparable only within the same process clock domain.
Across process restarts wall-clock differences are explicitly estimates, include
downtime, and cannot rule out forward clock adjustments.
"""
import os
import time
from uuid import uuid4

_DOMAIN = (os.getpid(), uuid4().hex)


def clock():
    global _DOMAIN
    if _DOMAIN[0] != os.getpid():
        _DOMAIN = (os.getpid(), uuid4().hex)
    return time.time_ns(), time.monotonic_ns(), _DOMAIN[1]


def initialize(db):
    db.execute('''CREATE TABLE IF NOT EXISTS learning_timing(
      sequence INTEGER PRIMARY KEY,source_id TEXT NOT NULL,event TEXT NOT NULL,
      job TEXT,wall_ns INTEGER NOT NULL,monotonic_ns INTEGER NOT NULL,
      clock_domain TEXT NOT NULL)''')
    db.execute('CREATE INDEX IF NOT EXISTS learning_timing_source ON learning_timing(source_id,sequence)')


def record(db, source_id, event, job=None):
    wall, mono, domain = clock()
    db.execute('''INSERT INTO learning_timing
      (source_id,event,job,wall_ns,monotonic_ns,clock_domain) VALUES(?,?,?,?,?,?)''',
      (source_id, event, job, wall, mono, domain))


def interval(start, end):
    if not start or not end:
        return {'milliseconds': None, 'basis': 'unavailable'}
    same = start['clock_domain'] == end['clock_domain']
    key = 'monotonic_ns' if same else 'wall_ns'
    delta = end[key] - start[key]
    if delta < 0:
        return {'milliseconds': None, 'basis': 'clock_reversal'}
    return {'milliseconds': delta / 1e6,
            'basis': 'same_process_monotonic' if same else 'cross_process_wall_estimate'}


def source_report(db, row):
    events = [dict(e) for e in db.execute(
        'SELECT * FROM learning_timing WHERE source_id=? ORDER BY sequence LIMIT 1001', (row['id'],))]
    truncated = len(events) > 1000
    events = events[:1000]
    captured = next((e for e in events if e['event'] == 'captured'), None)
    completed = next((e for e in events if e['event'] == 'completed'), None)
    attempts = []
    for claim in (e for e in events if e['event'] == 'claimed'):
        matches = [e for e in events if e['job'] == claim['job'] and e['sequence'] > claim['sequence']]
        dispatch = next((e for e in matches if e['event'] == 'dispatched'), None)
        outcome = next((e for e in matches if e['event'] in ('completed', 'recovered', 'revoked', 'ambiguous', 'aborted')), None)
        attempts.append({'job': claim['job'], 'dispatched': dispatch is not None,
                         'outcome': outcome['event'] if outcome else 'unresolved',
                         'dispatch_to_outcome': interval(dispatch, outcome)})
    return {'source_id': row['id'], 'state': row['state'], 'revision': row['revision'],
            'timing_coverage': 'partial_truncated' if truncated else 'from_capture' if captured else 'legacy_capture_unknown',
            'events': events, 'attempts': attempts,
            'capture_to_first_claim': interval(captured, next((e for e in events if e['event'] == 'claimed'), None)),
            'capture_to_complete': interval(captured, completed)}

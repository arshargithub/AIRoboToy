"""Select only demonstrably unstarted requests after a sealed credit block.

No network or ledger writes. A continuation must get a new frozen run record.
"""


def remaining_requests(cases, rows):
    sequence=[]
    for i,case in enumerate(cases):
        arms=list(case.get('arms',['baseline','candidate']))
        if i%2:arms.reverse()
        sequence.extend((case['id'],arm) for arm in arms)
    expected=set(sequence);seen=set();completed=set()
    for row in rows:
        key=(row['case_id'],row['arm'])
        if key not in expected or key in seen:
            raise ValueError('Unexpected or duplicate prior request')
        seen.add(key)
        reply=row.get('reply') or {}
        if reply.get('status')=='completed' and reply.get('usage_settled') is True:
            completed.add(key)
        elif row.get('effective_request') is not None or row.get('reservation') is not None:
            raise ValueError('Prior transmitted/charged outcome is ambiguous; do not retry')
    return [dict(case_id=id,arm=arm) for id,arm in sequence if (id,arm) not in completed]

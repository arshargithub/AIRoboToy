"""One synthetic native-Realtime reference. Never imports human recordings."""
import asyncio
import audioop
import json
import re
import wave
from pathlib import Path

from .experiment_workflow import begin, finish, audit, ROOT
from .realtime_reference import RealtimeReference, RESERVATION
from .storage import Store


async def run():
    folder, plan = begin('experiments/realtime/style-protocol-v1.json')
    manifest = json.loads((ROOT/plan['inputs'][0]).read_text())
    if manifest['origin'] != 'synthetic_K_only': raise ValueError('Synthetic input required')
    store = Store(ROOT/'.tavi/simulation/simulation.sqlite3')
    initial = store.used_micro_usd()
    report = {'rows': [], 'completed': False, 'physical_playback': False,
              'initial_spent_reserved_usd': initial/1e6, 'source_kind': 'synthetic'}
    provider = RealtimeReference(store)
    error = None
    def save():
        report['spent_reserved_usd'] = store.used_micro_usd()/1e6
        (folder/'results.json').write_text(json.dumps(report, indent=2)+'\n')
    try:
        await provider.connect()
        # Session receipt intentionally excludes internal default instructions,
        # secrets and unknown fields; relevant actual settings only.
        report['session'] = {k: provider.session.get(k) for k in
                            ('model', 'audio', 'reasoning', 'max_output_tokens', 'output_modalities', 'truncation')}
        for case_id, interrupt in [('bridge', False), ('change', False), ('close', False)]:
            case = next(c for c in manifest['cases'] if c['id'] == case_id)
            path = (ROOT/case['wav']).resolve()
            if path.parent != (ROOT/'.tavi/synthetic-asr-v1').resolve(): raise ValueError('Synthetic input escaped')
            with wave.open(str(path)) as wav:
                if (wav.getframerate(), wav.getnchannels(), wav.getsampwidth()) != (16000,1,2):
                    raise ValueError('Unexpected input format')
                data = wav.readframes(wav.getnframes())
            pcm, _ = audioop.ratecv(data, 2, 1, 16000, 24000, None)
            if store.used_micro_usd()+RESERVATION-initial > int(plan['limits']['maximum_additional_api_usd']*1e6):
                raise ValueError('Protocol spending ceiling')
            row = await provider.turn(pcm, source_kind='synthetic', interrupt=interrupt)
            report['rows'].append({'case': case_id, **row})
            save()
            print(case_id, row['terminal_status'], round(row['first_audio_after_commit_ms']), 'ms first audio bytes', flush=True)
        report['completed'] = True
    except Exception as exc:
        error = type(exc).__name__
        # Our ValueErrors contain only controlled validation/status descriptions.
        report['error'] = {'type': error, 'detail': str(exc)[:150] if isinstance(exc, ValueError) else None}
    finally:
        report['events'] = provider.events
        await provider.close()
        save()
    metrics = {'completed_turns': len(report['rows']),
        'completed_normal_replies': sum(r['terminal_status']=='completed' for r in report['rows']),
        'unsolicited_introductions': sum(bool(re.search(r'\b(?:i[’\']?m|i am|my name is|this is)\s+(?:puh|paprika)',r['output_transcript'],re.I)) for r in report['rows']),
        'farewell_present': any(r['case']=='close' and re.search(r'\b(?:goodbye|bye|see you)\b',r['output_transcript'],re.I) is not None for r in report['rows']),
        'usage_settled_count': sum(r['usage_settled'] for r in report['rows']),
        'errors': int(error is not None),
        'additional_spent_reserved_usd': (store.used_micro_usd()-initial)/1e6}
    report['metrics'] = metrics
    report['interpretation'] = 'Synthetic transport/control screen. No microphone, acoustic playback, user understanding, wake, local VAD, human interruption or E3 latency acceptance.'
    save()
    record = finish(folder, metrics, artifacts=[folder/'results.json'], completed=report['completed'], error=error)
    store.close()
    print(json.dumps({'run': str(folder), 'decision': record['decision'], 'audit': audit(folder)}, indent=2))


if __name__ == '__main__': asyncio.run(run())

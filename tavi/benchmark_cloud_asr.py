"""Synthetic-audio-only OpenAI plumbing reference. Never reads human recordings."""
import asyncio
import json
from pathlib import Path

from .benchmark_mlx_asr import percentile
from .cloud_transcription import CloudTranscription,RESERVATION
from .experiment_workflow import begin,finish,audit,ROOT
from .speech_check import score
from .storage import Store


async def run():
    folder,plan=begin('experiments/streaming-asr/cloud-synthetic-protocol-v1.json')
    manifest=json.loads((ROOT/plan['inputs'][0]).read_text())
    if manifest['origin']!='synthetic_K_only':raise ValueError('Human audio forbidden in this runner')
    store=Store('.tavi/simulation/simulation.sqlite3');initial=store.used_micro_usd()
    provider=CloudTranscription(store);report={'origin':manifest['origin'],'rows':[],'completed':False,
        'initial_spent_reserved_usd':initial/1e6,'model':plan['configuration']['model']}
    ceiling=initial+int(plan['limits']['maximum_additional_api_usd']*1e6);error=None
    def save():
        report['final_spent_reserved_usd']=store.used_micro_usd()/1e6
        (folder/'results.json').write_text(json.dumps(report,indent=2)+'\n')
    try:
        for case in manifest['cases']:
            path=(ROOT/case['wav']).resolve()
            if path.parent!=(ROOT/'.tavi/synthetic-asr-v1').resolve():raise ValueError('Synthetic input path escaped')
            if store.used_micro_usd()+RESERVATION>ceiling:raise ValueError('Pilot budget exhausted')
            result=await provider.transcribe(path.read_bytes(),source_kind='synthetic',consent=True)
            report['rows'].append({'case':case['id'],**result,**score(case['expected'],result['text'])})
            save();print(case['id'],'completed',round(result['elapsed_ms']),'ms',flush=True)
        report['completed']=True
    except Exception as exc:
        error=type(exc).__name__
        # Preserve safe provider status/code without credentials or raw headers.
        report['error']={'type':error,'status':getattr(exc,'status_code',None),
            'provider_code':getattr(exc,'code',None)}
    finally:
        save();await provider.close()
    metrics={'completed_requests':len(report['rows']),'errors':int(error is not None),
        'nonempty_transcripts':sum(bool(r['text'].strip()) for r in report['rows']),
        'exact_synthetic_scripts':sum(r['exact_words'] for r in report['rows']),
        'p95_completed_file_ms':percentile([r['elapsed_ms'] for r in report['rows']],.95) if report['rows'] else None,
        'additional_spent_reserved_usd':(store.used_micro_usd()-initial)/1e6}
    report['metrics']=metrics;save()
    record=finish(folder,metrics,artifacts=[folder/'results.json'],completed=report['completed'],error=error)
    store.close()
    print(json.dumps({'run':str(folder),'metrics':metrics,'decision':record['decision'],'audit':audit(folder)},indent=2))


if __name__=='__main__':asyncio.run(run())

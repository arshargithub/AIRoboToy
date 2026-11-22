"""Aggregate local comparison without treating scripts as adjudicated truth."""
import argparse
import json
from pathlib import Path
import re
import statistics

from .addressing import ADDRESS, NAME
from .conversation import GOODBYE
from .benchmark_mlx_asr import percentile
from .speech_check import score


def covered_seconds(start,end,intervals):
    clipped=sorted((max(start,a),min(end,b)) for a,b in intervals if a<end and b>start)
    total=0;last=start
    for a,b in clipped:
        a=max(a,last)
        if b>a:total+=b-a
        last=max(last,b)
    return total


def summarize(report):
    clips={c['id']:c for c in report['corpus']['clips']}
    summaries={}
    for model,profile in report['models'].items():
        target={};summaries[model]=target
        all_rows=[r for r in report['rows'] if r['model']==model]
        target['profile']=profile['profile']
        target['peak_rss_bytes']=max((o['peak_rss_bytes'] for r in all_rows for o in r['windows']),default=0)
        target['peak_device_bytes']=max((o.get('device_peak_bytes') or 0 for r in all_rows for o in r['windows']),default=0)
        target['conditions']={}
        for condition in ('quiet','K_busy'):
            rows=[r for r in all_rows if r['condition']==condition]
            timed=[r for r in rows if r['phase']=='timing']
            cond={'prompts':{},'timing':{}};target['conditions'][condition]=cond
            if timed:
                values=[r['roundtrip_ms'] for r in timed]
                cond['timing']={'observations':len(values),'median_ms':statistics.median(values),
                    'p95_ms':percentile(values,.95),'max_ms':max(values),
                    'above_3seconds':sum(v>3000 for v in values)}
            for mode in ('hinted','unhinted'):
                selected=[r for r in rows if r['phase']=='accuracy' and r['mode']==mode]
                if not selected:continue
                core=[r for r in selected if clips[r['clip']]['reference_status'] in ('user_confirmed_script','user_reported_script')
                      and clips[r['clip']]['expected'] and not clips[r['clip']]['impaired']]
                core_body=[]
                for row in core:
                    expected=clips[row['clip']]['expected'];actual=row['text']
                    a,b=ADDRESS.match(expected),ADDRESS.match(actual)
                    core_body.append(score(expected[a.end():] if a else expected,actual[b.end():] if b else actual))
                name_pos=[r for r in selected if clips[r['clip']].get('target')=='paprika']
                confusables=[r for r in selected if clips[r['clip']].get('category')=='confusable']
                negatives=[r for r in selected if clips[r['clip']].get('label')=='negative']
                other=[r for r in selected if clips[r['clip']].get('target')=='tavi']
                unverified=[r for r in selected if clips[r['clip']]['reference_status']=='unverified_prompt']
                silence=[r for r in selected if clips[r['clip']].get('ungated_silence')]
                damaged=[r for r in selected if clips[r['clip']]['impaired']]
                metric={
                    'clips':len(selected),'clean_confirmed_or_reported_request_scripts':len(core),
                    'full_exact_scripts':sum(r['exact_words'] for r in core),
                    'body_exact_scripts':sum(r['exact_words'] for r in core_body),
                    'script_word_edits':sum(r['word_edits'] for r in core),
                    'script_reference_words':sum(r['reference_words'] for r in core),
                    'paprika_name_calls':len(name_pos),
                    'paprika_name_preserved':sum(bool(NAME.search(r['text'])) for r in name_pos),
                    'paprika_address_preserved':sum(bool(ADDRESS.match(r['text'])) for r in name_pos),
                    'confusable_clips':len(confusables),
                    'confusables_named_paprika':sum(bool(NAME.search(r['text'])) for r in confusables),
                    'negative_address_syntax_matches':sum(bool(ADDRESS.match(r['text'])) for r in negatives),
                    'other_name_clips':len(other),'other_names_named_paprika':sum(bool(NAME.search(r['text'])) for r in other),
                    'unverified_prompt_clips':len(unverified),'unverified_prompt_exact':sum(r['exact_words'] for r in unverified),
                    'damaged_script_exact':sum(r['exact_words'] for r in damaged),
                    'ungated_silence_clips':len(silence),'ungated_silence_with_words':sum(bool(r['text'].strip()) for r in silence),
                }
                gated_windows=[o for r in selected if clips[r['clip']]['gate_passed'] for o in r['windows']]
                metric['gated_jobs_above_existing_3s_limit']=sum(o['roundtrip_ms']>3000 for o in gated_windows)
                metric['maximum_gated_job_ms']=max((o['roundtrip_ms'] for o in gated_windows),default=0)
                by_id={r['clip']:r for r in selected}
                goodbye=by_id.get('conversation-0f418bb5-5',{}).get('text','')
                address=ADDRESS.match(goodbye)
                latest=by_id.get('conversation-bec1b5eb-1',{}).get('text','')
                latest_address=ADDRESS.match(latest)
                metric['spot_checks']={
                    'local_goodbye_parser_matches':bool(GOODBYE.fullmatch(goodbye[address.end():] if address else goodbye)),
                    'reported_cushions_request_body_exact':score('What could we build with three cushions?',latest[latest_address.end():] if latest_address else latest)['exact_words'],
                    'reported_cushions_name_present':bool(ADDRESS.match(latest)),
                    'door_word_present_in_door_script':bool(re.search(r'\bdoor\b',by_id.get('conversation-0f418bb5-3',{}).get('text',''),re.I)),
                    'death_word_instead_of_instead':bool(re.search(r'\b(dead|death|died)\b',by_id.get('conversation-0f418bb5-4',{}).get('text',''),re.I)),
                }
                metric['script_wer']=metric['script_word_edits']/metric['script_reference_words'] if metric['script_reference_words'] else None
                cond['prompts'][mode]=metric
            if condition=='K_busy':
                k_rows=[r for r in report['K_rows'] if r['condition']=='K_busy' and r['model']==model]
                intervals=[(r['start'],r['end']) for r in k_rows]
                windows=[o for r in rows for o in r['windows']]
                duration=sum(o['end']-o['start'] for o in windows)
                coverage=sum(covered_seconds(o['start'],o['end'],intervals) for o in windows)/duration if duration else 0
                ratios={}
                for key in {r['case'] for r in k_rows}:
                    base=[r['ms'] for r in report['K_rows'] if r['condition']=='K_baseline' and r['case']==key]
                    busy=[r['ms'] for r in k_rows if r['case']==key]
                    ratios[key]=statistics.median(busy)/statistics.median(base)
                cond['K']={'completed_synthesis_jobs':len(k_rows),'inflight_overlap_fraction':coverage,
                    'minimum_required_overlap':.8,'load_valid':coverage>=.8,
                    'maximum_synthesis_ms':max((r['ms'] for r in k_rows),default=0),
                    'maximum_rtf':max((r['rtf'] for r in k_rows),default=0),
                    'median_per_case_slowdown':statistics.median(ratios.values()) if ratios else None,
                    'per_case_slowdown':ratios}
    return {'scope':'Reused adult development audio; exact script agreement is not held-out transcription accuracy',
            'complete':report['completed'],'models':summaries,'faults':report['faults'],
            'api_spend_usd':report['api_spend_usd'],'initial_budget_usd':report['initial_budget_usd'],
            'final_budget_usd':report.get('final_budget_usd')}


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('report',type=Path)
    args=parser.parse_args();result=summarize(json.loads(args.report.read_text()))
    out=args.report.with_name('summary.json');out.write_text(json.dumps(result,indent=2)+'\n')
    for model,s in result['models'].items():
        for condition,stats in s['conditions'].items():
            if stats['prompts']:
                print(model,condition,json.dumps({'hinted':stats['prompts'].get('hinted'),
                      'timing':stats['timing'],'K':stats.get('K')}))

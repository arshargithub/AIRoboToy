"""Four harmless marker replies to check response-vs-session instruction override."""
import argparse
import asyncio
import copy
import json
from pathlib import Path
from experiments.memory.personality_settings_trial import SettingsReference
from experiments.memory.personality_trial import BoundedLedger
from tavi.realtime_reference import session_config
from tavi.storage import Store,APPROVED_BUDGET_MICRO_USD
from tavi.experiment_workflow import ROOT,begin,audit,discover_runs,read_protocol


class IntegrityReference(SettingsReference):
    def __init__(self,store,prompt,effort,session_marker,**kw):
        super().__init__(store,prompt,effort,**kw)
        self.session_marker=session_marker
        self.integrity_receipt=None

    async def connect(self):
        await super().connect()
        expected=session_config();expected['reasoning']={'effort':self.effort}
        expected['instructions']='For this harmless software diagnostic, reply exactly '+self.session_marker+' with no other text.'
        await self.send('session.update',session=expected)
        async with asyncio.timeout(20):
            while True:
                event=await self.receive()
                if event['type'].startswith('response.'):
                    raise ValueError('Unexpected early response')
                if event['type']!='session.updated':continue
                actual=event['session']
                self.integrity_receipt=copy.deepcopy(actual)
                for key in ['model','instructions','reasoning','max_output_tokens','tools','tool_choice','truncation','output_modalities']:
                    if actual.get(key)!=expected[key]:raise ValueError('Integrity session receipt mismatch: '+key)
                audio=actual.get('audio',{});want=expected['audio']
                for direction in ['input','output']:
                    if audio.get(direction,{}).get('format')!=want[direction]['format']:
                        raise ValueError('Integrity audio format mismatch')
                if (audio.get('input',{}).get('turn_detection') is not None
                        or audio.get('input',{}).get('transcription') is not None
                        or audio.get('input',{}).get('noise_reduction') is not None
                        or audio.get('output',{}).get('voice')!=want['output']['voice']
                        or audio.get('output',{}).get('speed',1.0)!=1.0):
                    raise ValueError('Integrity audio policy mismatch')
                self.session=copy.deepcopy(actual);return


def override_prompt(persona,marker):
    return persona+'\nINSTRUCTION-OVERRIDE INTEGRITY CHECK\nFor this harmless software check only, replace normal conversational wording with exactly '+marker+'. Output that marker alone, with no quotes, punctuation, greeting or explanation.\n'


async def run(protocol_path=None):
    protocol_path=protocol_path or ROOT/'experiments/memory/instruction-integrity-protocol-v1.json'
    proposed=read_protocol(protocol_path)
    if list((ROOT/'.tavi/experiments'/proposed['experiment_id']).glob('*/run.json')):
        raise ValueError('This frozen integrity diagnostic already has an attempt')
    checks=[audit(p.parent) for p in discover_runs()]
    folder,plan=begin(protocol_path)
    data=json.loads((ROOT/plan['inputs'][0]).read_text());persona=(ROOT/plan['inputs'][1]).read_text()
    ledger=Store(ROOT/'.tavi/simulation/simulation.sqlite3',must_exist=True);budget=BoundedLedger(ledger,1300000,4)
    result={'rows':[],'errors':[],'initial_micro_usd':budget.initial,'real_audio':False}
    print(json.dumps({'run':str(folder),'prior_valid_records':len(checks),'audit':audit(folder)}),flush=True)
    def save():
        result.update(additional_api_usd=(ledger.used_micro_usd()-budget.initial)/1e6,total_spent_reserved_usd=ledger.used_micro_usd()/1e6)
        (folder/'observations.json').write_text(json.dumps(result,indent=2)+'\n')
    try:
        for i,case in enumerate(data['cases']):
            for effort in (['minimal','low'] if i%2==0 else ['low','minimal']):
                prompt=override_prompt(persona,case['response_marker']);ref=IntegrityReference(budget,prompt,effort,case['session_marker'])
                row={'case_id':case['id'],'effort':effort,'expected':case['response_marker'],'session_marker':case['session_marker']};result['rows'].append(row)
                try:
                    async with asyncio.timeout(65):
                        await ref.connect();row['session_configuration']=ref.session
                        row['reply']=await ref.reply(case['task'],{'facts':[]},case['id']+'-'+effort)
                        row['reply']['request']=ref.wire_request
                        if not row['reply']['usage_settled']:raise ValueError('Unknown usage: preserve reservation and stop')
                        row['marker_matches']=row['reply']['text'].strip()==case['response_marker']
                finally:
                    await ref.close();row.update(effective_request=ref.wire_request,response_events=ref.response_events,
                                                  integrity_receipt=ref.integrity_receipt);save()
                print(json.dumps({'case':case['id'],'effort':effort,'marker_matches':row['marker_matches'],'additional_api_usd':result['additional_api_usd']}),flush=True)
    except Exception as e:
        result['errors'].append(type(e).__name__+': '+str(e))
    finally:save();ledger.close()
    print(json.dumps({'run':str(folder),'collected':len(result['rows']),'errors':result['errors'],'additional_api_usd':result['additional_api_usd']}),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--protocol',type=Path)
    asyncio.run(run(parser.parse_args().protocol))

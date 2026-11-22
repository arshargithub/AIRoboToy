"""Bounded fictional text/context native-audio reference; no live playback.

The complete-text publication barrier is deliberately absent in this reference.
It measures a different architecture, not a drop-in replacement for validated K.
"""
import asyncio
import base64
import json
import time
from uuid import uuid4
from tavi.realtime_reference import RealtimeReference, OutputGate, RESERVATION, charge_usage
from tavi.storage import APPROVED_BUDGET_MICRO_USD
from experiments.memory.companion_contract import MISSION


def response_options(task, evidence, case_id):
    if (task['actual_speaker_id'] not in task['people']
            or task['actual_speaker_id'] not in task['audience_ids']
            or not set(task['audience_ids']) <= set(task['people'])):
        raise ValueError('Unqualified task identity')
    # The caller supplies the separately source-qualified context. No generated
    # identity or subject field is used as an authorization decision.
    text=json.dumps({'task':task,'memory_evidence':evidence},ensure_ascii=False)
    if len(text.encode())>25000: raise ValueError('Context exceeds reference bound')
    return {'conversation':'none','metadata':{'case_id':case_id},
            'instructions':MISSION,'output_modalities':['audio'],
            'input':[{'type':'message','role':'user','content':[{'type':'input_text','text':text}]}]}


class NativeMemoryReference(RealtimeReference):
    async def reply(self,task,evidence,case_id):
        options=response_options(task,evidence,case_id)
        reservation='memory-native:'+uuid4().hex
        self.store.reserve(reservation,RESERVATION,APPROVED_BUDGET_MICRO_USD)
        result={'case_id':case_id,'request':options,'reservation':reservation,'text':'',
                'first_audio_ms':None,'audio_events':[],'usage_settled':False}
        output=bytearray();response_id=None;gate=OutputGate();start=time.monotonic()
        await self.send('response.create',response=options)
        async with asyncio.timeout(35):
            while True:
                event=await self.receive();kind=event['type']
                if kind=='response.created':
                    if response_id:raise ValueError('Unexpected additional response')
                    response=event['response'];response_id=response['id']
                    if response.get('metadata',{}).get('case_id')!=case_id:
                        raise ValueError('Unbound native case')
                elif kind in ('response.output_audio.delta','response.output_audio_transcript.delta','response.done'):
                    actual=event['response']['id'] if kind=='response.done' else event.get('response_id')
                    if not response_id or actual!=response_id:raise ValueError('Unbound native output')
                    if kind=='response.output_audio.delta':
                        pcm=base64.b64decode(event['delta'],validate=True)
                        if gate.received_frames+len(pcm)//2>30*24000:raise ValueError('Audio duration exceeds bound')
                        gate.accept(pcm);output.extend(pcm)
                        elapsed=(time.monotonic()-start)*1000
                        if result['first_audio_ms'] is None:result['first_audio_ms']=elapsed
                        result['audio_events'].append({'at_ms':elapsed,'frames':len(pcm)//2})
                    elif kind=='response.output_audio_transcript.delta':
                        result['text']+=event['delta']
                        if len(result['text'])>5000:raise ValueError('Transcript exceeds bound')
                    else:
                        result['terminal_ms']=(time.monotonic()-start)*1000
                        result['status']=event['response']['status'];result['usage']=event['response'].get('usage')
                        charge=charge_usage(result['usage'])
                        if charge is not None:self.store.settle(reservation,charge);result['usage_settled']=True
                        if result['status']!='completed' or not output or not result['text'].strip():
                            raise ValueError('Incomplete native reply')
                        break
        return result,bytes(output)

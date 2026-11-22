"""Matched synthetic readiness screen; no microphone, speakers or human-file import.

Actual local turbo -> existing completion-guarded text/K controller versus native
Realtime. This is a six-pair engineering screen, not the original E3 acceptance.
"""
import asyncio
import audioop
import base64
from io import BytesIO
import json
from pathlib import Path
import statistics
import time
import wave

from .chunked_conversation import ChunkedConversation
from .conversation_providers import PaidText, REQUEST_RESERVATION
from .experiment_workflow import begin, finish, audit, ROOT
from .local_speech import LocalSpeech, validate_wave
from .mlx_final_asr import MlxFinalASR
from .realtime_reference import RealtimeReference, RESERVATION
from .speech_check import score
from .storage import Store


class Envelope:
    def __init__(self, store, maximum_micro_usd=6_300_000):
        self.store=store;self.ceiling=store.used_micro_usd()+maximum_micro_usd
        self.calls={'native':0,'text':0}
    def reserve(self, request_id, amount, cap):
        kind='native' if request_id.startswith('realtime:') else 'text' if request_id.startswith('conversation:') else None
        if kind is None or self.calls[kind]>=6 or self.used_micro_usd()+amount>self.ceiling:
            raise ValueError('Matched screen request/spending bound exceeded')
        self.store.reserve(request_id,amount,cap);self.calls[kind]+=1
    def __getattr__(self,name):return getattr(self.store,name)


def load_synthetic(manifest, case_id):
    if manifest.get('origin')!='synthetic_K_only':raise ValueError('Synthetic K input required')
    case=next(c for c in manifest['cases'] if c['id']==case_id)
    original=ROOT/case['wav']
    if original.is_symlink():raise ValueError('Synthetic input cannot be a symlink')
    path=original.resolve()
    if path.parent!=(ROOT/'.tavi/synthetic-asr-v1').resolve():
        raise ValueError('Synthetic input escaped')
    with wave.open(str(path)) as w:
        if (w.getframerate(),w.getnchannels(),w.getsampwidth())!=(16000,1,2) or not 0<w.getnframes()<=5*16000:
            raise ValueError('Wrong bounded input format')
        pcm=w.readframes(w.getnframes())
        if len(pcm)!=w.getnframes()*2:raise ValueError('Incomplete input')
    return case,pcm


def wave_bytes(pcm):
    output=BytesIO()
    with wave.open(output,'wb') as w:
        w.setnchannels(1);w.setsampwidth(2);w.setframerate(24000);w.writeframes(pcm)
    return validate_wave(output.getvalue(),24000).wav


class ObservedNative(RealtimeReference):
    def __init__(self,store):super().__init__(store);self.output=[]
    async def receive(self):
        event=await super().receive()
        if event['type']=='response.output_audio.delta':
            self.output.append({'at':time.monotonic(),'pcm':base64.b64decode(event['delta'],validate=True)})
        return event
    async def compare_turn(self,pcm,output_path):
        converted,_=audioop.ratecv(pcm,2,1,16000,24000,None);self.output=[]
        result=await self.turn(converted,source_kind='synthetic',interrupt=False)
        data=b''.join(p['pcm'] for p in self.output);output_path.write_bytes(wave_bytes(data))
        first=self.output[0]['at']
        result['audio_receipts']=[{'ready_after_commit_ms':result['first_audio_after_commit_ms']+(p['at']-first)*1000,
                                  'frames':len(p['pcm'])//2} for p in self.output]
        result['first_ready_after_input_ms']=result['first_audio_after_commit_ms']
        result['generation_complete_before_first_audio']=result['terminal_after_commit_ms']<=result['first_ready_after_input_ms']
        result['output_wave']=str(output_path.relative_to(ROOT))
        return result


async def local_turn(controller,decoder,pcm,number,output_path):
    # Same duration and100ms input pacing as the native transport. This chain's
    # final recognizer receives the complete file only after manual endpoint.
    start=time.monotonic()
    for offset in range(0,len(pcm),3200):
        await asyncio.sleep(max(0,start+min(offset+3200,len(pcm))/32000-time.monotonic()))
    endpoint=time.monotonic()
    decoded=await asyncio.to_thread(decoder.decode,pcm,endpoint+3)
    asr_end=time.monotonic()
    metrics_start=len(controller.metrics)
    controller.feed('synthetic',{'events':[{'type':'speech_started','utterance':number},
        {'type':'recognition','utterance':number,'text':decoded.text,'final':True,'first_detection':True}]})
    rid=controller.accepted_response_id
    if not rid or controller.input_rejection:raise ValueError('Local controller rejected synthetic input')
    parts=[];chunks=[];first=None;text=None
    async with asyncio.timeout(25):
        while controller.completed_response_id!=rid:
            if controller.failure:raise ValueError('Local '+controller.failure['component']+' pipeline failed')
            if controller.audio is not None:
                audio=controller.audio
                if audio['id']!=rid or audio['sequence']!=len(chunks):raise ValueError('Local output association/order failed')
                now=time.monotonic()
                if first is None:first=(now-endpoint)*1000;text=controller.last_reply
                data=controller.audio_bytes('synthetic',rid,audio['sequence'])
                validate_wave(data,24000)
                with wave.open(BytesIO(data)) as w:parts.append(w.readframes(w.getnframes()))
                chunks.append({'sequence':audio['sequence'],'ready_after_input_ms':(now-endpoint)*1000,
                               'duration_ms':audio['duration_ms'],'text':audio['text']})
                for command in ('started','played'):
                    if not controller.command('synthetic',command,{'response_id':rid,'sequence':audio['sequence']}):
                        raise ValueError('Local virtual playback acknowledgement rejected')
            await asyncio.sleep(.005)
    metrics=list(controller.metrics)[metrics_start:]
    text_done=next((m['elapsed_ms'] for m in metrics if m['kind']=='text_completed' and m.get('response_id')==rid),None)
    first_chunk=next((m['elapsed_ms'] for m in metrics if m['kind']=='chunk_ready' and m.get('response_id')==rid),None)
    if text_done is None or first_chunk is None or first_chunk<text_done:raise ValueError('Completion publication barrier failed')
    if ''.join(c['text'] for c in chunks)!=text:raise ValueError('Local text/audio association failed')
    output_path.write_bytes(wave_bytes(b''.join(parts)))
    return {'text':text,'recognized_text':decoded.text,'confidence':decoded.confidence,
            'recognizer_profile':decoder.profile,'asr_ms':(asr_end-endpoint)*1000,
            'first_ready_after_input_ms':first,'complete_after_input_ms':(time.monotonic()-endpoint)*1000,
            'request_to_text_completed_ms':text_done,'generation_complete_before_first_audio':True,
            'chunks':chunks,'controller_completed':True,'output_wave':str(output_path.relative_to(ROOT))}


async def run():
    folder,plan=begin('experiments/realtime/matched-paths-protocol-v1.json')
    manifest=json.loads((ROOT/plan['inputs'][0]).read_text())
    raw_store=Store(ROOT/'.tavi/simulation/simulation.sqlite3');initial=raw_store.used_micro_usd()
    store=Envelope(raw_store,int(plan['limits']['maximum_additional_api_usd']*1e6))
    report={'rows':[],'completed':False,'synthetic_inputs':True,'physical_playback':False,
            'initial_spent_reserved_usd':initial/1e6,'sessions':[],'startup':{}}
    decoder=MlxFinalASR();voice=LocalSpeech('kokoro-k-mlx');provider=PaidText(store)
    c=ChunkedConversation(store,provider=provider,speech=voice);native=None;error=None
    def save():
        report['spent_reserved_usd']=store.used_micro_usd()/1e6
        (folder/'results.json').write_text(json.dumps(report,indent=2)+'\n')
    async def heartbeat():
        while True:
            if c.lease:c.feed('synthetic',{'events':[]});c.expire()
            await asyncio.sleep(.032)
    pulse=None
    try:
        began=time.monotonic();await asyncio.to_thread(decoder.prepare)
        report['startup']['local_asr_prepare_ms']=(time.monotonic()-began)*1000
        began=time.monotonic();await voice.prepare()
        report['startup']['local_K_prepare_ms']=(time.monotonic()-began)*1000
        pulse=asyncio.create_task(heartbeat())
        for session_index,cases in enumerate([['bridge','change','close'],['pause','keys','colour']]):
            c.start('synthetic');native=ObservedNative(store);began=time.monotonic();await native.connect()
            report['sessions'].append({'index':session_index,'native_connect_ms':(time.monotonic()-began)*1000,
                'actual_native_session':{k:native.session.get(k) for k in ('model','audio','reasoning','max_output_tokens','output_modalities','truncation')}})
            failed=set()
            for turn_index,case_id in enumerate(cases):
                case,pcm=load_synthetic(manifest,case_id)
                pair_index=session_index*3+turn_index
                order=['local','native'] if pair_index%2==0 else ['native','local']
                for path in order:
                    row={'case':case_id,'path':path,'session':session_index,'turn':turn_index,'order':order,
                         'is_first_prepared_session_turn':turn_index==0,'status':'error'}
                    if path in failed:row['error']='Earlier path failure in this session; no retry'
                    else:
                        before=store.used_micro_usd()
                        try:
                            target=folder/f'{pair_index}-{path}.wav'
                            if path=='local':
                                result=await local_turn(c,decoder,pcm,pair_index+1,target)
                                result['script_diagnostic']=score(case['expected'],result['recognized_text'])
                            else:result=await native.compare_turn(pcm,target)
                            row.update(result,status='ok')
                        except Exception as exc:
                            failed.add(path);row['error']=str(exc)[:140] if isinstance(exc,(ValueError,TimeoutError)) else type(exc).__name__
                        row['spent_or_reserved_usd']=(store.used_micro_usd()-before)/1e6
                    report['rows'].append(row);save()
                    print(case_id,path,row['status'],round(row.get('first_ready_after_input_ms',0)),'ms ready after input',flush=True)
            await native.close();native=None;c.stop()
        report['completed']=True
    except Exception as exc:
        error=type(exc).__name__;report['error']=str(exc)[:140] if isinstance(exc,(ValueError,TimeoutError)) else error
    finally:
        if native:await native.close()
        if pulse:pulse.cancel();await asyncio.gather(pulse,return_exceptions=True)
        await c.close();await asyncio.to_thread(decoder.close)
        save()
    rows=report['rows'];errors=sum(r['status']!='ok' for r in rows)+int(error is not None)
    metrics={'observations':len(rows),'errors':errors,
        'local_script_matches':sum(r['path']=='local' and r.get('script_diagnostic',{}).get('exact_words',False) for r in rows),
        'local_guarded_completions':sum(r['path']=='local' and r.get('controller_completed',False) and r.get('generation_complete_before_first_audio',False) for r in rows),
        'native_complete_replies':sum(r['path']=='native' and r.get('terminal_status')=='completed' for r in rows),
        'additional_spent_reserved_usd':(store.used_micro_usd()-initial)/1e6}
    report['metrics']=metrics
    report['summary']={}
    for path in ('local','native'):
        good=[r for r in rows if r['path']==path and r['status']=='ok'];times=[r['first_ready_after_input_ms'] for r in good]
        report['summary'][path]={'completed':len(good),'attempts':sum(r['path']==path for r in rows),
            'median_ready_after_input_ms':statistics.median(times) if times else None,'max_ready_after_input_ms':max(times) if times else None,
            'ready_after_input_ms':times,'spent_or_reserved_usd':sum(r.get('spent_or_reserved_usd',0) for r in rows if r['path']==path)}
    report['interpretation']='Different reasoning/voice/publication; manual endpoint, no HTTP/browser/acoustic/substantive-word timing; virtual accelerated playback. Six unique synthetic cases, no population p95, full E3 or identity/memory acceptance.'
    save();artifacts=[folder/'results.json',*folder.glob('*.wav')]
    record=finish(folder,metrics,artifacts=artifacts,completed=report['completed'],error=error)
    raw_store.close();print(json.dumps({'run':str(folder),'metrics':metrics,'summary':report['summary'],'decision':record['decision'],'audit':audit(folder)},indent=2))


if __name__=='__main__':asyncio.run(run())

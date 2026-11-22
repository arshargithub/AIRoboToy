'use strict';
const $=id=>document.getElementById(id);
const phrases=['Paprika.','Paprika, tell me a story about a dragon.','Paprika, can you think of a game we can play together?'];
const runs=[],requests=new Set();
let context=null,mic=null,node=null,input=null,sink=null,lease=null,active=false,starting=false,generation=0;
let queue=[],sending=false,lastContact=0,lastPacket=0,origin=null,current=null,cueIndex=0,currentUtterance=0;
let source=null,reference=null,referenceGain=null,loadingReference=false;
function state(kind,title,help){$('face-card').dataset.state=kind;$('state').textContent=title;$('state-help').textContent=help;$('face').textContent=kind==='heard'?'• ◡ •':kind==='checking'?'• ··· •':kind==='listening'?'• ᴗ •':'— ‿ —';}
function controls(){
 $('start').disabled=active||starting;$('stop').disabled=!active&&!starting;
 $('mode').disabled=active||starting;$('purpose').disabled=active||starting;
 $('download').disabled=active||starting||runs.length===0;
 $('reference-controls').hidden=$('purpose').value!=='echo';
 $('play').disabled=!active||!!source||loadingReference||current?.purpose!=='echo';
 $('cancel').disabled=!source;$('volume').disabled=!!source;
 if(!active)$('next').disabled=true;
}
function showCue(){
 const purpose=current?.purpose||$('purpose').value;
 $('next').hidden=purpose!=='calls';
 $('cue').textContent=purpose==='calls'?phrases[cueIndex]:purpose==='echo'?'Stay silent while the test voice plays.':'Read aloud or talk naturally.';
 $('cue-help').textContent=purpose==='calls'?'Say this once, then wait for the full turn. Paprika = puh-PREE-kuh.':purpose==='echo'?'Use the Play button below. Any activation during your silence is unwanted.':'Talk to someone else or read a book. Do not address Paprika.';
}
async function requestJson(path,options={},timeout=1000){
 const controller=new AbortController();requests.add(controller);const timer=setTimeout(()=>controller.abort(),timeout);
 try{const response=await fetch(path,{...options,signal:controller.signal});const data=await response.json();if(!response.ok)throw Error(data.error||'Local service request failed');return data;}
 catch(error){error.stage=path;throw error;}
 finally{clearTimeout(timer);requests.delete(controller);}
}
function stopReference(reason='manual'){
 if(!source)return;source.onended=null;try{source.stop()}catch{}source.disconnect();source=null;
 if(referenceGain){referenceGain.disconnect();referenceGain=null;}
 const trial=current?.reference_trials.at(-1);if(trial&&!trial.ended_ms){trial.ended_ms=performance.now()-current.started_ms;trial.reason=reason;}
 $('play-status').textContent=reason==='completed'?'Test voice finished · microphone still listening':reason==='muted'?'Test voice stopped · microphone off':'Test voice stopped';
 controls();
}
async function mute(message='Microphone off'){
 const oldLease=lease,oldContext=context;
 generation++;active=false;starting=false;queue=[];lease=null;context=null;
 document.body.classList.remove('active');
 requests.forEach(c=>c.abort());stopReference('muted');
 if(node){node.port.onmessage=null;node.disconnect();node=null;}
 if(input){input.disconnect();input=null;}if(sink){sink.disconnect();sink=null;}
 if(mic){mic.getTracks().forEach(t=>{t.onended=null;t.stop()});mic=null;}
 if(current&&!current.ended_at){current.ended_at=new Date().toISOString();current.duration_ms=current.started_ms===null?0:performance.now()-current.started_ms;}
 $('mic-status').textContent=message;state('off',message,'Microphone and playback are stopped.');$('speech-level').value=0;controls();
 if(oldLease)fetch('/api/live-wake/stop',{method:'POST',headers:{'X-Audio-Stream':oldLease},signal:AbortSignal.timeout(1000)}).catch(()=>{});
 if(oldContext)await oldContext.close();
}
async function fail(error){
 if(current)current.faults.push({message:error.message,stage:error.stage||'capture',at:new Date().toISOString()});
 $('error').textContent=error.message;await mute('Stopped · restart to retry');
}
function detail(result){
 $('details').textContent=JSON.stringify({mode:current.mode,purpose:current.purpose,frames_processed:result.sequence+1,
  buffered_ms:result.buffered_ms,recognition_running:result.decode_running,recognition_pending:result.decode_pending,
  partial_snapshots_replaced:result.partial_snapshots_replaced,max_queue_frames:current.max_queue,
  latest_decode_ms:current.latest_decode_ms??null,echo_cancellation:current.settings.echoCancellation??'not reported'},null,2);
}
function handleEvents(events,result){
 for(const e of events){
  if(!active)return;
  if(e.type==='speech_started'){
   if(current.turns.length>=80){fail(Error('This run reached its 80-turn limit; download before continuing'));return;}
   currentUtterance=e.utterance;
   current.turns.push({utterance:e.utterance,speech_onset_sample:e.speech_onset_sample,buffer_start_sample:e.buffer_start_sample,
    started_during_reference:!!source,snapshots:[],activation:false,final:false});
   $('next').disabled=true;state('listening','Listening to your words','The complete turn is kept while the name is checked locally.');
  }
  const turn=current.turns.find(t=>t.utterance===e.utterance);if(!turn)continue;
  if(e.type==='speech_ended'){
   Object.assign(turn,{endpoint_seen:true,speech_end_sample:e.speech_end_sample,retained_samples:e.retained_samples});
   if(e.utterance===currentUtterance)state(turn.activation?'heard':'checking',turn.activation?'Heard Paprika · finishing your turn':'Checking the full turn','Waiting for the final recognized words.');
  }
  if(e.type!=='recognition')continue;
  const notice=Math.max(0,(context.currentTime-(origin+e.speech_onset_sample)/16000)*1000);
  turn.snapshots.push({final:e.final,name_match:e.name_match,decode_ms:e.decode_ms,queue_wait_ms:e.queue_wait_ms,
   asr_run_id:e.asr_run_id,recognition_id:e.recognition_id,confidence:e.confidence??null,
   audio_start_sample:e.audio_start_sample,audio_samples:e.audio_samples,
   snapshot_end_sample:e.snapshot_end_sample,notice_since_vad_onset_ms:notice});
  if(turn.snapshots.length>12)turn.snapshots.shift();
  turn.text=e.text;current.latest_decode_ms=e.decode_ms;
  if(e.first_detection){turn.activation=true;turn.first_notice_since_vad_onset_ms=notice;turn.notice_before_endpoint=!turn.endpoint_seen;current.activations++;}
  if(e.final){turn.final=true;turn.final_name_match=e.name_match;current.completed++;}
  $('detections').textContent=current.activations;$('completed').textContent=current.completed;
  if(e.utterance===currentUtterance){
   $('request').textContent=e.text;$('request-label').textContent=e.final?'Full recognized turn':'Recognized words so far';
   if(turn.activation){
    state('heard',e.final?'Heard Paprika · turn captured':'Heard Paprika!',e.final?'Check that your complete request appears below.':'Keep speaking. Your full request is still being captured.');
    $('notice-timing').textContent=`First notice: ${Math.round(turn.first_notice_since_vad_onset_ms)} ms after detected speech began (estimate, not name-end latency).`;
   }else{state(e.final?'listening':'checking',e.final?'No Paprika match':'Checking speech locally',e.final?'The words below did not produce an activation.':'No cloud service is involved.');$('notice-timing').textContent='';}
   if(e.final){
    $('next').disabled=current.purpose!=='calls'||cueIndex>=phrases.length-1;
    if(current.purpose==='calls'&&cueIndex===phrases.length-1)$('cue-help').textContent='Three phrases complete. Mute, then choose the next mode or test.';
   }
  }
  if(e.final){
   const li=document.createElement('li');li.textContent=(turn.activation?'Heard Paprika: ':'No activation: ')+e.text;
   $('recent').prepend(li);while($('recent').children.length>5)$('recent').lastElementChild.remove();
  }
 }
}
async function pump(){
 if(sending||!active)return;sending=true;const gen=generation;
 try{
  while(active&&generation===gen&&queue.length){
   const packet=queue.shift(),started=performance.now();
   const result=await requestJson('/api/live-wake/frame',{method:'POST',headers:{'Content-Type':'application/octet-stream','X-Audio-Stream':lease,'X-Audio-Sequence':String(packet.sequence)},body:packet.pcm});
   if(!active||generation!==gen)break;lastContact=performance.now();
   current.transport.push({rtt_ms:lastContact-started,queue_frames:queue.length});if(current.transport.length>500)current.transport.shift();
   $('speech-level').value=result.probability;handleEvents(result.events,result);if(active)detail(result);
  }
 }catch(error){if(generation===gen)await fail(error)}
 finally{sending=false;if(active&&queue.length)pump();}
}
$('start').onclick=async()=>{
 if(active||starting)return;if(runs.length>=12){$('error').textContent='Twelve test runs are saved in this page. Download diagnostics, then reload to start fresh.';return;}
 starting=true;document.body.classList.add('active');const gen=++generation;cueIndex=0;currentUtterance=0;origin=null;
 current={mode:$('mode').value,purpose:$('purpose').value,created_at:new Date().toISOString(),started_ms:null,
  settings:{},turns:[],reference_trials:[],transport:[],faults:[],activations:0,completed:0,max_queue:0};runs.push(current);
 $('error').textContent='';$('request').textContent='';$('notice-timing').textContent='';$('detections').textContent='0';$('completed').textContent='0';$('elapsed').textContent='0 s';showCue();controls();
 try{
  state('checking','Starting local listening','Allow microphone access if asked.');
  const created=new AudioContext({sampleRate:16000});context=created;await Promise.race([created.resume(),new Promise((_,reject)=>setTimeout(()=>reject(Error('Audio startup timed out; try Chrome or Safari')),5000))]);if(gen!==generation)return;
  if(created.sampleRate!==16000)throw Error('A 16 kHz audio context is required; try Chrome or Safari');
  await created.audioWorklet.addModule('/capture.js');if(gen!==generation)return;
  const acquired=await navigator.mediaDevices.getUserMedia({audio:{channelCount:1,echoCancellation:true,noiseSuppression:true,autoGainControl:false},video:false});
  if(gen!==generation){acquired.getTracks().forEach(t=>t.stop());return;}mic=acquired;current.settings=mic.getAudioTracks()[0].getSettings();current.device_label=mic.getAudioTracks()[0].label||'Default microphone';
  $('mic-status').textContent='Microphone acquired · loading local model · no audio sent to cloud';
  const started=await requestJson('/api/live-wake/start',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({mode:current.mode})},20000);
  if(gen!==generation){fetch('/api/live-wake/stop',{method:'POST',headers:{'X-Audio-Stream':started.stream_id},signal:AbortSignal.timeout(1000)}).catch(()=>{});return;}
  lease=started.stream_id;current.configuration=started;input=created.createMediaStreamSource(mic);node=new AudioWorkletNode(created,'tavi-capture');sink=created.createGain();sink.gain.value=0;input.connect(node);node.connect(sink);sink.connect(created.destination);
  active=true;starting=false;queue=[];lastContact=lastPacket=performance.now();current.started_ms=performance.now();
  node.port.onmessage=event=>{
   if(!active||gen!==generation)return;const packet=event.data;lastPacket=performance.now();
   if(packet.sampleRate!==16000||packet.pcm.byteLength!==1024){fail(Error('Unexpected microphone format'));return;}
   if(origin===null)origin=packet.endFrame-(packet.sequence+1)*512;
   if(queue.length>=4){fail(Error('Capture backlog exceeded 128 ms; microphone stopped'));return;}
   queue.push(packet);current.max_queue=Math.max(current.max_queue,queue.length);pump();
  };
  mic.getTracks().forEach(t=>t.onended=()=>fail(Error('Microphone disconnected')));
  $('mic-status').textContent=`Microphone on · ${current.device_label} · local only`;state('listening','Listening for Paprika','Say the displayed phrase once, then leave a short pause.');controls();
 }catch(error){if(gen===generation)await fail(error)}
};
$('stop').onclick=()=>mute();
$('next').onclick=()=>{if(!active||cueIndex>=phrases.length-1)return;cueIndex++;showCue();$('next').disabled=true;state('listening','Ready for the next phrase','Say the displayed words once.');};
$('purpose').onchange=()=>{current=null;cueIndex=0;showCue();controls();};
$('volume').oninput=()=>{$('volume-value').textContent=Math.round(Number($('volume').value)*100)+'%';};
$('cancel').onclick=()=>stopReference();
$('play').onclick=async()=>{
 if(!active||source||loadingReference||current.purpose!=='echo')return;loadingReference=true;controls();const gen=generation;
 try{
  if(!reference){const response=await fetch('/paprika-reference.wav',{signal:AbortSignal.timeout(5000)});if(!response.ok)throw Error('Local Paprika test voice is unavailable');const bytes=await response.arrayBuffer();if(gen!==generation)return;reference=await context.decodeAudioData(bytes);}
  if(!active||gen!==generation)return;source=context.createBufferSource();source.buffer=reference;referenceGain=context.createGain();referenceGain.gain.value=Number($('volume').value);source.connect(referenceGain);referenceGain.connect(context.destination);
  current.reference_trials.push({started_ms:performance.now()-current.started_ms,volume:Number($('volume').value)});
  source.onended=()=>stopReference('completed');source.start();$('play-status').textContent='Test voice playing · stay silent';
 }catch(error){if(gen===generation){$('error').textContent=error.message;current.faults.push({message:error.message,stage:'reference'});}}
 finally{loadingReference=false;controls();}
};
$('download').onclick=()=>{
 const include=$('include-text').checked;
 const report={schema_version:1,kind:'paprika_live_whisper_development_diagnostics',api_spend_usd:0,
  timing_note:'Browser notice since VAD speech onset is an estimate, not name-end-to-acknowledgement latency. No independent acoustic onset/stop recording.',
  transcripts_included:include,runs:runs.map(r=>({...r,turns:r.turns.map(t=>{const {text,...metadata}=t;return include?{...metadata,text}:metadata;})}))};
 const link=document.createElement('a');link.href=URL.createObjectURL(new Blob([JSON.stringify(report,null,2)],{type:'application/json'}));link.download='paprika-live-diagnostics-'+crypto.randomUUID()+'.json';link.click();setTimeout(()=>URL.revokeObjectURL(link.href),1000);
};
setInterval(()=>{
 if(!active)return;
 const now=performance.now();$('elapsed').textContent=Math.floor((now-current.started_ms)/1000)+' s';
 if(now-lastPacket>1000||context?.state!=='running')fail(Error('Microphone frames stalled; capture stopped'));
 else if(now-lastContact>1500)fail(Error('Local service is unresponsive; capture stopped'));
 else if(now-current.started_ms>600000)mute('Ten-minute run limit reached · download diagnostics');
},500);
window.addEventListener('pagehide',()=>mute());showCue();controls();

'use strict';
const $ = id => document.getElementById(id);
const oldPhrases = [...Array(10).fill('TAH-vee'), 'TV', 'Toby', 'toffee', 'coffee', 'that view', 'Have we met?', 'Hey Toby', 'Tell me a story', 'Taffy', 'The tabby cat'];
let plan = {kind:'tavi_private_wake_samples', clip_ms:3200, gap_ms:1800, minimum_frames:85, max_frames:126,
 trials:oldPhrases.map((phrase,i)=>({number:i+1,phrase,label:i<10?'positive':'negative'}))};
const comparing = !!document.body.dataset.protocol;
let ready = !comparing, protocolHash = null, collector = new SampleCollector();
let context=null,mic=null,node=null,input=null,sink=null,timers=[],active=false,starting=false,epoch=0,cueEpoch=0,speaker='',settings={},collectionId='',lastFrame=0,finished=false,paused=false,currentIndex=0,recording=false;
const attempts={},captureSegments=[];
let previewing=false,previewTimers=[];
function later(fn,ms) { const gen=cueEpoch; timers.push(setTimeout(()=>{if(active&&cueEpoch===gen)fn()},ms)); }
function clearCues(){cueEpoch++;timers.forEach(clearTimeout);timers=[];recording=false;}
function showStage(stage){if(comparing)for(const id of ['setup','session','break','done'])$(id).hidden=id!==stage;}
function face(phase,heading,count,help){if(!comparing)return;$('recording-card').dataset.phase=phase;$('phase').textContent=heading;$('countdown').textContent=count;$('cue-help').textContent=help;}
function savedProgress(){ $('progress').value=collector.clips.length;if(comparing)$('progress-label').textContent=`${collector.clips.length} of ${plan.trials.length} saved`; }
function controls() {
 $('start').disabled=!ready||active||starting||collector.clips.length>0;
 $('stop').disabled=!active&&!starting&&!paused;
 $('download').disabled=active||starting||collector.clips.length===0;
 $('speaker').disabled=active||starting; $('consent').disabled=active||starting;
 if(comparing){$('stop').disabled=!active&&!starting&&!paused&&!previewing;$('practice').disabled=!ready||active||starting||previewing;$('retry').disabled=!active||!recording;$('pause').disabled=!active;$('resume').disabled=active||starting;document.querySelectorAll('[data-speaker]').forEach(b=>b.disabled=active||starting);}
}
async function close(message) {
 epoch++;active=false;starting=false;clearCues();collector.discard();
 if(node){node.port.onmessage=null;node.disconnect();node=null;}
 if(input){input.disconnect();input=null;} if(sink){sink.disconnect();sink=null;}
 if(mic){mic.getTracks().forEach(t=>{t.onended=null;t.stop()});mic=null;}
 const old=context;context=null;
 $('status').textContent=message;controls();
 if(old)await old.close();
}
async function fail(error) { paused=false;$('error').textContent=error.message;await close('Stopped · completed clips can be downloaded; reload to restart');showStage(collector.clips.length?'done':'setup');if(comparing){$('done-title').textContent='Session stopped';$('done-message').textContent=`${collector.clips.length} of 32 phrases saved. This partial recording cannot be used for the full comparison.`;} }
function prepareTrial(i,delay=plan.gap_ms){
 if(!active)return;currentIndex=i;
 if(!comparing){later(()=>beginTrial(i),delay);return;}
 const phrase=plan.trials[i].phrase;
 $('phrase').textContent=phrase.replace(', ', ',\n');$('time-fill').style.width='0%';
 face('ready','Read this first',Math.ceil(delay/1000),'Wait for “Your turn”.');
 for(let elapsed=1000;elapsed<delay;elapsed+=1000)later(()=>{$('countdown').textContent=Math.ceil((delay-elapsed)/1000)},elapsed);
 later(()=>beginTrial(i),delay);
}
function beginTrial(i) {
 if(!active)return;
 recording=true;attempts[i]=(attempts[i]||0)+1;
 collector.begin(plan.trials[i]);$('cue').textContent=`${i+1}/${plan.trials.length} · SAY ONCE: ${plan.trials[i].phrase}`;
 face('recording','Your turn!','●','Say these words once.');controls();
 if(comparing)for(let elapsed=100;elapsed<plan.clip_ms;elapsed+=100)later(()=>{$('time-fill').style.width=`${elapsed/plan.clip_ms*100}%`},elapsed);
 if(!comparing)later(()=>{$('cue').textContent='Stay quiet · finishing this clip'},plan.clip_ms-700);
 later(()=>{
  try {
   const clip=collector.finish();if(clip.frames.length<plan.minimum_frames)throw Error('Too few audio frames; collection stopped');
   recording=false;savedProgress();$('status').textContent=`${collector.clips.length}/${plan.trials.length} clips saved in page memory`;controls();
   if(i===plan.trials.length-1){finished=true;close('Finished · microphone off · download your samples');$('cue').textContent='Finished — download your samples';if(comparing){$('done-title').textContent='All done!';$('done-message').textContent='32 phrases saved. The microphone is off.';}showStage('done');}
   else if(comparing&&collector.clips.length===plan.break_after){pauseSession();}
   else {$('cue').textContent='Stay quiet · next cue shortly';prepareTrial(i+1);}
  } catch(e) {fail(e)}
 },plan.clip_ms);
}
async function startCapture(){
 if(!ready||active||starting||previewing)return;speaker=$('speaker').value.trim();
 if(!speaker){$('error').textContent='Enter a speaker label first';return;}
 if(!$('consent').checked){$('error').textContent='Read and tick the recording agreement first';return;}
 paused=false;starting=true;const gen=++epoch;controls();$('error').textContent='';$('status').textContent='Starting microphone · allow access if prompted';showStage('session');face('ready','Starting microphone','…','Allow microphone access if asked.');
 try {
  const created=new AudioContext({sampleRate:16000});context=created;
  await Promise.race([created.resume(),new Promise((_,reject)=>setTimeout(()=>reject(Error('Audio startup timed out; try Chrome or Safari')),5000))]);
  if(gen!==epoch)return;
  if(created.sampleRate!==16000)throw Error('A 16 kHz audio context is required');
  await created.audioWorklet.addModule('/capture.js');if(gen!==epoch)return;
  const acquired=await navigator.mediaDevices.getUserMedia({audio:{channelCount:1,echoCancellation:true,noiseSuppression:true,autoGainControl:false},video:false});
  if(gen!==epoch){acquired.getTracks().forEach(t=>t.stop());return;}
  mic=acquired;settings=mic.getAudioTracks()[0].getSettings();captureSegments.push({from_clip:collector.clips.length+1,settings});input=created.createMediaStreamSource(mic);
  node=new AudioWorkletNode(created,'tavi-capture');sink=created.createGain();sink.gain.value=0;
  input.connect(node);node.connect(sink);sink.connect(created.destination);
  if(!collectionId)collectionId=crypto.randomUUID();active=true;starting=false;lastFrame=performance.now();
  node.port.onmessage=e=>{if(!active||epoch!==gen)return;lastFrame=performance.now();try{collector.append(e.data)}catch(error){fail(error)}};
  mic.getTracks().forEach(t=>t.onended=()=>fail(Error('Microphone disconnected')));
  $('cue').textContent='Get ready · next cue in 3 seconds';$('status').textContent='Microphone on · local recording only';controls();prepareTrial(collector.clips.length,3000);
 } catch(e) {if(gen===epoch)await fail(e);}
}
$('start').onclick=startCapture;
function pauseSession(){paused=true;close('Paused · microphone off');showStage('break');if(comparing)$('break-message').textContent=`${collector.clips.length} of 32 phrases saved. The microphone is off.`;}
if(comparing){
 function endPractice(){previewTimers.forEach(clearTimeout);previewTimers=[];previewing=false;showStage('setup');$('status').textContent='Practice finished · microphone off · nothing recorded';controls();}
 $('practice').onclick=()=>{
  if(!ready||active||starting||previewing)return;previewing=true;showStage('session');controls();
  $('phrase').textContent='Paprika,\nare you there?';$('time-fill').style.width='0%';
  $('status').textContent='Practice only · microphone off · nothing is being recorded';
  face('ready','Read this first','3','Wait for “Your turn”.');
  for(let i=1;i<=2;i++)previewTimers.push(setTimeout(()=>{$('countdown').textContent=3-i},i*1000));
  previewTimers.push(setTimeout(()=>{face('recording','Your turn!','●','Say these words once. Practice only — microphone off.');},3000));
  for(let ms=3100;ms<7000;ms+=100)previewTimers.push(setTimeout(()=>{$('time-fill').style.width=`${(ms-3000)/40}%`},ms));
  previewTimers.push(setTimeout(endPractice,7000));
 };
 $('pause').onclick=pauseSession;$('resume').onclick=startCapture;
 $('retry').onclick=()=>{if(!active||!recording)return;clearCues();collector.discard();controls();prepareTrial(currentIndex);};
 document.querySelectorAll('[data-speaker]').forEach(button=>button.onclick=()=>{$('speaker').value=button.dataset.speaker;document.querySelectorAll('[data-speaker]').forEach(b=>b.setAttribute('aria-pressed',String(b===button)));});
 $('speaker').oninput=()=>document.querySelectorAll('[data-speaker]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.speaker===$('speaker').value.trim())));
}
$('stop').onclick=()=>{if(previewing){previewTimers.forEach(clearTimeout);previewTimers=[];previewing=false;showStage('setup');$('status').textContent='Microphone off · practice stopped';controls();return;}paused=false;close('Stopped · microphone off');$('cue').textContent='Stopped · reload to record a fresh session';showStage(collector.clips.length?'done':'setup');if(comparing){$('done-title').textContent='Session ended early';$('done-message').textContent=`${collector.clips.length} of 32 phrases saved. Reload to start a complete comparison.`;}};
function encode(frames) { let binary='';for(const bytes of frames)for(let i=0;i<bytes.length;i+=8192)binary+=String.fromCharCode(...bytes.subarray(i,i+8192));return btoa(binary); }
$('download').onclick=()=>{
 const report={schema_version:1,kind:plan.kind,collection_id:collectionId,speaker,complete:finished&&collector.clips.length===plan.trials.length,
  created_at:new Date().toISOString(),sample_rate:16000,format:'mono_pcm16le_base64',settings,
  consent:'User explicitly checked local-development recording agreement',
  ...(comparing?{protocol_id:plan.protocol_id,protocol_sha256:protocolHash,attempts,capture_segments:captureSegments}:{}),
  clips:collector.clips.map(({frames,...metadata})=>({...metadata,sample_count:frames.length*512,pcm_base64:encode(frames)}))};
 const link=document.createElement('a');link.href=URL.createObjectURL(new Blob([JSON.stringify(report)],{type:'application/json'}));
 link.download=`${comparing?'tavi-paprika-comparison':'tavi-wake-samples'}-${collectionId}.json`;link.click();setTimeout(()=>URL.revokeObjectURL(link.href),1000);
};
setInterval(()=>{if(active&&(performance.now()-lastFrame>1000||context?.state!=='running'))fail(Error('Microphone frames stalled'));},500);
window.addEventListener('pagehide',()=>close('Microphone off'));
async function initialize() {
 controls();if(!comparing)return;
 try {
  // This request fetches public experiment instructions only. PCM never leaves this page.
  const response=await fetch(document.body.dataset.protocol,{cache:'no-store'});if(!response.ok)throw Error('Comparison instructions unavailable');
  const bytes=await response.arrayBuffer();const loaded=JSON.parse(new TextDecoder().decode(bytes));
  if(loaded.protocol_id!=='tavi-paprika-whisper-v1'||loaded.trials.length!==32||loaded.clip_ms!==4000||loaded.max_frames!==150)throw Error('Unexpected comparison protocol');
  protocolHash=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',bytes)),b=>b.toString(16).padStart(2,'0')).join('');
  plan=loaded;collector=new SampleCollector(plan.trials.length,plan.max_frames);ready=true;
  $('status').textContent='Microphone off · comparison ready · no samples recorded';controls();
 } catch(e) {$('error').textContent=e.message;$('status').textContent='Microphone off · reload to try loading the comparison again';}
}
initialize();

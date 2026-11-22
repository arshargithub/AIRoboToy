'use strict';
const $=id=>document.getElementById(id);
const selectedIntent=()=>document.querySelector('input[name=intent]:checked')?.value||'unlabelled';
let ctx=null,stream=null,node=null,input=null,gain=null,source=null,lease=null,queue=[],sending=false,active=false,starting=false,generation=0;
let playbackGain=null,loadingReference=false;
let reference=null,startedAt=0,latest=null,settings={},interrupts=[],plays=0,faults=[],warnings=[],contextRate=null,lastContact=0,wakes=0,wakeReady=null,wakeBackend="baseline";
const delayLimit=1000;
const speechGate=new SpeechInterruptionGate(.65,2);
const previousGate=new SpeechInterruptionGate(.9,3);
let cueTimer=null,speakingTrials=0;
let playbackChecks=[],currentCheck=null,transportSamples=[],maxQueue=0;
const guidedWake=new GuidedWakeTest({show:text=>{$('cue').textContent=text},done:report=>{$('results').textContent=JSON.stringify(report.summary,null,2);details();}});
function finishCheck(reason){if(cueTimer!==null){clearTimeout(cueTimer);cueTimer=null;}$('cue').textContent='';if(currentCheck){currentCheck.reason=reason;playbackChecks.push(currentCheck);currentCheck=null;}}

function display(message){$('status').textContent=message;$('face').dataset.speaking=String(!!source);$('face').textContent=source?'• ▥ •':active?'• ◡ •':'— ‿ —';}
function details(){const pairs=[['Microphone',active?'On · local only':'Off'],['Audio context',ctx?ctx.sampleRate+' Hz':'—'],['Echo cancellation',String(settings.echoCancellation??'not reported')],['Noise suppression',String(settings.noiseSuppression??'not reported')],['Frames processed',latest?.frames??0],['Inference',latest?latest.inference_ms.toFixed(2)+' ms':'—'],['Pre-roll',latest?(latest.preroll_samples/16000).toFixed(2)+' s':'—'],['Transport backlog',queue.length+' frames'],['Wake detector',wakeReady===null?'Checked on start':wakeReady?(wakeBackend==='custom'?'Tavi · custom trial':wakeBackend==='hey'?'Hey Tavi · trial':'Tavi · baseline'):'Not installed'],['Tavi detections',wakes],['Reference plays',plays],['Speech interruptions',interrupts.length]];
$('details').replaceChildren(...pairs.flatMap(([a,b])=>{let dt=document.createElement('dt'),dd=document.createElement('dd');dt.textContent=a;dd.textContent=b;return[dt,dd]}));$('start').disabled=active||starting;$('stop').disabled=!active&&!starting;$('wake-test').disabled=!active||!!source||guidedWake.active||!['custom','hey'].includes(wakeBackend);$('play').disabled=!active||!!source||guidedWake.active||selectedIntent()==='unlabelled';document.querySelectorAll('input[name=intent]').forEach(radio=>radio.disabled=!!source);$('autostop').disabled=!!source;$('volume').disabled=!!source;$('cancel').disabled=!source;}
async function fetchJson(path,options={},timeout=delayLimit){try{const r=await fetch(path,{...options,signal:AbortSignal.timeout(timeout)});const value=await r.json();if(!r.ok)throw Error(value.error||'Local audio request failed');return value;}catch(e){e.stage=path;throw e;}}
function stopPlayback(reason='manual',packet=null){if(!source)return;finishCheck(reason);const stopped=ctx.currentTime;source.onended=null;source.stop();source.disconnect();source=null;if(playbackGain){playbackGain.disconnect();playbackGain=null;}
 if(reason==='speech'){const metric={graph_clock_delta_ms:(stopped-packet.endFrame/ctx.sampleRate)*1000,playback_position_ms:Math.max(0,(stopped-startedAt)*1000),probability:latest.probability};interrupts.push(metric);$('results').textContent=JSON.stringify(metric,null,2);}
 display(active?(reason==='speech'?'Speech detected · playback interrupted':'Microphone on · waiting'):'Microphone off');details();}
async function mute(reason='Microphone off'){
 guidedWake.finish(false);
 const oldLease=lease;generation++;active=false;starting=false;queue=[];lease=null;stopPlayback();
 if(node){node.port.onmessage=null;node.disconnect();node=null;}if(input){input.disconnect();input=null;}
 if(stream){stream.getTracks().forEach(t=>{t.onended=null;t.stop()});stream=null;}
 if(ctx){await ctx.close();ctx=null;}gain=null;display(reason);details();
 if(oldLease)fetch('/api/audio/stop',{method:'POST',headers:{'X-Audio-Stream':oldLease},signal:AbortSignal.timeout(delayLimit)}).catch(()=>{});
}
async function fail(error){faults.push({message:error.message,stage:error.stage||'endpoint',time:new Date().toISOString()});$('error').textContent=error.message;await mute('Microphone stopped · restart to retry');}
async function pump(){if(sending||!active)return;sending=true;const gen=generation;
 try{while(queue.length&&active&&generation===gen){const packet=queue.shift(),streamId=lease,requestStart=performance.now();
  const result=await fetchJson('/api/audio/frame',{method:'POST',headers:{'Content-Type':'application/octet-stream','X-Audio-Stream':streamId,'X-Audio-Sequence':String(packet.sequence)},body:packet.pcm});
  if(!active||generation!==gen)break;transportSamples.push({rtt_ms:performance.now()-requestStart,inference_ms:result.inference_ms});if(transportSamples.length>500)transportSamples.shift();latest=result;if(result.keyword){guidedWake.detected(result.wake_score);wakes++;$('results').textContent='Heard Tavi (experimental local detection)';}lastContact=performance.now();$('probability').value=result.probability;
  if(source){
    const confirmed=speechGate.accept(packet,result,ctx.sampleRate,ctx.currentTime);
    const previousConfirmed=previousGate.accept(packet,result,ctx.sampleRate,ctx.currentTime);
    if(currentCheck){currentCheck.frames++;currentCheck.max_probability=Math.max(currentCheck.max_probability,result.probability);currentCheck.confirmed_frames+=Number(confirmed);currentCheck.previous_gate_confirmed_frames+=Number(previousConfirmed);if(currentCheck.frame_trace.length<600)currentCheck.frame_trace.push({capture_position_ms:packet.endFrame/ctx.sampleRate*1000-startedAt*1000,probability:result.probability,gate:speechGate.reason,previous_gate:previousGate.reason,rtt_ms:performance.now()-requestStart});}
    if(confirmed&&$('autostop').checked)stopPlayback('speech',packet);
  }else if(!source)display(result.speech?'Listening · speech detected':'Microphone on · waiting');details();}
 }catch(e){if(generation===gen)await fail(e)}finally{sending=false;if(active&&queue.length)pump();}}
$('start').onclick=async()=>{if(active||starting)return;starting=true;display('Starting audio · allow microphone access if prompted');details();$('error').textContent='';const gen=++generation;
 try{ctx=new AudioContext({sampleRate:16000});contextRate=ctx.sampleRate;await Promise.race([ctx.resume(),new Promise((_,reject)=>setTimeout(()=>reject(Error('Audio startup timed out. Try this page in Chrome or Safari.')),5000))]);if(ctx.sampleRate!==16000)throw Error('This browser cannot provide a 16 kHz audio context');
  await ctx.audioWorklet.addModule('/capture.js');
  display('Waiting for microphone permission · Mute cancels');
  const acquired=await navigator.mediaDevices.getUserMedia({audio:{channelCount:1,echoCancellation:true,noiseSuppression:true,autoGainControl:false},video:false});
  if(gen!==generation){acquired.getTracks().forEach(t=>t.stop());return;}stream=acquired;
  const track=stream.getAudioTracks()[0],capabilities=track.getCapabilities?.()||{};
  if(Array.isArray(capabilities.echoCancellation)&&capabilities.echoCancellation.includes('all')){
    try{await track.applyConstraints({echoCancellation:{exact:'all'}});}catch(e){warnings.push({message:'System-audio echo mode unavailable; using browser default',time:new Date().toISOString()});}
  }
  settings=track.getSettings();
  const started=await fetchJson('/api/audio/start',{method:'POST'},10000);if(gen!==generation)return;lease=started.stream_id;wakeReady=started.wake_ready;wakeBackend=started.wake_backend;
  input=ctx.createMediaStreamSource(stream);node=new AudioWorkletNode(ctx,'tavi-capture');gain=ctx.createGain();gain.gain.value=0;
  input.connect(node);node.connect(gain);gain.connect(ctx.destination);active=true;latest=null;queue=[];lastContact=performance.now();
  node.port.onmessage=e=>{if(!active||gen!==generation)return;if(e.data.sampleRate!==16000){fail(Error('Unexpected worklet sample rate'));return;}if(queue.length>=4){fail(Error('Audio backlog exceeded 128 ms; capture stopped'));return;}queue.push(e.data);maxQueue=Math.max(maxQueue,queue.length);pump();};
  stream.getTracks().forEach(t=>t.onended=()=>fail(Error('Microphone disconnected or permission revoked')));display('Microphone on · waiting');details();
 }catch(e){if(gen===generation)await fail(e);}finally{if(gen===generation)starting=false;details();}};
$('wake-test').onclick=()=>{guidedWake.start(wakeBackend==='hey'?'Hey TAH-vee':'TAH-vee');details();};
$('volume').oninput=()=>{$('volume-value').textContent=Number($('volume').value).toFixed(2);};
$('intent').onchange=()=>details();
$('stop').onclick=()=>mute();$('cancel').onclick=()=>stopPlayback();
$('play').onclick=async()=>{if(!active||source||loadingReference)return;loadingReference=true;const gen=generation;$('error').textContent='';
 try{if(!reference){const r=await fetch('/reference.wav');if(!r.ok)throw Error('Reference clip missing; run python -m tavi.setup_audio');reference=await ctx.decodeAudioData(await r.arrayBuffer());}
 if(!active||gen!==generation)return;source=ctx.createBufferSource();source.buffer=reference;const volume=ctx.createGain();playbackGain=volume;volume.gain.value=Number($('volume').value);source.connect(volume);volume.connect(ctx.destination);
 source.onended=()=>{finishCheck('completed');source=null;volume.disconnect();display('Reference finished · microphone on');details()};startedAt=ctx.currentTime;speechGate.reset(startedAt);previousGate.reset(startedAt);currentCheck={play:plays+1,intent:selectedIntent(),autostop:$('autostop').checked,volume:Number($('volume').value),frames:0,confirmed_frames:0,previous_gate_confirmed_frames:0,frame_trace:[],max_probability:0};source.start();plays++;display('Talking · test in progress');
 if(selectedIntent()==='speak'){
  const delay=[2,5,8][speakingTrials++%3];currentCheck.cue_planned_ms=delay*1000;
  $('cue').textContent='Wait for SPEAK NOW. Say the phrase once only.';
  cueTimer=setTimeout(()=>{cueTimer=null;if(!source||generation!==gen||!currentCheck)return;currentCheck.cue_displayed_position_ms=(ctx.currentTime-startedAt)*1000;$('cue').textContent='SPEAK NOW: Please stop talking';},delay*1000);
 }else $('cue').textContent='Remain silent for the entire clip.';
 details();
 }catch(e){$('error').textContent=e.message;}finally{loadingReference=false;}};
$('download').onclick=()=>{const report={schema_version:3,kind:'E1_diagnostics_not_acoustic_acceptance',settings,reference_plays:plays,wake_detections:wakes,wake_ready:wakeReady,wake_backend:wakeBackend,guided_wake_test:guidedWake.result,interruptions:interrupts,playback_checks:playbackChecks,interruption_gate:{threshold:speechGate.threshold,consecutive_frames:speechGate.required},comparison_gate:{threshold:previousGate.threshold,consecutive_frames:previousGate.required},faults,warnings,context_sample_rate:contextRate,latest,transport_samples:transportSamples,max_queue_frames:maxQueue,api_spend_usd:0};const link=document.createElement('a');link.href=URL.createObjectURL(new Blob([JSON.stringify(report,null,2)],{type:'application/json'}));link.download='tavi-audio-diagnostics.json';link.click();setTimeout(()=>URL.revokeObjectURL(link.href),1000);};
setInterval(()=>{if(active&&performance.now()-lastContact>1500)fail(Error('Local audio service is unresponsive'));if(active&&ctx?.state!=='running')fail(Error('Audio context suspended'));},500);
window.addEventListener('pagehide',()=>mute());details();

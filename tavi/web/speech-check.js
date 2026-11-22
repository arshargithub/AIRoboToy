'use strict';
const $=id=>document.getElementById(id),collector=new SampleCollector(8,250);
let plan,digest,context=null,mic=null,node=null,input=null,sink=null,source=null,gain=null,session=null,reference=null;
let generation=0,starting=false,lastFrame=0,startedAt=0,settings={},complete=false;
const hex=bytes=>Array.from(new Uint8Array(bytes),x=>x.toString(16).padStart(2,'0')).join('');
function stopAudio(){if(source){source.onended=null;try{source.stop()}catch{}source.disconnect();source=null;}if(gain){gain.disconnect();gain=null;}}
async function closeMic(){
 generation++;starting=false;stopAudio();
 if(node){node.port.onmessage=null;node.disconnect();node=null;}if(input){input.disconnect();input=null;}if(sink){sink.disconnect();sink=null;}
 if(mic){mic.getTracks().forEach(t=>{t.onended=null;t.stop()});mic=null;}
 const old=context;context=null;if(old&&old.state!=='closed')await old.close();
}
function show(phase,trial,index){
 $('session').dataset.phase=phase;$('step').textContent=`Turn ${index+1} of ${plan.trials.length}`;
 $('progress').value=collector.clips.length;
 $('phrase').textContent=trial.phrase||'Stay quiet for this turn.';
 $('condition').textContent=trial.phrase?(trial.condition==='overlap'?'Paprika will talk. Speak over it when the card turns green.':'Quiet turn · your voice only.'):(trial.condition==='overlap'?'Paprika will talk. You stay quiet.':'Quiet room. You stay quiet.');
 const words={read:['Read this first','Get ready. Recording starts in three seconds.'],wait:['Wait…','Stay quiet until the card turns green.'],speak:['Your turn — say it now','Say the whole phrase once. Stay quiet after you finish.'],silent:['Stay quiet','Do not say anything. We’re checking whether silence creates invented words.']}[phase];
 $('phase').textContent=words[0];$('help').textContent=words[1];
 $('status').textContent=phase==='read'?'Microphone on · this preparation interval is not saved':'Microphone on · saving this eight-second clip locally';
}
function finished(all){
 complete=all;closeMic();$('session').hidden=true;$('done').hidden=false;
 $('done-title').textContent=all?'All eight turns saved':'Recording stopped';
 $('done-help').textContent=`${collector.clips.length} complete clips are ready. ${all?'':'The unfinished turn was discarded.'}`;
 $('download').disabled=!collector.clips.length;$('status').textContent='Microphone off';
}
function fail(error){$('error').textContent=error.message;if(session?.active)session.finish(false);else{closeMic();$('start').disabled=false;$('status').textContent='Microphone off · recording could not start';}}
function play(){
 stopAudio();source=context.createBufferSource();source.buffer=reference;gain=context.createGain();gain.gain.value=Number($('volume').value);source.connect(gain);gain.connect(context.destination);
 collector.current.reference_start_frame=Math.round(context.currentTime*16000);source.start();
}
$('start').onclick=async()=>{
 if(starting||context)return;starting=true;$('start').disabled=true;$('error').textContent='';$('status').textContent='Starting · allow microphone access if asked';const captured=++generation;
 try{
  const audio=new AudioContext({sampleRate:16000});context=audio;await audio.resume();if(captured!==generation)return;
  if(audio.sampleRate!==16000)throw Error('This check needs a 16 kHz audio context.');
  const bytes=await (await fetch('/paprika-reference.wav')).arrayBuffer();if(captured!==generation)return;
  if(hex(await crypto.subtle.digest('SHA-256',bytes))!==plan.reference_sha256)throw Error('The reference voice differs from this test protocol.');
  reference=await audio.decodeAudioData(bytes);await audio.audioWorklet.addModule('/capture.js');if(captured!==generation)return;
  const stream=await navigator.mediaDevices.getUserMedia({audio:{channelCount:1,echoCancellation:true,noiseSuppression:true,autoGainControl:false},video:false});
  if(captured!==generation){stream.getTracks().forEach(t=>t.stop());return;}mic=stream;
  const actual=stream.getAudioTracks()[0].getSettings();settings=Object.fromEntries(['sampleRate','channelCount','echoCancellation','noiseSuppression','autoGainControl','latency'].filter(k=>k in actual).map(k=>[k,actual[k]]));
  input=audio.createMediaStreamSource(stream);node=new AudioWorkletNode(audio,'tavi-capture');sink=audio.createGain();sink.gain.value=0;input.connect(node);node.connect(sink);sink.connect(audio.destination);
  session=new SpeechCheckSession({plan,collector,show,play,stopAudio,done:finished});
  node.port.onmessage=e=>{if(captured!==generation)return;lastFrame=performance.now();try{
   const packet=e.data;
   if(session.recording&&collector.current){if(!collector.current.frames.length)collector.current.capture_start_frame=packet.endFrame-512;if(collector.current.frames.length+1===plan.cue_frame)collector.current.cue_context_frame=packet.endFrame;}
   session.frame(packet);
  }catch(error){fail(error);}};
  mic.getTracks().forEach(t=>t.onended=()=>fail(Error('Microphone disconnected; the partial turn was discarded.')));
  startedAt=lastFrame=performance.now();starting=false;$('setup').hidden=true;$('session').hidden=false;session.start();$('session').scrollIntoView?.({block:'start',behavior:'smooth'});
 }catch(error){if(captured===generation)fail(error);}
};
$('stop').onclick=()=>session?.finish(false);
$('volume').oninput=()=>{$('volume-value').textContent=Math.round(Number($('volume').value)*100)+'%';if(gain)gain.gain.value=Number($('volume').value);};
function encoded(frames){let text='';for(const frame of frames)text+=String.fromCharCode(...frame);return btoa(text);}
$('download').onclick=()=>{
 if(context||starting||!collector.clips.length)return;
 const report={schema_version:1,kind:plan.kind,protocol_id:plan.protocol_id,protocol_sha256:digest,
  created_at:new Date().toISOString(),consent:'Explicit Start recording on this Mac button',complete,sample_rate:16000,format:'mono_pcm16le_base64',settings,reference_volume:Number($('volume').value),
  clips:collector.clips.map(({frames,...metadata})=>({...metadata,sample_count:frames.length*512,pcm_base64:encoded(frames)}))};
 const link=document.createElement('a');link.href=URL.createObjectURL(new Blob([JSON.stringify(report)],{type:'application/json'}));link.download='paprika-speech-check-'+crypto.randomUUID()+'.json';link.click();setTimeout(()=>URL.revokeObjectURL(link.href),1000);$('saved').textContent='Download started. Tell me “Downloaded” in the chat.';
};
setInterval(()=>{if(session?.active&&(performance.now()-lastFrame>1500||context?.state!=='running'))fail(Error('Microphone frames stalled. Save the completed clips.'));else if(session?.active&&performance.now()-startedAt>180000)fail(Error('Three-minute safety limit reached. Save the completed clips.'));},500);
window.addEventListener('pagehide',()=>{if(session?.active)session.finish(false);else closeMic();});
(async()=>{try{const response=await fetch('/speech-check-protocol.json');if(!response.ok)throw Error('Could not load the recording protocol.');const bytes=await response.arrayBuffer();digest=hex(await crypto.subtle.digest('SHA-256',bytes));plan=JSON.parse(new TextDecoder().decode(bytes));$('start').disabled=false;$('status').textContent='Ready · microphone off';}catch(error){$('error').textContent=error.message;$('status').textContent='Microphone off';}})();

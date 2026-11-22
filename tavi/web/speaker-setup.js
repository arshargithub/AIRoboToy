'use strict';
const $=id=>document.getElementById(id);let session=null,state=null,phase='setup',available=false,busy=false,recording=false,serial=0,context=null,mic=null,node=null,input=null,sink=null,timer=null,frames=[],lastSequence=null,pcm=null,preview=null,audioURL=null,retryTechnical=false,captureSettings={};
try{session=sessionStorage.getItem('paprika-adult-voice-session');}catch{}
const text=(id,value)=>{$(id).textContent=value;};
function saveSession(value){session=value;try{if(value)sessionStorage.setItem('paprika-adult-voice-session',value);else sessionStorage.removeItem('paprika-adult-voice-session');}catch{}}
async function api(path,{method='GET',body,raw=false,index}={}){
 const headers={};if(session)headers['X-Enrollment-Session']=session;
 if(body!==undefined)headers['Content-Type']=raw?'application/octet-stream':'application/json';if(index!==undefined)headers['X-Clip-Index']=String(index);
 const r=await fetch(path,{method,headers,body:body===undefined?undefined:raw?body:JSON.stringify(body),signal:AbortSignal.timeout(35000)});const d=await r.json();if(!r.ok){const e=Error(d.error||'Local action failed. Keep this page open and try again.');e.status=r.status;throw e;}return d;
}
function show(next){
 phase=next;$('card').dataset.phase=phase;
 text('microphone-state',recording?'Microphone on · recording this phrase':mic?'Microphone on · countdown, not saving yet':'Microphone off · no background listening');const setup=phase==='setup',done=phase==='done',finish=phase==='finish';
 $('setup').hidden=!setup;$('record-panel').hidden=setup||finish||done;$('finish-panel').hidden=!finish;$('done').hidden=!done;
 text('step',setup?'Get ready':done?'Finished':finish?'One last step':`${(state?.saved_clips??0)+1} of 6`);
 text('title',setup?'Six short recordings, all local':done?'Your candidate profile is saved':finish?'Save your voice profile':phase==='recording'?'Speak now':phase==='countdown'?'Get ready…':phase==='checking'?'Checking your recording':'Read this phrase');
 text('help',setup?'About two to three minutes. Read one phrase at a time. We check each recording before saving it.':done?'This completes enrollment collection, not recognition testing.':finish?'Your next voice check will use fresh speech, not these same recordings.':'Say the whole phrase once in your normal voice. Then stay quiet until recording stops.');
 text('phrase',state?.phrase||'');$('record').hidden=!['phrase','preview'].includes(phase);$('stop-recording').hidden=!['countdown','recording'].includes(phase);$('use').hidden=phase!=='preview'||!preview;$('retry-check').hidden=phase!=='preview'||!!preview||!pcm||!retryTechnical;
 $('record').className=phase==='preview'&&(!!preview||retryTechnical)?'':'primary';$('retry-check').className=retryTechnical?'primary':'';
 $('playback').hidden=phase!=='preview'||!audioURL;$('progress').hidden=!['recording','countdown'].includes(phase);$('pause').disabled=phase==='checking';$('record').disabled=busy;$('use').disabled=busy;
 text('record',phase==='preview'?'Record again':'Record this phrase');
}
function showState(){if(state?.complete)show('done');else if(state?.saved_clips===6)show('finish');else show('phrase');}
async function checkDrive(){
 try{const d=await api('/api/setup');available=d.available;text('ready',d.message);$('begin').disabled=!available;return d;}
 catch(e){available=false;text('ready','Local setup service is unavailable. Keep this page open and try Check drive again.');$('begin').disabled=true;}
}
function clearAudio(){$('playback').pause();if(audioURL)URL.revokeObjectURL(audioURL);audioURL=null;$('playback').removeAttribute('src');pcm=null;preview=null;retryTechnical=false;text('quality','');}
function wav(bytes){const out=new Uint8Array(44+bytes.byteLength),v=new DataView(out.buffer);for(const [offset,s] of [[0,'RIFF'],[8,'WAVE'],[12,'fmt '],[36,'data']])for(let i=0;i<s.length;i++)v.setUint8(offset+i,s.charCodeAt(i));v.setUint32(4,36+bytes.byteLength,true);v.setUint32(16,16,true);v.setUint16(20,1,true);v.setUint16(22,1,true);v.setUint32(24,16000,true);v.setUint32(28,32000,true);v.setUint16(32,2,true);v.setUint16(34,16,true);v.setUint32(40,bytes.byteLength,true);out.set(new Uint8Array(bytes.buffer,bytes.byteOffset,bytes.byteLength),44);return new Blob([out],{type:'audio/wav'});}
async function shutMic(){
 recording=false;clearTimeout(timer);timer=null;
 if(node){node.port.onmessage=null;node.disconnect();node=null;}if(input){input.disconnect();input=null;}if(sink){sink.disconnect();sink=null;}
 if(mic){mic.getTracks().forEach(t=>{t.onended=null;t.stop();});mic=null;}
 const old=context;context=null;if(old)await old.close().catch(()=>{});
}
async function checkRecording(){
 if(!pcm)return;const version=serial;busy=true;show('checking');text('cue','Microphone off · checking locally');text('error','');
 try{const d=await api('/api/preview',{method:'POST',raw:true,index:state.saved_clips,body:pcm});if(version!==serial)return;
  const hash=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',pcm))).map(n=>n.toString(16).padStart(2,'0')).join('');if(hash!==d.pcm_sha256)throw Error('The local result did not match this recording. Record the phrase again.');
  preview=d;text('quality','Clear voice found. Play it if you want. If you were the only person speaking and said the phrase, use this recording.');
 }catch(e){if(version!==serial)return;preview=null;retryTechnical=!e.status||e.status>=500||/external drive|Reconnect|local.*unavailable/i.test(e.message);text('quality','This recording has not been saved. You can play it, record again, or retry the local check after reconnecting the drive.');text('error',e.message);}
 finally{if(version===serial){busy=false;show('preview');text('cue','Microphone off · review your recording');}}
}
async function finishRecording(){
 if(!['recording','countdown'].includes(phase))return;
 if(!recording){serial++;await shutMic();busy=false;show('phrase');text('cue','Microphone off · ready');return;}
 const version=serial,wasRecording=recording;show('checking');text('cue','Stopping microphone…');await shutMic();if(version!==serial)return;
 if(!wasRecording||!frames.length){busy=false;show('phrase');text('cue','Microphone off · ready');return;}
 const out=new Uint8Array(frames.length*1024);frames.forEach((frame,i)=>out.set(new Uint8Array(frame),i*1024));pcm=out;frames=[];
 audioURL=URL.createObjectURL(wav(pcm));$('playback').src=audioURL;await checkRecording();
}
async function record(){
 if(busy||!['phrase','preview'].includes(phase))return;serial++;const version=serial;clearAudio();frames=[];lastSequence=null;busy=true;show('countdown');text('error','');text('cue','Microphone setup · allow access if asked');$('progress').value=0;
 try{
  const ctx=new AudioContext({sampleRate:16000});context=ctx;await ctx.resume();if(version!==serial)return;if(ctx.sampleRate!==16000)throw Error('This browser did not provide 16 kHz sound. Try this page in Chrome or Safari.');await ctx.audioWorklet.addModule('/capture.js');if(version!==serial)return;
  const stream=await navigator.mediaDevices.getUserMedia({audio:{channelCount:1,echoCancellation:true,noiseSuppression:true,autoGainControl:false},video:false});if(version!==serial){stream.getTracks().forEach(t=>t.stop());return;}mic=stream;captureSettings={audio_context_rate:ctx.sampleRate,requested_echo_cancellation:true,requested_noise_suppression:true,requested_auto_gain_control:false};
  const reported=(stream.getAudioTracks?.()??[])[0]?.getSettings?.()??{};for(const name of ['sampleRate','channelCount','echoCancellation','noiseSuppression','autoGainControl'])if(reported[name]!==undefined)captureSettings['actual_'+name]=reported[name];show('countdown');
  input=ctx.createMediaStreamSource(stream);node=new AudioWorkletNode(ctx,'tavi-capture');sink=ctx.createGain();sink.gain.value=0;input.connect(node);node.connect(sink);sink.connect(ctx.destination);
  node.port.onmessage=e=>{
   if(!recording||version!==serial)return;const packet=e.data;
   if(packet.sampleRate!==16000||packet.pcm.byteLength!==1024||(lastSequence!==null&&packet.sequence!==lastSequence+1)){serial++;shutMic();busy=false;show('phrase');text('error','Audio frames were interrupted. The microphone is off. Record this phrase again.');return;}
   lastSequence=packet.sequence;frames.push(packet.pcm.slice(0));$('progress').value=frames.length;text('cue',`Speak now · ${Math.max(0,Math.ceil((250-frames.length)*.032))} seconds left`);
   if(frames.length>=250)finishRecording();
  };
  stream.getTracks().forEach(t=>t.onended=()=>{if(version===serial){serial++;shutMic();busy=false;show('phrase');text('error','Microphone disconnected. Reconnect it and record this phrase again.');}});
  for(const n of [2,1]){if(version!==serial)return;text('cue',`Get ready · ${n}`);await new Promise(resolve=>setTimeout(resolve,1000));}
  if(version!==serial)return;recording=true;show('recording');text('cue','Speak now · 8 seconds left');timer=setTimeout(async()=>{serial++;await shutMic();frames=[];busy=false;show('phrase');text('cue','Microphone off · ready');text('error','Microphone frames stalled. Reconnect the microphone and record this phrase again.');},10000);
 }catch(e){if(version!==serial)return;await shutMic();busy=false;show('phrase');text('cue','Microphone off · ready');text('error',e.name==='NotAllowedError'?'Microphone access was not allowed. Allow it in this browser’s site settings, then press Record again.':e.message);}
}
$('begin').onclick=async()=>{
 if(busy)return;text('error','');const person=$('person').value,choice=document.querySelector('input[name=processing]:checked')?.value,retain=document.querySelector('input[name=retention]:checked')?.value;
 if(!person||!$('adult').checked||choice!=='local-only'||!retain){text('error',!person?'Choose the adult who is speaking.':!$('adult').checked?'Confirm that you are the selected adult, speaking alone.':choice!=='local-only'?'Choose local-only processing to continue. No microphone has started.':'Choose whether to keep reference recordings. No microphone has started.');return;}
 busy=true;$('begin').disabled=true;
 try{state=await api('/api/begin',{method:'POST',body:{person_id:person,adult_alone:true,processing:choice,retain_audio:retain==='keep',consent:'adult-local-voice-enrollment-v1'}});saveSession(state.session);busy=false;showState();text('cue','Microphone off · ready');}
 catch(e){text('error',e.message);$('new-profile').hidden=!session;}
 finally{busy=false;$('begin').disabled=!available;}
};
$('record').onclick=record;$('stop-recording').onclick=finishRecording;$('retry-check').onclick=checkRecording;
$('use').onclick=async()=>{
 if(!preview||busy)return;busy=true;$('use').disabled=true;text('error','');text('cue','Microphone off · saving locally');
 try{state=await api('/api/use',{method:'POST',body:{index:state.saved_clips,sha:preview.pcm_sha256,capture_settings:captureSettings}});clearAudio();busy=false;showState();text('cue','Microphone off · ready');}
 catch(e){
  try{const fresh=await api('/api/state');if(fresh.clip_hashes?.[state.saved_clips]===preview?.pcm_sha256){state=fresh;clearAudio();busy=false;showState();text('cue','Microphone off · saved');return;}}catch{}
  preview=null;retryTechnical=true;busy=false;show('preview');text('error',e.message+' Keep this recording and use Retry local check.');text('cue','Microphone off · recording not saved yet');
 }
 finally{busy=false;$('use').disabled=false;}
};
$('pause').onclick=async()=>{serial++;await shutMic();busy=false;show('setup');text('error','Enrollment paused. Accepted recordings are saved locally; the current unsaved recording is not part of the profile. Confirm your choices to resume.');$('adult').checked=false;$('resume').hidden=false;$('new-profile').hidden=false;text('resume',`${state?.saved_clips??0} of 6 recordings saved for ${state?.name??'this adult'}. Original choice: ${state?.retain_audio?'keep reference recordings and profile':'profile and measurements only'}.`);};
$('back-setup').onclick=()=>$('pause').onclick();
$('finish').onclick=async()=>{if(busy)return;busy=true;$('finish').disabled=true;text('error','');try{state=await api('/api/finish',{method:'POST',body:{note:$('note').value}});showState();}catch(e){text('error',e.message);}finally{busy=false;$('finish').disabled=false;}};
$('check-drive').onclick=checkDrive;
$('new-profile').onclick=()=>{serial++;saveSession(null);state=null;clearAudio();$('resume').hidden=true;$('new-profile').hidden=true;$('adult').checked=false;document.querySelectorAll('input[type=radio]').forEach(e=>e.checked=false);show('setup');text('error','Existing recordings and profiles are kept. Choose settings for a separate new profile.');};
window.addEventListener('pagehide',()=>{serial++;shutMic();});
(async()=>{await checkDrive();if(session){try{state=await api('/api/state');if(state.complete){show('done');return;}$('person').value=state.person_id;$('resume').hidden=false;text('resume',`${state.saved_clips} of 6 recordings already saved for ${state.name}. Your original choice was ${state.retain_audio?'keep reference recordings and profile':'profile and measurements only'}. Choose the same option to resume.`);$('new-profile').hidden=false;}catch(e){text('error',e.message);$('new-profile').hidden=false;}}show('setup');})();

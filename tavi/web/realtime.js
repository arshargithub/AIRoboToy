'use strict';
const $=id=>document.getElementById(id),gate=new SpeechInterruptionGate(.65,2);
const closureCheck=typeof location!=='undefined'&&new URLSearchParams(location.search).get('workflow')==='closure-v2';
const engagementCheck=typeof location!=='undefined'&&(location.pathname==='/engagement'||new URLSearchParams(location.search).get('workflow')==='engagement-v1');
const phrases=engagementCheck?['I wonder what we could build next.','Paprika, what is our pretend fort called?',
 'Tell me a longer story about that fort.','Wait, make it a space adventure instead.',
 'What is our pretend fox’s name?','Goodbye, Paprika.','I wonder what we could build next.']:
 closureCheck?['Paprika, suggest one name for a tiny silver robot.','That is all for now. Goodbye.']:[
 'Paprika, tell me a short story about a fox finding a treasure.',
 'Make the treasure a tiny silver robot.',
 'Tell me another story about the fox, this time in a forest.',
 'Wait, make it a space adventure instead.',
 'That is all for now, Paprika. Goodbye.'
];
const questions=engagementCheck?{standby_quiet:'Was Paprika quiet on both “I wonder” steps?',wake:'Did Paprika respond to the first addressed request, including the whole question?',context:'Did Paprika call the pretend fort Star Nest and its fox Pixel?',followup:'Did follow-ups work without repeating Paprika?',stopped_promptly:'Did Paprika stop promptly on your first interruption?',changed_story:'Did the replacement story become a space adventure?',goodbye:'Did Paprika finish its goodbye and return to local listening?',responsive:'Did waking and follow-ups feel quick enough?'}:closureCheck?{quiet_complete:'Did the first reply finish and show the goodbye phrase automatically?',goodbye:'Did Paprika say goodbye, finish, and turn the microphone off automatically?',no_reintroduction:'Did Paprika answer directly without introducing itself again?',responsive:'Did the replies still feel quick enough?'}:{quiet_complete:'Did the first two replies finish while you stayed quiet?',followup:'Did the treasure become a tiny silver robot?',stopped_promptly:'Did Paprika stop promptly on your first interruption?',changed_story:'Did the replacement reply switch to a space adventure?',goodbye:'Did Paprika finish with a goodbye?',responsive:'Did the replies feel quick enough for a natural conversation?',voice_acceptable:'Would this different voice be acceptable if the conversation worked better?'};
let id=null,ctx=null,mic=null,node=null,input=null,sink=null,playback=null,active=false,starting=false,generation=0,queue=[],pumping=false,sequence=0,prep=0,origin=null,expectedWorklet=-1;
let asked=0,replyCount=0,playing=null,replyLatency=new Map(),seen=new Set(),blocked=new Set(),trace=[],ratings={},stopPromise=null;
let phaseTimer=null,readyTimer=null,watchdog=null,lastFrame=0,began=0,saveAudio=false,savedResult=null;
function show(section){for(const name of ['setup','practice-card','ready','live','review'])$(name).hidden=name!==section;}
function status(s){$('status').textContent=s;}
function note(kind,data={}){if(trace.length<600)trace.push({kind,at_ms:performance.now(),...data});}
function phase(cue,title,help,phrase=undefined){$('live').dataset.cue=cue;$('cue').textContent=title;$('help').textContent=help;
 // A status change must not erase the sentence the person is still reading.
 // Only an explicit next phrase (or explicit null) changes this prompt.
 if(phrase!==undefined){$('phrase').hidden=phrase===null;$('phrase').textContent=phrase??'';}}
function timeoutPhase(ms,message){clearTimeout(phaseTimer);phaseTimer=setTimeout(()=>finish(message),ms);}
function ask(index){asked=index;$('step').textContent=`Step ${index+1} of ${phrases.length}`;const local=engagementCheck&&(index===0||index===6);phase('speak',local?'Local listening check':index===3?'Interrupt now':'Your turn',local?'Say the whole phrase once, then stay quiet. Paprika should not answer. The page moves on after the local check.':index===3?'Say the whole phrase while Paprika is talking. Then stay quiet and hear the new reply.':'Say the whole phrase once. Then stay quiet and wait for the reply.',phrases[index]);status(local?'Microphone on · local listening · cloud channel closed':'Microphone on · your turn');timeoutPhase(20000,'This step did not finish in time. Save the attempt so we can investigate.');}
async function api(path,data={},timeout=6000){const response=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({session_id:id,...data}),signal:AbortSignal.timeout(timeout)});const result=await response.json();if(!response.ok)throw Error(result.error||'Local test request failed');return result;}
function consent(){return ['adult','cloud','recording',...(engagementCheck?['context-fixture']:[])].every(k=>$(k).checked);}
for(const k of ['adult','cloud','recording','context-fixture'])$(k).onchange=()=>{$('prepare').disabled=!consent();};
$('practice').onclick=()=>{$('practice-card').dataset.cue='wait';$('practice-title').textContent='Wait for the green “Your turn” cue';show('practice-card');status('Practice · microphone off');};
$('practice-cue').onclick=()=>{$('practice-card').dataset.cue='speak';$('practice-title').textContent='Your turn · say the big phrase';};
$('practice-back').onclick=()=>{show('setup');status('Microphone off · nothing sent');};
$('practice-listen').onclick=()=>{
 show('live');$('step').textContent='Practice · microphone stays off';
 phase('speak','Your turn','Read the sentence at your own pace.',phrases[0]);
 phase('wait','Listening locally','Preview only: when you start speaking, the sentence stays here so you can finish. No microphone or cloud connection is open.');
 $('stop').hidden=true;$('preview-back').hidden=false;status('Practice · microphone off');
};
$('preview-back').onclick=()=>{$('preview-back').hidden=true;$('stop').hidden=false;show('setup');status('Microphone off · nothing sent');};
$('prepare').onclick=async()=>{
 if(!consent()||starting)return;starting=true;const version=++generation;id=crypto.randomUUID().replaceAll('-','');saveAudio=$('save-audio').checked;status('Getting ready · microphone off');$('prepare').disabled=true;$('error').textContent='';
 try{await api('/prepare',{adult:true,cloud:true,recording:true,save_audio:saveAudio,workflow:engagementCheck?'engagement-v1':closureCheck?'closure-v2':'full-v1',...(engagementCheck?{context_fixture:true}:{})},35000);if(version!==generation)return;show('ready');status('Ready · microphone off · start within25 seconds');readyTimer=setTimeout(()=>finish('The ready window expired. Save this attempt; no microphone was opened.'),25000);}
 catch(error){if(version===generation)await finish(error.message);}
 finally{starting=false;}
};
async function bounded(promise,ms,message){let timer;try{return await Promise.race([promise,new Promise((_,reject)=>{timer=setTimeout(()=>reject(Error(message)),ms);})]);}finally{clearTimeout(timer);}}
function clearTimers(){clearTimeout(phaseTimer);clearTimeout(readyTimer);clearInterval(watchdog);}
function playbackStart(responseId,scheduledStart){
 if(!active)return;playing=responseId;gate.reset(scheduledStart);replyCount++;note('playback_started',{id:responseId,reply_number:replyCount,estimated_ms_since_vad_speech_end:replyLatency.get(responseId)??null});
 if(!closureCheck&&replyCount===(engagementCheck?2:3)){phase('talk','Listen first','Keep listening. We will show the interruption phrase in about two seconds.');clearTimeout(phaseTimer);phaseTimer=setTimeout(()=>{if(active&&playing===responseId)ask(3);},Math.max(0,(scheduledStart+2-ctx.currentTime)*1000));}
 else{phase('talk','Paprika is talking','Stay quiet until the reply finishes. The next phrase will appear automatically.');timeoutPhase(35000,'The reply did not finish. Save this attempt.');}
 status('Microphone on · Paprika is talking · you can interrupt');
}
async function playbackComplete(responseId){
 if(!active||blocked.has(responseId))return;note('playback_ended',{id:responseId});playing=null;
 try{await api('/played',{id:responseId,latency_ms:replyLatency.get(responseId)??null});if(!active)return;
  if(engagementCheck){if(replyCount===1)ask(2);else if(replyCount===3)ask(4);else if(replyCount===4)ask(5);else if(replyCount===5){if(asked!==6){phase('wait','Returning to local listening','Stay quiet. The cloud channel closes before the final local-only phrase appears.');timeoutPhase(10000,'The goodbye did not return to local listening. Save this attempt.');}}else await finish('The story finished before an interruption was confirmed. Save this attempt.');}
  else if(closureCheck){if(replyCount===1)ask(1);else if(replyCount===2)await finish();else await finish('An unexpected reply happened. Save this attempt.');}
  else if(replyCount===1)ask(1);else if(replyCount===2)ask(2);else if(replyCount===4)ask(4);else if(replyCount===5)await finish();else await finish('The forest story finished before an interruption was confirmed. Save this attempt.');
 }catch(error){await finish(error.message);}
}
async function interrupt(){
 const responseId=playing;if(!responseId)return;const played=playback.stop(responseId); // Before network, even if API fails.
 blocked.add(responseId);playing=null;note('local_playback_stopped',{id:responseId,played_ms:played});
 await api('/interrupt',{id:responseId,played_ms:played});
}
async function pump(){
 if(pumping||!active)return;pumping=true;const version=generation;
 try{while(active&&generation===version&&queue.length){const packet=queue.shift();
  if(ctx.currentTime-packet.endFrame/16000>.2)throw Error('Microphone audio fell behind. Save this attempt.');
  const bytes=new Uint8Array(packet.pcm);let binary='';for(const b of bytes)binary+=String.fromCharCode(b);
  const result=await api('/frame',{sequence:packet.sequence,pcm:btoa(binary)});
  if(!active||generation!==version)break;
  if(playing&&gate.accept(packet,result,16000,ctx.currentTime))await interrupt();
  if(!active||generation!==version)break;
  for(const event of result.events){
   if(engagementCheck){
    if(event.kind==='local_speech_started'){phase('wait','Listening locally','Finish the phrase, then stay quiet. Nothing from this standby turn has been sent to the cloud.');status('Microphone on · local speech check');}
    if(event.kind==='checking_address'){phase('wait','Checking the name locally','Stay quiet while the local recognizer checks whether you addressed Paprika.');status('Microphone on · checking locally');}
    if(event.kind==='address_confirmed'){note('address_confirmed_locally');if(asked!==1){await finish('Paprika activated during a local-only step. Save this attempt.');break;}phase('wait','Heard Paprika','Your complete first request will be sent with the shared pretend facts. Stay quiet.');}
    if(event.kind==='standby_rejected'){note('standby_speech_kept_local');if(asked===0)ask(1);else if(asked===6)await finish();else await finish('The local check did not recognize an addressed request. Save this attempt.');}
    if(event.kind==='standby'){note('returned_to_local_standby',{reason:event.reason});if(replyCount===5&&event.reason==='goodbye')ask(6);else await finish('The conversation returned to local listening before this step finished. Save this attempt.');}
   }
   if(!active)break;
   if(event.kind==='speech_started'){note('speech_started');status('Microphone on · listening to you');}
   if(event.kind==='committed'){note('input_committed',{speech_end_sample:event.speech_end_sample});if(!playing){phase('wait','Thinking','Your words have been sent. Stay quiet while the reply starts.');status('Microphone on · thinking');}}
   if(event.kind==='audio'&&!blocked.has(event.id)){
    if(!seen.has(event.id)){seen.add(event.id);replyLatency.set(event.id,(ctx.currentTime-(origin+event.speech_end_sample)/16000)*1000);}
    const raw=atob(event.pcm),buffer=new ArrayBuffer(raw.length),view=new DataView(buffer);for(let i=0;i<raw.length;i++)view.setUint8(i,raw.charCodeAt(i));
    if(raw.length%2)throw Error('Invalid reply audio');const samples=new Int16Array(raw.length/2);for(let i=0;i<samples.length;i++)samples[i]=view.getInt16(i*2,true);
    playback.add(event.id,samples);
   }
   if(event.kind==='done'){note('provider_terminal',{id:event.id,status:event.status});if(event.status==='completed'&&!blocked.has(event.id))playback.done(event.id);}
  }
 }}catch(error){if(version===generation)await finish(error.message);}
 finally{pumping=false;if(active&&queue.length)pump();}
}
if(engagementCheck){
 $('page-title').textContent='From local listening to a conversation.';
 $('setup-title').textContent='One guided conversation, with pretend play facts';
 $('setup-purpose').textContent='We are checking that Paprika stays quiet until addressed, gets the whole first question, uses the supplied pretend facts, follows up without its name, stops for an interruption, and returns to local listening after goodbye. K remains your selected voice; this trial uses a different voice.';
 $('scope-copy').textContent='Standby speech is checked entirely on this Mac. A complete locally recognized address opens the cloud connection and forwards that first utterance; engaged follow-ups use native cloud speech. Two fixed fictional facts are supplied before each reply. This does not recognize people, learn memories or choose a memory engine. A local farewell check and a 20-second idle fallback close the cloud session. Replies stream as they arrive and can fail after speech begins.';
 $('cloud-copy').textContent='Send this test’s new addressed speech and engaged follow-ups to OpenAI, with the fictional shared facts. Nearby sounds can be included while engaged. Standard provider monitoring retention applies. Unaddressed standby speech, voice embeddings and the memory database are not uploaded.';
 $('context-choice').hidden=false;
 $('limits-copy').textContent='Five short cloud requests at most, up to $5 reserved within the existing $25 cap; the test ends within three minutes. Two other spoken steps are local-only checks. No old recording is uploaded. Save keeps replies, timings, local check outcomes and ratings privately on this Mac; the optional listening copy also keeps microphone audio. Unsaved audio disappears if this server restarts.';
 $('practice-help').textContent='Say the big phrase only after the green cue, then stay quiet. Two steps should get no reply. One step tells you exactly when to interrupt. The page guides every transition and turns off the microphone before review.';
 $('practice-phrase').textContent=phrases[0];
 $('ready-copy').textContent='The local speech detector and recognizer are ready. The microphone is still off and no cloud voice connection is open. Next we’ll ask for microphone permission, count down, then show the first phrase.';
 $('comparison-copy').textContent='Integration probe only: local MLX Whisper turbo address/closure checks, local Silero and interruption, native OpenAI speech, and a bounded fictional shared-context adapter. No family recognition, persistent memory engine, full acoustic p95 or product acceptance is claimed. The first turn waits for complete local recognition; follow-ups stream while engaged.';
}
$('start').onclick=async()=>{
 if(active)return;clearTimeout(readyTimer);const version=++generation;starting=true;$('stop').hidden=false;$('preview-back').hidden=true;show('live');phase('wait','Starting the microphone','Allow microphone access if asked. Wait for the green cue before speaking.',null);status('Waiting for microphone permission');
 try{
  const context=new AudioContext({sampleRate:16000});ctx=context;await bounded(context.resume(),5000,'Audio startup timed out. Save this attempt.');if(version!==generation){await context.close();return;}
  if(context.sampleRate!==16000)throw Error('This browser could not start the required audio format. Save the attempt.');
  const permission=navigator.mediaDevices.getUserMedia({audio:{channelCount:1,echoCancellation:true,noiseSuppression:true,autoGainControl:false}});
  permission.then(stream=>{if(version!==generation)stream.getTracks().forEach(t=>t.stop());},()=>{});
  const stream=await bounded(permission,15000,'Microphone permission timed out. Save this attempt.');
  if(version!==generation){stream.getTracks().forEach(t=>t.stop());await context.close();return;}
  mic=stream;const settings=mic.getAudioTracks?.()[0]?.getSettings?.()||{};note('microphone_settings',{settings:Object.fromEntries(['sampleRate','channelCount','echoCancellation','noiseSuppression','autoGainControl','voiceIsolation'].filter(k=>k in settings).map(k=>[k,settings[k]])),audio_context_rate:context.sampleRate,base_latency:context.baseLatency??null,output_latency:context.outputLatency??null});for(const t of mic.getTracks())t.onended=()=>finish('Microphone disconnected. Save this attempt.');
  await context.audioWorklet.addModule('/capture.js');if(version!==generation)return;
  playback=new NativePlayback(context,{onStart:playbackStart,onComplete:playbackComplete,onEvent:event=>note('playback_state',event)});
  input=context.createMediaStreamSource(stream);node=new AudioWorkletNode(context,'tavi-capture');sink=context.createGain();sink.gain.value=0;input.connect(node);node.connect(sink);sink.connect(context.destination);
  active=true;starting=false;prep=0;sequence=0;expectedWorklet=-1;lastFrame=began=performance.now();
  node.port.onmessage=({data})=>{
   if(!active||version!==generation)return;lastFrame=performance.now();
   if(data.sampleRate!==16000||data.pcm.byteLength!==1024||expectedWorklet!==-1&&data.sequence!==expectedWorklet+1){finish('The microphone recording had a gap. Save this attempt.');return;}expectedWorklet=data.sequence;
   if(prep++<94){if(prep===94){origin=data.endFrame;ask(0);}return;}
   if(queue.length>=6){finish('Audio processing could not keep up. Save this attempt.');return;}
   queue.push({...data,sequence:sequence++});pump();
  };
  phase('wait','Get ready…','Stay quiet for about three seconds. Then the first phrase appears.');status('Microphone on · getting ready');
  watchdog=setInterval(()=>{if(active&&(performance.now()-lastFrame>2000||performance.now()-began>180000||ctx.state!=='running'))finish('The microphone stopped or the time limit was reached. Save this attempt.');},250);
 }catch(error){if(version===generation)await finish(error.message);}
 finally{starting=false;}
};
function renderReview(){
 const parent=$('ratings');parent.replaceChildren();
 for(const [key,title] of Object.entries(questions)){const card=document.createElement('div');card.className='review-item';const p=document.createElement('p');p.textContent=title;card.append(p);const row=document.createElement('div');row.className='row choice';
  for(const [value,label] of [['yes','Yes'],['no','No'],['unsure','Not sure']]){const button=document.createElement('button');button.textContent=label;button.setAttribute('aria-pressed','false');button.onclick=()=>{ratings[key]=value;for(const b of row.children)b.setAttribute('aria-pressed',String(b===button));};row.append(button);}card.append(row);parent.append(card);
 }
 $('save-help').textContent=saveAudio?'Save keeps microphone audio, replies, your ratings and timings privately on this Mac. No audio is uploaded again.':'Save keeps replies, your ratings and timings privately on this Mac. No microphone audio will be saved.';
}
async function finish(message=''){
 if(stopPromise)return stopPromise;const stoppedId=id;generation++;active=false;starting=false;queue=[];clearTimers();
 // Hardware and scheduled sound stop before any localhost/cloud await.
 if(playback){if(playing)note('playback_state_at_stop',playback.snapshot(playing));playback.stopAll();playback=null;}playing=null;
 if(node){node.port.onmessage=null;node.disconnect();node=null;}if(input){input.disconnect();input=null;}if(sink){sink.disconnect();sink=null;}
 if(mic){for(const t of mic.getTracks()){t.onended=null;t.stop();}mic=null;}
 if(ctx){ctx.close().catch(()=>{});ctx=null;}
 show('review');renderReview();status('Microphone off · reviewing this attempt');$('error').textContent=message;note('test_stopped',{reason:message||'guided_complete'});$('save').disabled=true;
 stopPromise=(async()=>{try{if(stoppedId)await api('/stop');$('save').disabled=!stoppedId;}catch(error){$('error').textContent=[message,error.message].filter(Boolean).join(' ');$('recovery').hidden=false;}})();return stopPromise;
}
$('stop').onclick=()=>finish('You stopped this attempt. Review what happened and save any partial results.');
async function saveAttempt(){
 if(savedResult)return true;
 $('save').disabled=true;$('retry').disabled=true;
 try{const result=await api('/save',{ratings,note:$('note').value,playback_trace:trace});savedResult=result;$('saved').textContent=`Saved on this Mac. You’re finished—tell the chat “done.” Spending including reservations: $${result.spent_reserved_usd.toFixed(3)} of $25.`;for(const child of $('ratings').children)for(const button of child.children[1].children)button.disabled=true;$('note').disabled=true;$('retry').disabled=false;return true;}
 catch(error){$('error').textContent=error.message+' Your notes remain on this page. Try Save again, download the notes, or choose the clearly labelled restart without saving.';$('save').disabled=false;$('retry').disabled=false;$('recovery').hidden=false;$('restart-unsaved').hidden=false;return false;}
}
$('save').onclick=saveAttempt;
$('retry').onclick=async()=>{note('repeat_requested_before_or_after_review');if(await saveAttempt())location.reload();};
$('restart-unsaved').onclick=()=>location.reload();
$('recovery').onclick=()=>{const blob=new Blob([JSON.stringify({kind:'paprika_native_browser_recovery',session_id:id,ratings,note:$('note').value,playback_trace:trace},null,2)],{type:'application/json'});const url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download='paprika-native-notes.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);};
window.addEventListener('pagehide',()=>{generation++;active=false;clearTimers();playback?.stopAll();mic?.getTracks().forEach(t=>t.stop());ctx?.close().catch(()=>{});if(id)fetch('/stop',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({session_id:id}),keepalive:true}).catch(()=>{});});

if(closureCheck){
 $('page-title').textContent='Check the last step.';
 $('setup-title').textContent='One short reply, then goodbye';
 $('setup-purpose').textContent='Your earlier trial already covered follow-ups and interruption. This short check only verifies that the reply finishes, the page moves on, Paprika says goodbye, and the microphone turns off. We are also checking the repeated introduction fix. K remains your selected voice.';
 $('limits-copy').textContent='Only this test’s new adult speech goes to OpenAI; no older recording is uploaded. Two short requests, up to $2 reserved within your existing $25 cap. Saving keeps replies, ratings and timings privately on this Mac; the optional listening copy also keeps microphone audio locally. No recording is uploaded again automatically. Unsaved audio disappears if this server restarts.';
 $('practice-help').textContent='Say the big phrase only after the green cue. Stay quiet while Paprika replies. The page then shows the goodbye phrase automatically.';
 $('practice-phrase').textContent=phrases[0];
}

'use strict';
(()=>{
 const $=id=>document.getElementById(id),person=document.body.dataset.person,key='paprika-family-voice-v1:'+person;
 let config=null,state=null,session=null,pending=null,phase='setup',busy=false,consented=false,storageOK=true,afterStorage='setup',serial=0;
 let mic=null,ctx=null,node=null,input=null,sink=null,timer=null,recording=false,frames=[],lastSeq=null,pcm=null,currentPrompt=null,settings={},reviewChoices={},audioURL=null;
 const copies=new Map(),emptySha='e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855';
 try{const saved=JSON.parse(localStorage.getItem(key)||'null');if(saved){session=saved.session;pending=saved.pending||null;}}catch{}
 const text=(id,value)=>{$(id).textContent=value;};
 function persist(next=phase){
  try{localStorage.setItem(key,JSON.stringify({session,pending}));storageOK=true;return true;}
  catch{storageOK=false;afterStorage=next;phase='storage';render();return false;}
 }
 async function api(path,{method='GET',body,raw=false,meta}={}){
  const headers={'X-Person-ID':person};if(session)headers['X-Collection-Session']=session;
  if(body!==undefined)headers['Content-Type']=raw?'application/octet-stream':'application/json';
  if(meta){headers['X-Attempt-ID']=meta.id;headers['X-Prompt-ID']=meta.prompt_id;headers['X-Capture-Settings']=JSON.stringify(settings);}
  const response=await fetch(path,{method,headers,body:body===undefined?undefined:raw?body:JSON.stringify(body),signal:AbortSignal.timeout(path==='/api/begin'?90000:35000)});
  const data=await response.json();if(!response.ok){const e=Error(data.error||'Local action could not finish. Earlier samples are kept.');e.status=response.status;throw e;}
  if(data.person_id&&data.person_id!==person)throw Error('This result belongs to a different person. Recording stays off.');
  return data;
 }
 function stopAudio(){const a=$('audio');a.pause();a.removeAttribute('src');if(audioURL)URL.revokeObjectURL(audioURL);audioURL=null;}
 async function shutMic(){
  recording=false;clearTimeout(timer);timer=null;
  if(node){node.port.onmessage=null;node.disconnect();node=null;}if(input){input.disconnect();input=null;}if(sink){sink.disconnect();sink=null;}
  if(mic){mic.getTracks().forEach(t=>{t.onended=null;t.stop();});mic=null;}const old=ctx;ctx=null;if(old)await old.close().catch(()=>{});
 }
 function show(next){phase=next;render();}
 function derive(){
  if(!state)return show('setup');
  if(state.complete)return show('done');if(state.profile_saved)return show('summary');
  if(pending){
   const saved=state.attempts.find(a=>a.id===pending.id);
   if(saved&&(!pending.sha||pending.sha===saved.pcm_sha256)){currentPrompt=config.prompts.find(p=>p.id===saved.prompt_id);if(pcm)copies.set(saved.id,waveBlob(pcm));pending=null;pcm=null;persist('celebrate');if(storageOK)return show('celebrate');return;}
   currentPrompt=config.prompts.find(p=>p.id===pending.prompt_id);return show('recover');
  }
  if(state.reviewed)return show('summary');
  if(state.total>=state.segment_end)return show(config.child?'child_done':'review');
  currentPrompt=state.next_prompt;show('turn');
 }
 function makeReview(){
  const list=$('review-list');list.replaceChildren();reviewChoices={};
  for(const a of state.attempts){
   const row=document.createElement('div');row.className='review-row';const title=document.createElement('strong');title.textContent=`Turn ${a.number} · ${config.prompts.find(p=>p.id===a.prompt_id)?.question||'Voice sample'}`;row.append(title);
   const help=document.createElement('p');help.textContent=a.outcome==='clear'?(a.review==='exclude'?'Left out of the profile':'Clear voice found · review whose voice it is'):({short:'Too little clear speech',quiet:'Very quiet',clipped:'Distorted sound',duplicate:'Repeated audio · not counted',interrupted:'Unfinished turn · not counted'}[a.outcome]||'Not used');row.append(help);
   if(a.outcome==='clear'&&a.review!=='exclude'){
    const select=document.createElement('select');select.setAttribute('aria-label',`Review voice sample ${a.number}`);
    for(const [value,label] of [['keep',`Keep · only ${config.name}'s normal voice`],['other_voice','Someone else spoke · discard this sample'],['silly_voice','A silly voice · discard this sample'],['skip','Not sure · discard this sample']]){const o=document.createElement('option');o.value=value;o.textContent=label;select.append(o);}
    select.value='keep';reviewChoices[a.id]='keep';select.onchange=()=>{reviewChoices[a.id]=select.value;$('attested').checked=false;};row.append(select);
    if(state.retain_audio||copies.has(a.id)){const play=document.createElement('button');play.className='secondary';play.textContent='Listen to this sample';play.onclick=()=>playSample(a.id);row.append(play);}
   }
   list.append(row);
  }
  $('attested').checked=false;
 }
 let renderedPhase=null;
 function render(){
  document.body.dataset.phase=phase;$('card').dataset.phase=phase;
  text('mic-status',mic?(recording?'Microphone on · recording this answer':'Microphone on · countdown, not saving yet'):'Microphone off');
  const turn=['turn','countdown','recording','checking','celebrate','recover'].includes(phase);
  for(const [id,value] of [['setup',phase==='setup'],['turn-panel',turn],['child-done',phase==='child_done'],['review',phase==='review'],['summary',phase==='summary'],['paused',phase==='paused'],['done',phase==='done'],['storage',phase==='storage']])$(id).hidden=!value;
  $('pause').hidden=!consented||['setup','done','paused','storage'].includes(phase);$('pause').disabled=busy&&!turn;
  text('step',phase==='setup'?'GET READY':phase==='review'?(config?.child?'GROWN-UP REVIEW':'REVIEW YOUR SAMPLES'):phase==='done'?'COLLECTION COMPLETE':turn?`STOP ${phase==='celebrate'?state.total:(currentPrompt?config.prompts.findIndex(p=>p.id===currentPrompt.id)+1:state?.total+1)} OF ${state?.segment_end||6}`:'MICROPHONE OFF');
  const titles={setup:`Voice setup for ${config?.name||person}`,practice:'One little practice',turn:config?.child?'What do you think?':'Answer in your normal voice',countdown:'Get ready…',recording:'Your turn · speak now',checking:'Keeping your place…',celebrate:config?.child?'Thanks, explorer!':'Thank you',recover:'Earlier useful samples are safe',child_done:'Thanks for exploring with me!',review:'Keep the useful examples',summary:state?.kept>=6?'Save the candidate profile':'Useful examples are kept',paused:'We can come back later',done:`${config?.name||person}’s candidate profile is saved`,storage:'Keep this tab open'};
  // Practice uses the turn panel with an explicit button; no microphone yet.
  if(phase==='practice')$('turn-panel').hidden=false;
  text('title',titles[phase]||'Voice setup');
  text('help',phase==='setup'?(config?.child?`A grown-up stays with ${config.name}. Answer little adventure questions in a normal voice; no sentence needs to be read perfectly.`:'Six short answers, one voice at a time. Speak naturally for a sentence or two. These pretend setup answers are not personal memories.'):phase==='practice'?'Listen to the question or ask a grown-up to read it. The microphone is still off. You choose when to start each recording.':turn?'The question stays here. Speak only when the green cue says Speak now. The microphone stops automatically after eight seconds, or when you choose Done speaking.':'No new recording is happening.');
  const p=currentPrompt||{id:'practice',question:'What would you put in a space backpack?',help:'Tell Paprika what you could use it for.'};
  text('question',p.question);text('question-help',p.help||'');
  text('cue',phase==='recording'?'SPEAK NOW · your voice is being recorded':phase==='countdown'?'Get ready · wait for the green cue':phase==='checking'?'Microphone off · checking locally':phase==='celebrate'?'Microphone off · another part of the adventure':phase==='recover'?'Microphone off · no need to repeat this question':'Microphone off · ready when you are');
  $('record').hidden=!['turn','practice'].includes(phase);text('record',phase==='practice'?(config?.child?'I’m ready · start the adventure':'I’m ready · start the first question'):'Record my answer');$('record').disabled=busy||!storageOK;
  $('stop-recording').hidden=!['countdown','recording'].includes(phase);text('stop-recording',phase==='countdown'?'Cancel · microphone off':'Done speaking');
  $('next').hidden=phase!=='celebrate';text('next',state?.total>=state?.segment_end?(config?.child?'Finish our adventure':'Review the samples'):'Next question');
  $('retry').hidden=phase!=='recover'||!pcm;$('skip').hidden=phase!=='recover'||!pending;$('latest').hidden=phase!=='recover';$('back-setup').hidden=phase!=='recover';
  $('progress').hidden=!['countdown','recording'].includes(phase);$('hear').hidden=!['turn','practice'].includes(phase);$('hear').disabled=busy;
  if(phase==='review'&&renderedPhase!=='review'){makeReview();text('review-help',state.retain_audio?'Listening is optional. Leave out any example with another person, a silly voice or uncertainty. Excluded temporary recordings are discarded.':'Raw audio was not saved as files. Listening copies exist only for turns still on this page; after a reload, use your supervision to review and leave out anything uncertain.');}
  if(phase==='summary'){
   text('coverage',`${state.kept} useful reviewed samples kept · at least 6 needed.`);
   text('summary-help',state.kept>=6?'This saves a local candidate for later voice testing. It will not enable recognition or personal-memory access.':state.total>=24?'This collection has reached its limit. Keep the samples and stop for local quality review; do not keep repeating sentences.':'Finish for now, or use fresh questions to collect more. Earlier useful samples stay kept; no earlier sentence needs repeating.');
   $('finish').hidden=state.kept<6&&!state.profile_saved;$('finish-later').hidden=state.kept>=6||state.profile_saved;
   const room=Math.min(24,state.sitting_start+12)-state.total;$('more').hidden=state.kept>=6||room<=0;
   text('more',`Try ${Math.min(room,Math.max(2,6-state.kept))} fresh questions`);
  }
  if(phase==='paused')text('paused-copy',`${state.kept} useful samples kept. ${state.kept>=6?'A candidate can be saved after review.':'Collection is incomplete; no recognition has been enabled.'}`);
  if(state){$('journey').replaceChildren();for(let n=state.sitting_start+1;n<=state.segment_end;n++){const li=document.createElement('li');li.textContent=n<=state.total?'✓':String(n-state.sitting_start);li.className=n<=state.total?'done':'';$('journey').append(li);}}
  renderedPhase=phase;
 }
 function fail(error,next='recover'){text('error',error.message||String(error));show(next);}
 async function check(){
  try{config=await api('/api/setup?person='+person);text('ready',config.message);$('begin').disabled=!config.available;
   text('world-title',config.child?'A LITTLE SPACE ADVENTURE':'LOCAL VOICE SETUP');
   text('adult-copy',config.child?`I am an adult supervising ${config.name}, and everyone nearby agrees to this local recording.`:'I am Adult Two, recording my own voice, and everyone nearby agrees.');
   text('willing-copy',config.child?`I have asked ${config.name}: they want to join in and know they can stop at any time.`:'I want to take part and know I can stop at any time.');
   text('attestation-copy',config.child?`I supervised the recordings. The samples I keep contain only ${config.name}’s normal voice.`:'The samples I keep contain only my normal voice.');
   text('begin',session?'Resume this collection':config.child?`Start the adventure for ${config.name}`:'Start my local voice setup');
  }catch(error){$('begin').disabled=true;text('ready','Local setup is unavailable. Keep this page open and choose Check again.');}
 }
 function setupChoices(refresh=true){
  consented=false;stopAudio();$('adult').checked=false;$('willing').checked=false;$('alone').checked=false;$('new-sitting').checked=false;
  document.querySelectorAll('input[type=radio]').forEach(e=>e.checked=false);
  if(state){$('resume-note').hidden=false;text('resume-note',`${state.eligible} useful examples already collected for ${state.name}. Original choice: ${state.retain_audio?'keep useful reference recordings and profile':'voice vectors and measurements only'}. Choose that same option to resume.`);$('new-sitting-wrap').hidden=state.total<state.sitting_start+12||state.total>=24;}
  show('setup');if(refresh)check();
 }
 async function beginCollection(){
  if(busy||!config?.available)return;
  const processing=document.querySelector('input[name=processing]:checked')?.value,retention=document.querySelector('input[name=retention]:checked')?.value;
  if(!$('adult').checked||!$('willing').checked||!$('alone').checked||processing!=='local-only'||!retention){text('error','Complete the adult or own-voice confirmation, willingness, one-voice and local recording choices above. Nothing is recording.');return;}
  busy=true;text('error','');text('ready','Preparing this local collection… Microphone off.');
  try{const d=await api('/api/begin',{method:'POST',body:{person_id:person,consent:config.consent,adult_confirmed:true,subject_willing:true,alone:true,supervised:config.child,own_voice:!config.child,processing,retain_audio:retention==='keep',new_sitting:$('new-sitting').checked}});
   session=d.session;state=d;consented=true;if(!persist('practice'))return;
   if(state.total||state.complete||pending)derive();else{currentPrompt=null;show('practice');}
  }catch(error){fail(error,'setup');}finally{busy=false;render();}
 }
 function waveBlob(bytes){
  const out=new Uint8Array(44+bytes.byteLength),v=new DataView(out.buffer);for(const [o,s] of [[0,'RIFF'],[8,'WAVE'],[12,'fmt '],[36,'data']])for(let i=0;i<s.length;i++)v.setUint8(o+i,s.charCodeAt(i));
  v.setUint32(4,36+bytes.byteLength,true);v.setUint32(16,16,true);v.setUint16(20,1,true);v.setUint16(22,1,true);v.setUint32(24,16000,true);v.setUint32(28,32000,true);v.setUint16(32,2,true);v.setUint16(34,16,true);v.setUint32(40,bytes.byteLength,true);out.set(bytes,44);return new Blob([out],{type:'audio/wav'});
 }
 async function hash(bytes){return Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',bytes))).map(x=>x.toString(16).padStart(2,'0')).join('');}
 async function checkRecording(){
  if(!pending||!pcm||busy)return;const version=serial;
  if(!pending.sha){pending.sha=await hash(pcm);if(version!==serial||!persist('recover'))return;}
  busy=true;show('checking');text('error','');
  try{const result=await api('/api/attempt',{method:'POST',raw:true,body:pcm,meta:pending});if(version!==serial)return;
   const a=result.attempts.find(a=>a.id===pending.id);if(!a||a.pcm_sha256!==pending.sha)throw Error('The local check did not match this recording. Keep this page open and show the latest saved progress.');
   copies.set(pending.id,waveBlob(pcm));state=result;pending=null;pcm=null;if(persist('celebrate'))show('celebrate');
  }catch(error){if(version!==serial)return;
   try{const saved=await api('/api/state');const a=saved.attempts.find(a=>a.id===pending?.id);if(a&&a.pcm_sha256===pending.sha){state=saved;pending=null;pcm=null;if(persist('celebrate'))show('celebrate');return;}}catch{}
   fail(error);
  }finally{if(version===serial){busy=false;render();}}
 }
 async function finishRecording(){
  if(!['countdown','recording'].includes(phase))return;
  if(!recording){serial++;await shutMic();busy=false;show('turn');return;}
  const version=serial;show('checking');await shutMic();if(version!==serial)return;
  pcm=new Uint8Array(frames.length*1024);frames.forEach((frame,i)=>pcm.set(new Uint8Array(frame),i*1024));frames=[];
  const sha=await hash(pcm);if(version!==serial)return;pending.sha=sha;busy=false;if(persist('recover'))await checkRecording();
 }
 async function record(){
  if(phase==='practice'){stopAudio();currentPrompt=state.next_prompt;show('turn');return;}
  if(busy||phase!=='turn'||!consented||!storageOK)return;
  stopAudio();serial++;const version=serial;pcm=null;frames=[];lastSeq=null;pending=pending||{id:crypto.randomUUID().replaceAll('-',''),prompt_id:currentPrompt.id,sha:null};
  if(!persist('turn'))return;busy=true;show('countdown');text('error','');text('cue','Microphone setup · allow access if asked');$('progress').value=0;
  try{
   const context=new AudioContext({sampleRate:16000});ctx=context;await context.resume();if(version!==serial)return;
   if(context.sampleRate!==16000)throw Error('This browser did not provide16kHzsound. Try this link in Chrome or Safari on this Mac.');
   await context.audioWorklet.addModule('/capture.js');if(version!==serial)return;
   const stream=await navigator.mediaDevices.getUserMedia({audio:{channelCount:1,echoCancellation:true,noiseSuppression:true,autoGainControl:false}});
   if(version!==serial){stream.getTracks().forEach(t=>t.stop());return;}mic=stream;
   settings={audio_context_rate:context.sampleRate,requested_echo_cancellation:true,requested_noise_suppression:true,requested_auto_gain_control:false};
   const actual=stream.getAudioTracks?.()[0]?.getSettings?.()||{};
   for(const k of ['sampleRate','channelCount','echoCancellation','noiseSuppression','autoGainControl'])if(typeof actual[k]==='number'||typeof actual[k]==='boolean'||k==='echoCancellation'&&['all','remote-only'].includes(actual[k]))settings['actual_'+k]=actual[k];
   node=new AudioWorkletNode(context,'tavi-capture');input=context.createMediaStreamSource(stream);sink=context.createGain();sink.gain.value=0;
   input.connect(node);node.connect(sink);sink.connect(context.destination);
   node.port.onmessage=({data})=>{
    if(version!==serial||!recording)return;
    if(data.sampleRate!==16000||!(data.pcm instanceof ArrayBuffer)||data.pcm.byteLength!==1024||(lastSeq!==null&&data.sequence!==lastSeq+1)){
     serial++;shutMic();busy=false;fail(Error('The microphone stream was interrupted. Earlier samples are kept. Use a fresh question instead of repeating this one.'));return;
    }
    lastSeq=data.sequence;frames.push(data.pcm);$('progress').value=frames.length;if(frames.length>=250)finishRecording();
   };
   stream.getTracks().forEach(t=>t.onended=()=>{if(version===serial){serial++;shutMic();busy=false;fail(Error('The microphone disconnected. Reconnect it, then use a fresh question. Earlier useful samples are kept.'));}});
   render();for(let n=2;n>0;n--){text('cue',`Get ready · ${n}`);await new Promise(resolve=>timer=setTimeout(resolve,1000));if(version!==serial)return;}
   recording=true;show('recording');timer=setTimeout(()=>{if(version===serial){serial++;shutMic();busy=false;fail(Error('The microphone stopped sending sound. Earlier samples are kept. Use a fresh question after checking the microphone.'));}},10000);
  }catch(error){if(version!==serial)return;await shutMic();busy=false;fail(Error(error.name==='NotAllowedError'?'Microphone access was not allowed. Allow this page’s microphone access, then choose Record. No voice has been saved.':error.message),'turn');}
 }
 async function pause(){
  serial++;stopAudio();await shutMic();busy=false;
  try{state=await api('/api/pause',{method:'POST',body:{}});consented=false;show('paused');}
  catch(error){fail(error);}
 }
 async function playBlob(blob){stopAudio();audioURL=URL.createObjectURL(blob);$('audio').src=audioURL;await $('audio').play();}
 async function playSample(id){try{if(copies.has(id))return await playBlob(copies.get(id));const r=await fetch('/api/audio/'+id,{headers:{'X-Person-ID':person,'X-Collection-Session':session},signal:AbortSignal.timeout(10000)});if(!r.ok)throw Error('No listening copy is available. Use your supervision to review; leave out anything uncertain.');await playBlob(await r.blob());}catch(error){text('error',error.message);}}
 $('hear').onclick=async()=>{
  if(!['turn','practice'].includes(phase)||busy)return;
  try{stopAudio();$('audio').src='/prompts/'+(currentPrompt?.id||'practice')+'.wav';await $('audio').play();text('audio-help','Listen to the whole question. The microphone is off. Choose Record when ready.');}
  catch{text('audio-help','Question audio is unavailable. A grown-up can read the question before recording; no repeat is needed.');}
 };
 $('audio').onerror=()=>text('audio-help','Question audio could not play. A grown-up can read it before recording.');
 $('begin').onclick=beginCollection;$('check').onclick=check;$('record').onclick=record;$('stop-recording').onclick=finishRecording;$('retry').onclick=checkRecording;$('pause').onclick=pause;$('finish-later').onclick=pause;
 $('next').onclick=()=>{stopAudio();text('error','');currentPrompt=null;derive();};
 $('open-review').onclick=()=>{stopAudio();show('review');};$('back-review').onclick=()=>{stopAudio();show('review');};
 $('approve').onclick=async()=>{
  if(busy)return;if(!$('attested').checked){text('error','The supervising adult or speaker needs to confirm whose normal voice is being kept.');return;}
  busy=true;stopAudio();text('error','');
  try{state=await api('/api/review',{method:'POST',body:{choices:reviewChoices,attested:true}});for(const a of state.attempts)if(a.review==='exclude')copies.delete(a.id);show('summary');}
  catch(error){text('error',error.message);}finally{busy=false;}
 };
 $('more').onclick=async()=>{if(busy)return;busy=true;try{state=await api('/api/more',{method:'POST',body:{}});currentPrompt=state.next_prompt;show('turn');}catch(error){text('error',error.message);}finally{busy=false;render();}};
 $('finish').onclick=async()=>{if(busy)return;busy=true;stopAudio();text('error','');try{state=await api('/api/finish',{method:'POST',body:{}});copies.clear();frames=[];pcm=null;pending=null;persist('done');if(storageOK)show('done');}catch(error){text('error',error.message);}finally{busy=false;}};
 $('skip').onclick=async()=>{if(busy||!pending)return;busy=true;try{state=await api('/api/skip',{method:'POST',body:{...pending,sha:pending.sha||emptySha}});pending=null;pcm=null;if(persist('celebrate'))show('celebrate');}catch(error){text('error',error.message);}finally{busy=false;render();}};
 $('latest').onclick=async()=>{try{state=await api('/api/state');pending=null;pcm=null;if(persist('turn'))derive();}catch(error){text('error',error.message);}};
 $('resume').onclick=setupChoices;
 $('back-setup').onclick=setupChoices;
 $('retry-storage').onclick=()=>{if(persist(afterStorage))show(afterStorage);};
 $('separate').onclick=()=>{serial++;stopAudio();shutMic();session=null;pending=null;state=null;pcm=null;consented=false;if(persist('setup')){$('resume-note').hidden=true;setupChoices();text('error','Earlier collections are kept. Choose settings for a separate collection.');}};
 window.addEventListener('pagehide',()=>{serial++;stopAudio();shutMic();copies.clear();frames=[];pcm=null;});
 window.addEventListener('pageshow',async event=>{
  if(!event.persisted)return;serial++;stopAudio();await shutMic();busy=false;consented=false;
  try{if(session)state=await api('/api/state');if(state?.complete){show('done');return;}setupChoices();}
  catch(error){fail(error,'setup');}
 });
 (async()=>{await check();if(session){try{state=await api('/api/state');if(state.complete){show('done');return;}$('separate').hidden=false;}catch(error){text('error',error.message);$('separate').hidden=false;}}setupChoices(false);})();
})();

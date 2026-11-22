'use strict';
(()=>{
 const $=id=>document.getElementById(id),api=window.paprika;
 let overview=null,person=null,state=null,token=null,pending=null,pcm=null,phase='people',busy=false,consented=false,storageOK=true,serial=0;
 let context=null,mic=null,node=null,input=null,sink=null,recording=false,frames=[],lastSeq=null,timer=null,audioURL=null,choices={},countdownResume=null,captureSettings={};
 const key=()=>`paprika-voice-check-v1:${person.person_id}:${document.querySelector('input[name=phase]:checked')?.value||'development'}`;
 const text=(id,value)=>{$(id).textContent=value;};
 function savePlace(){try{localStorage.setItem(key(),JSON.stringify({token,pending}));storageOK=true;return true;}catch{storageOK=false;show('storage');return false;}}
 function stopAudio(){const a=$('audio');a.pause();a.removeAttribute('src');if(audioURL)URL.revokeObjectURL(audioURL);audioURL=null;}
 async function shutMic(){recording=false;clearTimeout(timer);if(countdownResume){countdownResume();countdownResume=null;}if(node){node.port.onmessage=null;node.disconnect();node=null;}if(input){input.disconnect();input=null;}if(sink){sink.disconnect();sink=null;}if(mic){mic.getTracks().forEach(t=>{t.onended=null;t.stop();});mic=null;}const c=context;context=null;if(c)await c.close().catch(()=>{});await api.micIntent(false).catch(()=>{});render();}
 function show(next){phase=next;document.body.dataset.step=phase;for(const id of ['people','settings','review','done','storage'])$(id).hidden=id!==phase;$('question-panel').hidden=!['question','preparing','countdown','recording','checking','celebrate','recover'].includes(phase);render();}
 function render(){
  text('mic-status',mic?(recording?'Microphone on · recording':'Microphone on · wait'):'Microphone off');
  if(!state)return;
  text('step',`QUESTION ${phase==='celebrate'?state.total:state.total+1} · ${state.eligible} useful examples this visit`);
  const p=state.next_prompt;if(phase!=='celebrate'&&phase!=='recover'&&p){text('question',p.question);text('question-help',p.help||'');}
  const cue={question:'Microphone off · ready when you are',preparing:'Getting the microphone ready · allow access if asked',countdown:'Get ready · wait for the green cue',recording:'SPEAK NOW · your voice is being recorded',checking:'Microphone off · checking locally',celebrate:'Microphone off · thank you for sharing',recover:'Microphone off · earlier useful examples are safe'}[phase];if(cue)text('cue',cue);
  $('record-progress').max=person.person_id==='short'?31:156;text('recording-help',person.person_id==='short'?'Say just one word. This short check stops after about one second.':'Answer naturally with a sentence or two. No special words need reading or remembering. The recording stops after about five seconds.');
  text('turn-title',phase==='celebrate'?'Another little part of the adventure':phase==='recover'?'Let’s keep your place':person.child?'What do you think?':'Answer in your normal voice');
  $('record').hidden=phase!=='question';$('record').disabled=busy||!storageOK;$('hear').hidden=phase!=='question'||p?.audio===false;$('stop').hidden=!['countdown','recording'].includes(phase);text('stop',phase==='countdown'?'Cancel · microphone off':'Done speaking');
  $('next').hidden=phase!=='celebrate';text('next',state.total>=state.batch_end?'Grown-up: review these examples':'Next question');
  $('retry-check').hidden=phase!=='recover'||!pcm;$('skip').hidden=phase!=='recover'||!pending;$('latest').hidden=phase!=='recover';$('record-progress').hidden=!['countdown','recording'].includes(phase);
  $('pause').hidden=phase==='checking';$('more').hidden=state.total>=12;$('save').disabled=busy;$('more').disabled=busy;
 }
 async function refresh(){
  try{overview=await api.voices();text('overview',`${overview.current_profiles} of 4 family voices saved. Each person can do a short visit when available.`);const list=$('people-list');list.replaceChildren();
   for(const role of overview.people){const b=document.createElement('button');b.className='person-card';b.disabled=!role.enrolled;const icon=document.createElement('span');icon.className='avatar';icon.textContent=role.person_id==='guest'?'?':role.name[0];const copy=document.createElement('span'),name=document.createElement('strong'),help=document.createElement('small');name.textContent=role.name;help.textContent=!role.enrolled?(role.control?'Opens after the matching rule is frozen':'Enrollment needed first'):role.control?`${role.progress.heldout} independent control examples kept`:role.person_id==='guest'?`${role.progress.development} of 20 fresh examples · adult outside the four family members`:`${role.progress.development} of 12 fresh examples · ${role.examples} enrollment examples kept`;copy.append(name,help);const arrow=document.createElement('span');arrow.className='arrow';arrow.textContent='↗';b.append(icon,copy,arrow);b.onclick=()=>settings(role);list.append(b);}
  }catch(e){text('error','Connect the external drive, then choose Check again. '+e.message);}
 }
 function settings(role){
  person=role;consented=false;token=null;pending=null;pcm=null;state=null;stopAudio();for(const id of ['adult','willing','alone','local','guest','occasion'])$(id).checked=false;document.querySelectorAll('input[type=radio]').forEach(r=>r.checked=false);
  text('settings-name',role.name+'’s fresh voice check');text('settings-help',role.child?'A grown-up stays nearby. Listen to little adventure questions, then answer with your normal voice. We are checking how your voice sounds, not whether an answer is right.':'A few natural spoken answers. These are voice measurements only; none of the pretend answers become personal memories.');
  text('adult-copy',role.child?`I am an adult supervising ${role.name}, and everyone nearby agrees to this local recording.`:role.person_id==='guest'?'I am the guest adult recording my own voice, and everyone nearby agrees.':`I am ${role.name}, recording my own voice, and everyone nearby agrees.`);
  text('willing-copy',role.child?`${role.name} wants to join and knows they can stop any time.`:'I want to take part and know I can stop any time.');$('guest-wrap').hidden=role.person_id!=='guest';$('heldout-radio').disabled=overview.heldout_locked;$('occasion-wrap').hidden=true;text('phase-help',overview.heldout_help);text('resume-note','Choose a round and recording option. If this visit was paused, we’ll show its saved progress.');text('error','');$('development-radio').disabled=!!role.control;text('alone-copy',role.person_id==='overlap'?'Both willing people will answer at the same time. An adult supervises any child.':'Only this person will speak in each recording. Others can help with the question while the microphone is off.');if(role.control){text('adult-copy',role.person_id==='overlap'?'I am the adult supervising this two-voice check, and both people agree to this local recording.':'I am an adult recording my own short answers, and everyone nearby agrees.');text('willing-copy',role.person_id==='overlap'?'Both people want to join and know they can stop any time.':'I want to take part and can stop any time.');}show('settings');
 }
 document.querySelectorAll('input[name=phase]').forEach(r=>r.onchange=()=>{$('occasion-wrap').hidden=r.value!=='heldout'||!r.checked;});
 async function begin(){
  if(busy)return;const round=document.querySelector('input[name=phase]:checked')?.value,retain=document.querySelector('input[name=retention]:checked')?.value;
  if(!round||!retain||!['adult','willing','alone','local'].every(id=>$(id).checked)||person.person_id==='guest'&&!$('guest').checked||round==='heldout'&&!$('occasion').checked){text('error','Complete the recording choices and confirmations above. The microphone is off.');return;}
  busy=true;try{
   let saved;try{saved=JSON.parse(localStorage.getItem(key())||'null');}catch{}token=saved?.token||null;pending=saved?.pending||null;
   state=await api.voiceAction('begin',{person_id:person.person_id,phase:round,consent:'fresh-local-voice-calibration-v1',adult:true,subject_willing:true,alone:person.person_id!=='overlap',two_speakers_agree:person.person_id==='overlap'&&$('alone').checked,local_only:true,retain_audio:retain==='audio',supervised:person.child,own_voice:!person.child,outside_family:$('guest').checked,different_occasion:$('occasion').checked},person.person_id,token);
   token=state.session;consented=true;if(!savePlace())return;derive();
  }catch(e){text('error',e.message);}finally{busy=false;render();}
 }
 function derive(){
  if(state.complete){done();return;}
  if(pending){const saved=state.attempts.find(a=>a.id===pending.id);if(saved){pending=null;pcm=null;if(!savePlace())return;}else{show('recover');return;}}
  if(state.total>=state.batch_end){review();return;}text('error','');show('question');
 }
 async function record(){
  if(busy||phase!=='question'||!consented||!storageOK)return;stopAudio();busy=true;const version=++serial;frames=[];lastSeq=null;pcm=null;text('error','');show('preparing');
  try{
   await api.micIntent(true);const c=new AudioContext({sampleRate:16000});context=c;await c.resume();if(version!==serial)return;if(c.sampleRate!==16000)throw Error('The microphone format changed. Try again.');
   await c.audioWorklet.addModule('/capture.js');if(version!==serial)return;
   const stream=await navigator.mediaDevices.getUserMedia({audio:{channelCount:1,echoCancellation:true,noiseSuppression:true,autoGainControl:false},video:false});if(version!==serial){stream.getTracks().forEach(t=>t.stop());return;}mic=stream;captureSettings={};const actual=stream.getTracks()[0]?.getSettings?.()||{};for(const k of ['sampleRate','channelCount','echoCancellation','noiseSuppression','autoGainControl'])if(['boolean','number'].includes(typeof actual[k]))captureSettings[k]=actual[k];
   node=new AudioWorkletNode(c,'tavi-capture');input=c.createMediaStreamSource(stream);sink=c.createGain();sink.gain.value=0;input.connect(node);node.connect(sink);sink.connect(c.destination);
   node.port.onmessage=({data})=>{if(version!==serial||!recording)return;if(data.sampleRate!==16000||!(data.pcm instanceof ArrayBuffer)||data.pcm.byteLength!==1024||lastSeq!==null&&data.sequence!==lastSeq+1){serial++;shutMic();busy=false;show('recover');text('error','The microphone stream stopped. Earlier useful examples are kept.');return;}lastSeq=data.sequence;frames.push(data.pcm);$('record-progress').value=frames.length;if(frames.length>=(person.person_id==='short'?31:156))finishRecording();};
   stream.getTracks().forEach(t=>t.onended=()=>{if(version===serial){serial++;shutMic();busy=false;show('recover');text('error','The microphone disconnected. Reconnect it, then show saved progress.');}});
   show('countdown');$('record-progress').value=0;for(let n=2;n>0;n--){text('cue','Get ready · '+n);await new Promise(r=>{countdownResume=r;timer=setTimeout(()=>{countdownResume=null;r();},1000);});if(version!==serial)return;}
   pending={id:crypto.randomUUID().replaceAll('-',''),prompt:state.next_prompt.id,settings:captureSettings};if(!savePlace()){await shutMic();busy=false;return;}
   recording=true;show('recording');timer=setTimeout(()=>{if(version===serial){serial++;shutMic();busy=false;show('recover');text('error','No more microphone sound arrived. Earlier examples are kept.');}},7000);
  }catch(e){if(version!==serial)return;await shutMic();busy=false;pending=null;savePlace();show('question');text('error',e.name==='NotAllowedError'?'Allow Paprika’s microphone in System Settings → Privacy & Security → Microphone, then choose Record.':e.message);}
 }
 async function finishRecording(){
  if(!recording){serial++;await shutMic();busy=false;show('question');return;}
  const version=serial;show('checking');await shutMic();if(version!==serial)return;
  pcm=new Uint8Array(frames.length*1024);frames.forEach((f,i)=>pcm.set(new Uint8Array(f),i*1024));frames=[];busy=false;if(pcm.length)await checkRecording();else{pending=null;savePlace();show('question');text('error','No sound was saved. The same question is still ready.');}
 }
 async function checkRecording(){
  if(busy||!pcm||!pending)return;busy=true;const version=serial;show('checking');text('error','');
  try{pending.sha=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',pcm))).map(x=>x.toString(16).padStart(2,'0')).join('');if(!savePlace())return;state=await api.voiceAttempt(pcm,{person:person.person_id,session:token,id:pending.id,prompt:pending.prompt,settings:pending.settings||{}});if(version!==serial)return;const a=state.attempts.find(a=>a.id===pending.id);if(!a||a.pcm_sha256!==pending.sha)throw Error('The local check did not acknowledge this exact answer.');pending=null;pcm=null;if(!savePlace())return;show('celebrate');text('question-help',['clear','short_control'].includes(a.outcome)?'A useful voice example is kept for grown-up review.':'Not enough clear voice this time. We’ll try a fresh question; nothing needs repeating.');}
  catch(e){if(version!==serial)return;try{const saved=await api.voiceAction('state',{},person.person_id,token);if(saved.attempts.some(a=>a.id===pending.id&&a.pcm_sha256===pending.sha)){state=saved;pending=null;pcm=null;savePlace();show('celebrate');return;}}catch{}show('recover');text('error',e.message);}
  finally{if(version===serial){busy=false;render();}}
 }
 function review(){
  stopAudio();choices={};const list=$('review-list');list.replaceChildren();
  for(const a of state.attempts){const row=document.createElement('div');row.className='review-row';const title=document.createElement('strong');title.textContent='Answer '+a.number;row.append(title);const help=document.createElement('p');help.textContent=['clear','short_control'].includes(a.outcome)&&a.review!=='exclude'?'Clear voice found · confirm whose voice it is':a.outcome==='reused'?'Already checked audio · not counted again':'Not enough usable voice · not counted';row.append(help);
   if(['clear','short_control'].includes(a.outcome)&&a.review!=='exclude'){const s=document.createElement('select');s.setAttribute('aria-label','Review answer '+a.number);for(const [value,label] of [['keep',person.person_id==='overlap'?'Keep · both agreed voices speaking together':`Keep · only ${person.name}’s normal voice`],['exclude','Another voice, a silly voice, or unsure · exclude and delete temporary audio']]){const o=document.createElement('option');o.value=value;o.textContent=label;s.append(o);}s.value='keep';choices[a.id]='keep';s.onchange=()=>{choices[a.id]=s.value;$('attested').checked=false;};row.append(s);if(state.retain_audio){const b=document.createElement('button');b.className='secondary';b.textContent='Listen to this answer';b.onclick=async()=>{try{await play(await api.voiceSample({person:person.person_id,session:token,id:a.id}));}catch(e){text('error',e.message);}};row.append(b);}}
   list.append(row);
  }
  $('attested').checked=false;text('attested-copy',person.person_id==='overlap'?'I supervised both willing people. Kept examples contain both natural voices speaking together.':person.child?`I supervised these answers. Kept examples contain only ${person.name}’s natural voice.`:`Kept examples contain only ${person.name}’s natural voice. I did not use earlier audio or a synthetic voice.`);show('review');
 }
 async function saveReview(finish){
  if(busy)return;if(!$('attested').checked){text('error','Confirm whose voice is kept before saving.');return;}busy=true;stopAudio();text('error','');
  try{state=await api.voiceAction('review',{choices,attested:true,finish},person.person_id,token);if(state.complete)done();else derive();}
  catch(e){text('error',e.message);}finally{busy=false;render();}
 }
 async function done(){
  await shutMic();consented=false;show('done');text('done-copy',`${state.kept} useful examples saved this visit. You can stop now; the rest can happen another time.`);pending=null;pcm=null;savePlace();
  try{await api.voiceAction('fit',{});await api.voiceAction('qualify',{});overview=await api.voices();}catch{} // No threshold/score is shown during labelling.
 }
 async function play(bytes){stopAudio();audioURL=URL.createObjectURL(new Blob([new Uint8Array(bytes)],{type:'audio/wav'}));$('audio').src=audioURL;await $('audio').play();}
 $('begin').onclick=begin;$('refresh').onclick=refresh;$('choose-another').onclick=()=>{show('people');refresh();};$('record').onclick=record;$('stop').onclick=finishRecording;$('retry-check').onclick=checkRecording;
 $('hear').onclick=async()=>{if(busy||phase!=='question')return;try{await play(await api.voiceQuestion(state.next_prompt.id));}catch{text('error','A grown-up can read the question while the microphone is off. Record when ready.');}};
 $('next').onclick=()=>{stopAudio();derive();};$('pause').onclick=async()=>{serial++;await shutMic();busy=false;if(state)review();};$('save').onclick=()=>saveReview(true);$('more').onclick=()=>saveReview(false);
 $('latest').onclick=async()=>{try{state=await api.voiceAction('state',{},person.person_id,token);derive();}catch(e){text('error',e.message);}};
 $('skip').onclick=async()=>{if(!pending||busy)return;busy=true;try{state=await api.voiceAction('skip',{id:pending.id,prompt:pending.prompt},person.person_id,token);pending=null;pcm=null;savePlace();derive();}catch(e){text('error',e.message);}finally{busy=false;render();}};
 $('retry-storage').onclick=()=>{if(savePlace())derive();};$('another-visit').onclick=()=>{show('people');refresh();};
 async function home(){serial++;stopAudio();await shutMic();consented=false;await api.openHome();}
 $('home').onclick=home;$('done-home').onclick=home;
 api?.onPause(async()=>{serial++;stopAudio();await shutMic();busy=false;consented=false;if(person){show('settings');text('error','Listening stopped. Confirm the choices again before resuming.');for(const id of ['adult','willing','alone','local','guest','occasion'])$(id).checked=false;}});
 window.addEventListener('pagehide',()=>{serial++;stopAudio();shutMic();frames=[];pcm=null;});
 window.addEventListener('pageshow',e=>{if(e.persisted){serial++;shutMic();consented=false;if(person)settings(person);}});
 if(!api){text('error','Open Family voices inside Paprika.app. No microphone has started.');return;}
 show('people');refresh();
})();

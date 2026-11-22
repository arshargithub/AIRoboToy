'use strict';
(()=>{
 const $=id=>document.getElementById(id),bridge=window.paprika;
 let polling=false;
 let ready=false,working=false,connected=false,page='setup',lastEngaged=false,chatFinished=false,memoryPaused=false,memoryRecovery=false;
 const endpoint=bridge?new MacAudioEndpoint(bridge,render,error):null;
 const guide=new MacCheckGuide({render:renderGuide,stop:()=>endpoint?.stop()});let guideState=null;
 function spending(s){
  if(!Number.isFinite(s.spent_or_reserved_usd)||!Number.isFinite(s.budget_usd))return 'Spending details are unavailable.';
  return `Spent or conservatively reserved: $${s.spent_or_reserved_usd.toFixed(4)} of $${s.budget_usd.toFixed(2)}.`;
 }
 function renderGuide(g){
  const copy=g.copy();$('check-guide').hidden=g.stage==='idle';$('check-step').textContent=copy[0];$('check-help').textContent=copy[1];$('check-phrase').textContent=copy[2];$('check-phrase').hidden=!copy[2];$('check-review').hidden=!['review','saved'].includes(g.stage);$('check-save').disabled=g.stage==='saved';$('check-return').textContent=g.stage==='saved'?'Return to setup':'Return to setup without saving';
 }
 function error(e){$('error').textContent=e.message||String(e);$('error-card').hidden=false;ready=false;if(guide.running)guide.finish(e.message);controls();}
 function pauseMemories(){
  if(memoryPaused)return;
  memoryPaused=true;memoryRecovery=true;$('family-memory').checked=false;$('family-memory').disabled=true;
  const checking=guide.running;
  if(checking)guide.finish('The memory part could not finish. Listening has stopped; you can save this partial check.');
  else endpoint.stop().catch(error);
  $('error').textContent=checking?'Memories need a check. Listening is off. Save or review the partial check above, then return to setup.':'Memories need a check. Listening is off. Continue to setup to chat without using or learning memories.';
  $('error-card').hidden=false;$('retry').hidden=true;$('memory-return').hidden=checking;
  $(checking?'check-guide':'error-card').scrollIntoView?.({block:'center'});
  if(!checking)$('memory-return').focus?.();
  controls();
 }
 function controls(){
  const active=endpoint?.active,starting=endpoint?.starting,busy=working||active||starting||guide.stage==='review';
  $('start').disabled=!ready||!!busy||!$('adult').checked||!document.querySelector('input[name=processing]:checked');
  $('check-start').disabled=$('start').disabled||!$('check-adult').checked||document.querySelector('input[name=processing]:checked')?.value!=='online';
  $('setup-screen').hidden=page!=='setup';$('companion-screen').hidden=page!=='companion';document.body.dataset.page=page;
  $('retry').disabled=!!working;$('mute').hidden=!active;$('mute').disabled=!active;
  $('resume').hidden=page!=='companion'||!!active||!!starting||guide.stage==='review'||memoryRecovery;
  $('resume').textContent=$('adult').checked&&document.querySelector('input[name=processing]:checked')?'Listen again':'Set up listening';
  $('interrupt').hidden=!active;$('end').hidden=!active;$('presence-light').dataset.on=active?'true':'false';
 }
 function render(view){
  const state=view.state,presentation=companionState(view,{pendingSpeech:!!endpoint?.pendingSpeech.size});
  if(state){
   if(lastEngaged&&state.engagement!=='active'&&view.active)chatFinished=true;
   if(state.engagement==='active')chatFinished=false;
   lastEngaged=state.engagement==='active';
  }
  $('face-card').dataset.state=presentation.kind;$('state').textContent=presentation.title;$('cue').textContent=presentation.cue;$('mic-state').textContent=presentation.mic;
  $('chat-finished').hidden=!view.active||!chatFinished||presentation.kind!=='standby';
  if(state){$('heard').textContent=state.heard||'Nothing yet.';$('reply').textContent=state.reply||'Nothing yet.';$('budget').textContent=spending(state);}
  $('interrupt').disabled=!view.playing&&!view.loading&&!['generating','ready'].includes(state?.output);$('end').disabled=state?.engagement!=='active';
  if(state?.failure?.code==='memory_worker_unavailable'&&!memoryPaused){
   pauseMemories();
  }else if(state?.error&&!memoryRecovery){$('error').textContent=state.error+' Try another question, or mute and reconnect.';$('error-card').hidden=false;}
  controls();
  if(guide.running){if(state)guideState=state;guide.observe(view);}
 }
 async function check(reconnect=false){
  if(!bridge){error(Error('Open Paprika.app to use this screen.'));return;}
  working=true;controls();
  try{
   const s=await(reconnect?bridge.reconnect():bridge.status());connected=true;ready=s.prerequisites.ready;
   $('connection').textContent='Ready on this Mac';
   $('readiness').textContent=!s.prerequisites.drive?'Connect the external drive, then choose Reconnect.':!s.prerequisites.local_files?'Local speech files are unavailable. Reconnect after restoring this project’s environments.':!s.prerequisites.cloud_key?'Local listening is ready. Online replies are unavailable; choose offline for now.':'Ready when you are.';
   $('budget').textContent=spending(s);
   if(!ready)error(Error($('readiness').textContent));else {$('error-card').hidden=true;if(!endpoint.active&&!endpoint.starting)render({active:false,starting:false,state:null});}
   if(bridge.voices){try{const family=await bridge.voices();$('family-summary').textContent=`${family.current_profiles} of 4 voices saved · ${family.identity_qualified?'voice checks qualified':'fresh voice checks needed'}`;$('family-memory').disabled=!(family.identity_qualified&&family.memory_qualified);if(!(family.identity_qualified&&family.memory_qualified))$('family-memory').checked=false;}catch{$('family-summary').textContent='Connect the external drive to check family voices.';}}
   if(memoryPaused){$('family-memory').checked=false;$('family-memory').disabled=true;$('family-note').textContent='Memories are paused for this visit. Choose how to chat and confirm microphone use again.';}
  }catch(e){connected=false;ready=false;$('connection').textContent='Waiting for this Mac';error(e);}
  finally{working=false;controls();}
 }
 function clearChoices(){ for(const id of ['adult','check-adult','family-voice','family-memory','family-audience'])$(id).checked=false;document.querySelectorAll('input[name=processing]').forEach(r=>r.checked=false); }
 function familyChoices(){return {voice:$('family-voice').checked,memory:!memoryPaused&&$('family-memory').checked,audience:$('family-audience').checked};}
 async function setup(){
  if(guide.running){guide.finish('Returned to setup before the check finished. Save or leave this partial result below.');return;}
  if(guide.stage==='review')return;
  memoryRecovery=false;$('memory-return').hidden=true;$('retry').hidden=false;
  await endpoint?.stop();page='setup';clearChoices();lastEngaged=chatFinished=false;guide.move('idle');controls();await check();
 }
 async function start(guided=false){
  if($(guided?'check-start':'start').disabled)return;
  const selected=document.querySelector('input[name=processing]:checked');$('error-card').hidden=true;page='companion';lastEngaged=chatFinished=false;
  if(!guided)guide.move('idle');
  controls();await endpoint.start(selected.value==='online',familyChoices());controls();
 }
 $('adult').onchange=controls;$('check-adult').onchange=controls;document.querySelectorAll('input[name=processing]').forEach(r=>r.onchange=controls);
 $('start').onclick=()=>start();
 $('check-start').onclick=async()=>{if($('check-start').disabled)return;guideState=null;$('check-note').value='';$('check-result').value='';$('check-include-text').checked=false;$('check-saved').textContent='';await start(true);if(endpoint.active)guide.start();controls();};
 $('back').onclick=setup;
 $('memory-return').onclick=async()=>{$('memory-return').hidden=true;$('retry').hidden=false;await setup();};
 $('family-setup').onclick=async()=>{await endpoint?.stop();await bridge.openVoices();};
 $('check-return').onclick=()=>{guide.move('idle');setup();};
 $('mute').onclick=()=>{if(guide.running)guide.finish();else endpoint.stop();};
 $('resume').onclick=async()=>{if(!$('adult').checked||!document.querySelector('input[name=processing]:checked'))return setup();$('error-card').hidden=true;await endpoint.start(document.querySelector('input[name=processing]:checked').value==='online',familyChoices());};
 $('interrupt').onclick=()=>endpoint.interrupt().catch(error);$('end').onclick=()=>{if(guide.running)guide.finish('Chat ended early.');else endpoint.end().catch(error);};
 $('check-save').onclick=async()=>{
  if(endpoint.active||endpoint.starting){error(Error('Wait for the microphone to turn off before saving.'));return;}
  if(!$('check-result').value){$('check-saved').textContent='Choose how it went, then Save.';return;}
  try{const report=guide.report($('check-result').value,$('check-note').value);if($('check-include-text').checked)report.last_exchange={heard:guideState?.heard||'',reply:guideState?.reply||''};await bridge.saveReview(report);guide.move('saved');$('check-saved').textContent='Saved on this Mac. Thank you.';controls();}
  catch(e){$('check-saved').textContent='Could not save. Keep this page open and choose Save again. '+e.message;}
 };
 $('retry').onclick=async()=>{if(guide.running)guide.finish('Reconnected before the check finished.');await endpoint?.stop();clearChoices();if(guide.stage!=='review')page='setup';await check(true);};
 $('volume').oninput=()=>{$('volume-value').textContent=Math.round(Number($('volume').value)*100)+'%';endpoint?.setVolume(Number($('volume').value));};
 bridge?.onPause(async()=>{if(guide.running)guide.finish('Listening stopped by the Mac or menu. Save this partial check.');await endpoint.stop();clearChoices();$('cue').textContent='Listening stopped. Set up listening when you’re ready.';controls();});
 window.addEventListener('pagehide',()=>endpoint?.stop());
 if(typeof requestAnimationFrame==='function'){
  let last=0,level=0;const reduced=window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;
  function animate(time){if(time-last>=50){const target=reduced?(endpoint?.source ? .2:0):endpoint?.speechLevel?.()||0;level+=(target-level)*.5;$('face-card').style.setProperty('--speech',level.toFixed(3));last=time;}requestAnimationFrame(animate);}requestAnimationFrame(animate);
 }
 setInterval(async()=>{
  if(working||polling)return;polling=true;
  try{const s=await bridge?.status();if(!s)return;if(!s.prerequisites.ready){ready=false;clearChoices();controls();if(endpoint?.active||endpoint?.starting)await endpoint.fail(Error('The external drive or local speech files are unavailable. Reconnect before starting again.'));else error(Error('Connect the external drive and restore local speech files, then choose Reconnect.'));}if(s.family?.family_memory_requested&&s.family.memory?.ready===false&&endpoint?.active)pauseMemories();if(!connected)await check();}
  catch(e){if(connected){connected=false;ready=false;$('connection').textContent='Waiting for this Mac';if(endpoint?.active||endpoint?.starting)await endpoint.fail(Error('The connection stopped. Reconnect and start again.'));else error(e);}}
  finally{polling=false;}
 },5000);
 check();
})();

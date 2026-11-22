'use strict';
const $=id=>document.getElementById(id),put=(id,value)=>{$(id).textContent=value};
let plan=null,passage='short_story',preference=null,current=null,playVersion=0,saving=false;
const opinions=new Map(),character=new Map(),listening=[],traits=new Set();
const VOICES=['K','M','N','O'],CASES=['short_story','greeting'];
const trialFor=voice=>plan.trials.find(t=>t.case===passage&&t.voice===voice);
function dirty(){if(!$('saved').hidden)put('dirty','Changes since the last download. Save again when you’re ready.');}
function stop(reason='stopped'){
 ++playVersion;
 if(current){const {audio,event}=current;current=null;audio.onended=audio.onerror=null;audio.pause();event.ended_reason=reason;event.ended_at=new Date().toISOString();}
 for(const voice of VOICES)put('play-'+voice.toLowerCase(),'Play '+voice);
}
function render(){
 put('phrase',trialFor('K').text);
 for(const key of CASES)$('passage-'+key).setAttribute('aria-pressed',String(key===passage));
 for(const code of VOICES){
  const voice=code.toLowerCase(),selected=preference===voice;
  $('prefer-'+voice).setAttribute('aria-pressed',String(selected));$('card-'+voice).dataset.favorite=String(selected);
  put('prefer-'+voice,selected?'Closest so far ✓':'Closest so far');
  $('opinion-'+voice).value=opinions.get(trialFor(code).id)?.rating||'';
  for(const dimension of ['huskiness','humanlike'])$('tone-'+dimension+'-'+voice).value=character.get(trialFor(code).id)?.[dimension]||'';
 }
 $('prefer-none').setAttribute('aria-pressed',String(preference==='none'));
 put('choice',preference==='none'?'None of these fits':preference?'Closest so far: Voice '+preference.toUpperCase():'No closest voice picked yet.');
 if(preference==='none')$('decision').value='still_looking';
 $('decision').disabled=preference==='none';
 $('save').disabled=!preference||saving;
}
async function load(){
 try{
  const response=await fetch('/voice-husky-protocol.json',{signal:AbortSignal.timeout(5000)});
  if(!response.ok)throw Error('Samples unavailable');
  const data=await response.json();
  if(data.id!=='paprika-voice-husky-v1'||!Array.isArray(data.trials)||data.trials.length!==8||data.trials.some((t,i)=>t.src!==`/voice-husky/sample-${i+1}.wav`))throw Error('Invalid sample plan');
  for(const key of CASES){
   const matches=VOICES.map(voice=>data.trials.filter(t=>t.case===key&&t.voice===voice));
   if(matches.some(rows=>rows.length!==1)||new Set(matches.map(rows=>rows[0].text)).size!==1)throw Error('Matching words required');
  }
  plan=data;$('comparison').hidden=false;$('retry').hidden=true;put('error','');
  put('voice-names',VOICES.map(voice=>'Voice '+voice+': '+plan.voices[voice]).join(' · '));render();
 }catch(error){$('retry').hidden=false;put('error','The local samples could not load. Use Reload listening samples to try again.');}
}
async function play(voice){
 if(!plan)return;
 if(current?.voice===voice){stop();put('play-status','Stopped. Play any voice again whenever you like.');return;}
 stop('switched');const version=playVersion,trial=trialFor(voice);
 // A distinct element per play keeps late events from an old source from
 // changing the state of the voice the listener switched to.
 const audio=new Audio(trial.src),event={trial_id:trial.id,voice,started_at:new Date().toISOString(),ended_reason:null};
 audio.volume=Number($('volume').value);current={voice,audio,event};listening.push(event);
 if(listening.length>100)listening.shift();dirty();
 const fail=()=>{if(current?.audio!==audio)return;stop('error');put('play-status','Playback stopped.');put('error','Voice '+voice+' could not play. Try it again, or report the problem below and save what you have.');};
 audio.onerror=fail;
 audio.onended=()=>{if(current?.audio!==audio)return;stop('completed');put('play-status','Voice '+voice+' finished. Rate how much you like it, replay, or try another voice.');};
 put('error','');put('play-'+voice.toLowerCase(),'Stop '+voice);put('play-status','Playing voice '+voice+'… Click another Play button to switch.');
 try{await audio.play();if(version!==playVersion)audio.pause();}
 catch(error){if(version===playVersion)fail();}
}
for(const voice of VOICES.map(v=>v.toLowerCase())){
 $('play-'+voice).onclick=()=>play(voice.toUpperCase());
 for(const dimension of ['huskiness','humanlike'])$('tone-'+dimension+'-'+voice).onchange=()=>{
  if(!plan)return;const trial=trialFor(voice.toUpperCase()),row=character.get(trial.id)||{trial_id:trial.id,voice:trial.voice};
  const value=$('tone-'+dimension+'-'+voice).value;
  const allowed=dimension==='huskiness'?['none','slight','clear','too_rough']:['synthetic','mixed','humanlike'];
  if(allowed.includes(value))row[dimension]=value;else delete row[dimension];
  if(row.huskiness||row.humanlike)character.set(trial.id,row);else character.delete(trial.id);dirty();
 };
 $('opinion-'+voice).onchange=()=>{
  if(!plan)return;const trial=trialFor(voice.toUpperCase()),rating=$('opinion-'+voice).value;
  if(['love','like','okay','not_for_me'].includes(rating))opinions.set(trial.id,{trial_id:trial.id,voice:trial.voice,rating});else opinions.delete(trial.id);
  dirty();
 };
}
for(const key of CASES)$('passage-'+key).onclick=()=>{
 if(!plan||passage===key)return;stop('passage_changed');passage=key;put('error','');put('play-status','New passage. Play any voices to compare the same words.');render();
};
for(const key of [...VOICES.map(v=>v.toLowerCase()),'none'])$('prefer-'+key).onclick=()=>{if(!plan)return;if(preference!==key)$('decision').value='still_looking';preference=key;dirty();render();};
$('volume').oninput=()=>{if(current)current.audio.volume=Number($('volume').value);put('volume-value',Math.round(Number($('volume').value)*100)+'%');dirty();};
$('note').oninput=$('audio-issue').oninput=$('decision').onchange=dirty;
for(const key of ['youthful','confident','warm','texture','natural','expressive'])$('trait-'+key).onclick=()=>{if(traits.has(key))traits.delete(key);else traits.add(key);$('trait-'+key).setAttribute('aria-pressed',String(traits.has(key)));dirty();};
$('retry').onclick=load;
$('save').onclick=()=>{
 if(!plan||!preference||saving)return;
 stop('saved');saving=true;render();
 try{
  const completed=new Set(listening.filter(e=>e.ended_reason==='completed').map(e=>e.trial_id));
  const report={schema_version:1,kind:plan.kind,protocol_id:plan.id,ui_protocol_id:plan.id,audition_method:plan.method,reference_feedback:plan.reference_feedback,design_model:plan.design_model,design_settings:plan.design_settings,pronunciation:plan.pronunciation,created_at:new Date().toISOString(),
   trials:plan.trials,opinions:Array.from(opinions.values()),character_observations:Array.from(character.values()),opinions_complete:opinions.size===plan.trials.length,
   completed_samples:Array.from(completed),listening,closest_voice:preference,selection_status:$('decision').value,
   accepted_voice:$('decision').value==='accepted'?preference:null,direction_tags:Array.from(traits),
   note:$('note').value.slice(0,500),audio_issue:$('audio-issue').value.slice(0,500),
   voices:plan.voices,playback_volume:Number($('volume').value),microphone_used:false,api_spend_usd:0};
  const filename='paprika-voice-character-'+crypto.randomUUID()+'.json',link=document.createElement('a');
  link.href=URL.createObjectURL(new Blob([JSON.stringify(report,null,2)],{type:'application/json'}));link.download=filename;link.click();setTimeout(()=>URL.revokeObjectURL(link.href),1000);
  $('saved').hidden=false;put('filename','File: '+filename);put('dirty','');put('error','');put('save','Save updated feedback');
  put('play-status','Playback stopped. Your comparison stays here if you want to keep listening.');
 }catch(error){put('error','Could not save. Your choices are still here. Try the save button again.');}
 finally{saving=false;render();}
};
window.addEventListener('pagehide',()=>stop('page_closed'));load();

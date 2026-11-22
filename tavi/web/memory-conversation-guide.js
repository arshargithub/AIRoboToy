'use strict';
function memoryPilotConsent(){
 const adult=document.getElementById('pilot-adult').checked;
 const choice=document.querySelector('input[name=pilot-processing]:checked')?.value;
 if(adult&&choice==='local-speech-cloud-text')return true;
 const help=document.getElementById('guide-error');help.textContent=!adult?'Confirm that you are an adult testing alone before starting.':choice==='local-only'?'This conversation needs online text replies. You can leave without starting, or choose local speech with online replies. No microphone has started.':'Choose how your speech and text may be processed before starting.';
 return false;
}
const ExistingKGuide=KConversationGuide;
KConversationGuide=class extends ExistingKGuide{
 async start(){
  if(!memoryPilotConsent())return;
  await super.start();
  if(!this.data)return;
  this.data.variant='memory-v1';this.data.ui_protocol='memory-adult-functional-v1';this.data.identity='Fictional Nora selected by adult setup; not voice identification';
  this.data.steps=[
   {key:'book',prompt:'Paprika, could you suggest a new mystery for me to read?'},
   {key:'book_followup',prompt:'What makes that one a good match for me?'},
   {key:'comfort',prompt:'I feel tense. What could help me unwind?'},
   {key:'gift',prompt:'What would be a good new present for Theo?'},
   {key:'goodbye',prompt:'Goodbye, Paprika.'}
  ];this.render(this);
 }
 observe(state){
  super.observe(state);
  if(this.data&&this.index===4&&this.data.steps[4]?.playback_end==='source_ended'&&state.engagement==='idle')this.data.goodbye_closed=true;
 }
 playbackStarted(id){
  if(!this.running)return;const s=this.data.steps[this.index];if(s.response_id!==id||s.started)return;s.started=true;this.show('listen',45000);
 }
 playbackEnded(id,reason){
  if(!this.running)return;const s=this.data.steps[this.index];if(s.response_id!==id||s.playback_end)return;
  s.playback_end=reason;
  if(reason!=='source_ended'){this.finish('A reply stopped early. The microphone is off; save the partial attempt and describe what happened.');return;}
  if(this.index===4){this.data.goodbye_closed=this.lastEngagement==='idle';this.quiet(3000,'finish');return;}
  this.index++;this.quiet(1500,'call');
 }
 copy(){
  const step=this.data?.steps?.[this.index],n=(this.index??0)+1,phrase=step?.prompt||'';
  return {
   setup:['Get ready','Does memory make the conversation feel personal?','About two to three minutes. You will pretend to be Nora, an adult test role. Follow each speaking cue, listen to the full reply, then save feedback here. This is a functional pilot; replies may take several seconds.',''],
   starting:['Microphone setup','Getting Paprika ready…','Allow the microphone if asked. Wait here while local listening, memory and K get ready.',''],
   quiet:['Stay quiet','Wait for your next speaking cue','Let the room settle. The next phrase will appear automatically.',phrase],
   call:[`${n} of 5 · Speak`,'Say this naturally',n===1?'Say the whole sentence without pausing after Paprika.':'Say the displayed sentence. You are still Nora; no wake name is needed.',phrase],
   waiting:[`${n} of 5 · Thinking`,'Paprika is thinking','Stay quiet. Watch the thinking cue; the reply may take several seconds.',phrase],
   listen:[`${n} of 5 · Listen`,'Paprika is talking',n===5?'Let goodbye finish; the microphone will turn off automatically.':'Listen to the full reply. Keep your reaction in mind for the final review.',phrase],
   check_words:['Review · Microphone off','Check the heard words','Compare the recognized request with what you said. You can play a local recording if you chose to keep one.',''],
   review:['Review · Microphone off','How personal did it feel?','Save your attempt here, including a partial attempt if anything failed. Add your thoughts about relevance, warmth, repetition and waiting.',''],
   saved:['Finished · Microphone off','Your results are saved','Everything is saved locally. You can now tell the assistant “done.” No download is needed.','']
  }[this.stage];
 }
};

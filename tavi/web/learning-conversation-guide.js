'use strict';
const ExistingMemoryGuide=KConversationGuide;
KConversationGuide=class extends ExistingMemoryGuide{
 constructor(options){super(options);this.checkpoint=options.checkpoint;}
 async start(){
  await super.start();if(!this.data||!this.running)return;
  this.variant='learning-v1';this.data.variant='learning-v1';this.data.ui_protocol='learning-adult-v1';this.data.identity='Fictional Mira selected by adult setup; not voice identification';this.data.memory_checkpoints=[];
  this.data.steps=[
   {key:'teach',prompt:'Paprika, I enjoy making little wooden gliders and adjusting their wings.'},
   {key:'recall',prompt:'Paprika, what small project would I enjoy?'},
   {key:'correct',prompt:'I do not want to make gliders anymore. I want to build stick bridges instead.'},
   {key:'recall_change',prompt:'Paprika, what small project would I enjoy now?'},
   {key:'goodbye',prompt:'Goodbye, Paprika.'}
  ];this.render(this);
 }
 observe(state){
  super.observe(state);if(!this.running)return;
  const l=state.learning;
  if(l?.error||['needs_reconciliation','owner_busy','job_bound'].includes(l?.status))this.finish('A memory could not be saved safely. The microphone is off. Save this partial attempt below; you do not need to repeat anything.');
 }
 playbackEnded(id,reason){
  if(!this.running)return;const s=this.data.steps[this.index];if(s.response_id!==id||s.playback_end)return;
  s.playback_end=reason;
  if(reason!=='source_ended'){this.finish('A reply stopped early. The microphone is off. Save this partial attempt below.');return;}
  if(this.index===0||this.index===2){this.remember(this.index===0?1:2);return;}
  if(this.index===4){this.data.goodbye_closed=this.lastEngagement==='idle';this.quiet(3000,'finish');return;}
  this.index++;this.quiet(1500,'call');
 }
 async remember(checkpoint){
  const serial=this.serial;this.show('remembering',45000);
  try{
   while(this.running&&serial===this.serial){
    const value=await this.checkpoint(checkpoint);
    if(serial!==this.serial||!this.running)return;
    if(value.ready){this.data.memory_checkpoints.push({checkpoint,ready:true});this.index++;this.quiet(1500,'call');return;}
    await new Promise(resolve=>this.setTimer(resolve,400));
   }
  }catch(error){if(serial===this.serial&&this.running)this.finish('The memory save or restart could not finish. The microphone is off. Save this partial attempt below.');}
 }
 copy(){
  const s=this.data?.steps?.[this.index],phrase=s?.prompt||'',n=(this.index??0)+1;
  return {
   setup:['Get ready','Can Paprika learn and change its mind?','About three minutes. Pretend to be Mira, teach a hobby, then change it. Paprika will restart its conversation before each memory check. Follow the cards here.',''],
   starting:['Get ready','Getting Paprika ready…','Allow microphone access if asked, then wait for your speaking cue. Local listening, voice and a new empty memory bank are getting ready.',''],
   quiet:['Stay quiet','Your next phrase is coming','Wait for the Speak card. Do not say the next sentence yet.',phrase],
   call:[`${n} of 5 · Speak`,'Say this naturally',this.index===0?'Say the whole sentence without pausing after Paprika.':this.index===2?'This is a change of preference. Say the whole sentence.':'Use the whole displayed sentence, including Paprika when shown.',phrase],
   waiting:[`${n} of 5 · Thinking`,'Paprika is thinking','Stay quiet and wait for the reply.',phrase],
   listen:[`${n} of 5 · Listen`,'Listen to the whole reply',this.index===4?'Let goodbye finish. The microphone will turn off automatically.':'Listen for whether the response fits what you have told Paprika.',phrase],
   remembering:['Stay quiet · Memory check','Saving, then restarting the conversation','No speaking needed. We are waiting for the memory to finish saving, then clearing the chat and reopening the memory workers. The next reply must use saved memory. This deliberate check is separate from the normal reply wait.',phrase],
   check_words:['Review · Microphone off','Check the heard words','Compare the recognized requests with what you actually said. Local listening copies are available if you chose recording.',''],
   review:['Review · Microphone off','Did it remember the change?','Did the first suggestion fit gliders, and the later suggestion fit stick bridges? Rate memory accuracy and waiting separately, add any thoughts, then save here.',''],
   saved:['Finished · Microphone off','Your results are saved','The attempt is saved privately on this Mac. Its fictional memories remain isolated for review. You can tell the assistant “done.” No download is needed.','']
  }[this.stage];
 }
};

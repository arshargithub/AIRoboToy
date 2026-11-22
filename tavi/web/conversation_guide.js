'use strict';
// A guided experiment observes playback; it never fabricates a successful result.
class ConversationGuide {
 constructor({render,startCapture,stopCapture,setTimer=(fn,ms)=>setTimeout(fn,ms),clearTimer=id=>clearTimeout(id),clock=()=>performance.now()}){
  Object.assign(this,{render,startCapture,stopCapture,setTimer,clearTimer,clock});
  this.stage='setup';this.timer=null;this.serial=0;this.data=null;
 }
 get running(){return !['setup','check_words','review','saved'].includes(this.stage);}
 show(stage,timeout=0){
  this.clearTimer(this.timer);this.timer=null;this.stage=stage;
  if(this.data)this.data.phase_events.push({stage,at_ms:this.clock()});
  this.render(this);
  if(timeout){const serial=this.serial;this.timer=this.setTimer(()=>{if(serial===this.serial)this.finish('Timed out waiting for the next part.');},timeout);}
 }
 async start(){
  if(this.running)return;
  this.serial++;const serial=this.serial;
  this.data={protocol:'interruption-v2-guided-review',first_response_id:null,replacement_response_id:null,
   first_playback_end:null,replacement_playback_end:null,result:null,note:'',finished_reason:null,word_reviews:[],phase_events:[]};
  this.show('starting');
  const ready=await this.startCapture();
  if(serial!==this.serial)return;
  if(ready)this.show('call',30000);else this.finish('Microphone or local service could not start.');
 }
 accepted(id){
  if(!this.running||!id)return;
  if(!this.data.first_response_id){this.data.first_response_id=id;this.show('waiting_story',20000);}
  else if(id!==this.data.first_response_id&&id!==this.data.replacement_response_id){
   this.data.replacement_response_id=id;this.show('waiting_replacement',20000);
  }
 }
 playbackStarted(id){
  if(!this.running)return;
  if(id===this.data.first_response_id){
   this.show('get_ready');const serial=this.serial;
   this.timer=this.setTimer(()=>{if(serial===this.serial&&this.stage==='get_ready')this.show('interrupt',20000);},1500);
  }else if(id===this.data.replacement_response_id)this.show('listen',35000);
 }
 playbackEnded(id,reason){
  if(!this.running)return;
  if(id===this.data.first_response_id){
   this.data.first_playback_end=reason;this.show('waiting_replacement',20000);
  }else if(id===this.data.replacement_response_id){
   this.data.replacement_playback_end=reason;this.finish('The new reply ended.');
  }
 }
 finish(reason='You stopped the test.',stop=true){
  if(!this.running)return;
  this.serial++;this.clearTimer(this.timer);this.timer=null;
  this.data.finished_reason=reason;
  this.data.word_reviews=[['first',this.data.first_response_id],['replacement',this.data.replacement_response_id]]
   .filter(([,id])=>id).map(([position,id])=>({position,response_id:id,rating:null}));
  this.wordIndex=0;this.stage=this.data.word_reviews.length?'check_words':'review';
  this.data.phase_events.push({stage:this.stage,at_ms:this.clock()});
  // End capture before asking the person to review. No further spoken answer
  // can accidentally trigger a paid follow-up while they use the controls.
  if(stop)this.stopCapture();this.render(this);
 }
 currentWords(){return this.stage==='check_words'?this.data.word_reviews[this.wordIndex]:null;}
 rateWords(rating){const item=this.currentWords();if(item&&['correct','incorrect_or_incomplete','unknown'].includes(rating)){item.rating=rating;this.render(this);}}
 nextWords(){const item=this.currentWords();if(!item?.rating)return;this.wordIndex++;this.show(this.wordIndex<this.data.word_reviews.length?'check_words':'review');}
 report(result){if(this.stage==='review'&&['worked','problem','unsure'].includes(result)){this.data.result=result;this.render(this);}}
 saved(){if(this.stage==='review')this.show('saved');}
 reset(){if(this.stage==='saved'){this.data=null;this.wordIndex=0;this.stage='setup';this.render(this);}}
}
// A varied live check for the provisional K voice. The old two-turn protocol
// stays available for interpreting earlier exports and regression tests.
class KConversationGuide extends ConversationGuide {
 async start(){
  if(this.running)return;
  this.serial++;const serial=this.serial;this.wordIndex=0;this.index=0;this.seen=new Set();this.lastEngagement=null;this.lastInputRejection=null;
  this.data={protocol:'k-live-conversation-v1',ui_protocol:'k-live-local-save-v2',result:null,note:'',finished_reason:null,phase_events:[],word_reviews:[],
   first_response_id:null,replacement_response_id:null,first_playback_end:null,replacement_playback_end:null,
   completed:false,goodbye_closed:null,unexpected_responses:[],
   steps:[
    {key:'quiet_reply',prompt:'Paprika, what can we make with a cardboard box?'},
    {key:'followup',prompt:'How could we make it into a spaceship?'},
    {key:'story',prompt:'Tell me a short story about a fox finding a secret door.'},
    {key:'interruption',prompt:'Wait, make it an underwater adventure with a turtle instead.'},
    {key:'goodbye',prompt:'Goodbye, Paprika.'}
   ]};
  if(this.variant==='latency-v1'){
   this.data.variant=this.variant;
   const prompts=['Paprika, what could we build with three cushions?','How could we turn it into a castle?',
    'Tell me a short story about a rabbit exploring a moon cave.',
    'Wait, make it a jungle adventure with a friendly lizard instead.','Goodbye, Paprika.'];
   this.data.steps.forEach((step,i)=>step.prompt=prompts[i]);
  }
  if(this.variant==='turbo-v1'){
   this.data.variant=this.variant;
   const prompts=['Paprika, what can we build with three cushions and a blanket?',
    'How can we make a window in our castle?',
    'Tell me a short story about a fox building a boat.',
    'Wait, make it a space adventure with a sleepy dragon instead.','Goodbye, Paprika.'];
   this.data.steps.forEach((step,i)=>step.prompt=prompts[i]);
  }
  this.show('starting');const ready=await this.startCapture();if(serial!==this.serial)return;
  if(!ready){this.finish('Microphone or local service could not start.');return;}
  this.quiet(3000,'call');
 }
 quiet(ms,next){
  this.show('quiet');const serial=this.serial;
  this.timer=this.setTimer(()=>{if(serial!==this.serial||this.stage!=='quiet')return;
   if(next==='finish'){this.data.completed=true;this.finish(this.data.goodbye_closed===true?'The conversation check finished.':'Goodbye finished, but the chat did not close locally. Save this attempt for inspection.');}
   else this.show('call',30000);
  },ms);
 }
 observe(state){
  if(!this.running)return;this.lastEngagement=state.engagement;
  if(state.input_rejection){
   const rejection=state.input_rejection,key=rejection.recognition_id??rejection.utterance;
   const fresh=key!==this.lastInputRejection;this.lastInputRejection=key;
   if(fresh&&this.index===0&&this.stage==='call'){
    this.data.input_rejection={...rejection};
    this.finish('I heard speech, but could not confirm you were speaking to Paprika. The microphone is off. Save this attempt so we can check it; no need to keep repeating the phrase.');return;
   }
  }
  if(state.failure){
   this.data.failure={...state.failure};
   this.finish(state.failure.code==='memory_worker_unavailable'?'Paprika could not reach its memories. The microphone is off. Save this partial attempt below; you do not need to repeat anything.':state.failure.component==='speech'?'K’s local voice failed. The microphone is off; review and save this partial attempt.':'The online reply failed. The microphone is off; review and save this partial attempt.');return;
  }
  if(this.index===4&&this.data.steps[4].playback_end==='source_ended'&&state.engagement==='idle')this.data.goodbye_closed=true;
 }
 accepted(id){
  if(!this.running||!id||this.seen.has(id))return;
  this.seen.add(id);const step=this.data.steps[this.index];
  if(this.stage==='quiet'||this.stage==='starting'||step.response_id){
   this.data.unexpected_responses.push({response_id:id,stage:this.stage,at_ms:this.clock()});
   this.finish('An unexpected reply arrived. Save this attempt so we can inspect it.');return;
  }
  step.response_id=id;
  if(this.index===2)this.data.first_response_id=id;
  if(this.index===3)this.data.replacement_response_id=id;
  this.show('waiting',25000);
 }
 playbackStarted(id){
  if(!this.running)return;const step=this.data.steps[this.index];if(step.response_id!==id)return;
  if(step.started)return;step.started=true;
  if(this.index===2){
   this.show('get_ready');const serial=this.serial;
   this.timer=this.setTimer(()=>{if(serial===this.serial&&this.stage==='get_ready')this.show('interrupt',20000);},1500);
  }else this.show('listen',35000);
 }
 playbackEnded(id,reason){
  if(!this.running)return;const step=this.data.steps[this.index];if(step.response_id!==id||step.playback_end)return;
  step.playback_end=reason;
  if(this.index===2){
   this.data.first_playback_end=reason;
   if(reason!=='speech'){this.finish('The story ended without a speech-triggered stop. Save this attempt.');return;}
   this.index=3;this.show('finish_interruption',25000);return;
  }
  if(this.index===3)this.data.replacement_playback_end=reason;
  if(reason!=='source_ended'){this.finish('A reply stopped when it should have finished. Save this attempt.');return;}
  if(this.index===4){if(this.lastEngagement==='idle')this.data.goodbye_closed=true;this.quiet(5000,'finish');return;}
  this.index++;this.quiet(2000,'call');
 }
 responseIds(){return this.data?[...this.data.steps.map(s=>s.response_id),...this.data.unexpected_responses.map(s=>s.response_id)].filter(Boolean):[];}
 finish(reason='You stopped the test.',stop=true){
  if(!this.running)return;this.serial++;this.clearTimer(this.timer);this.timer=null;
  this.data.finished_reason=reason;
  if(this.data.goodbye_closed===null&&this.data.steps[4].playback_end)this.data.goodbye_closed=false;
  this.data.word_reviews=this.data.steps.filter(s=>s.response_id).map(s=>({position:s.key,prompt:s.prompt,response_id:s.response_id,rating:null}));
  this.wordIndex=0;this.stage=this.variant==='turbo-v1'&&this.data.completed&&this.data.word_reviews.length?'check_words':'review';
  this.data.phase_events.push({stage:this.stage,at_ms:this.clock()});if(stop)this.stopCapture();this.render(this);
 }
 copy(){
  const n=this.index+1,prompt=this.data?.steps[this.index]?.prompt||'';
  if(this.variant==='turbo-v1'&&this.stage==='setup')return ['Get ready','Try clearer listening with K',
   'About two minutes. Check whole requests, follow-ups without the name, complete quiet replies and interruption. Listen for long waits too. The voice is still K. Follow each card, then save here.',''];
  return {
   setup:this.variant==='latency-v1'?['Get ready','Try the faster conversation','About two minutes with fresh phrases. Listen for how soon K starts, awkward pauses between sentences, complete replies and clean interruption. Follow each card, then save here.','']:['Get ready','Ready to try K?','About two minutes: quiet replies, a follow-up, interruption and goodbye. Follow each card, then review and save here.',''],
   starting:['Get ready','Starting K…','Allow microphone access if asked. Wait while the local voice and recognizer get ready.',''],
   quiet:['Stay quiet','Listen for unwanted replies','Don’t speak yet. The next speaking cue will appear automatically.',''],
   call:[`${n} of 5 · Speak`,'Say this naturally',this.index===0?'Say the whole request without pausing after the name.':'Keep the conversation going. Use exactly the displayed words; no wake name is needed until goodbye.',prompt],
   waiting:[`${n} of 5 · Wait`,'Wait for K','Stay quiet while the reply is prepared. We measure this delay.',''],
   listen:[`${n} of 5 · Listen`,'Stay quiet for this whole reply',this.index===4?'Let goodbye finish. We’ll check for any extra reply, then turn the microphone off.':'Let K finish. Don’t speak until the next speaking cue.',''],
   get_ready:['4 of 5 · Get ready','Get ready to interrupt','Wait for the green Speak now card.',this.data?.steps[3].prompt||''],
   interrupt:['4 of 5 · Interrupt','Speak now','Say the whole sentence, even if K stops halfway through.',this.data?.steps[3].prompt||''],
   finish_interruption:['4 of 5 · Finish speaking','Finish your sentence, then stay quiet','K stopped. Finish the displayed sentence and wait for the replacement reply.',prompt],
   check_words:['Review · Microphone off','Check what K heard','Compare each request with what you actually said. Mark missing words honestly, then continue.',''],
   review:['One last step · Microphone off','Save your test results','The speaking part is finished. Save now so the assistant can review the result. Feedback and word checks below are optional.',''],
   saved:['Finished','Results saved on this Mac','Your results are ready for the assistant to review. You can now say “done” in chat. No download or upload is needed.','']
  }[this.stage];
 }
 beginWordReview(){if(this.stage==='review'&&this.data.word_reviews.length){this.wordIndex=0;this.show('check_words');}}
 report(result){if(['review','check_words'].includes(this.stage)&&['worked','problem','unsure'].includes(result)){this.data.result=result;this.render(this);}}
 saved(){if(['review','check_words'].includes(this.stage))this.show('saved');}
}
if(typeof module!=='undefined')module.exports={ConversationGuide,KConversationGuide};

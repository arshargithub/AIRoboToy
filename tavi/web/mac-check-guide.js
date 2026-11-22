'use strict';
// In-app adult check; no automatic retries, microphone recordings or identity labels.
class MacCheckGuide{
 constructor({render,stop}){this.render=render;this.stop=stop;this.stage='idle';this.first=null;this.second=null;this.third=null;this.timer=null;this.events=[];}
 start(){this.first=this.second=this.third=null;this.completed=false;this.events=[];this.created=new Date().toISOString();this.move('ask');this.timer=setTimeout(()=>this.finish('The check timed out. Your partial result can still be saved.'),120000);}
 move(stage){this.stage=stage;this.events.push({stage,at:performance.now()});this.render(this);}
 get running(){return !['idle','review','saved'].includes(this.stage);}
 observe(view){
  if(!this.running)return;const s=view.state;if(!s)return;
  const id=s.accepted_response_id;
  if(this.stage==='ask'&&id){this.first=id;this.move('quiet');}
  if(this.stage==='quiet'&&s.completed_response_id===this.first&&!view.playing&&!view.loading){this.move('followup');return;}
  if(this.stage==='followup'&&id&&id!==this.first){this.second=id;this.move('wait');}
  if(this.stage==='wait'&&view.playing){this.move('interrupt');return;}
  if(this.stage==='interrupt'&&id&&id!==this.first&&id!==this.second){this.third=id;this.move('replacement');}
  if(this.stage==='replacement'&&s.completed_response_id===this.third&&!view.playing&&!view.loading){this.completed=true;this.finish('The check reached the end.');}
 }
 finish(reason='Stopped early. You can save this partial result.'){
  if(!this.running)return;clearTimeout(this.timer);this.reason=reason;this.move('review');this.stop();
 }
 copy(){return ({
  ask:['1 of 3 · Speak now','Say the whole sentence. The words stay here until Paprika starts replying.','Paprika, tell me a short story about a friendly dragon.'],
  quiet:['1 of 3 · Stay quiet','Let this first reply finish completely. We are checking that Paprika can hear herself without stopping.','Paprika, tell me a short story about a friendly dragon.'],
  followup:['2 of 3 · Speak now','Ask for another story without saying Paprika again.','Tell me another dragon story, a little longer.'],
  wait:['2 of 3 · Wait for the voice','Get ready to interrupt. Wait until you hear Paprika talking.','Wait, make it about a tiny robot instead.'],
  interrupt:['3 of 3 · Interrupt now','Say the whole sentence while Paprika talks, even if she stops partway through it.','Wait, make it about a tiny robot instead.'],
  replacement:['3 of 3 · Finish your words, then listen','After you finish speaking, stay quiet for the new reply. The microphone will turn off when it ends.','Wait, make it about a tiny robot instead.'],
  review:['Microphone off · Review','Save your feedback here, including anything that went wrong. No audio was recorded.',''],
  saved:['Saved on this Mac','The check is complete. You can close Paprika or start an ordinary conversation.','']
 })[this.stage]||['','',''];}
 report(result,note){return{kind:'paprika_mac_adult_check',unscored_feedback:true,created_at:this.created,finished_reason:this.reason,result,note:note.slice(0,1000),events:this.events,completed_sequence:this.completed,real_audio_retained:false,identity_enabled:false};}
}
if(typeof module!=='undefined')module.exports={MacCheckGuide};

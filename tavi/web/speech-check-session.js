'use strict';
class SpeechCheckSession {
 constructor({plan,collector,show,play,stopAudio,done,schedule=(fn,ms)=>setTimeout(fn,ms),cancel=id=>clearTimeout(id)}){
  Object.assign(this,{plan,collector,show,play,stopAudio,done,schedule,cancel});this.active=false;this.timer=null;this.index=0;
 }
 start(){if(this.active)throw Error('Recording already active');this.active=true;this.prepare();}
 prepare(){
  this.recording=false;const trial=this.plan.trials[this.index];this.show('read',trial,this.index);
  this.timer=this.schedule(()=>{
   if(!this.active)return;
   this.collector.begin(trial);this.recording=true;this.show('wait',trial,this.index);
   if(trial.condition==='overlap')this.play(trial);
  },this.plan.read_ms);
 }
 frame(packet){
  if(!this.active||!this.recording)return;
  this.collector.append(packet);const count=this.collector.current.frames.length;
  if(count===this.plan.cue_frame)this.show(this.plan.trials[this.index].phrase?'speak':'silent',this.plan.trials[this.index],this.index);
  if(count===this.plan.clip_frames){
   this.recording=false;this.stopAudio();this.collector.finish();this.index++;
   if(this.index===this.plan.trials.length)this.finish(true);else this.prepare();
  }
 }
 finish(complete=false){
  if(!this.active)return;
  this.active=false;this.recording=false;this.cancel(this.timer);this.collector.discard();this.stopAudio();this.done(complete);
 }
}
if(typeof module!=='undefined')module.exports={SpeechCheckSession};

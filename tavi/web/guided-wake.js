// A labelled smoke test. Cue windows are opportunities, not measured speech onsets.
class GuidedWakeTest {
 constructor({show,done,schedule=setTimeout,cancel=clearTimeout,clock=()=>performance.now()}){Object.assign(this,{show,done,schedule,cancel,clock});this.active=false;this.result=null;this.timers=[];this.current=null;}
 start(phrase='TAH-vee'){
  if(this.active)throw Error('A name test is already running');
  const epoch=this.epoch=(this.epoch||0)+1;this.active=true;this.result={complete:false,trials:[]};this.current=null;
  const phrases=[...Array(10).fill(phrase),'TV','Toby','coffee','toffee','that view'];
  this.show('Get ready. Say each displayed phrase once. First cue in 3 seconds.');
  phrases.forEach((phrase,i)=>this.timers.push(this.schedule(()=>{
   if(!this.active||this.epoch!==epoch)return;
   this.current={number:i+1,phrase,expected_wake:i<10,detections:[],cue_time_ms:this.clock()};this.result.trials.push(this.current);
   this.show(`${i+1}/15 — Say once: ${phrase}`);
  },3000+i*5000)));
  this.timers.push(this.schedule(()=>{if(this.epoch===epoch)this.finish(true)},3000+phrases.length*5000));
 }
 detected(score){if(this.active&&this.current)this.current.detections.push({after_cue_ms:this.clock()-this.current.cue_time_ms,score});}
 finish(complete=false){
  if(!this.active)return;
  this.epoch=(this.epoch||0)+1;this.active=false;this.current=null;this.timers.forEach(t=>this.cancel(t));this.timers=[];this.result.complete=complete;
  const pos=this.result.trials.filter(t=>t.expected_wake),neg=this.result.trials.filter(t=>!t.expected_wake);
  this.result.summary={positive_trials:pos.length,detected_positive_trials:pos.filter(t=>t.detections.length).length,negative_trials:neg.length,false_wake_trials:neg.filter(t=>t.detections.length).length,duplicate_events:pos.reduce((n,t)=>n+Math.max(0,t.detections.length-1),0)};
  const s=this.result.summary;
  this.show(complete?`Finished: ${s.detected_positive_trials}/${s.positive_trials} names detected; ${s.false_wake_trials}/${s.negative_trials} negative phrases triggered.`:'Name test cancelled');
  this.done(this.result);
 }
}
if(typeof module!=='undefined')module.exports={GuidedWakeTest};

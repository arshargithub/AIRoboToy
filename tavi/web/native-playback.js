// Playback scheduling clock, not an independent microphone-to-speaker measure.
class NativePlayback {
 constructor(context,{volume=.35,onStart=()=>{},onComplete=()=>{},onEvent=()=>{}}={}){this.ctx=context;this.onStart=onStart;this.onComplete=onComplete;this.onEvent=onEvent;this.rows=new Map();this.gain=context.createGain();this.gain.gain.value=volume;this.gain.connect(context.destination);}
 add(id,pcm){let r=this.rows.get(id);if(r?.blocked)return;if(r?.done)throw Error('Reply audio arrived after provider completion');if(!r){r={id,chunks:[],done:false,blocked:false,finished:false,start:this.ctx.currentTime+.02};this.rows.set(id,r);this.onStart(id,r.start);}
  const frames=pcm.length,buffer=this.ctx.createBuffer(1,frames,24000),samples=buffer.getChannelData(0);for(let i=0;i<frames;i++)samples[i]=pcm[i]/32768;
  const source=this.ctx.createBufferSource();source.buffer=buffer;source.connect(this.gain);const start=Math.max(this.ctx.currentTime+.02,r.next??r.start);const chunk={source,start,end:start+frames/24000,frames,ended:false};r.next=chunk.end;r.chunks.push(chunk);
  source.onended=()=>{chunk.ended=true;source.disconnect();this.check(r)};source.start(start);
 }
 done(id){const r=this.rows.get(id);if(r){r.done=true;this.check(r);}}
 check(r){
  // Source ended events are authoritative. Rechecking a separately calculated
  // floating-point end against currentTime can miss completion permanently.
  if(r.done&&!r.blocked&&!r.finished&&r.chunks.every(c=>c.ended)){r.finished=true;this.onEvent({kind:'completed',...this.snapshot(r.id)});this.onComplete(r.id);}
 }
 snapshot(id){const r=this.rows.get(id);if(!r)return {id,known:false};return {id,known:true,provider_done:!!r.done,blocked:!!r.blocked,finished:!!r.finished,chunks:r.chunks.length,ended_chunks:r.chunks.filter(c=>c.ended).length,context_seconds:this.ctx.currentTime,last_scheduled_end:r.next??null};}
 playedMs(id){const r=this.rows.get(id);if(!r)return 0;return Math.floor(r.chunks.reduce((n,c)=>n+Math.max(0,Math.min(c.end,this.ctx.currentTime)-c.start),0)*1000);}
 stop(id){let r=this.rows.get(id);if(!r){r={id,chunks:[],blocked:true};this.rows.set(id,r);return 0;}if(r.blocked)return r.stoppedMs??0;const ms=this.playedMs(id);r.blocked=true;r.stoppedMs=ms;for(const c of r.chunks){c.source.onended=null;try{c.source.stop()}catch{}c.source.disconnect();}return ms;}
 stopAll(){for(const id of this.rows.keys())this.stop(id);this.gain.disconnect();}
}
if(typeof module!=='undefined')module.exports={NativePlayback};

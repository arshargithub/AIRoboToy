// Preserved pre-fix player; silent browser regression control only.
// Playback scheduling clock, not an independent microphone-to-speaker measure.
class PreviousNativePlayback {
 constructor(context,{volume=.35,onStart=()=>{},onComplete=()=>{}}={}){this.ctx=context;this.onStart=onStart;this.onComplete=onComplete;this.rows=new Map();this.gain=context.createGain();this.gain.gain.value=volume;this.gain.connect(context.destination);}
 add(id,pcm){let r=this.rows.get(id);if(r?.blocked)return;if(!r){r={id,chunks:[],done:false,blocked:false,finished:false,start:this.ctx.currentTime+.02};this.rows.set(id,r);this.onStart(id,r.start);}
  const frames=pcm.length,buffer=this.ctx.createBuffer(1,frames,24000),samples=buffer.getChannelData(0);for(let i=0;i<frames;i++)samples[i]=pcm[i]/32768;
  const source=this.ctx.createBufferSource();source.buffer=buffer;source.connect(this.gain);const start=Math.max(this.ctx.currentTime+.02,r.next??r.start);const chunk={source,start,end:start+frames/24000,frames};r.next=chunk.end;r.chunks.push(chunk);source.onended=()=>{source.disconnect();this.check(r)};source.start(start);
 }
 done(id){const r=this.rows.get(id);if(r){r.done=true;this.check(r);}}
 check(r){if(r.done&&!r.blocked&&!r.finished&&r.chunks.every(c=>this.ctx.currentTime>=c.end-.001)){r.finished=true;this.onComplete(r.id);}}
 playedMs(id){const r=this.rows.get(id);if(!r)return 0;return Math.floor(r.chunks.reduce((n,c)=>n+Math.max(0,Math.min(c.end,this.ctx.currentTime)-c.start),0)*1000);}
 stop(id){let r=this.rows.get(id);if(!r){r={id,chunks:[],blocked:true};this.rows.set(id,r);return 0;}if(r.blocked)return r.stoppedMs??0;const ms=this.playedMs(id);r.blocked=true;r.stoppedMs=ms;for(const c of r.chunks){c.source.onended=null;try{c.source.stop()}catch{}c.source.disconnect();}return ms;}
 stopAll(){for(const id of this.rows.keys())this.stop(id);this.gain.disconnect();}
}
if(typeof module!=='undefined')module.exports={NativePlayback};

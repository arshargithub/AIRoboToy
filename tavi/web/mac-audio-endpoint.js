'use strict';
// Physical audio is owned here. Core generations/leases own conversational work.
// No microphone buffers are retained beyond the bounded transport queue.
class MacAudioEndpoint{
 constructor(bridge,onState,onError){
  this.bridge=bridge;this.onState=onState;this.onError=onError;this.serial=0;this.active=false;this.starting=false;this.stopping=null;
  this.queue=[];this.sending=false;this.stream=null;this.context=null;this.mic=null;this.node=null;this.input=null;this.sink=null;
  this.source=null;this.outputGain=null;this.playing=null;this.loading=null;this.latest=null;this.volume=.35;
  this.blocked=new Set();this.played=new Set();this.pendingSpeech=new Set();this.gate=new SpeechInterruptionGate(.65,2);
  this.prefetch=new ChunkAudioPrefetch();this.lastPacket=0;this.lastContact=0;this.playVersion=0;
  this.analyser=null;this.levelData=null;
 }
 notify(){this.onState({active:this.active,starting:this.starting,playing:!!this.source,loading:!!this.loading,state:this.latest});}
 async start(online,family={}){
  if(this.stopping)await this.stopping;
  if(this.active||this.starting)return;
  this.starting=true;const serial=++this.serial;this.latest=null;this.blocked.clear();this.played.clear();this.pendingSpeech.clear();this.notify();
  try{
   await this.bridge.micIntent(true);
   if(serial!==this.serial)return;
   const context=new AudioContext({sampleRate:16000});this.context=context;await context.resume();
   if(serial!==this.serial)return;
   if(context.sampleRate!==16000)throw Error('The Mac microphone did not provide the required format. Choose Try again.');
   await context.audioWorklet.addModule('/capture.js');if(serial!==this.serial)return;
   const mic=await navigator.mediaDevices.getUserMedia({audio:{channelCount:1,echoCancellation:true,noiseSuppression:true,autoGainControl:false},video:false});
   if(serial!==this.serial){mic.getTracks().forEach(t=>t.stop());return;}this.mic=mic;
   const result=await this.bridge.call('start',{online,protocol:1,endpoint_id:'mac',consent:'mac-local-speech-transactional-text-v1',adult:true,local_audio_only:true,retain_audio:false,
    family_voice:family.voice===true,family_memory:family.memory===true,family_only_audience:family.audience===true});
   if(serial!==this.serial){this.bridge.call('stop',{},result.stream_id).catch(()=>{});return;}
   this.stream=result.stream_id;this.latest=result.conversation;
   this.node=new AudioWorkletNode(context,'tavi-capture');this.input=context.createMediaStreamSource(mic);this.sink=context.createGain();this.sink.gain.value=0;
   this.input.connect(this.node);this.node.connect(this.sink);this.sink.connect(context.destination);
   this.active=true;this.starting=false;this.queue=[];this.lastPacket=this.lastContact=performance.now();
   this.node.port.onmessage=({data})=>{
    if(serial!==this.serial||!this.active)return;this.lastPacket=performance.now();
    if(data.sampleRate!==16000||!(data.pcm instanceof ArrayBuffer)||data.pcm.byteLength!==1024){this.fail(Error('Microphone format changed. Start again.'));return;}
    if(this.queue.length>=4){this.fail(Error('The Mac fell behind the microphone. Capture stopped; try again.'));return;}
    this.queue.push(data);this.pump(serial);
   };
   mic.getTracks().forEach(t=>t.onended=()=>this.fail(Error('Microphone disconnected. Reconnect it and start again.')));
   context.onstatechange=()=>{if(this.active&&context.state!=='running')this.fail(Error('Audio was suspended. Start again when the Mac is awake.'));};
   this.watch=setInterval(()=>{if(this.active&&(performance.now()-this.lastPacket>1500||performance.now()-this.lastContact>2000))this.fail(Error('Audio connection stopped. Reconnect, then start again.'));},250);
   this.notify();
  }catch(error){if(serial===this.serial)await this.fail(error);}
 }
 clearPlayback(block=true){
  this.playVersion++;this.prefetch.clear();
  const id=this.playing?.id||this.loading?.id;
  if(block&&id){this.blocked.add(id);while(this.blocked.size>80)this.blocked.delete(this.blocked.values().next().value);}
  if(this.source){this.source.onended=null;try{this.source.stop();}catch{}this.source.disconnect();this.source=null;}
  if(this.outputGain){this.outputGain.disconnect();this.outputGain=null;}
  if(this.analyser){this.analyser.disconnect();this.analyser=null;}this.levelData=null;
  this.playing=null;this.loading=null;return id;
 }
 stop(){
  if(this.stopping)return this.stopping;
  const stream=this.stream;this.serial++;this.active=false;this.starting=false;this.stream=null;this.queue=[];clearInterval(this.watch);this.clearPlayback();
  if(this.node){this.node.port.onmessage=null;this.node.disconnect();this.node=null;}if(this.input){this.input.disconnect();this.input=null;}if(this.sink){this.sink.disconnect();this.sink=null;}
  if(this.mic){this.mic.getTracks().forEach(t=>{t.onended=null;t.stop();});this.mic=null;}
  const context=this.context;this.context=null;if(context)context.onstatechange=null;
  this.latest=null;this.notify();
  this.stopping=(async()=>{
   if(context)await context.close().catch(()=>{});
   await this.bridge.micIntent(false).catch(()=>{});
   if(stream)await this.bridge.call('stop',{},stream).catch(()=>{});
  })().finally(()=>{this.stopping=null;this.notify();});
  return this.stopping;
 }
 async fail(error){await this.stop();this.onError(error.name==='NotAllowedError'?Error('Microphone access was not allowed. Enable Paprika in System Settings → Privacy & Security → Microphone, then try again.'):error);}
 async call(command,body={}){
  const serial=this.serial;
  const result=await this.bridge.call(command,body,this.stream);
  if(serial===this.serial&&this.active&&result.conversation)this.reconcile(result.conversation);
  return result;
 }
 async interrupt(utterance=null){
  const id=this.clearPlayback()||this.latest?.token?.response_id;this.notify();
  if(this.active&&id)await this.call('interrupt',{response_id:id,utterance});
 }
 async end(){this.clearPlayback();if(this.active)await this.call('end');}
 setVolume(value){this.volume=value;if(this.outputGain)this.outputGain.gain.value=value;}
 speechLevel(){
  if(!this.source||!this.analyser)return 0;
  const data=this.levelData||(this.levelData=new Uint8Array(256));this.analyser.getByteTimeDomainData(data);
  let sum=0;for(const value of data){const x=(value-128)/128;sum+=x*x;}
  return Math.min(1,Math.sqrt(sum/data.length)*9);
 }
 async pump(serial){
  if(this.sending)return;this.sending=true;
  try{
   while(this.active&&serial===this.serial&&this.queue.length){
    const packet=this.queue.shift();const result=await this.bridge.frame(new Uint8Array(packet.pcm),packet.sequence,this.stream);
    if(serial!==this.serial||!this.active)break;this.lastContact=performance.now();
    for(const e of result.events){
     if(e.type==='speech_started'&&!this.source)this.pendingSpeech.add(e.utterance);
     if(e.type==='recognition'&&e.final)this.pendingSpeech.delete(e.utterance);
    }
    if((this.source||this.playing)&&this.gate.accept(packet,result,this.context.sampleRate,this.context.currentTime))await this.interrupt(result.utterance);
    this.reconcile(result.conversation);
   }
  }catch(error){if(serial===this.serial)await this.fail(error);}
  finally{this.sending=false;if(this.active&&this.queue.length)this.pump(this.serial);}
 }
 reconcile(state){
  if(this.latest&&Number.isFinite(this.latest.revision)&&state.revision<this.latest.revision)return;
  this.latest=state;
  if(!state.lease_active){this.fail(Error('Listening session ended. Choose Start to listen again.'));return;}
  const id=state.token?.response_id;
  if(this.playing&&this.playing.id!==id)this.clearPlayback();
  if(this.loading&&this.loading.id!==id)this.clearPlayback();
  if(this.loading&&(state.pending_input||this.pendingSpeech.size))this.clearPlayback(false);
  const a=state.audio;
  if(this.active&&a&&!state.pending_input&&!this.pendingSpeech.size&&!this.blocked.has(a.id)&&!this.played.has(`${a.id}:${a.sequence}`)&&!this.source&&!this.loading)this.play(a);
  if(this.active&&this.source&&!state.pending_input&&!this.pendingSpeech.size&&state.prefetch_audio?.id===this.playing.id){
   const stream=this.stream,context=this.context;
   this.prefetch.offer(state.prefetch_audio,`${this.serial}:${stream}`,(audio)=>this.load(audio,context,stream));
  }else if(state.pending_input||this.pendingSpeech.size)this.prefetch.clear();
  this.notify();
 }
 async load(audio,context,stream){const bytes=await this.bridge.audio(audio.id,audio.sequence,stream);return context.decodeAudioData(new Uint8Array(bytes).buffer);}
 async play(audio){
  const serial=this.serial,version=++this.playVersion,context=this.context,stream=this.stream;this.loading=audio;this.notify();
  const valid=()=>serial===this.serial&&version===this.playVersion&&this.active&&!this.blocked.has(audio.id)&&this.latest?.token?.response_id===audio.id;
  try{
   let buffer=await this.prefetch.take(audio,`${serial}:${stream}`);if(!valid())return;
   if(!buffer)buffer=await this.load(audio,context,stream);if(!valid())return;
   const source=context.createBufferSource();source.buffer=buffer;this.outputGain=context.createGain();this.outputGain.gain.value=this.volume;
   source.connect(this.outputGain);
   if(context.createAnalyser){this.analyser=context.createAnalyser();this.analyser.fftSize=256;this.outputGain.connect(this.analyser);this.analyser.connect(context.destination);}
   else this.outputGain.connect(context.destination);
   this.source=source;this.playing=audio;this.loading=null;this.gate.reset(context.currentTime);
   source.onended=async()=>{
    if(serial!==this.serial||this.source!==source)return;
    source.disconnect();this.source=null;this.outputGain.disconnect();this.outputGain=null;this.playing=null;
    if(this.analyser){this.analyser.disconnect();this.analyser=null;}this.levelData=null;
    this.played.add(`${audio.id}:${audio.sequence}`);while(this.played.size>160)this.played.delete(this.played.values().next().value);
    try{await this.call('played',{response_id:audio.id,sequence:audio.sequence});}catch(error){if(serial===this.serial)this.fail(error);}
    this.notify();
   };
   source.start();this.notify();await this.call('started',{response_id:audio.id,sequence:audio.sequence});
  }catch(error){if(serial===this.serial&&version===this.playVersion)await this.fail(error);}
  finally{if(version===this.playVersion){this.loading=null;this.notify();}}
 }
}
if(typeof module!=='undefined')module.exports={MacAudioEndpoint};

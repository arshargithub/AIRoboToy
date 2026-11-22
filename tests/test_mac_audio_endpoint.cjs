const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),{test}=require('node:test');
const {SpeechInterruptionGate}=require('../tavi/web/interruption.js'),{ChunkAudioPrefetch}=require('../tavi/web/chunk-audio-prefetch.js');
const settle=()=>new Promise(resolve=>setImmediate(resolve));
function fixture({deferMic=false,deferAudio=false}={}){
 const calls=[],states=[],errors=[],timers=[];let resolveMic,resolveAudio,worklet,clock=0;
 const state={lease_active:true,revision:1,engagement:'idle',input:'wake_only',output:'silent',token:null,audio:null,pending_input:false};
 const track={stopped:0,stop(){this.stopped++;}};const mic={getTracks:()=>[track]};
 class Context{
  constructor(){this.sampleRate=16000;this.currentTime=0;this.state='running';this.destination={};this.processors=new Map();this.audioWorklet={addModule:async path=>{assert.equal(path,'/capture.js');vm.runInNewContext(fs.readFileSync('tavi/web/capture.js','utf8'),{AudioWorkletProcessor:class{constructor(){this.port={postMessage(){}};}},registerProcessor:(n,c)=>this.processors.set(n,c),Int16Array,sampleRate:16000,currentFrame:0});}};}
  async resume(){}async close(){this.state='closed';}createMediaStreamSource(){return{connect(){},disconnect(){}};}createGain(){return{gain:{value:0},connect(){},disconnect(){}};}
  createAnalyser(){return{connect(){},disconnect(){},getByteTimeDomainData(data){data.fill(144);}};}
  async decodeAudioData(){return{duration:1};}createBufferSource(){calls.push('source-created');return{connect(){},disconnect(){},start(){calls.push('source-started');},stop(){calls.push('source-stopped');}};}
 }
 const bridge={micIntent:async v=>calls.push(['intent',v]),call:async(command,body,stream)=>{calls.push([command,body,stream]);if(command==='start')return{stream_id:'lease',conversation:{...state}};return{conversation:{...state,revision:++state.revision}};},
  frame:async(pcm,sequence,stream)=>{assert(pcm instanceof Uint8Array);assert.equal(pcm.length,1024);calls.push(['frame',sequence,stream]);return{events:[],probability:0,conversation:{...state,revision:++state.revision}};},
  audio:async()=>deferAudio?new Promise(r=>resolveAudio=r):new Uint8Array(50)};
 const scope={SpeechInterruptionGate,ChunkAudioPrefetch,AudioContext:Context,AudioWorkletNode:class{constructor(c,n){assert(c.processors.has(n));this.processor=new(c.processors.get(n))();this.port={};this.processor.port.postMessage=data=>this.port.onmessage?.({data});worklet=this;}connect(){}disconnect(){}},
  navigator:{mediaDevices:{getUserMedia:async()=>{calls.push('getUserMedia');return deferMic?new Promise(r=>resolveMic=r):mic;}}},performance:{now:()=>clock},Uint8Array,ArrayBuffer,setInterval:fn=>{timers.push(fn);return timers.length;},clearInterval(){},setTimeout,clearTimeout,module:{exports:{}}};
 vm.runInNewContext(fs.readFileSync('tavi/web/mac-audio-endpoint.js','utf8'),scope);
 const endpoint=new scope.module.exports.MacAudioEndpoint(bridge,s=>states.push(s),e=>errors.push(e));
 return{endpoint,bridge,calls,states,errors,track,state,async resolveMic(){resolveMic(mic);await settle();},async resolveAudio(){resolveAudio(new Uint8Array(50));await settle();},emit(){const samples=new Float32Array(128).fill(.1);for(let i=0;i<4;i++)worklet.processor.process([[samples]]);},watchdog(){clock=2501;timers[0]();}};
}
test('construction never requests microphone; real registered worklet transports bounded PCM',async()=>{
 const t=fixture();assert.equal(t.calls.length,0);await t.endpoint.start(false);t.emit();await settle();assert(t.calls.some(c=>Array.isArray(c)&&c[0]==='frame'));await t.endpoint.stop();assert.equal(t.track.stopped,1);
});
test('permission resolved after mute is stopped and cannot start core capture',async()=>{
 const t=fixture({deferMic:true}),starting=t.endpoint.start(true);await settle();await t.endpoint.stop();await t.resolveMic();await starting;
 assert.equal(t.track.stopped,1);assert(!t.calls.some(c=>Array.isArray(c)&&c[0]==='start'));assert.equal(t.endpoint.active,false);
});
test('playback acknowledgement follows physical source end, never download',async()=>{
 const t=fixture();await t.endpoint.start(true);t.state.token={response_id:'reply'};t.endpoint.latest={...t.state};await t.endpoint.play({id:'reply',sequence:0});
 assert(t.calls.some(c=>Array.isArray(c)&&c[0]==='started'));assert(!t.calls.some(c=>Array.isArray(c)&&c[0]==='played'));
 t.endpoint.source.onended();await settle();assert(t.calls.some(c=>Array.isArray(c)&&c[0]==='played'));await t.endpoint.stop();
});
test('interrupt stops local source before telling core and never marks it played',async()=>{
 const t=fixture();await t.endpoint.start(true);t.state.token={response_id:'reply'};t.endpoint.latest={...t.state};await t.endpoint.play({id:'reply',sequence:0});await t.endpoint.interrupt(4);
 assert(t.calls.indexOf('source-stopped')<t.calls.findIndex(c=>Array.isArray(c)&&c[0]==='interrupt'));assert(!t.calls.some(c=>Array.isArray(c)&&c[0]==='played'));await t.endpoint.stop();
});
test('late audio fetch after mute cannot play or send receipts',async()=>{
 const t=fixture({deferAudio:true});await t.endpoint.start(true);t.state.token={response_id:'reply'};t.endpoint.latest={...t.state};const playback=t.endpoint.play({id:'reply',sequence:0});await settle();await t.endpoint.stop();await t.resolveAudio();await playback;
 assert(!t.calls.includes('source-created'));assert(!t.calls.some(c=>Array.isArray(c)&&['played','started'].includes(c[0])));
});
test('pending speech holds ready audio until transcription finishes',async()=>{
 const t=fixture();await t.endpoint.start(true);t.state.token={response_id:'reply'};t.state.audio={id:'reply',sequence:0};t.endpoint.pendingSpeech.add(1);t.endpoint.reconcile({...t.state,revision:2});await settle();assert(!t.calls.includes('source-created'));await t.endpoint.stop();
});
test('expired lease turns microphone off',async()=>{
 const t=fixture();await t.endpoint.start(false);t.endpoint.reconcile({...t.state,lease_active:false,revision:2});await settle();assert.equal(t.track.stopped,1);assert.equal(t.errors.length,1);
});
test('audio watchdog stops tracks and offers recovery without restarting',async()=>{
 const t=fixture();await t.endpoint.start(false);t.watchdog();await settle();assert.equal(t.track.stopped,1);assert.equal(t.endpoint.active,false);assert.equal(t.errors.length,1);assert.equal(t.calls.filter(c=>Array.isArray(c)&&c[0]==='start').length,1);
});
test('speech animation reads only active output level and releases its analyser on mute',async()=>{
 const t=fixture();assert.equal(t.endpoint.speechLevel(),0);await t.endpoint.start(true);t.state.token={response_id:'reply'};t.endpoint.latest={...t.state};await t.endpoint.play({id:'reply',sequence:0});
 assert(t.endpoint.speechLevel()>0);assert(t.endpoint.speechLevel()<=1);await t.endpoint.stop();assert.equal(t.endpoint.speechLevel(),0);assert.equal(t.endpoint.analyser,null);assert.equal(t.endpoint.levelData,null);
});
test('delayed permission intent after mute creates no audio context or capture',async()=>{
 const t=fixture();let resolve;t.bridge.micIntent=v=>v?new Promise(r=>resolve=r):Promise.resolve();
 const starting=t.endpoint.start(false);await settle();await t.endpoint.stop();resolve();await starting;
 assert.equal(t.endpoint.context,null);assert(!t.calls.includes('getUserMedia'));assert.equal(t.endpoint.active,false);
});
test('new start waits for previous cleanup and concurrent stops share it',async()=>{
 const t=fixture();await t.endpoint.start(false);let release;const call=t.bridge.call;
 t.bridge.call=(c,...args)=>c==='stop'?new Promise(r=>release=r):call(c,...args);
 const stopped=t.endpoint.stop(),again=t.endpoint.stop();assert.equal(stopped,again);assert.equal(t.track.stopped,1);
 await settle();const starting=t.endpoint.start(false);await settle();assert.equal(t.calls.filter(c=>Array.isArray(c)&&c[0]==='start').length,1);
 release({});await stopped;await starting;assert.equal(t.endpoint.active,true);t.bridge.call=call;await t.endpoint.stop();
});
test('suspend and device loss stop physical capture and playback without auto resume',async()=>{
 for(const cause of ['suspend','device','transport']){
  const t=fixture();await t.endpoint.start(false);t.state.token={response_id:'old'};t.endpoint.latest={...t.state};await t.endpoint.play({id:'old',sequence:0});
  if(cause==='suspend'){t.endpoint.context.state='suspended';t.endpoint.context.onstatechange();}
  else if(cause==='device')t.track.onended();
  else {t.bridge.frame=async()=>{throw Error('disposable service offline');};t.emit();}
  await settle();await settle();assert.equal(t.endpoint.active,false);assert.equal(t.endpoint.context,null);assert.equal(t.endpoint.source,null);
  assert.equal(t.track.stopped,1);assert.equal(t.errors.length,1);assert.equal(t.calls.filter(c=>Array.isArray(c)&&c[0]==='start').length,1);
 }
});
test('repeated lifecycle cleanup releases every fake audio context and leaves no pending work',async()=>{
 const t=fixture();for(let i=0;i<250;i++){
  await t.endpoint.start(false);await t.endpoint.stop();assert.equal(t.endpoint.context,null);assert.equal(t.endpoint.node,null);
  assert.equal(t.endpoint.stream,null);assert.equal(t.endpoint.source,null);assert.equal(t.endpoint.queue.length,0);assert.equal(t.endpoint.stopping,null);
 }
 assert.equal(t.track.stopped,250);assert.equal(t.errors.length,0);
});

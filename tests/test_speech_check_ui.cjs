const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),{webcrypto,createHash}=require('node:crypto');
const {SampleCollector}=require('../tavi/web/sample-collector.js');
const {SpeechCheckSession}=require('../tavi/web/speech-check-session.js');
function harness(){
 const els=new Map(),calls=[],timers=new Map(),tracks=[],sources=[];let timerId=0,node,download,seq=0;
 const schedule=(fn,ms)=>{timers.set(++timerId,{fn,ms});return timerId},cancel=i=>timers.delete(i);
 function el(id){if(!els.has(id))els.set(id,{value:'',textContent:'',hidden:false,disabled:false,dataset:{}});return els.get(id)}
 el('volume').value='.35';
 // Web Audio is simulated here. Fixed test bytes exercise the actual hash guard.
 const reference=Buffer.from('synthetic speech-check reference bytes');
 const protocol=JSON.parse(fs.readFileSync('tavi/web/speech-check-protocol.json','utf8'));
 protocol.reference_sha256=createHash('sha256').update(reference).digest('hex');
 const plan=Buffer.from(JSON.stringify(protocol));
 const sandbox={console,crypto:webcrypto,TextDecoder,Blob,ArrayBuffer,Uint8Array,btoa,SampleCollector,
  SpeechCheckSession:class extends SpeechCheckSession{constructor(options){super({...options,schedule,cancel})}},
  performance:{now:()=>1000},setTimeout:schedule,clearTimeout:cancel,setInterval(){},window:{addEventListener(){}},
  document:{getElementById:el,createElement:()=>({click(){}})},URL:{createObjectURL(blob){download=blob;return 'blob:test'},revokeObjectURL(){}},
  fetch:async path=>{calls.push(path);assert.ok(['/speech-check-protocol.json','/paprika-reference.wav'].includes(path),'recorder must never call an API');const b=path.includes('protocol')?plan:reference;return {ok:true,arrayBuffer:async()=>b.buffer.slice(b.byteOffset,b.byteOffset+b.byteLength)}},
  navigator:{mediaDevices:{getUserMedia:async()=>{const track={stops:0,stop(){this.stops++},getSettings:()=>({sampleRate:48000,echoCancellation:true})};tracks.push(track);return {getTracks:()=>[track],getAudioTracks:()=>[track]}}}},
  AudioContext:class{constructor(){this.sampleRate=16000;this.currentTime=1;this.state='running';this.audioWorklet={addModule:async()=>{}}}resume(){return Promise.resolve()}close(){this.state='closed';return Promise.resolve()}decodeAudioData(){return Promise.resolve({duration:12})}createMediaStreamSource(){return {connect(){},disconnect(){}}}createGain(){return {gain:{value:0},connect(){},disconnect(){}}}createBufferSource(){const source={connect(){},disconnect(){},start(){},stop(){}};sources.push(source);return source}},
  AudioWorkletNode:class{constructor(){this.port={};node=this}connect(){}disconnect(){}}};
 vm.createContext(sandbox);vm.runInContext(fs.readFileSync('tavi/web/speech-check.js','utf8'),sandbox);
 return {el,calls,tracks,sources,get download(){return download},async settle(){await new Promise(r=>setImmediate(r))},
  fire(ms){for(const [id,t]of [...timers])if(t.ms===ms){timers.delete(id);t.fn()}},
  frame(){node.port.onmessage?.({data:{sequence:seq,endFrame:16000+(++seq)*512,sampleRate:16000,pcm:new ArrayBuffer(1024)}})}};
}
(async()=>{
 const nativeLike={setTimeout(fn,ms){if(this?.plan)throw TypeError('Illegal invocation');return 1},clearTimeout(id){if(this?.plan)throw TypeError('Illegal invocation')}};
 vm.createContext(nativeLike);vm.runInContext(fs.readFileSync('tavi/web/speech-check-session.js','utf8'),nativeLike);
 vm.runInContext("const session=new SpeechCheckSession({plan:{read_ms:3,trials:[{}]},collector:{discard(){}},show(){},play(){},stopAudio(){},done(){}});session.start();session.finish();",nativeLike);
 const h=harness();for(let i=0;i<5;i++)await h.settle();assert.equal(h.tracks.length,0,'loading must not open the microphone');
 await h.el('start').onclick();assert.equal(h.tracks.length,1);assert.equal(h.el('session').dataset.phase,'read');
 for(let turn=0;turn<8;turn++){
  h.fire(3000);for(let i=0;i<64;i++)h.frame();
  assert.equal(h.el('session').dataset.phase,turn<6?'speak':'silent');
  for(let i=64;i<250;i++)h.frame();
 }
 await h.settle();assert.equal(h.tracks[0].stops,1);assert.equal(h.sources.length,4);assert.equal(h.el('download').disabled,false);
 h.el('download').onclick();const data=JSON.parse(await h.download.text());assert.equal(data.complete,true);assert.equal(data.clips.length,8);
 assert.equal(Buffer.from(data.clips[0].pcm_base64,'base64').length,250*1024);assert.match(data.consent,/Explicit/);
 assert.equal(data.clips[0].cue_context_frame-data.clips[0].capture_start_frame,64*512);
 const partial=harness();for(let i=0;i<5;i++)await partial.settle();await partial.el('start').onclick();partial.fire(3000);partial.frame();partial.el('stop').onclick();await partial.settle();partial.fire(3000);
 assert.equal(partial.tracks[0].stops,1);assert.equal(partial.el('download').disabled,true,'unfinished audio must be discarded');
 console.log('Speech check: explicit start, eight bounded clips, exact cues, local-only network, reference control, automatic mute and partial cleanup passed');
})().catch(e=>{console.error(e);process.exitCode=1});

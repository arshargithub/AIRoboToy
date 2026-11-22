const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),{webcrypto}=require('node:crypto');
const {SampleCollector}=require('../tavi/web/sample-collector.js'),{SpeechCheckSession}=require('../tavi/web/speech-check-session.js');
function harness({latePermission=false,ignoreSettings=false}={}){
 const els=new Map(),timers=new Map(),tracks=[],requests=[],blobs=[];let timerId=0,node,seq=0,download,resolvePermission;
 const schedule=(fn,ms)=>{timers.set(++timerId,{fn,ms});return timerId},cancel=id=>timers.delete(id);
 function make(tag='div'){return {tag,children:[],value:'',textContent:'',dataset:{},hidden:false,disabled:false,attributes:{},append(...x){this.children.push(...x)},replaceChildren(...x){this.children=x},setAttribute(k,v){this.attributes[k]=v},pause(){this.paused=true},click(){}}}
 function el(id){if(!els.has(id))els.set(id,make());return els.get(id)}
 function audios(root=el('clips')){return root.children.flatMap(c=>[...(c.tag==='audio'?[c]:[]),...audios(c)])}
 function stream(options){const track={stops:0,stop(){this.stops++},getSettings:()=>({sampleRate:48000,...(ignoreSettings?{echoCancellation:true,noiseSuppression:true,autoGainControl:false}:options.audio)})};tracks.push(track);return {getTracks:()=>[track],getAudioTracks:()=>[track]}}
 const sandbox={console,crypto:webcrypto,Blob,ArrayBuffer,Uint8Array,DataView,btoa,SampleCollector,
  SpeechCheckSession:class extends SpeechCheckSession{constructor(options){super({...options,schedule,cancel})}},
  performance:{now:()=>1000},setTimeout:schedule,clearTimeout:cancel,setInterval(){},window:{addEventListener(){}},
  document:{getElementById:el,createElement:tag=>make(tag),querySelectorAll:()=>audios()},fetch(){throw Error('No network API is permitted')},
  URL:{createObjectURL(blob){blobs.push(blob);if(blob.type==='application/json')download=blob;return 'blob:'+blobs.length},revokeObjectURL(){}},
  navigator:{mediaDevices:{getUserMedia(options){requests.push(options);return latePermission?new Promise(resolve=>resolvePermission=()=>resolve(stream(options))):Promise.resolve(stream(options))}}},
  AudioContext:class{constructor(){this.sampleRate=16000;this.state='running';this.audioWorklet={addModule:async()=>{}}}resume(){return Promise.resolve()}close(){this.state='closed';return Promise.resolve()}createMediaStreamSource(){return {connect(){},disconnect(){}}}createGain(){return {gain:{value:0},connect(){},disconnect(){}}}},
  AudioWorkletNode:class{constructor(){this.port={};node=this}connect(){}disconnect(){}}};
 vm.createContext(sandbox);vm.runInContext(fs.readFileSync('tavi/web/mic-check.js','utf8'),sandbox);
 return {el,tracks,requests,blobs,get download(){return download},resolvePermission(){resolvePermission()},async settle(){await new Promise(r=>setImmediate(r))},
  fire(ms){for(const [id,t]of [...timers])if(t.ms===ms){timers.delete(id);t.fn()}},
  frame(){const pcm=new Int16Array(512);pcm.fill(100);node.port.onmessage?.({data:{sequence:seq,endFrame:16000+(++seq)*512,sampleRate:16000,pcm:pcm.buffer}})},
  rate(clip,value){el('clips').children[clip].children[2].children[value].onclick()}};
}
(async()=>{
 const h=harness();assert.equal(h.requests.length,0);await h.el('start').onclick();
 for(let round=0;round<3;round++){
  for(let clip=0;clip<2;clip++){h.fire(3000);for(let i=0;i<64;i++)h.frame();assert.equal(h.el('recording').dataset.phase,'speak');for(let i=64;i<250;i++)h.frame()}
  await h.settle();assert.equal(h.tracks[round].stops,1,'close the microphone before playback/review');assert.equal(h.el('continue').disabled,true);
  h.rate(0,round===0?1:0);assert.equal(h.el('continue').disabled,true);h.rate(1,0);assert.equal(h.el('continue').disabled,false);
  await h.el('continue').onclick();
 }
 assert.equal(h.el('done').hidden,false);h.el('download').onclick();const data=JSON.parse(await h.download.text());
 assert.equal(data.complete,true);assert.equal(data.clips.length,6);assert.equal(data.clips[0].quality_rating,'impaired');assert.equal(data.clips[1].quality_rating,'clear');
 assert.deepEqual(h.requests.map(x=>[x.audio.echoCancellation,x.audio.noiseSuppression,x.audio.autoGainControl]),[[true,true,false],[true,false,false],[false,false,false]]);
 assert.equal(data.rounds.length,3);assert.ok(data.rounds.every(r=>r.settings_verified));
 assert.equal(Buffer.from(data.clips[0].pcm_base64,'base64').readInt16LE(0),100,'download must preserve original PCM');
 const view=new DataView(await h.blobs[0].arrayBuffer());assert.equal(view.getUint32(24,true),16000);assert.equal(view.getInt16(44,true),800,'listening gain must not alter stored recordings');
 assert.equal(data.clips[0].cue_context_frame-data.clips[0].capture_start_frame,64*512);
 const ignored=harness({ignoreSettings:true});await ignored.el('start').onclick();
 for(let clip=0;clip<2;clip++){ignored.fire(3000);for(let i=0;i<250;i++)ignored.frame()}
 await ignored.settle();ignored.rate(0,0);ignored.rate(1,0);await ignored.el('continue').onclick();ignored.el('stop').onclick();await ignored.settle();ignored.el('save-partial').onclick();ignored.el('download').onclick();
 const partial=JSON.parse(await ignored.download.text());assert.equal(partial.complete,false);assert.equal(partial.clips.length,2);assert.equal(partial.rounds[1].settings_verified,false,'requested settings must not masquerade as actual settings');
 const late=harness({latePermission:true});const pending=late.el('start').onclick();await late.settle();late.el('stop').onclick();await late.settle();late.resolvePermission();await pending;assert.equal(late.tracks[0].stops,1,'late permission cannot leave capture running after stop');
 console.log('Microphone check: three profiles, first/later pairs, local-only review, required ratings, original PCM, verified settings, partial saves and late permission passed');
})().catch(e=>{console.error(e);process.exitCode=1});

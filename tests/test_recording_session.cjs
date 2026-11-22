// Synthetic browser model: no real microphone, audio upload or user voice.
const assert=require('node:assert/strict');
const fs=require('node:fs');const vm=require('node:vm');const {webcrypto}=require('node:crypto');
const planBytes=fs.readFileSync('tavi/web/name-comparison-protocol.json');
const {SampleCollector}=require('../tavi/web/sample-collector.js');
function harness({delayedPermission=false,comparison=true}={}) {
 let now=0,next=0,node,stops=0,requests=0,download,permissionResolve;
 const jobs=new Map(),elements=new Map();
 const el=id=>{if(!elements.has(id))elements.set(id,{value:'',checked:false,textContent:'',dataset:{},style:{},hidden:false,disabled:false,click(){},setAttribute(){}});return elements.get(id)};
 const schedule=(fn,ms,repeat)=>{const id=++next;jobs.set(id,{fn,at:now+ms,repeat});return id};
 const stream={getTracks:()=>[track],getAudioTracks:()=>[track]},track={stop(){stops++},getSettings:()=>({sampleRate:16000})};
 const sandbox={SampleCollector,console,Uint8Array,ArrayBuffer,TextDecoder,Blob,crypto:webcrypto,
  performance:{now:()=>now},btoa:s=>Buffer.from(s,'binary').toString('base64'),
  URL:{createObjectURL(blob){download=blob;return 'blob:synthetic'},revokeObjectURL(){}},
  document:{body:{dataset:comparison?{protocol:'/name-comparison-protocol.json'}:{}},getElementById:el,querySelectorAll:()=>[],createElement:()=>({click(){}})},
  window:{addEventListener(){}},setTimeout:(fn,ms)=>schedule(fn,ms),clearTimeout:id=>jobs.delete(id),
  setInterval:(fn,ms)=>schedule(fn,ms,ms),
  fetch:async url=>{assert.equal(url,'/name-comparison-protocol.json');return {ok:true,arrayBuffer:async()=>planBytes.buffer.slice(planBytes.byteOffset,planBytes.byteOffset+planBytes.byteLength)}},
  AudioContext:class {constructor(){this.sampleRate=16000;this.state='running';this.audioWorklet={addModule:async()=>{}}}resume(){return Promise.resolve()}close(){this.state='closed';return Promise.resolve()}createMediaStreamSource(){return {connect(){},disconnect(){}}}createGain(){return {gain:{value:0},connect(){},disconnect(){}}}},
  AudioWorkletNode:class{constructor(){this.port={};node=this}connect(){}disconnect(){}},
  navigator:{mediaDevices:{getUserMedia(){requests++;return delayedPermission?new Promise(resolve=>permissionResolve=resolve):Promise.resolve(stream)}}}};
 vm.createContext(sandbox);vm.runInContext(fs.readFileSync('tavi/web/wake-samples.js','utf8'),sandbox);
 let sequence=0;
 schedule(()=>{if(node?.port.onmessage)node.port.onmessage({data:{sequence:sequence++,sampleRate:16000,pcm:new ArrayBuffer(1024)}})},32,32);
 return {el,async settle(){await new Promise(resolve=>setTimeout(resolve,10));},advance(ms){const target=now+ms;let turns=0;while(true){let chosen;for(const [id,j]of jobs)if(j.at<=target&&(!chosen||j.at<chosen[1].at))chosen=[id,j];if(!chosen)break;assert.ok(++turns<100000);const [id,j]=chosen;now=j.at;jobs.delete(id);if(j.repeat)jobs.set(id,{...j,at:now+j.repeat});j.fn()}now=target},
  authorize(){el('speaker').value='Synthetic test';el('consent').checked=true},
  get stops(){return stops},get requests(){return requests},get download(){return download},resolvePermission(){permissionResolve(stream)}};
}
(async()=>{
 const h=harness();await h.settle();assert.equal(h.requests,0);
 h.el('practice').onclick();h.advance(3000);assert.equal(h.el('phase').textContent,'Your turn!');assert.equal(h.requests,0,'practice never opens microphone');h.advance(4000);assert.equal(h.el('setup').hidden,false);
 await h.el('start').onclick();assert.equal(h.requests,0,'speaker and agreement required');
 h.authorize();await h.el('start').onclick();assert.equal(h.el('phrase').textContent,'Tavi');assert.equal(h.el('phase').textContent,'Read this first');
 h.advance(3000);assert.equal(h.el('phase').textContent,'Your turn!');
 h.advance(500);h.el('retry').onclick();h.advance(3000);assert.equal(h.el('phase').textContent,'Your turn!');
 h.advance(4*1000+15*7000);await h.settle();assert.equal(h.el('break').hidden,false);assert.equal(h.stops,1,'halfway closes microphone');assert.match(h.el('break-message').textContent,/16 of 32/);
 await h.el('resume').onclick();h.advance(16*7000);await h.settle();assert.equal(h.el('done').hidden,false);assert.equal(h.stops,2);
 h.el('download').onclick();const data=JSON.parse(await h.download.text());assert.equal(data.complete,true);assert.equal(data.clips.length,32);assert.equal(data.attempts['0'],2);assert.equal(data.protocol_id,'tavi-paprika-whisper-v1');
 assert.deepEqual(data.clips.map(c=>c.phrase),JSON.parse(planBytes).trials.map(t=>t.phrase));
 const paused=harness();await paused.settle();paused.authorize();await paused.el('start').onclick();paused.advance(3500);paused.el('pause').onclick();await paused.settle();assert.equal(paused.stops,1);assert.match(paused.el('break-message').textContent,/0 of 32/);await paused.el('resume').onclick();assert.equal(paused.el('phrase').textContent,'Tavi');paused.el('stop').onclick();
 const late=harness({delayedPermission:true});await late.settle();late.authorize();const pending=late.el('start').onclick();await late.settle();late.el('stop').onclick();late.resolvePermission();await pending;assert.equal(late.stops,1,'late permission stream closed after stop');late.advance(5000);assert.notEqual(late.el('phase').textContent,'Your turn!');
 const partial=harness();await partial.settle();partial.authorize();await partial.el('start').onclick();partial.advance(7000);partial.el('stop').onclick();partial.el('download').onclick();const unfinished=JSON.parse(await partial.download.text());assert.equal(unfinished.complete,false);assert.equal(unfinished.clips.length,1);assert.equal(partial.stops,1);
 const legacy=harness({comparison:false});legacy.authorize();await legacy.el('start').onclick();legacy.advance(3000+3200+19*5000);await legacy.settle();legacy.el('download').onclick();const old=JSON.parse(await legacy.download.text());assert.equal(old.complete,true);assert.equal(old.clips.length,20);assert.equal(old.kind,'tavi_private_wake_samples');
 console.log('Guided recording lifecycle, redo, halfway pause/resume, cancelled permission and legacy collection passed');
})().catch(e=>{console.error(e);process.exitCode=1});

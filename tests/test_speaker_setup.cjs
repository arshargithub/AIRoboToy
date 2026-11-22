const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict'),{webcrypto}=require('node:crypto');
const code=fs.readFileSync('tavi/web/speaker-setup.js','utf8');
function setup({loseFirstUseAck=false}={}){
 const nodes={},timers=[],counts={requested:0,stopped:0,closed:0,uploads:0,used:0,recovered:0};let resolveMic;const savedHashes=[];
 const get=id=>nodes[id]??(nodes[id]={value:'',checked:false,hidden:false,dataset:{},disabled:false,pause(){},removeAttribute(){}});
 class Context{constructor(){this.sampleRate=16000;this.audioWorklet={addModule:async()=>{}};}async resume(){}async close(){counts.closed++;}createMediaStreamSource(){return{connect(){},disconnect(){}};}createGain(){return{gain:{value:0},connect(){},disconnect(){}};}}
 const env={document:{getElementById:get,querySelector:s=>s.includes('processing')?{value:'local-only'}:s.includes('retention')?{value:'vectors'}:null,querySelectorAll:()=>[]},window:{addEventListener(){}},sessionStorage:{getItem:()=>null,setItem(){},removeItem(){}},AudioContext:Context,AudioWorkletNode:class{constructor(){this.port={};}connect(){}disconnect(){}},navigator:{mediaDevices:{getUserMedia(){counts.requested++;return new Promise(r=>resolveMic=r);}}},URL:{createObjectURL:()=> 'blob:test',revokeObjectURL(){}},Blob,DataView,Uint8Array,ArrayBuffer,crypto:webcrypto,AbortSignal,setTimeout:fn=>{timers.push(fn);return timers.length;},clearTimeout(){},fetch:async(path,options)=>{
  let data={available:true,message:'Ready'};
  if(path==='/api/preview'){counts.uploads++;data={clear_voice:true,pcm_sha256:Buffer.from(await webcrypto.subtle.digest('SHA-256',options.body)).toString('hex'),quality:{voiced_seconds:4}};}
  if(path==='/api/use'){counts.used++;savedHashes.push(JSON.parse(options.body).sha);data={person_id:'adultone',name:'Adult One',saved_clips:counts.used,clip_hashes:savedHashes,phrase:'Next phrase',complete:false};if(loseFirstUseAck&&counts.used===1)return{ok:false,status:503,json:async()=>({error:'Simulated lost save acknowledgement'})};}
  if(path==='/api/state'){counts.recovered++;data={person_id:'adultone',name:'Adult One',saved_clips:counts.used,clip_hashes:savedHashes,phrase:'Next phrase',complete:false};}
  if(path==='/api/finish')data={saved_clips:6,complete:true};
  return{ok:true,json:async()=>data};
 }};vm.createContext(env);vm.runInContext(code,env);
 const stream=()=>({getTracks:()=>[{stop(){counts.stopped++;},onended:null}]});
 return{env,nodes,get,timers,counts,resolve(){resolveMic(stream());},eval:s=>vm.runInContext(s,env)};
}
const settle=()=>new Promise(resolve=>setImmediate(resolve));
(async()=>{
 let t=setup();await settle();await t.get('begin').onclick();assert.equal(t.counts.requested,0);assert(t.get('error').textContent.includes('Choose the adult'));
 t.eval("state={saved_clips:0,phrase:'Read this phrase'};phase='phrase';busy=false");let recording=t.eval('record()');await settle();assert.equal(t.counts.requested,1);await t.eval('finishRecording()');t.resolve();await recording;assert.equal(t.counts.stopped,1);assert.equal(t.eval('recording'),false);assert.equal(t.eval('phase'),'phrase');
 t=setup();await settle();t.eval("state={saved_clips:0,phrase:'Read this phrase'};phase='phrase';busy=false");recording=t.eval('record()');await settle();t.resolve();await settle();assert(t.timers.length);await t.eval('finishRecording()');t.timers.shift()();await recording;assert.equal(t.counts.stopped,1);assert.equal(t.eval('recording'),false);
 t=setup({loseFirstUseAck:true});await settle();t.eval("session='test';state={saved_clips:0,phrase:'Read this phrase'};phase='phrase';busy=false");
 for(let clip=0;clip<6;clip++){
  recording=t.eval('record()');await settle();t.resolve();await settle();t.timers.shift()();await settle();t.timers.shift()();await recording;
  assert.equal(t.eval('phase'),'recording');assert.equal(t.get('phrase').textContent.length>0,true);
  for(let n=0;n<250;n++)t.eval(`node.port.onmessage({data:{sampleRate:16000,pcm:new ArrayBuffer(1024),sequence:${n}}})`);
  for(let n=0;n<100&&t.eval('phase')!=='preview';n++)await new Promise(resolve=>setTimeout(resolve,5));
  assert.equal(t.eval('phase'),'preview');assert.equal(t.eval('mic'),null);assert.equal(t.get('use').hidden,false);await t.get('use').onclick();t.timers.splice(0);
 }
 assert.equal(t.eval('phase'),'finish');t.get('note').value='QA only';await t.get('finish').onclick();assert.equal(t.eval('phase'),'done');assert.equal(t.counts.requested,6);assert.equal(t.counts.stopped,6);assert.equal(t.counts.uploads,6);assert.equal(t.counts.used,6);assert.equal(t.counts.recovered,1);
 console.log('Adult enrollment UI: consent guard, pending-permission/countdown cancellation,6fullrecord/review/use steps, automatic microphone stop, hash binding and final candidate save pass. No real microphone or network used.');
})().catch(e=>{console.error(e);process.exitCode=1;});

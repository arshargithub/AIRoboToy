const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),{webcrypto}=require('node:crypto');
const prompts=JSON.parse(fs.readFileSync('experiments/speaker-id/family-prompts-v1.json')).prompts;
const code=fs.readFileSync('tavi/web/family-capture.js','utf8');
const settle=()=>new Promise(resolve=>setImmediate(resolve));
function setup({person='childone',outcomes=[],lostAck=false,technical=false,storageFail=false}={}){
 const nodes={},timers=new Map(),stored={},listeners={},counts={mic:0,stopped:0,raw:0,begin:0,state:0,played:0},calls=[];let timerId=0,resolveMic,failed=false;
 const state={person_id:person,name:{childone:'Child One',childtwo:'Child Two',adulttwo:'Adult Two'}[person],child:person!=='adulttwo',retain_audio:false,attempts:[],eligible:0,kept:0,target:6,total:0,segment_end:6,sitting_start:0,paused:false,reviewed:false,next_prompt:prompts[0],complete:false,profile_saved:false};
 const copy=()=>JSON.parse(JSON.stringify(state));
 class Node{constructor(){this.hidden=false;this.disabled=false;this.checked=false;this.textContent='';this.value='';this.dataset={};this.children=[];}append(...n){this.children.push(...n);}replaceChildren(...n){this.children=[...n];}setAttribute(k,v){this[k]=v;}removeAttribute(k){delete this[k];}pause(){counts.promptPlaying=false;}async play(){counts.played++;counts.promptPlaying=true;}}
 const get=id=>nodes[id]??(nodes[id]=new Node());
 const storage={fail:storageFail,getItem:k=>stored[k]||null,setItem(k,v){if(this.fail)throw Error('storage blocked');stored[k]=v;}};
 class Context{constructor(){this.sampleRate=16000;this.processors=new Map();this.audioWorklet={addModule:async path=>{assert.equal(path,'/capture.js');const scope={AudioWorkletProcessor:class{constructor(){this.port={postMessage(){}};}},registerProcessor:(name,processor)=>this.processors.set(name,processor),Int16Array,sampleRate:16000,currentFrame:0};vm.runInNewContext(fs.readFileSync('tavi/web/capture.js','utf8'),scope);}};}async resume(){}async close(){}createMediaStreamSource(){return{connect(){},disconnect(){}};}createGain(){return{gain:{value:0},connect(){},disconnect(){}};}}
 const env={document:{body:{dataset:{person}},getElementById:get,createElement:()=>new Node(),querySelector:s=>s.includes('processing')?{value:'local-only'}:s.includes('retention')?{value:'vectors'}:null,querySelectorAll:()=>[]},window:{addEventListener:(name,fn)=>listeners[name]=fn},localStorage:storage,crypto:webcrypto,AudioContext:Context,
  AudioWorkletNode:class{constructor(context,name){assert(context.processors.has(name),`Unregistered audio processor: ${name}`);this.processor=new(context.processors.get(name))();this.port={};this.processor.port.postMessage=data=>this.port.onmessage?.({data});env.lastNode=this;}connect(){}disconnect(){}},navigator:{mediaDevices:{getUserMedia(){assert.equal(counts.promptPlaying,false,'Prompt playback must stop before microphone setup');counts.mic++;return new Promise(resolve=>resolveMic=resolve);}}},
  setTimeout:fn=>{timers.set(++timerId,fn);return timerId;},clearTimeout:id=>timers.delete(id),ArrayBuffer,Uint8Array,DataView,Blob,URL:{createObjectURL:()=> 'blob:local-test',revokeObjectURL(){}},AbortSignal,
  fetch:async(path,options={})=>{
   calls.push({path,options});const reply=(data,ok=true,status=200)=>({ok,status,json:async()=>data,blob:async()=>new Blob(['test'])});
   if(path.startsWith('/api/setup'))return reply({...copy(),available:true,message:'Ready',consent:'supervised-family-local-voice-v1',prompts,cloud:false,recognition_enabled:false});
   if(path==='/api/begin'){counts.begin++;const b=JSON.parse(options.body);assert.equal(b.person_id,person);assert.equal(b.supervised,person!=='adulttwo');assert.equal(b.own_voice,person==='adulttwo');state.paused=false;return reply({session:'controlled-session-'+person,...copy()});}
   if(path==='/api/state'){counts.state++;return reply(copy());}
   if(path==='/api/attempt'){
    counts.raw++;assert.equal(counts.stopped,counts.mic,'Microphone must stop before local check');assert.equal(options.headers['X-Person-ID'],person);
    if(technical&&!failed){failed=true;return reply({error:'Controlled local error'},false,503);}
    const id=options.headers['X-Attempt-ID'],sha=Buffer.from(await webcrypto.subtle.digest('SHA-256',options.body)).toString('hex');
    if(!state.attempts.some(a=>a.id===id)){
     const n=state.total,outcome=outcomes[n]||'clear';state.attempts.push({id,prompt_id:prompts[n].id,number:n+1,pcm_sha256:sha,outcome,review:'pending'});state.total++;state.eligible+=outcome==='clear';state.next_prompt=prompts[state.total];state.reviewed=false;
    }
    if(lostAck&&!failed){failed=true;return reply({error:'Controlled lost acknowledgement'},false,503);}return reply(copy());
   }
   if(path==='/api/review'){const b=JSON.parse(options.body);assert.equal(b.attested,true);for(const a of state.attempts)if(a.outcome==='clear'&&a.review!=='exclude')a.review=b.choices[a.id]==='keep'?'keep':'exclude';state.kept=state.attempts.filter(a=>a.review==='keep').length;state.reviewed=true;return reply(copy());}
   if(path==='/api/more'){state.segment_end=Math.min(12,state.total+Math.max(2,6-state.kept));state.reviewed=false;return reply(copy());}
   if(path==='/api/pause'){state.paused=true;return reply(copy());}
   if(path==='/api/finish'){assert(state.kept>=6);state.complete=true;state.profile_saved=true;return reply(copy());}
   if(path==='/api/skip'){const b=JSON.parse(options.body);state.attempts.push({id:b.id,prompt_id:b.prompt_id,number:++state.total,outcome:'interrupted',review:'exclude',pcm_sha256:b.sha});state.next_prompt=prompts[state.total];return reply(copy());}
   throw Error('Unexpected transport '+path);
  }};
 vm.createContext(env);vm.runInContext(code,env);
 return{env,get,state,counts,calls,storage,emit:name=>listeners[name]?.({persisted:true}),async consent(){await settle();for(const id of ['adult','willing','alone'])get(id).checked=true;await get('begin').onclick();},resolve(){resolveMic({getTracks:()=>[{stop(){counts.stopped++;},onended:null}],getAudioTracks:()=>[{getSettings:()=>({sampleRate:48000,echoCancellation:true,deviceId:'must-not-save'})}]});},tick(){const [id,fn]=timers.entries().next().value||[];assert(fn);timers.delete(id);fn();},frame(seq,n){const samples=new Float32Array(128).fill((n+1)/100);for(let i=0;i<4;i++)assert.equal(env.lastNode.processor.process([[samples]]),true);}};
}
async function record(t,n){const result=t.get('record').onclick();await settle();t.resolve();await settle();t.tick();await settle();t.tick();await result;assert.equal(t.get('card').dataset.phase,'recording');for(let frame=0;frame<250;frame++)t.frame(frame,n);for(let i=0;i<200&&!['celebrate','recover'].includes(t.get('card').dataset.phase);i++)await new Promise(resolve=>setTimeout(resolve,5));}
(async()=>{
 let checks=0;
 for(const person of ['childone','childtwo','adulttwo']){
  const t=setup({person,lostAck:person==='childone'});await settle();await t.get('begin').onclick();assert.equal(t.counts.begin,0);assert.equal(t.counts.mic,0);
  await t.consent();assert.equal(t.get('card').dataset.phase,'practice');assert.equal(t.counts.mic,0);await t.get('hear').onclick();t.get('record').onclick();assert.equal(t.counts.promptPlaying,false);await t.get('hear').onclick();
  for(let n=0;n<6;n++){await record(t,n);assert.equal(t.get('card').dataset.phase,'celebrate');assert.equal(t.get('question').textContent,prompts[n].question);t.get('next').onclick();}
  if(person!=='adulttwo'){assert.equal(t.get('card').dataset.phase,'child_done');t.get('open-review').onclick();}
  assert.equal(t.get('card').dataset.phase,'review');await t.get('approve').onclick();assert.equal(t.get('card').dataset.phase,'review');t.get('attested').checked=true;await t.get('approve').onclick();assert.equal(t.get('card').dataset.phase,'summary');await t.get('finish').onclick();assert.equal(t.get('card').dataset.phase,'done');assert.equal(t.counts.mic,6);assert.equal(t.counts.stopped,6);assert.equal(t.counts.raw,6);assert(!JSON.stringify(t.calls).includes('must-not-save'));checks++;
 }
 let t=setup({outcomes:['clear','short','clear','quiet','clear','clear']});await t.consent();t.get('record').onclick();for(let n=0;n<6;n++){await record(t,n);t.get('next').onclick();}t.get('open-review').onclick();t.get('attested').checked=true;await t.get('approve').onclick();assert.equal(t.state.kept,4);assert.equal(t.get('more').hidden,false);await t.get('more').onclick();for(let n=6;n<8;n++){await record(t,n);t.get('next').onclick();}t.get('open-review').onclick();t.get('attested').checked=true;await t.get('approve').onclick();assert.equal(t.state.kept,6);checks++;
 t=setup({technical:true});await t.consent();t.get('record').onclick();await record(t,0);assert.equal(t.get('card').dataset.phase,'recover');assert.equal(t.get('retry').hidden,false);await t.get('retry').onclick();assert.equal(t.get('card').dataset.phase,'celebrate');assert.equal(t.counts.mic,1);assert.equal(t.counts.raw,2);checks++;
 t=setup();await t.consent();t.get('record').onclick();let recording=t.get('record').onclick();await settle();await t.get('pause').onclick();t.resolve();await recording;assert.equal(t.get('card').dataset.phase,'paused');assert.equal(t.counts.stopped,1);assert.equal(t.counts.raw,0);checks++;
 t=setup({storageFail:true});await t.consent();assert.equal(t.get('card').dataset.phase,'storage');assert.equal(t.counts.mic,0);t.storage.fail=false;t.get('retry-storage').onclick();assert.equal(t.get('card').dataset.phase,'practice');checks++;
 t=setup();await t.consent();t.get('record').onclick();await record(t,0);t.emit('pagehide');await t.emit('pageshow');assert.equal(t.get('card').dataset.phase,'setup');assert.equal(t.get('adult').checked,false);assert.equal(t.state.total,1);assert.equal(t.counts.mic,1);checks++;
 console.log(`Family actual UI: ${checks} flows pass: three named consent/mic-off/full8second-auto-stop/batch-review/save paths, lost ACK, six-plus-two fresh questions, technical retry without new speech, pending-permission cancellation and storage failure. No real microphone/network/model used.`);
})().catch(error=>{console.error(error);process.exitCode=1;});

const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const {MacCheckGuide}=require('../tavi/web/mac-check-guide.js');
const {companionState}=require('../tavi/web/companion-state.js');
const settle=()=>new Promise(r=>setImmediate(r));
function fixture(){
 const nodes=new Map(),radios=['online','offline'].map(value=>({value,checked:false})),saved=[],calls=[],polls=[];let endpoint;
 const get=id=>{if(!nodes.has(id))nodes.set(id,{textContent:'',hidden:false,disabled:false,checked:false,value:'',dataset:{}});return nodes.get(id);};
 const bridge={status:async()=>({prerequisites:{ready:true,drive:true,local_files:true,cloud_key:true},spent_or_reserved_usd:20.49657}),saveReview:async r=>{saved.push(r);return{saved:true};},onPause(){},onVisibility(){}};
 class Endpoint{
  constructor(b,render,error){this.active=false;this.starting=false;this.pendingSpeech=new Set();this.render=render;this.error=error;endpoint=this;}
  async start(online,family){calls.push(['start',online,family]);this.active=true;this.render({active:true,starting:false,state:null});}
  async stop(){calls.push(['stop']);this.active=false;this.render({active:false,starting:false,state:null});}
  setVolume(){}async interrupt(){}async end(){}
  emit(id,completed=null,playing=false,extra={}){this.render({active:true,playing,loading:false,state:{accepted_response_id:id,completed_response_id:completed,engagement:'active',output:'silent',heard:'Controlled request',reply:'Controlled reply',spent_or_reserved_usd:20.49657,...extra}});}
 }
 const scope={document:{body:{dataset:{}},getElementById:get,querySelector:()=>radios.find(r=>r.checked)||null,querySelectorAll:()=>radios},window:{paprika:bridge,addEventListener(){}},MacAudioEndpoint:Endpoint,MacCheckGuide,companionState,setInterval(fn){polls.push(fn);}};
 vm.runInNewContext(fs.readFileSync('tavi/web/companion.js','utf8'),scope);
 return{get,radios,saved,calls,bridge,async poll(){await polls[0]();},endpoint:()=>endpoint,async choices(){await settle();get('adult').checked=true;get('adult').onchange();radios[0].checked=true;radios[0].onchange();get('check-adult').checked=true;get('check-adult').onchange();}};
}
test('actual app UI requires explicit processing/supervision and extra adult-check choice',async()=>{
 const t=fixture();await settle();assert.equal(t.get('start').disabled,true);assert.equal(t.calls.length,0);
 t.get('adult').checked=true;t.get('adult').onchange();assert.equal(t.get('start').disabled,true);
 t.radios[0].checked=true;t.radios[0].onchange();assert.equal(t.get('start').disabled,false);assert.equal(t.get('check-start').disabled,true);
 t.get('check-adult').checked=true;t.get('check-adult').onchange();assert.equal(t.get('check-start').disabled,false);
});
test('actual app guide completes, stops mic and saves explicit feedback without transcripts by default',async()=>{
 const t=fixture();await t.choices();await t.get('check-start').onclick();const e=t.endpoint();assert(t.get('check-phrase').textContent.startsWith('Paprika,'));
 e.emit('first');e.emit('first','first');assert(t.get('check-phrase').textContent.startsWith('Tell me another'));
 e.emit('second');e.emit('second',null,true);assert(t.get('check-phrase').textContent.includes('tiny robot'));
 e.emit('third');e.emit('third','third');await settle();assert.equal(e.active,false);assert.equal(t.get('check-review').hidden,false);
 await t.get('check-save').onclick();assert.equal(t.saved.length,0);assert(t.get('check-saved').textContent.includes('Choose'));
 t.get('check-result').value='problem';t.get('check-note').value='Controlled note';await t.get('check-save').onclick();assert.equal(t.saved.length,1);assert.equal(t.saved[0].completed_sequence,true);assert.equal(t.saved[0].last_exchange,undefined);assert.equal(t.get('check-save').disabled,true);
});
test('muting a guided check preserves partial feedback and stops capture',async()=>{
 const t=fixture();await t.choices();await t.get('check-start').onclick();t.endpoint().emit('first');await t.get('mute').onclick();await settle();
 t.get('check-result').value='unsure';t.get('check-include-text').checked=true;await t.get('check-save').onclick();assert.equal(t.saved[0].completed_sequence,false);assert.equal(t.saved[0].last_exchange.heard,'Controlled request');assert.equal(t.endpoint().active,false);
});
test('ordinary listening has a dedicated screen; back mutes and requires fresh choices',async()=>{
 const t=fixture();await t.choices();assert.equal(t.get('companion-screen').hidden,true);await t.get('start').onclick();assert.equal(t.get('setup-screen').hidden,true);assert.equal(t.get('companion-screen').hidden,false);
 await t.get('back').onclick();assert.equal(t.endpoint().active,false);assert.equal(t.get('setup-screen').hidden,false);assert.equal(t.get('companion-screen').hidden,true);assert.equal(t.get('adult').checked,false);assert.equal(t.get('start').disabled,true);
});
test('mute keeps the companion screen; deliberate resume reuses this session choice',async()=>{
 const t=fixture();await t.choices();await t.get('start').onclick();await t.get('mute').onclick();assert.equal(t.get('companion-screen').hidden,false);assert.equal(t.get('resume').hidden,false);await t.get('resume').onclick();assert.equal(t.endpoint().active,true);
});
test('completed chat visibly returns to name-only listening while keeping microphone on',async()=>{
 const t=fixture();await t.choices();await t.get('start').onclick();t.endpoint().emit('farewell',null,true,{closing_after_playback:true});assert.equal(t.get('face-card').dataset.state,'farewell');
 t.endpoint().emit(null,'farewell',false,{engagement:'idle'});assert.equal(t.get('chat-finished').hidden,false);assert.equal(t.get('face-card').dataset.state,'standby');assert.equal(t.get('mic-state').textContent,'Listening locally for my name');assert.equal(t.endpoint().active,true);
 t.endpoint().emit('new-turn',null,false,{input:'capturing'});assert.equal(t.get('chat-finished').hidden,true);assert.equal(t.get('face-card').dataset.state,'listening');
});
test('memory outage stops capture and guides a fresh no-memory setup without automatic retry',async()=>{
 const t=fixture();await t.choices();t.get('family-memory').checked=true;await t.get('start').onclick();
 t.endpoint().emit('memory-fault',null,false,{error:'Memory is unavailable',failure:{code:'memory_worker_unavailable'}});await settle();
 assert.equal(t.endpoint().active,false);assert.equal(t.get('memory-return').hidden,false);assert.equal(t.get('retry').hidden,true);assert.equal(t.get('resume').hidden,true);
 assert.match(t.get('error').textContent,/Listening is off/);assert.equal(t.calls.filter(c=>c[0]==='start').length,1);
 await t.get('memory-return').onclick();assert.equal(t.get('setup-screen').hidden,false);assert.equal(t.get('adult').checked,false);assert.equal(t.get('start').disabled,true);assert.equal(t.get('family-memory').disabled,true);
 await t.choices();await t.get('start').onclick();assert.equal(t.calls.filter(c=>c[0]==='start').at(-1)[2].memory,false);
 await t.get('mute').onclick();assert.equal(t.get('resume').hidden,false);
});
test('memory failure during guided check preserves partial feedback and gives the in-app next step',async()=>{
 const t=fixture();await t.choices();await t.get('check-start').onclick();
 t.endpoint().emit('memory-fault',null,false,{error:'Memory is unavailable',failure:{code:'memory_worker_unavailable'}});await settle();
 assert.equal(t.endpoint().active,false);assert.equal(t.get('check-review').hidden,false);assert.equal(t.get('memory-return').hidden,true);assert.match(t.get('error').textContent,/partial check above/);
 t.get('check-result').value='problem';await t.get('check-save').onclick();assert.equal(t.saved.length,1);assert.equal(t.saved[0].completed_sequence,false);
 await t.get('check-return').onclick();await settle();assert.equal(t.get('setup-screen').hidden,false);assert.equal(t.get('family-memory').disabled,true);assert.equal(t.get('start').disabled,true);
});
test('background learning failure pauses the active session without waiting for another question',async()=>{
 const t=fixture();await t.choices();await t.get('start').onclick();const status=t.bridge.status;
 t.bridge.status=async()=>({...await status(),family:{family_memory_requested:true,memory:{ready:false,status:'needs_reconciliation'}}});
 await t.poll();await settle();assert.equal(t.endpoint().active,false);assert.equal(t.get('memory-return').hidden,false);assert.match(t.get('error').textContent,/Memories need a check/);
 assert.equal(t.calls.filter(c=>c[0]==='start').length,1);
});
test('idle drive loss disables Start and clears consent before any microphone request',async()=>{
 const t=fixture();await t.choices();t.bridge.status=async()=>({prerequisites:{ready:false,drive:false,local_files:true,cloud_key:true}});
 await t.poll();assert.equal(t.get('start').disabled,true);assert.equal(t.get('adult').checked,false);assert.match(t.get('error').textContent,/external drive/);assert.equal(t.calls.length,0);
});
test('status polling never accumulates overlapping requests while a service is stalled',async()=>{
 const t=fixture();await settle();let count=0,release;t.bridge.status=()=>{count++;return new Promise(r=>release=r);};
 const first=t.poll();await settle();await t.poll();await t.poll();assert.equal(count,1);
 release({prerequisites:{ready:true}});await first;
});

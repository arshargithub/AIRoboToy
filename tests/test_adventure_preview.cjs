const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),{webcrypto}=require('node:crypto');
const M=require('../tavi/web/adventure-state.js').PaprikaAdventure;
let seq=0;const id=()=>`fixture-${++seq}`;
function started(){let s=M.create(id);s=M.apply(s,{type:'start'},id);return M.apply(s,{type:'practised'},id);}
function turn(s,outcome){s=M.apply(s,{type:'answered',outcome},id);s=M.apply(s,{type:'checked',attemptId:s.current.id,outcome},id);return M.apply(s,{type:'next'},id);}
let checks=0;function check(fn){fn();checks++;}
check(()=>{
 let s=started();const seen=[];
 for(let n=0;n<6;n++){seen.push(s.current.promptId);s=turn(s,M.defaults[n]);}
 assert.equal(s.stage,'child_done');assert.equal(M.counts(s).eligible,4);assert.equal(new Set(seen).size,6);
 s=M.apply(s,{type:'review'});s=M.apply(s,{type:'approve'});assert.equal(M.counts(s).kept,4);assert.equal(s.stage,'summary');
 s=M.apply(s,{type:'more'},id);for(let n=0;n<2;n++){assert(!seen.includes(s.current.promptId));s=turn(s,'clear');}
 s=M.apply(s,{type:'review'});s=M.apply(s,{type:'approve'});s=M.apply(s,{type:'finish'});
 assert.equal(s.stage,'saved');assert.equal(M.counts(s).kept,6);assert.equal(s.realProfileCreated,false);
});
check(()=>{
 let s=started();s=M.apply(s,{type:'answered',outcome:'clear'});const attemptId=s.current.id;
 const before=JSON.stringify(s);s=M.apply(s,{type:'checked',attemptId:'stale',outcome:'clear'});assert.equal(JSON.stringify(s),before);
 s=M.apply(s,{type:'pause'});s=M.restore(JSON.stringify(s));s=M.apply(s,{type:'resume'});assert.equal(s.stage,'checking');assert.equal(s.current.id,attemptId);
 s=M.apply(s,{type:'checked',attemptId,outcome:'clear'});const completed=JSON.stringify(s);
 s=M.apply(s,{type:'checked',attemptId,outcome:'clear'});assert.equal(JSON.stringify(s),completed);assert.equal(s.attempts.length,1);
});
check(()=>{
 let s=started();for(let n=0;n<6;n++)s=turn(s,'clear');s=M.apply(s,{type:'review'});
 s=M.apply(s,{type:'exclude',attemptId:s.attempts[0].id,reason:'other_voice'});s=M.apply(s,{type:'exclude',attemptId:s.attempts[1].id,reason:'silly_voice'});
 s=M.apply(s,{type:'approve'});assert.equal(M.counts(s).kept,4);assert.equal(s.attempts[0].exclusion,'other_voice');
 s=M.apply(s,{type:'more'},id);assert.equal(s.attempts.length,6);assert.equal(s.attempts[0].review,'exclude');
});
check(()=>{
 let s=started();for(let n=0;n<6;n++)s=turn(s,'noise');s=M.apply(s,{type:'review'});s=M.apply(s,{type:'approve'});s=M.apply(s,{type:'more'},id);
 for(let n=0;n<6;n++)s=turn(s,'short');s=M.apply(s,{type:'review'});s=M.apply(s,{type:'approve'});
 assert.equal(s.attempts.length,12);assert.equal(M.counts(s).kept,0);assert.equal(M.apply(s,{type:'more'},id).stage,'summary');
 assert.throws(()=>M.apply({...s,stage:'review'},{type:'exclude',attemptId:s.attempts[0].id,reason:'keep'}));
 assert.equal(M.apply(s,{type:'finish'}).stage,'saved');
});
check(()=>{
 let s=started();s=M.apply(s,{type:'answered',outcome:'noise'});const restored=M.restore(JSON.stringify(s));assert.equal(restored.stage,'checking');assert.equal(restored.current.simulatedOutcome,'noise');
 assert.throws(()=>M.restore(JSON.stringify({...s,realProfileCreated:true})));assert.throws(()=>M.restore(JSON.stringify({...s,current:{id:'bad',number:99,promptId:'bad'}})));
});
check(()=>{
 let raw=null,writes=0;const storage={getItem:()=>raw,setItem:(key,value)=>{writes++;raw=value;if(writes===1)throw Error('ack lost');}};
 const store=new M.Store(storage);let s=started();store.save(s);assert.equal(store.read().active,s.id);
 s=turn(s,'clear');store.save(s);assert.equal(store.read().sessions[s.id].attempts.length,1);
 const fresh=M.create(id);store.save(fresh);assert.equal(Object.keys(store.read().sessions).length,2);assert.equal(store.read().sessions[s.id].attempts.length,1);
});
check(()=>{
 const storage={getItem:()=>'{bad save',setItem:()=>assert.fail('Must not overwrite corrupt save')};
 assert.throws(()=>new M.Store(storage).save(started()));
 let raw=null;const st={getItem:()=>raw,setItem:(k,v)=>raw=v},store=new M.Store(st);
 for(let n=0;n<10;n++)store.save(M.create(id));assert.throws(()=>store.save(M.create(id)));assert.equal(Object.keys(store.read().sessions).length,10);
});
check(()=>{
 let s=started();for(let n=0;n<6;n++)s=turn(s,'clear');
 const copy=JSON.parse(JSON.stringify(s));copy.attempts[1].id=copy.attempts[0].id;assert.throws(()=>M.restore(JSON.stringify(copy)));
 assert.throws(()=>M.apply(started(),{type:'answered',outcome:'invented'}));
});
check(()=>{
 let s=started();for(let n=0;n<6;n++)s=turn(s,M.defaults[n]);s=M.apply(s,{type:'review'});s=M.apply(s,{type:'approve'});s=M.apply(s,{type:'finish'});
 s=M.restore(JSON.stringify(s));assert.equal(M.counts(s).kept,4);s=M.apply(s,{type:'more'},id);
 assert.equal(s.current.promptId,'garden');assert.equal(M.counts(s).kept,4);assert.equal(s.stage,'turn');
});
check(()=>{
 let raw=null;const storage={getItem:()=>raw,setItem:(k,v)=>raw=v},store=new M.Store(storage);
 let s=started();store.save(s);const stale=JSON.parse(JSON.stringify(s));s=turn(s,'clear');store.save(s);
 assert.throws(()=>store.save(M.apply(stale,{type:'pause'})));assert.equal(store.read().sessions[s.id].attempts.length,1);
});

function ui(storage){
 const nodes={},timers=new Map();let timerId=0,capabilityCalls=0;
 class Node{
  constructor(){this.hidden=false;this.value='';this.children=[];this.textContent='';this.disabled=false;}
  append(...n){this.children.push(...n);}replaceChildren(...n){this.children=[...n];}setAttribute(k,v){this[k]=v;}focus(){}click(){this.onclick?.();}
 }
 const get=id=>nodes[id]??(nodes[id]=new Node());get('outcome').value='script';
 const blocked=()=>{capabilityCalls++;throw Error('Preview attempted a forbidden capability');};
 const context={document:{getElementById:get,createElement:()=>new Node()},window:{addEventListener(){}},localStorage:storage,crypto:webcrypto,
  setTimeout:fn=>{timers.set(++timerId,fn);return timerId;},clearTimeout:id=>timers.delete(id),navigator:{mediaDevices:{getUserMedia:blocked}},fetch:blocked,WebSocket:blocked,AudioContext:blocked,Blob,URL:{createObjectURL:()=> 'blob:pretend',revokeObjectURL(){}}};
 vm.createContext(context);for(const file of ['adventure-state.js','adventure-preview.js'])vm.runInContext(fs.readFileSync('tavi/web/'+file,'utf8'),context);
 return {get,click:id=>get(id).onclick(),tick(){const [key,fn]=timers.entries().next().value||[];assert(fn);timers.delete(key);fn();},get capabilityCalls(){return capabilityCalls;}};
}
check(()=>{
 let raw=null;const storage={getItem:()=>raw,setItem:(k,v)=>raw=v};let t=ui(storage);t.click('primary');t.click('primary');
 const question=t.get('question').textContent;t.click('primary');assert.equal(t.get('question').textContent,question);
 t=ui(storage);assert.equal(t.get('question').textContent,question);t.tick();assert.match(t.get('title').textContent,/Another part/);t.click('primary');
 t.click('pause');assert.match(t.get('title').textContent,/come back/);t=ui(storage);t.click('primary');assert.equal(t.get('step').textContent,'STOP 2 OF 6');
 for(let n=1;n<6;n++){t.click('primary');t.tick();t.click('primary');}
 assert.match(t.get('title').textContent,/Thanks for exploring/);t.click('primary');assert.equal(t.get('review-list').children.length,6);t.click('primary');assert.match(t.get('coverage').textContent,/4 of 6/);
 t.click('secondary');for(let n=0;n<2;n++){t.click('primary');t.tick();t.click('primary');}t.click('primary');t.click('primary');assert.match(t.get('coverage').textContent,/6 of 6/);t.click('primary');assert.match(t.get('title').textContent,/All done/);assert.equal(t.capabilityCalls,0);
});
check(()=>{
 let raw=null,fail=false;const storage={getItem:()=>raw,setItem:(k,v)=>{if(fail)throw Error('quota');raw=v;}};const t=ui(storage);t.click('primary');t.click('primary');fail=true;t.click('primary');
 assert.equal(t.get('recovery').hidden,false);assert.equal(t.get('actions').hidden,true);assert.match(t.get('error').textContent,/still here/);
 fail=false;t.click('retry');t.tick();assert.match(t.get('title').textContent,/Another part/);
 fail=true;t.click('primary');t.click('temporary');assert.match(t.get('save-mode').textContent,/This visit only/);assert.equal(t.get('recovery').hidden,true);assert.equal(t.capabilityCalls,0);
});
check(()=>{
 const t=ui({getItem:()=>'{unreadable',setItem:()=>assert.fail('Existing save must remain')});assert.equal(t.get('recovery').hidden,false);t.click('temporary');t.click('primary');assert.match(t.get('title').textContent,/try one together/);assert.equal(t.capabilityCalls,0);
});
console.log(`Adventure preview: ${checks} state/store/actual-UI invariants pass, including six-plus-two flow, short/noisy turns, parent exclusions,12turn limit, pause/reload/pending-check, duplicate/stale receipts, lost save ACK, quota/corrupt recovery. No microphone/model/network calls.`);

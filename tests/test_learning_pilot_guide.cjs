const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const nodes={'pilot-adult':{checked:true},'guide-error':{textContent:''}};
const env={document:{getElementById:id=>nodes[id],querySelector:()=>({value:'local-speech-cloud-text'})},performance:{now:()=>0},setTimeout,clearTimeout};vm.createContext(env);
for(const file of ['conversation_guide.js','memory-conversation-guide.js','learning-conversation-guide.js'])vm.runInContext(fs.readFileSync('tavi/web/'+file,'utf8'),env);
(async()=>{
 let timer,stops=0,checkpoints=[];
 const make=vm.runInContext('options=>new KConversationGuide(options)',env);
 const g=make({render(){},startCapture:async()=>true,stopCapture:()=>stops++,checkpoint:async n=>{checkpoints.push(n);return {ready:true};},setTimer:fn=>{timer=fn;return 1;},clearTimer(){},clock:()=>0});g.variant='learning-v1';await g.start();
 for(let i=0;i<5;i++){
  timer();assert.equal(g.stage,'call');const phrase=g.copy()[3];assert(phrase);
  g.accepted('r'+i);assert.equal(g.copy()[3],phrase);g.playbackStarted('r'+i);assert.equal(g.copy()[3],phrase);g.observe({engagement:i===4?'idle':'active',learning:{status:'idle',pending:0}});g.playbackEnded('r'+i,'source_ended');
  if(i===0||i===2){assert.equal(g.stage,'remembering');assert.equal(g.copy()[3],phrase);await new Promise(resolve=>setImmediate(resolve));assert.equal(g.stage,'quiet');}
 }
 timer();assert.equal(g.stage,'review');assert.equal(g.data.completed,true);assert.deepEqual(checkpoints,[1,2]);assert.equal(stops,1);assert.equal(g.data.word_reviews.length,5);assert.equal(g.data.identity.includes('Mira'),true);
 g.report('worked');g.data.wait_rating='usable';g.saved();assert.equal(g.stage,'saved');
 const bad=make({render(){},startCapture:async()=>true,stopCapture:()=>stops++,checkpoint:async()=>{throw Error('failure');},setTimer:fn=>{timer=fn;return 1;},clearTimer(){},clock:()=>0});await bad.start();timer();bad.accepted('bad');bad.playbackStarted('bad');bad.playbackEnded('bad','source_ended');await new Promise(resolve=>setImmediate(resolve));assert.equal(bad.stage,'review');assert.equal(bad.data.completed,false);assert.equal(stops,2);
 console.log('Learning guide: full5turn flow,2owned save/restart checkpoints, persistent phrases, automatic mute, independent ratings/save and partial error recovery pass.');
 const outage=make({render(){},startCapture:async()=>true,stopCapture:()=>stops++,checkpoint:async()=>({ready:false}),setTimer:fn=>{timer=fn;return 1;},clearTimer(){},clock:()=>0});await outage.start();timer();
 outage.accepted('lookup-failed');outage.observe({engagement:'active',failure:{component:'reasoning',code:'memory_worker_unavailable'}});
 assert.equal(outage.stage,'review');assert.equal(outage.data.completed,false);assert.equal(outage.data.failure.code,'memory_worker_unavailable');
 assert.match(outage.data.finished_reason,/could not reach its memories/);assert.match(outage.data.finished_reason,/Save this partial attempt/);assert.equal(stops,3);
 assert.equal(saveEnv.canSaveGuide(outage),true);
 console.log('Memory outage guide: stops capture, names memory failure, preserves unlabelled partial save and does not request repeating speech.');
})().catch(e=>{console.error(e);process.exitCode=1;});
const transport=fs.readFileSync('tavi/web/conversation.js','utf8');
const canSaveSource=transport.slice(transport.indexOf('function canSaveGuide'),transport.indexOf('function renderGuide'));
const saveEnv={};vm.createContext(saveEnv);vm.runInContext(canSaveSource,saveEnv);
const g={variant:'learning-v1',stage:'review',data:{protocol:'k-live-conversation-v1',completed:true,result:null,wait_rating:null}};
assert.equal(saveEnv.canSaveGuide(g),false);g.data.result='worked';assert.equal(saveEnv.canSaveGuide(g),false);g.data.wait_rating='usable';assert.equal(saveEnv.canSaveGuide(g),true);
g.data.completed=false;g.data.result=null;g.data.wait_rating=null;assert.equal(saveEnv.canSaveGuide(g),true);
console.log('Actual save gate requires separate memory/wait ratings on completion, and permits unlabelled partial saves.');

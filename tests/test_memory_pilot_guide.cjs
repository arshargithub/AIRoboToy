const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const nodes={'pilot-adult':{checked:false},'guide-error':{textContent:''}};let choice=null;
const env={document:{getElementById:id=>nodes[id],querySelector:()=>choice?{value:choice}:null},performance:{now:()=>0},setTimeout,clearTimeout};vm.createContext(env);
vm.runInContext(fs.readFileSync('tavi/web/conversation_guide.js','utf8'),env);vm.runInContext(fs.readFileSync('tavi/web/memory-conversation-guide.js','utf8'),env);
(async()=>{
 assert.equal(vm.runInContext('memoryPilotConsent()',env),false);nodes['pilot-adult'].checked=true;choice='local-only';assert.equal(vm.runInContext('memoryPilotConsent()',env),false);
 let capture=0,stops=0,timer;
 env.makeGuide=vm.runInContext('(options)=>new KConversationGuide(options)',env);
 const g=env.makeGuide({render(){},startCapture:async()=>{capture++;return true;},stopCapture:()=>stops++,setTimer:(fn)=>{timer=fn;return 1;},clearTimer(){},clock:()=>0});g.variant='memory-v1';
 await g.start();assert.equal(capture,0);
 choice='local-speech-cloud-text';await g.start();assert.equal(capture,1);assert.equal(g.data.steps.length,5);
 for(let i=0;i<5;i++){
  timer();assert.equal(g.stage,'call');const phrase=g.copy()[3];assert(phrase);
  const id='r'+i;g.accepted(id);assert.equal(g.stage,'waiting');assert.equal(g.copy()[3],phrase);
  g.playbackStarted(id);assert.equal(g.stage,'listen');assert.equal(g.copy()[3],phrase);
  g.observe({engagement:i===4?'idle':'active'});g.playbackEnded(id,'source_ended');
 }
 timer();assert.equal(g.stage,'review');assert.equal(g.data.completed,true);assert.equal(g.data.goodbye_closed,true);assert.equal(stops,1);assert.equal(g.data.word_reviews.length,5);
 g.report('worked');g.data.note='QA only';g.saved();assert.equal(g.stage,'saved');
 console.log('Memory guide: consent gates,5turn flow, persistent phrases, followup, local goodbye, automatic mute and review/save pass.');
})().catch(e=>{console.error(e);process.exitCode=1;});

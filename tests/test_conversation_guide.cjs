const assert=require('node:assert/strict');
const {ConversationGuide}=require('../tavi/web/conversation_guide.js');
const vm=require('node:vm'),fs=require('node:fs');
function harness(ready=true){
 let stopped=0;const timers=new Map();let id=0;
 const g=new ConversationGuide({render(){},startCapture:async()=>ready,stopCapture(){stopped++},
  setTimer(fn,ms){timers.set(++id,{fn,ms});return id},clearTimer(i){timers.delete(i)}});
 return {g,timers,get stopped(){return stopped},fire(ms){for(const [i,t]of [...timers])if(t.ms===ms){timers.delete(i);t.fn()}}};
}
(async()=>{
 // WebKit timer functions reject an arbitrary object as their receiver. Test
 // the browser defaults, not only dependency-injected fake timer callbacks.
 const browser={performance:{now:()=>0},setTimeout(fn,ms){if(this?.stage)throw TypeError('Illegal invocation');return 1},clearTimeout(id){if(this?.stage)throw TypeError('Illegal invocation')}};
 vm.createContext(browser);vm.runInContext(fs.readFileSync('tavi/web/conversation_guide.js','utf8'),browser);
 await vm.runInContext("(async()=>{const g=new ConversationGuide({render(){},startCapture:async()=>true,stopCapture(){}});await g.start();if(g.stage!=='call')throw Error('Did not start');g.accepted('story');g.playbackStarted('story');g.finish();})()",browser);
 const h=harness();await h.g.start();assert.equal(h.g.stage,'call');h.g.accepted('story');
 h.g.playbackStarted('story');assert.equal(h.g.stage,'get_ready');h.fire(1500);assert.equal(h.g.stage,'interrupt');
 h.g.playbackEnded('story','speech');assert.equal(h.g.stage,'waiting_replacement');assert.equal(h.stopped,0);
 h.g.accepted('new');h.g.playbackStarted('new');assert.equal(h.g.stage,'listen');h.g.playbackEnded('new','source_ended');
 assert.equal(h.g.stage,'check_words');assert.equal(h.stopped,1);assert.equal(h.g.data.result,null,'source end must not auto-mark success');
 h.g.nextWords();assert.equal(h.g.wordIndex,0,'no implicit word-correctness label');h.g.rateWords('correct');h.g.nextWords();
 assert.equal(h.g.currentWords().response_id,'new');h.g.rateWords('incorrect_or_incomplete');h.g.nextWords();assert.equal(h.g.stage,'review');
 h.g.report('problem');assert.equal(h.g.data.result,'problem');h.g.saved();assert.equal(h.g.stage,'saved');assert.equal(h.timers.size,0);
 const timeout=harness();await timeout.g.start();timeout.fire(30000);assert.equal(timeout.g.stage,'review');assert.equal(timeout.stopped,1);assert.match(timeout.g.data.finished_reason,/Timed out/);
 const failure=harness(false);await failure.g.start();assert.equal(failure.g.stage,'review');assert.equal(failure.stopped,1);
 const stop=harness();await stop.g.start();stop.g.accepted('story');stop.g.playbackStarted('story');stop.g.finish();stop.fire(1500);assert.equal(stop.g.stage,'check_words','a late cue cannot restart a stopped test');
 const early=harness();await early.g.start();early.g.accepted('short');early.g.playbackStarted('short');early.g.playbackEnded('short','source_ended');early.fire(1500);assert.equal(early.g.stage,'waiting_replacement');early.fire(20000);assert.equal(early.g.data.result,null);
 console.log('Conversation guide: timed cues, actual playback transitions, timeout, stop, failed startup and honest human review passed');
})().catch(e=>{console.error(e);process.exitCode=1});

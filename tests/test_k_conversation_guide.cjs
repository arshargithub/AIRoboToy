const assert=require('node:assert/strict');
const {KConversationGuide}=require('../tavi/web/conversation_guide.js');
function harness(){let stopped=0,id=0;const timers=new Map();const g=new KConversationGuide({render(){},startCapture:async()=>true,stopCapture(){stopped++},clock:()=>0,
 setTimer(fn,ms){timers.set(++id,{fn,ms});return id},clearTimer(id){timers.delete(id)}});
 return {g,get stopped(){return stopped},timers,fire(ms){for(const [id,t]of [...timers])if(t.ms===ms){timers.delete(id);t.fn()}}};}
(async()=>{
 const h=harness();await h.g.start();assert.equal(h.g.stage,'quiet');h.fire(3000);assert.equal(h.g.stage,'call');
 for(let i=0;i<5;i++){
  const id='r'+i;h.g.accepted(id);h.g.accepted(id);h.g.playbackStarted(id);
  if(i===2){assert.equal(h.g.stage,'get_ready');h.fire(1500);assert.equal(h.g.stage,'interrupt');h.g.playbackEnded(id,'speech');assert.equal(h.g.stage,'finish_interruption');}
  else{assert.equal(h.g.stage,'listen');if(i===4)h.g.observe({engagement:'idle'});h.g.playbackEnded(id,'source_ended');if(i<4){assert.equal(h.g.stage,'quiet');h.fire(2000);}}
 }
 assert.equal(h.stopped,0);h.fire(5000);assert.equal(h.stopped,1);assert.equal(h.g.stage,'review');assert.ok(h.g.data.word_reviews.every(r=>r.rating===null));h.g.beginWordReview();assert.equal(h.g.stage,'check_words');assert.equal(h.g.data.result,null);assert.equal(h.g.data.completed,true);assert.equal(h.g.data.goodbye_closed,true);
 assert.deepEqual(h.g.responseIds(),['r0','r1','r2','r3','r4']);assert.equal(h.g.data.word_reviews.length,5);
 for(let i=0;i<5;i++){assert.equal(h.g.currentWords().response_id,'r'+i);assert.ok(h.g.currentWords().prompt);h.g.rateWords(i===1?'incorrect_or_incomplete':'correct');h.g.nextWords();}
 assert.equal(h.g.stage,'review');assert.equal(h.g.data.result,null);h.g.report('problem');h.g.saved();assert.equal(h.g.stage,'saved');assert.equal(h.timers.size,0);
 const echo=harness();await echo.g.start();echo.g.accepted('unwanted');assert.equal(echo.stopped,1);assert.equal(echo.g.stage,'review');assert.equal(echo.g.data.unexpected_responses.length,1);assert.ok(echo.g.responseIds().includes('unwanted'));
 const cut=harness();await cut.g.start();cut.fire(3000);cut.g.accepted('baseline');cut.g.playbackStarted('baseline');cut.g.playbackEnded('baseline','speech');assert.equal(cut.g.stage,'review');assert.match(cut.g.data.finished_reason,/should have finished/);assert.equal(cut.g.data.completed,false);
 const timeout=harness();await timeout.g.start();timeout.fire(3000);timeout.fire(30000);assert.equal(timeout.stopped,1);assert.equal(timeout.g.data.completed,false);
 const voiceFail=harness();await voiceFail.g.start();voiceFail.fire(3000);voiceFail.g.accepted('failed-turn');voiceFail.g.observe({engagement:'active',failure:{component:'speech',code:'unsupported_phoneme',response_id:'failed-turn'}});assert.equal(voiceFail.stopped,1);assert.equal(voiceFail.g.stage,'review');assert.equal(voiceFail.g.data.failure.component,'speech');assert.equal(voiceFail.g.data.completed,false);assert.equal(voiceFail.timers.size,0);
 const late=harness();await late.g.start();late.g.finish();late.fire(3000);assert.equal(late.g.stage,'review','A late timer must not restart stopped capture');
 const fresh=harness();fresh.g.variant='latency-v1';assert.match(fresh.g.copy()[1],/faster/);await fresh.g.start();assert.equal(fresh.g.data.variant,'latency-v1');assert.match(fresh.g.data.steps[0].prompt,/three cushions/);assert.match(fresh.g.data.steps[3].prompt,/friendly lizard/);fresh.g.finish();
 const turbo=harness();turbo.g.variant='turbo-v1';assert.match(turbo.g.copy()[1],/clearer listening/);assert.match(turbo.g.copy()[2],/long waits/);await turbo.g.start();assert.equal(turbo.g.data.variant,'turbo-v1');assert.match(turbo.g.data.steps[0].prompt,/blanket/);assert.match(turbo.g.data.steps[3].prompt,/sleepy dragon/);turbo.g.data.completed=true;turbo.g.data.steps[0].response_id='calibration';turbo.g.finish();assert.equal(turbo.g.stage,'check_words');assert.equal(turbo.stopped,1);turbo.g.rateWords('incorrect_or_incomplete');turbo.g.nextWords();assert.equal(turbo.g.stage,'review');assert.equal(turbo.g.data.word_reviews[0].rating,'incorrect_or_incomplete');
 const rejected=harness();await rejected.g.start();rejected.fire(3000);rejected.g.observe({engagement:'idle',input_rejection:{utterance:1,recognition_id:'rejected-1',reason:'name_missing'}});assert.equal(rejected.stopped,1);assert.equal(rejected.g.stage,'review');assert.match(rejected.g.data.finished_reason,/no need to keep repeating/);assert.equal(rejected.g.data.input_rejection.reason,'name_missing');
 const background=harness();await background.g.start();const ignored={engagement:'idle',input_rejection:{utterance:1,recognition_id:'background-1',reason:'name_missing'}};background.g.observe(ignored);background.fire(3000);background.g.observe(ignored);assert.equal(background.g.stage,'call','An earlier quiet-phase rejection must not stop the speaking phase');background.g.finish();
 const close=harness();await close.g.start();close.g.index=4;close.g.data.steps[4].response_id='bye';close.g.playbackEnded('bye','source_ended');close.fire(5000);assert.equal(close.g.data.goodbye_closed,false,'Playback ending alone does not establish session closure');
 console.log('K guide: five varied turns, quiet controls, speech-only interruption, unknown closure, partial failure and explicit human review passed.');
})().catch(e=>{console.error(e);process.exitCode=1});

const assert=require('node:assert/strict');
const {SpeechInterruptionGate}=require('../tavi/web/interruption.js');
const gate=new SpeechInterruptionGate();
function frame(seq,prob,time){return gate.accept({sequence:seq,endFrame:(time+.032)*16000},{probability:prob},16000,time+.04);}
gate.reset(1);
assert.equal(frame(0,1,.95),false,'pre-playback speech cannot stop new playback');
assert.equal(frame(1,.95,1.00),false);
assert.equal(frame(2,.8,1.032),false,'brief spike resets');
assert.equal(frame(3,.95,1.064),false);
assert.equal(frame(4,.95,1.096),false);
assert.equal(frame(5,.95,1.128),true,'sustained speech interrupts without startup blanking');
gate.reset(2);
assert.equal(gate.accept({sequence:0,endFrame:2.032*16000},{probability:1},16000,2.5),false,'old results are discarded');
assert.equal(frame(1,.95,2.50),false);
assert.equal(frame(3,.95,2.532),false,'sequence gaps reset confirmation');
assert.equal(frame(4,.95,2.564),false);
assert.equal(frame(5,.95,2.596),false);
assert.equal(frame(6,.95,2.628),true);
console.log('Interruption gate checks passed');

const sensitive=new SpeechInterruptionGate(.65,2);
sensitive.reset(0);
assert.equal(sensitive.accept({sequence:0,endFrame:512},{probability:.7},16000,.04),false);
assert.equal(sensitive.reason,'confirming');
assert.equal(sensitive.accept({sequence:1,endFrame:1024},{probability:.7},16000,.072),true,'two moderate-confidence speech frames can interrupt');
sensitive.reset(0);
for(let i=0;i<20;i++)assert.equal(sensitive.accept({sequence:i,endFrame:(i+1)*512},{probability:.08},16000,(i+1)*.032+.008),false,'low residual probabilities stay below candidate threshold');
console.log('Sensitive candidate and diagnostic reasons passed');

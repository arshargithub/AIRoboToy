const assert=require('node:assert/strict');
const {GuidedWakeTest}=require('../tavi/web/guided-wake.js');
let jobs=[],cancelled=[],now=0,report;
const test=new GuidedWakeTest({show:()=>{},done:r=>report=r,schedule:(fn,ms)=>{jobs.push({fn,ms});return jobs.length-1},cancel:id=>cancelled.push(id),clock:()=>now});
test.start();assert.throws(()=>test.start());
assert.equal(jobs.length,16);
for(let i=0;i<15;i++){now=jobs[i].ms;jobs[i].fn();if(i<10){now+=500;test.detected(.9)}}
assert.equal(test.result.trials[0].detections[0].after_cue_ms,500);
jobs[15].fn();assert.equal(report.complete,true);assert.equal(report.summary.detected_positive_trials,10);assert.equal(report.summary.false_wake_trials,0);
test.detected(.9);assert.equal(report.trials[14].detections.length,0,'late callbacks cannot change completed trial');
jobs=[];test.start();jobs[0].fn();test.detected(.9);test.finish(false);assert.equal(report.complete,false);assert.equal(report.trials.length,1);jobs[1].fn();assert.equal(report.trials.length,1,'cancelled timer cannot add trials');
console.log('Guided wake smoke-test checks passed');

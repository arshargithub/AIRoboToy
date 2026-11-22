const assert=require('node:assert/strict');const {SampleCollector}=require('../tavi/web/sample-collector.js');
const c=new SampleCollector(2,2),packet=i=>({sequence:i,sampleRate:16000,pcm:new ArrayBuffer(1024)});
c.append(packet(0));assert.equal(c.clips.length,0,'no collection outside explicit clip');
c.begin({label:'positive'});c.append(packet(4));c.append(packet(5));assert.throws(()=>c.append(packet(6)));c.finish();assert.equal(c.clips[0].frames.length,2);
c.begin({label:'negative'});c.append(packet(10));assert.throws(()=>c.append(packet(12)));c.discard();assert.equal(c.clips.length,1);
c.begin({label:'negative'});c.append(packet(20));c.finish();assert.throws(()=>c.begin({}));
console.log('Bounded local sample collection checks passed');

const assert=require('node:assert/strict');
const {ChunkAudioPrefetch}=require('../tavi/web/chunk-audio-prefetch.js');
(async()=>{
 const c=new ChunkAudioPrefetch(),a={id:'r',sequence:1};let resolve,calls=0;
 const load=()=>{calls++;return new Promise(r=>resolve=r);};
 c.offer(a,'lease1',load);c.offer(a,'lease1',load);await Promise.resolve();assert.equal(calls,1);
 resolve('buffer');assert.equal(await c.take(a,'lease1'),'buffer');assert.equal(await c.take(a,'lease1'),null);
 c.offer(a,'lease1',load);await Promise.resolve();c.clear();resolve('stale');assert.equal(await c.take(a,'lease1'),null);
 c.offer(a,'lease1',async()=>{throw Error('temporary');});assert.equal(await c.take(a,'lease1'),null);
 c.offer(a,'lease1',async()=>'private');assert.equal(await c.take(a,'lease2'),null);c.clear();
 let pending; c.offer(a,'lease1',()=>new Promise(r=>pending=r));await Promise.resolve();
 const taken=c.take(a,'lease1');c.clear();pending('stale taken');assert.equal(await taken,null);
 console.log('Prefetch: deduplication, lease binding, cancellation, failure fallback and consumed-inflight invalidation pass.');
})().catch(e=>{console.error(e);process.exitCode=1;});

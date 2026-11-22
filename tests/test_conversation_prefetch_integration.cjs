// Execute the actual playback functions in an isolated unit-test runtime.
// No browser, microphone, speaker, HTTP server or external request is involved.
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const {ChunkAudioPrefetch}=require('../tavi/web/chunk-audio-prefetch.js');
const sourceText=fs.readFileSync('tavi/web/conversation.js','utf8');
const functions=sourceText.slice(sourceText.indexOf('async function loadAudioBuffer'),sourceText.indexOf('async function pump'));
function setup(){
 let fetches=0,decodes=0,starts=0;const commands=[];
 const context={currentTime:1,destination:{},decodeAudioData:async()=>{decodes++;return{duration:1};},
  createBufferSource(){return{connect(){},disconnect(){},start(){starts++;}};},
  createGain(){return{gain:{value:0},connect(){},disconnect(){}};}};
 const env={Promise,Set,Map,AbortSignal,performance:{now:()=>0},audioPrefetch:new ChunkAudioPrefetch(),ctx:context,active:true,gen:1,lease:'lease',loadVersion:0,loadingId:null,source:null,outputGain:null,playingId:null,chunkReplyId:null,latest:{token:{response_id:'r'}},playedChunks:new Set(),blocked:new Set(),speechEnds:new Map(),origin:0,currentRun:{events:[]},gate:{reset(){}},guide:{playbackStarted(){},playbackEnded(){}},face(){},text(){},finishPlaybackTrace(){},$(){return{value:.35};},async action(name,body){commands.push({name,body});},async fail(e){throw e;},async fetch(path,options){fetches++;assert.equal(options.headers['X-Audio-Stream'],'lease');return{ok:true,arrayBuffer:async()=>new ArrayBuffer(8)};}};
 vm.createContext(env);vm.runInContext(functions,env);
 return{env,commands,counts:()=>({fetches,decodes,starts})};
}
(async()=>{
 const a={id:'r',sequence:1,duration_ms:1000};
 let t=setup();t.env.audioPrefetch.offer(a,'1:lease',(audio,signal)=>t.env.loadAudioBuffer(audio,t.env.ctx,'lease',signal));
 await t.env.playAudio(a,1);
 assert.deepEqual(t.counts(),{fetches:1,decodes:1,starts:1});
 assert.deepEqual(t.commands.map(x=>x.name),['started']);
 await t.env.source.onended();assert.deepEqual(t.commands.map(x=>x.name),['started','played']);
 t=setup();t.env.audioPrefetch.offer(a,'1:lease',async()=>({duration:1}));t.env.latest.token.response_id='new';
 await t.env.playAudio(a,1);assert.equal(t.counts().starts,0);assert.equal(t.commands.length,0);
 t=setup();t.env.audioPrefetch.offer(a,'1:lease',async()=>{throw Error('prefetch failure');});await t.env.playAudio(a,1);
 assert.deepEqual(t.counts(),{fetches:1,decodes:1,starts:1});
 t=setup();let release;t.env.audioPrefetch.offer(a,'1:lease',()=>new Promise(r=>release=r));await Promise.resolve();
 const playing=t.env.playAudio(a,1);t.env.active=false;t.env.gen++;t.env.loadVersion++;t.env.audioPrefetch.clear();release({duration:1});await playing;
 assert.equal(t.counts().starts,0);assert.equal(t.commands.length,0);
 console.log('Actual playback integration: prefetched buffer reused once; receipts follow playback; stale token/mute discard; failed prefetch falls back.');
})().catch(e=>{console.error(e);process.exitCode=1;});

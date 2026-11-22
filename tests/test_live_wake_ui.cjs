// Synthetic DOM/microphone tests. These never capture human audio.
const assert=require('node:assert/strict');const fs=require('node:fs');const vm=require('node:vm');const {webcrypto}=require('node:crypto');
function harness({latePermission=false,stallFrames=false,lateStart=false}={}){
 const elements=new Map(),contexts=[],calls=[],track={stops:0,stop(){this.stops++},getSettings:()=>({echoCancellation:true})};
 let node,download,resolvePermission,resolveStart,playback,next=0;const timers=new Map();
 function el(id){if(!elements.has(id)){const e={value:'',textContent:'',checked:false,disabled:false,hidden:false,dataset:{},children:[],click(){},prepend(child){child.parent=this;this.children.unshift(child)}};Object.defineProperty(e,'lastElementChild',{get(){return this.children.at(-1)}});elements.set(id,e)}return elements.get(id)}
 el('mode').value='hinted';el('purpose').value='calls';el('volume').value='.35';
 const stream={getTracks:()=>[track],getAudioTracks:()=>[track]};const queued=[];
 const base={sequence:0,probability:.99,speech:true,buffered_ms:1000,decode_running:false,decode_pending:false,partial_snapshots_replaced:0,events:[]};
 const response=data=>({ok:true,json:async()=>data});
 async function fetch(path,options={}){
  calls.push({path,options});
  if(path==='/api/live-wake/start'){
   const data={stream_id:'lease-'+calls.length,mode:JSON.parse(options.body).mode};
   if(lateStart)return new Promise(resolve=>resolveStart=()=>resolve(response(data)));
   return response(data);
  }
  if(path==='/api/live-wake/stop')return response({stopped:true});
  if(path==='/paprika-reference.wav')return {ok:true,arrayBuffer:async()=>new ArrayBuffer(8)};
  if(path==='/api/live-wake/frame'){
   if(stallFrames)return new Promise((resolve,reject)=>options.signal.addEventListener('abort',()=>reject(Error('Aborted')),{once:true}));
   return response({...base,...(queued.shift()||{})});
  }
  throw Error('Unexpected external or fixture request: '+path);
 }
 const sandbox={console,crypto:webcrypto,AbortController,AbortSignal,Blob,ArrayBuffer,
  document:{body:{classList:{add(){},remove(){}}},getElementById:el,createElement:()=>({click(){},remove(){const i=this.parent?.children.indexOf(this);if(i>=0)this.parent.children.splice(i,1)}})},
  window:{addEventListener(){}},performance:{now:()=>1000},
  URL:{createObjectURL(blob){download=blob;return 'blob:synthetic'},revokeObjectURL(){}},
  setTimeout:(fn,ms)=>{timers.set(++next,{fn,ms});return next},clearTimeout:id=>timers.delete(id),setInterval(){},fetch,
  navigator:{mediaDevices:{getUserMedia(){calls.push({mic:true});return latePermission?new Promise(resolve=>resolvePermission=()=>resolve(stream)):Promise.resolve(stream)}}},
  AudioContext:class{constructor(){this.currentTime=1;this.sampleRate=16000;this.state='running';this.audioWorklet={addModule:async()=>{}};contexts.push(this)}resume(){return Promise.resolve()}close(){this.state='closed';return Promise.resolve()}createMediaStreamSource(){return {connect(){},disconnect(){}}}createGain(){return {gain:{value:0},connect(){},disconnect(){}}}decodeAudioData(){return Promise.resolve({duration:1})}createBufferSource(){playback={connect(){},disconnect(){},start(){},stop(){}};return playback}},
  AudioWorkletNode:class{constructor(){this.port={};node=this}connect(){}disconnect(){}}};
 vm.createContext(sandbox);vm.runInContext(fs.readFileSync('tavi/web/live-wake.js','utf8'),sandbox);
 return {el,calls,track,contexts,queued,get download(){return download},async settle(){await new Promise(resolve=>setImmediate(resolve));},
  packet(seq){node.port.onmessage?.({data:{sequence:seq,endFrame:(seq+1)*512,sampleRate:16000,pcm:new ArrayBuffer(1024)}})},
  resolvePermission(){resolvePermission()},resolveStart(){resolveStart()},finishVoice(){playback.onended?.()}};
}
(async()=>{
 const h=harness();assert.equal(h.calls.length,0,'no microphone or network on load');await h.el('start').onclick();
 h.queued.push({events:[{type:'speech_started',utterance:1,speech_onset_sample:0,buffer_start_sample:0},
  {type:'recognition',utterance:1,final:false,text:'Paprika',name_match:true,first_detection:true,speech_onset_sample:0,snapshot_end_sample:10240,decode_ms:190,queue_wait_ms:0}]});
 h.packet(0);await h.settle();assert.equal(h.el('state').textContent,'Heard Paprika!');assert.equal(h.el('detections').textContent,1);
 h.queued.push({speech:false,events:[{type:'speech_ended',utterance:1,speech_end_sample:40000,retained_samples:52800},
  {type:'recognition',utterance:1,final:true,text:'Paprika, tell me a story about a dragon.',name_match:true,first_detection:false,speech_onset_sample:0,snapshot_end_sample:43200,decode_ms:200,queue_wait_ms:0}]});
 h.packet(1);await h.settle();assert.match(h.el('request').textContent,/dragon/);assert.equal(h.el('next').disabled,false);assert.equal(h.el('completed').textContent,1);h.el('next').onclick();assert.match(h.el('cue').textContent,/dragon/);
 await h.el('stop').onclick();assert.equal(h.track.stops,1);h.el('download').onclick();const data=JSON.parse(await h.download.text());assert.equal(data.runs[0].turns[0].activation,true);assert.equal('text' in data.runs[0].turns[0],false,'transcripts excluded by default');assert.equal(data.api_spend_usd,0);assert.equal(data.transcripts_included,false);
 h.el('include-text').checked=true;h.el('download').onclick();const withText=JSON.parse(await h.download.text());assert.match(withText.runs[0].turns[0].text,/dragon/);
 const late=harness({latePermission:true});const pending=late.el('start').onclick();await late.settle();await late.el('stop').onclick();late.resolvePermission();await pending;assert.equal(late.track.stops,1);assert.equal(late.calls.filter(c=>c.path==='/api/live-wake/start').length,0);
 const stale=harness({lateStart:true});const start=stale.el('start').onclick();await stale.settle();await stale.el('stop').onclick();stale.resolveStart();await start;assert.ok(stale.calls.some(c=>c.path==='/api/live-wake/stop'),'late backend lease explicitly stopped');assert.equal(stale.track.stops,1);
 const overloaded=harness({stallFrames:true});await overloaded.el('start').onclick();for(let i=0;i<6;i++)overloaded.packet(i);await overloaded.settle();assert.match(overloaded.el('error').textContent,/128 ms/);assert.equal(overloaded.track.stops,1);
 const echo=harness();echo.el('purpose').value='echo';echo.el('purpose').onchange();await echo.el('start').onclick();await echo.el('play').onclick();assert.match(echo.el('play-status').textContent,/playing/);echo.finishVoice();assert.match(echo.el('play-status').textContent,/finished/);await echo.el('stop').onclick();echo.el('download').onclick();const playbackData=JSON.parse(await echo.download.text());assert.equal(playbackData.runs[0].reference_trials[0].reason,'completed');assert.equal(echo.track.stops,1);
 console.log('Live UI: partial/final turns, explicit transcript export, cancelled permission, late lease and bounded transport passed');
})().catch(error=>{console.error(error);process.exitCode=1});

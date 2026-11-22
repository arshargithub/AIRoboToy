// No real microphone, cloud call or speaker output in this browser model.
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');const {webcrypto}=require('node:crypto');
const {SpeechInterruptionGate}=require('../tavi/web/interruption.js');
const {ConversationGuide,KConversationGuide}=require('../tavi/web/conversation_guide.js');
const {LocalAudioRecording}=require('../tavi/web/local-audio-recording.js');
const {ChunkAudioPrefetch}=require('../tavi/web/chunk-audio-prefetch.js');
function harness({guideMode=false,delivery='whole',finalAsr='base.en',delayAudio=false,delayAudioAfter=Infinity,latePermission=false,probability=.99,audioFrameLimit=5625,diagnosticsFailure=false,saveFailures=0}={}){
 const elements=new Map(),calls=[],contexts=[],sources=[];let node,download,permissionResolve,audioResolve,saved;
 const timers=new Map();let timerId=0;const schedule=(fn,ms)=>{timers.set(++timerId,{fn,ms});return timerId},cancel=id=>timers.delete(id);
 const track={stops:0,stop(){this.stops++},getSettings:()=>({echoCancellation:true})};
 function el(id){if(!elements.has(id))elements.set(id,{textContent:'',checked:false,disabled:false,hidden:false,value:'',dataset:{},setAttribute(k,v){this[k]=v}});return elements.get(id)}
 el('online').checked=true;el('volume').value='.35';
 const idle={revision:1,lease_active:true,engagement:'idle',input:'wake_only',output:'silent',token:null,audio:null,heard:'',reply:'',online_replies:true,spent_or_reserved_usd:0,budget_usd:25};let state={...idle};const responses=[],frameEvents=[],playedReplies=[];
 const response=value=>({ok:true,json:async()=>value});
 async function fetch(path,options={}){
  calls.push({path,options});
  if(path==='/api/conversation/save-test'){if(saveFailures-->0)throw Error('Synthetic local save failure');saved=JSON.parse(options.body);return response({saved:true,filename:'conversation-synthetic.json'})}
  if(path==='/api/conversation/start')return response({stream_id:'lease',conversation:state});
  if(path==='/api/conversation/frame'){state=responses.shift()||state;return response({sequence:0,utterance:2,probability,events:frameEvents.shift()||[],conversation:state})}
  if(path==='/api/conversation/audio'){
   if(delayAudio||calls.filter(c=>c.path==='/api/conversation/audio').length>=delayAudioAfter)return new Promise(resolve=>audioResolve=()=>resolve({ok:true,arrayBuffer:async()=>new ArrayBuffer(16)}));
   return {ok:true,arrayBuffer:async()=>new ArrayBuffer(16)};
  }
  if(path==='/api/conversation/started'){state={...state,revision:state.revision+1,output:'playing'};return response({accepted:true,conversation:state})}
  if(path==='/api/conversation/played'){state=playedReplies.shift()||{...state,revision:state.revision+1,output:'silent',audio:null};return response({accepted:true,conversation:state})}
  if(path==='/api/conversation/interrupt'){state={...idle,revision:state.revision+1,engagement:'active',input:'capturing',token:{response_id:'new'}};return response({accepted:true,conversation:state})}
  if(path==='/api/conversation/stop'){state={...idle,revision:state.revision+1};return response({stopped:true})}
  if(path==='/api/conversation/diagnostics'){if(diagnosticsFailure)throw Error('Local server unavailable');return response({model:'fake',spent_or_reserved_usd:0,budget_usd:25,metrics:[],heard:'must not export this server field'})}
  throw Error('Unexpected request '+path);
 }
 const stream={getTracks:()=>[track],getAudioTracks:()=>[track]};
 const sandbox={ChunkAudioPrefetch,KConversationGuide:class extends KConversationGuide{constructor(options){super({...options,setTimer:schedule,clearTimer:cancel})}},SpeechInterruptionGate,LocalAudioRecording:class extends LocalAudioRecording{constructor(){super(audioFrameLimit)}},Uint8Array,btoa,ConversationGuide:class extends ConversationGuide{constructor(options){super({...options,setTimer:schedule,clearTimer:cancel})}},console,crypto:webcrypto,AbortController,AbortSignal,Blob,ArrayBuffer,
  performance:{now:()=>1000},document:{body:{dataset:{mode:'guided',guide:guideMode?'k-live':'',delivery,finalAsr}},getElementById:el,createElement:()=>({click(){}})},window:{addEventListener(){}},
  URL:{createObjectURL(blob){download=blob;return 'blob:synthetic'},revokeObjectURL(){}},setTimeout:schedule,clearTimeout:cancel,setInterval(){},fetch,
  navigator:{mediaDevices:{getUserMedia(){return latePermission?new Promise(resolve=>permissionResolve=()=>resolve(stream)):Promise.resolve(stream)}}},
  AudioContext:class{constructor(){this.currentTime=1;this.sampleRate=16000;this.state='running';this.audioWorklet={addModule:async()=>{}};contexts.push(this)}resume(){return Promise.resolve()}close(){this.state='closed';return Promise.resolve()}createMediaStreamSource(){return {connect(){},disconnect(){}}}createGain(){return {gain:{value:0},connect(){},disconnect(){}}}decodeAudioData(){return Promise.resolve({duration:1})}createBufferSource(){const s={stops:0,connect(){},disconnect(){},start(){},stop(){this.stops++}};sources.push(s);return s}},
  AudioWorkletNode:class{constructor(){this.port={};node=this}connect(){}disconnect(){}}};
 vm.createContext(sandbox);vm.runInContext(fs.readFileSync('tavi/web/conversation.js','utf8'),sandbox);
 const ready={...idle,revision:5,engagement:'active',output:'ready',token:{response_id:'r1'},audio:{id:'r1',duration_ms:1000},heard:'Paprika, tell me a story about a dragon.',reply:'A little dragon sailed to the moon.',accepted_utterance:1,accepted_response_id:'r1',accepted_recognition_id:'recognition-1'};
 return {el,calls,sources,contexts,track,responses,frameEvents,playedReplies,idle,ready,get saved(){return saved},get download(){return download},async settle(){await new Promise(resolve=>setImmediate(resolve))},fireTimers(ms){for(const [id,t]of [...timers])if(t.ms===ms){timers.delete(id);t.fn()}},
  packet(seq){const endFrame=16000+(seq+1)*512;contexts.at(-1).currentTime=endFrame/16000;node.port.onmessage?.({data:{sequence:seq,endFrame,sampleRate:16000,pcm:new ArrayBuffer(1024)}})},
  finish(){sources.at(-1).onended?.()},resolveAudio(){audioResolve()},resolvePermission(){permissionResolve()}};
}
(async()=>{
 const turbo=harness({guideMode:true,delivery:'sentences',finalAsr:'turbo-mlx'});assert.match(turbo.el('guide-title').textContent,/clearer listening/);assert.match(turbo.el('page-title').textContent,/clearer listening/);await turbo.el('guide-start-no-audio').onclick();turbo.fireTimers(3000);assert.match(turbo.el('guide-phrase').textContent,/blanket/);await turbo.el('mute').onclick();await turbo.el('guide-save').onclick();assert.equal(turbo.saved.runs[0].guided_test.variant,'turbo-v1');
 const rejectedWake=harness({guideMode:true,probability:0});await rejectedWake.el('guide-start').onclick();rejectedWake.fireTimers(3000);
 rejectedWake.responses.push({...rejectedWake.idle,revision:10,input_rejection:{utterance:1,recognition_id:'rejected-name',reason:'name_missing'}});rejectedWake.packet(0);await rejectedWake.settle();
 assert.equal(rejectedWake.track.stops,1,'An unconfirmed first request must stop capture and explain recovery');assert.equal(rejectedWake.el('guide-save').disabled,false);assert.match(rejectedWake.el('guide-finished').textContent,/no need to keep repeating/);assert.equal(rejectedWake.saved,undefined,'Never auto-save a rejected recording');await rejectedWake.el('guide-save').onclick();assert.equal(rejectedWake.saved.runs[0].guided_test.input_rejection.reason,'name_missing');assert.equal(rejectedWake.saved.audio_included,true);
 const chunks=harness({guideMode:true,delivery:'sentences',probability:0});assert.match(chunks.el('guide-title').textContent,/faster conversation/);await chunks.el('guide-start-no-audio').onclick();chunks.fireTimers(3000);assert.match(chunks.el('guide-phrase').textContent,/three cushions/);
 const c0={...chunks.ready,reply_delivery:'sentences',audio:{id:'r1',sequence:0,duration_ms:1000}};
 const c1={...c0,revision:7,audio:{id:'r1',sequence:1,duration_ms:1000}};
 chunks.responses.push(c0);chunks.packet(0);await chunks.settle();assert.equal(chunks.sources.length,1);
 chunks.playedReplies.push(c1);chunks.finish();await chunks.settle();assert.equal(chunks.sources.length,2,'Next sentence must play under the same response ID');
 assert.equal(chunks.el('guide-title').textContent,'Stay quiet for this whole reply','A sentence boundary must not finish the guided reply');
 chunks.playedReplies.push({...c1,revision:9,audio:null,output:'silent',completed_response_id:'r1'});
 chunks.finish();await chunks.settle();assert.match(chunks.el('guide-title').textContent,/unwanted replies/);
 const acks=chunks.calls.filter(c=>c.path==='/api/conversation/played').map(c=>JSON.parse(c.options.body));assert.deepEqual(acks.map(c=>c.sequence),[0,1]);
 const audioCalls=chunks.calls.filter(c=>c.path==='/api/conversation/audio');assert.deepEqual(audioCalls.map(c=>c.options.headers['X-Audio-Sequence']),['0','1']);
 chunks.responses.push({...c1,revision:10});chunks.packet(1);await chunks.settle();assert.equal(chunks.sources.length,2,'Old cached chunks must never replay');
 await chunks.el('mute').onclick();
 await chunks.el('guide-save').onclick();assert.equal(chunks.saved.runs[0].guided_test.variant,'latency-v1');assert.equal(chunks.saved.audio_included,false);
 const interruptedChunks=harness();await interruptedChunks.el('start').onclick();interruptedChunks.responses.push({...interruptedChunks.ready,reply_delivery:'sentences',audio:{id:'r1',sequence:0,duration_ms:1000}});interruptedChunks.packet(0);await interruptedChunks.settle();
 interruptedChunks.el('stop-reply').onclick();await interruptedChunks.settle();assert.equal(interruptedChunks.sources[0].stops,1);
 interruptedChunks.responses.push({...interruptedChunks.ready,revision:30,reply_delivery:'sentences',audio:{id:'r1',sequence:1,duration_ms:1000}});interruptedChunks.packet(1);await interruptedChunks.settle();assert.equal(interruptedChunks.sources.length,1,'Interruption blocks every later chunk from the same response');await interruptedChunks.el('mute').onclick();
 const seam=harness({delayAudioAfter:2});await seam.el('start').onclick();const seam0={...seam.ready,reply_delivery:'sentences',audio:{id:'r1',sequence:0,duration_ms:1000}};seam.responses.push(seam0);seam.packet(0);await seam.settle();seam.playedReplies.push({...seam0,revision:7,audio:{id:'r1',sequence:1,duration_ms:1000}});seam.finish();await seam.settle();
 seam.packet(1);await seam.settle();seam.packet(2);await seam.settle();assert.equal(seam.calls.filter(c=>c.path==='/api/conversation/interrupt').length,1,'Speech must interrupt while the next chunk is loading too');seam.resolveAudio();await seam.settle();assert.equal(seam.sources.length,1,'A late chunk download cannot resume an interrupted reply');await seam.el('mute').onclick();
 const h=harness();assert.deepEqual(h.calls.map(c=>c.path),['/api/conversation/diagnostics'],'Loading only reads configured voice; it must not start capture');assert.equal(h.contexts.length,0);await h.el('start').onclick();h.responses.push(h.ready);
 h.frameEvents.push([{type:'recognition',final:true,utterance:1,recognition_id:'recognition-1',asr_run_id:'asr-1',confidence:{min_avg_logprob:-1.2},text:'NeverExportThisField'}]);
 h.packet(0);await h.settle();assert.equal(h.el('state').textContent,'Talking');assert.equal(h.sources.length,1);assert.match(h.el('you').textContent,/dragon/);h.el('review-yes').onclick();h.finish();await h.settle();assert.equal(h.el('state').textContent,'Your turn');assert.equal(h.calls.filter(c=>c.path==='/api/conversation/played').length,1);
 await h.el('mute').onclick();await h.el('download').onclick();const data=JSON.parse(await h.download.text());assert.equal(data.transcripts_included,false);assert.equal(data.accepted_text,undefined);assert.equal(data.reviews[0].rating,'correct');assert.equal(JSON.stringify(data).includes('dragon'),false);assert.equal(JSON.stringify(data).includes('must not export'),false);
 assert.equal(data.audio_included,false);assert.equal(data.runs[0].local_audio,undefined,'default capture must not retain raw audio');
 assert.equal(data.runs[0].recognition_results[0].confidence.min_avg_logprob,-1.2);
 assert.equal(data.runs[0].recognition_results[0].recognition_id,data.reviews[0].recognition_id);
 assert.equal(JSON.stringify(data).includes('NeverExport'),false,'scores must not bypass the text export choice');
 h.el('include-text').checked=true;await h.el('download').onclick();const withText=JSON.parse(await h.download.text());assert.match(withText.accepted_text[0].request,/dragon/);
 const delayed=harness({delayAudio:true});await delayed.el('start').onclick();delayed.responses.push(delayed.ready);delayed.packet(0);await delayed.settle();delayed.responses.push({...delayed.ready,revision:10,input:'capturing',output:'silent',token:{response_id:'new'},audio:null});delayed.packet(1);await delayed.settle();delayed.resolveAudio();await delayed.settle();assert.equal(delayed.sources.length,0,'obsolete fetched audio must never start');await delayed.el('mute').onclick();
 const held=harness({delayAudio:true,probability:0});await held.el('start').onclick();held.responses.push(held.ready);held.packet(0);await held.settle();
 held.responses.push({...held.ready,revision:10,pending_input:true,audio:null});held.packet(1);await held.settle();
 assert.equal(held.el('state').textContent,'Listening to you');held.resolveAudio();await held.settle();
 assert.equal(held.sources.length,0,'audio fetch must pause while a replacement is unresolved');
 held.responses.push({...held.ready,revision:11,pending_input:false});held.packet(2);await held.settle();held.resolveAudio();await held.settle();
 assert.equal(held.sources.length,1,'empty replacement must allow the same reply to play');await held.el('mute').onclick();
 const cached=harness({probability:0});await cached.el('start').onclick();cached.responses.push(cached.ready);
 cached.frameEvents.push([{type:'speech_started',utterance:2}]);cached.packet(0);await cached.settle();
 assert.equal(cached.sources.length,0,'local onset must hold an actor snapshot that has not caught up');
 cached.frameEvents.push([{type:'speech_ended',utterance:2,speech_end_sample:512}]);cached.packet(1);await cached.settle();
 assert.equal(cached.sources.length,0,'hold through final recognition, not just VAD endpoint');
 cached.frameEvents.push([{type:'recognition',utterance:2,final:true,text:''}]);cached.packet(2);await cached.settle();
 assert.equal(cached.sources.length,1);await cached.el('mute').onclick();
 const interrupted=harness();await interrupted.el('start').onclick();interrupted.responses.push(interrupted.ready);interrupted.packet(0);await interrupted.settle();interrupted.packet(1);await interrupted.settle();interrupted.packet(2);await interrupted.settle();assert.equal(interrupted.sources[0].stops,1);assert.equal(interrupted.calls.filter(c=>c.path==='/api/conversation/interrupt').length,1);assert.equal(interrupted.sources[0].onended,null);assert.equal(interrupted.calls.filter(c=>c.path==='/api/conversation/played').length,0);await interrupted.el('mute').onclick();
 await interrupted.el('download').onclick();const interruptedReport=JSON.parse(await interrupted.download.text());
 const interruptedTrace=interruptedReport.runs[0].events.find(e=>e.kind==='playback_gate_summary');
 assert.equal(interruptedTrace.ended_reason,'speech');assert.equal(interruptedTrace.buffer_duration_ms,1000);
 assert.equal(interruptedTrace.max_confirmation_frames,2);assert.equal(interruptedTrace.gate_reasons.confirmed,1);
 assert.match(interrupted.el('playback-status').textContent,/detected your interruption/);
 const unconfirmed=harness({probability:.6});await unconfirmed.el('start').onclick();unconfirmed.responses.push(unconfirmed.ready);
 for(let i=0;i<5;i++){unconfirmed.packet(i);await unconfirmed.settle()}
 assert.equal(unconfirmed.sources[0].stops,0);unconfirmed.finish();await unconfirmed.settle();
 assert.match(unconfirmed.el('playback-status').textContent,/reached its end/);
 await unconfirmed.el('mute').onclick();await unconfirmed.el('download').onclick();
 const unconfirmedTrace=JSON.parse(await unconfirmed.download.text()).runs[0].events.find(e=>e.kind==='playback_gate_summary');
 assert.equal(unconfirmedTrace.ended_reason,'source_ended');assert.equal(unconfirmedTrace.peak_probability,.6);
 assert.equal(unconfirmedTrace.max_confirmation_frames,0);assert.equal(unconfirmedTrace.gate_reasons.below_threshold,4);
 assert.equal(unconfirmedTrace.confirmed_at_ms,null);assert.equal(unconfirmedTrace.frames,4);
 assert.equal(JSON.stringify(unconfirmedTrace).includes('dragon'),false,'gate diagnostics must contain no conversation text');
 const late=harness({latePermission:true});const pending=late.el('start').onclick();await late.settle();await late.el('mute').onclick();late.resolvePermission();await pending;assert.equal(late.track.stops,1);assert.equal(late.calls.filter(c=>c.path==='/api/conversation/start').length,0);
 const stale=harness();await stale.el('start').onclick();stale.responses.push(stale.ready);stale.packet(0);await stale.settle();stale.responses.push({...stale.idle,revision:1});stale.packet(1);await stale.settle();assert.equal(stale.el('state').textContent,'Talking','older HTTP snapshots cannot override a newer playback state');await stale.el('mute').onclick();
 const guided=harness({probability:0});
 await guided.el('start').onclick();guided.responses.push({...guided.ready,token:{response_id:'private'},accepted_response_id:'private',audio:{id:'private',duration_ms:1000},heard:'Earlier private free-chat request.',reply:'Earlier private reply.'});
 guided.packet(0);await guided.settle();await guided.el('mute').onclick();
 await guided.el('guide-start').onclick();assert.match(guided.el('guide-title').textContent,/Say this/);
 guided.responses.push({...guided.ready,revision:20});guided.frameEvents.push([{type:'recognition',final:true,utterance:1,recognition_id:'recognition-1',audio_start_sample:0,audio_samples:512}]);guided.packet(0);await guided.settle();assert.match(guided.el('guide-title').textContent,/Get ready/);
 guided.fireTimers(1500);assert.equal(guided.el('guide-title').textContent,'Speak now');
 guided.el('stop-reply').onclick();await guided.settle();
 guided.responses.push({...guided.ready,revision:40,token:{response_id:'r2'},accepted_response_id:'r2',accepted_recognition_id:'recognition-2',heard:'Wait, make it a space adventure instead.',reply:'A dragon explores Mars.',audio:{id:'r2',duration_ms:1000}});
 guided.frameEvents.push([{type:'recognition',final:true,utterance:2,recognition_id:'recognition-2',audio_start_sample:512,audio_samples:512}]);
 guided.packet(1);await guided.settle();assert.match(guided.el('guide-title').textContent,/Listen to the new/);guided.finish();await guided.settle();
 assert.equal(guided.track.stops,2,'guided completion must mute the second capture without a separate button');assert.equal(guided.el('guide-word-review').hidden,false);
 assert.equal(guided.el('guide-word-next').disabled,true);assert.equal(guided.el('guide-review').hidden,true);
 assert.equal(guided.el('guide-word-audio').hidden,false,'word review should offer its own local listening copy');
 assert.match(guided.el('guide-word-prompt').textContent,/Paprika/);guided.el('guide-words-yes').onclick();guided.el('guide-word-next').onclick();
 assert.match(guided.el('guide-word-prompt').textContent,/space/);guided.el('guide-words-no').onclick();guided.el('guide-word-next').onclick();assert.equal(guided.el('guide-review').hidden,false);
 assert.equal(guided.el('guide-save').disabled,true,'the test must ask the person what happened');guided.el('guide-problem').onclick();
 guided.el('guide-note').value='The beginning was missing.';await guided.el('guide-save').onclick();
 const guidedText=JSON.parse(await guided.download.text());assert.equal(guidedText.transcripts_included,true);assert.equal(guidedText.runs.length,1);assert.equal(guidedText.accepted_text.length,2);
 assert.equal(JSON.stringify(guidedText).includes('Earlier private'),false,'guided export must exclude earlier free-chat text');
 assert.equal(guidedText.runs[0].guided_test.first_playback_end,'manual','a button stop cannot masquerade as speech interruption');
 assert.equal(guidedText.runs[0].guided_test.note,'The beginning was missing.');
 assert.equal(guidedText.reviews.length,2);assert.equal(guidedText.reviews[1].rating,'incorrect_or_incomplete');
 assert.equal(guidedText.reviews[1].recognition_id,'recognition-2');
 assert.equal(guided.el('guide-save-again').hidden,false);await guided.el('guide-save-again').onclick();assert.equal(JSON.parse(await guided.download.text()).runs.length,1);
 const noWords=harness();await noWords.el('guide-start').onclick();noWords.fireTimers(30000);await noWords.settle();
 noWords.el('guide-problem').onclick();noWords.el('guide-note').value='Private note';await noWords.el('guide-save-private').onclick();
 const privateReport=JSON.parse(await noWords.download.text());assert.equal(privateReport.transcripts_included,false);assert.equal(privateReport.runs[0].guided_test.note,'');assert.equal(JSON.stringify(privateReport).includes('Private note'),false);
 const recorded=harness({probability:0,diagnosticsFailure:true});await recorded.el('guide-start').onclick();
 recorded.packet(0);await recorded.settle();recorded.packet(1);await recorded.settle();recorded.el('guide-stop').onclick();await recorded.settle();recorded.el('guide-unsure').onclick();
 await recorded.el('guide-save').onclick();const savedAudio=JSON.parse(await recorded.download.text());
 assert.equal(savedAudio.audio_included,true);assert.equal(savedAudio.runs[0].local_audio.sample_count,1024);assert.equal(Buffer.from(savedAudio.runs[0].local_audio.pcm_base64,'base64').length,2048);
 assert.equal(savedAudio.runs[0].local_audio.start_context_frame,16000);assert.equal(savedAudio.runs[0].local_audio.closed,true);
 assert.match(savedAudio.server.unavailable,/unavailable/,'local results must remain saveable after a backend failure');
 assert.ok(recorded.calls.every(c=>!c.path.includes('upload')),'local recording cannot introduce an upload endpoint');
 await recorded.el('start').onclick();recorded.packet(0);await recorded.settle();await recorded.el('mute').onclick();recorded.el('include-text').checked=true;await recorded.el('download').onclick();
 const laterFreeChat=JSON.parse(await recorded.download.text());assert.equal(laterFreeChat.audio_included,false);assert.ok(laterFreeChat.runs.every(run=>!run.local_audio),'free-chat export must not inherit earlier guided audio');
 const timings=harness({probability:0});await timings.el('guide-start').onclick();timings.packet(0);await timings.settle();timings.el('guide-stop').onclick();await timings.settle();timings.el('guide-unsure').onclick();await timings.el('guide-save-private').onclick();
 const timingsOnly=JSON.parse(await timings.download.text());assert.equal(timingsOnly.audio_included,false);assert.equal(timingsOnly.transcripts_included,false);assert.equal(JSON.stringify(timingsOnly).includes('pcm_base64'),false);
 const without=harness({probability:0});await without.el('guide-start-no-audio').onclick();without.packet(0);await without.settle();without.el('guide-stop').onclick();await without.settle();without.el('guide-unsure').onclick();await without.el('guide-save').onclick();assert.equal(JSON.parse(await without.download.text()).audio_included,false,'the no-recording choice must remain fully functional');
 const free=harness({probability:0});await free.el('start').onclick();free.packet(0);await free.settle();await free.el('mute').onclick();await free.el('download').onclick();assert.equal(JSON.parse(await free.download.text()).audio_included,false,'ordinary free chat does not record');
 const limited=harness({probability:0,audioFrameLimit:2});await limited.el('guide-start').onclick();
 for(let i=0;i<3;i++){limited.packet(i);await limited.settle()}
 assert.equal(limited.track.stops,1);assert.match(limited.el('error').textContent,/recording limit/);assert.equal(limited.el('guide-review').hidden,false);
 limited.el('guide-problem').onclick();await limited.el('guide-save').onclick();const partialAudio=JSON.parse(await limited.download.text());
 assert.equal(partialAudio.runs[0].local_audio.limit_reached,true);assert.equal(partialAudio.runs[0].local_audio.sample_count,1024);
 const k=harness({guideMode:true,probability:0});await k.el('guide-start-no-audio').onclick();
 assert.match(k.el('guide-title').textContent,/unwanted replies/);k.fireTimers(3000);assert.match(k.el('guide-phrase').textContent,/cardboard box/);
 for(let i=0;i<5;i++){
  const rid='k-'+i;k.responses.push({...k.ready,revision:100+i*20,token:{response_id:rid},accepted_response_id:rid,accepted_recognition_id:'kr-'+i,heard:'Synthetic request '+i,reply:'Synthetic reply '+i,audio:{id:rid,duration_ms:1000}});
  k.packet(i);await k.settle();
  if(i===2){assert.match(k.el('guide-title').textContent,/Get ready/);k.fireTimers(1500);assert.equal(k.el('guide-title').textContent,'Speak now');k.el('stop-reply').onclick();await k.settle();
   // A manual stop is deliberately not accepted as a speech-interruption pass.
   assert.equal(k.el('guide-review').hidden,false);assert.equal(k.el('guide-save').disabled,false);k.el('guide-check-words').onclick();break;}
  k.finish();await k.settle();assert.match(k.el('guide-title').textContent,/unwanted replies/);k.fireTimers(2000);
 }
 for(let i=0;i<3;i++){k.el('guide-words-yes').onclick();k.el('guide-word-next').onclick();}
 k.el('guide-problem').onclick();await k.el('guide-save').onclick();
 const kr=k.saved;assert.equal(kr.runs[0].guided_test.protocol,'k-live-conversation-v1');assert.equal(kr.runs[0].guided_test.completed,false);assert.equal(kr.accepted_text.length,3);assert.equal(kr.runs[0].guided_test.steps[2].playback_end,'manual');assert.equal(kr.audio_included,false);
 const vf=harness({guideMode:true,probability:0});await vf.el('guide-start-no-audio').onclick();vf.fireTimers(3000);
 vf.responses.push({...vf.ready,revision:100,token:null,audio:null,accepted_response_id:'voice-failed',heard:'Paprika, what can we make with a cardboard box?',error:'Local voice unavailable',failure:{component:'speech',code:'unsupported_phoneme',response_id:'voice-failed'}});vf.packet(0);await vf.settle();
 assert.equal(vf.track.stops,1,'Voice failure must immediately mute capture');assert.equal(vf.el('guide-review').hidden,false);assert.equal(vf.el('guide-save').disabled,false);vf.el('guide-check-words').onclick();assert.match(vf.el('guide-word-heard').textContent,/cardboard/);assert.match(vf.el('guide-title').textContent,/Check what K heard/);
 vf.el('guide-words-yes').onclick();vf.el('guide-word-next').onclick();vf.el('guide-problem').onclick();await vf.el('guide-save').onclick();const vfr=vf.saved;assert.equal(vfr.runs[0].guided_test.failure.code,'unsupported_phoneme');assert.equal(vfr.accepted_text.length,1);assert.equal(vfr.audio_included,false);
 const quick=harness({guideMode:true,probability:0,saveFailures:1});await quick.el('guide-start').onclick();quick.packet(0);await quick.settle();quick.el('guide-stop').onclick();await quick.settle();
 assert.equal(quick.saved,undefined,'Never save during capture or automatically at completion');assert.equal(quick.el('guide-save').disabled,false,'Save must be available without feedback or word labels');await quick.el('guide-save').onclick();assert.equal(quick.saved,undefined);assert.match(quick.el('error').textContent,/results are still here/);await quick.el('guide-save').onclick();assert.equal(quick.saved.audio_included,true);assert.equal(quick.saved.runs[0].guided_test.result,null);assert.deepEqual(quick.saved.local_save_consent,{destination:'project_private_local',explicit_save:true});assert.equal(quick.download,undefined,'Local save does not depend on a download');
 const privateK=harness({guideMode:true,probability:0});await privateK.el('guide-start').onclick();privateK.packet(0);await privateK.settle();privateK.el('guide-stop').onclick();await privateK.settle();await privateK.el('guide-save-private').onclick();assert.equal(privateK.saved.audio_included,false);assert.equal(privateK.saved.transcripts_included,false);await privateK.el('guide-download-copy').onclick();const pk=JSON.parse(await privateK.download.text());assert.equal(pk.audio_included,false);assert.equal(pk.transcripts_included,false,'Download copy must preserve a timings-only privacy choice');
 console.log('Guided UI: timed cue, automatic mute, explicit human result and private export passed');
 console.log('Conversation UI: actual playback states, whole-request reviews, private exports, stale audio, barge-in and late permission passed');
})().catch(error=>{console.error(error);process.exitCode=1});

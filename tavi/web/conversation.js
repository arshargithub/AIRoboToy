'use strict';
const $=id=>document.getElementById(id),requests=new Set(),blocked=new Set();
const gate=new SpeechInterruptionGate(.65,2),runs=[],reviews=[],turnTexts=new Map(),speechEnds=new Map();
const pendingSpeech=new Set();
const audioPrefetch=new ChunkAudioPrefetch();
let ctx=null,mic=null,node=null,input=null,sink=null,lease=null,active=false,starting=false,gen=0,queue=[],sending=false;
let source=null,outputGain=null,playingId=null,loadingId=null,loadVersion=0,latest=null,currentRun=null,lastPacket=0,lastContact=0,origin=null,reviewId=null;
let playbackTrace=null;
let chunkReplyId=null;const playedChunks=new Set();
let guideRun=null;
let diagnosticAudio=null;
let guidedAudioOptIn=false,lastGuideSaveIncludeText=true,lastGuideStage=null,lastDownloadName=null;
let wordAudioUrl=null,wordAudioKey=null;
function clearWordAudio(){
 $('guide-word-audio').pause?.();$('guide-word-audio').removeAttribute?.('src');
 if(wordAudioUrl)URL.revokeObjectURL(wordAudioUrl);wordAudioUrl=null;wordAudioKey=null;
}
function renderWordAudio(item){
 if(wordAudioKey===item.response_id)return;
 clearWordAudio();wordAudioKey=item.response_id;$('guide-word-audio').hidden=true;
 const rid=turnTexts.get(item.response_id)?.recognition_id;
 const event=guideRun?.recognition_results.find(e=>rid&&e.recognition_id===rid);
 const recorder=diagnosticAudio?.run===guideRun?diagnosticAudio.recorder:null;
 if(!recorder||!event||!Number.isInteger(event.audio_start_sample)||!Number.isInteger(event.audio_samples)){
  text('guide-word-audio-help','A listening copy is not available for this request. Check the words you remember, or choose Not sure.');return;
 }
 try{
  const copy=recorder.listeningWave(Math.max(0,event.audio_start_sample-16000),Math.min(recorder.frames.length*512,event.audio_start_sample+event.audio_samples+3200));
  wordAudioUrl=URL.createObjectURL(copy.blob);$('guide-word-audio').src=wordAudioUrl;$('guide-word-audio').hidden=false;
  text('guide-word-audio-help',`Optional: play your captured voice if you need to check. This listening copy includes surrounding sound and uses ${copy.gain.toFixed(1)}× gain; the saved recording is unchanged.`);
 }catch(error){text('guide-word-audio-help','The listening copy is unavailable. Your saved diagnostics will include the available recording and the missing bounds.');}
}
const guide=new (document.body.dataset.guide==='k-live'?KConversationGuide:ConversationGuide)({render:renderGuide,
 startCapture:async()=>{await $('start').onclick();guideRun=currentRun;if(guideRun)guideRun.guided_test=guide.data;renderGuide(guide);return active;},
 stopCapture:()=>mute('Test finished · microphone off'),
 checkpoint:stage=>json('/api/conversation/learning-checkpoint',{method:'POST',headers:{'Content-Type':'application/json','X-Audio-Stream':lease},body:JSON.stringify({checkpoint:stage})},15000)});
if(document.body.dataset.delivery==='sentences')guide.variant='latency-v1';
if(document.body.dataset.finalAsr==='turbo-mlx')guide.variant='turbo-v1';
if(document.body.dataset.memoryPilot==='true')guide.variant='memory-v1';
if(document.body.dataset.learningPilot==='true')guide.variant='learning-v1';
function canSaveGuide(g){return !!g.data&&['review','check_words','saved'].includes(g.stage)&&(g.data.protocol==='k-live-conversation-v1'||!!g.data.result)&&(!(['memory-v1','learning-v1'].includes(g.variant)&&g.data.completed)||!!g.data.result&&!!g.data.wait_rating);}
function renderGuide(g){
 const optionalReview=g.data?.protocol==='k-live-conversation-v1';
 const copy=g.copy?.()||{
  setup:['1 of 5 · Get ready','Check interruption and sound','About one minute. Ask for a story, interrupt when the card says Speak now, then check the words and save your result here.',''],
  starting:['1 · Get ready','Starting Paprika…','Allow microphone access if asked. Wait here while the local model gets ready.',''],
  call:['2 · Ask for a story','Say this to Paprika','Speak naturally. Say the whole sentence without pausing after the name.','Paprika, tell me a short story about a dragon.'],
  waiting_story:['2 · Ask for a story','Wait for the story','Stay quiet while Paprika prepares its reply. This may take a few seconds.',''],
  get_ready:['3 · Interrupt','Get ready…','Don’t speak yet. The card will change when it’s your turn.','Wait, make it a space adventure instead.'],
  interrupt:['3 · Interrupt','Speak now','Say the whole sentence, even if Paprika stops halfway through.','Wait, make it a space adventure instead.'],
  waiting_replacement:['3 · Interrupt','Finish your sentence, then listen','If you have finished speaking, stay quiet and wait for the new story.','Wait, make it a space adventure instead.'],
  listen:['3 · Interrupt','Listen to the new story','Stay quiet. We’ll turn the microphone off when the reply ends.',''],
  check_words:['4 of 5 · Check the words','Check what Paprika heard','The microphone is off. Compare the words below with what you actually said. Choose an answer, then continue.',''],
  review:['5 of 5 · Save your result','How did the conversation go?','The microphone is off. Choose one answer below, then save this attempt—even if something went wrong.',''],
  saved:['Finished','Download started','When the file appears in Downloads, tell the assistant “Downloaded”. If you cannot find it, use Save again below.','']
 }[g.stage];
 if(g.stage==='review'&&!(g.data?.completed||g.data?.replacement_playback_end)){copy[1]='Test stopped · save this attempt';copy[2]=optionalReview?'The microphone is off. Save this partial attempt now; feedback below is optional.':'The microphone is off. Choose what happened and save the partial result below before trying again. The reason is shown below.';}
 text('guide-step',copy[0]);text('guide-title',copy[1]);text('guide-help',copy[2]);text('guide-phrase',copy[3]);
 $('guide-phrase').hidden=!copy[3];$('guide-card').dataset.stage=g.stage;
 $('guide-start').hidden=g.stage!=='setup';$('guide-start-no-audio').hidden=g.stage!=='setup';
 $('guide-stop').hidden=!g.running;$('guide-review').hidden=!(g.stage==='review'||optionalReview&&g.stage==='check_words');
 $('guide-open-chat').hidden=g.stage!=='setup';
 $('guide-recording-choice').hidden=g.stage!=='setup';$('guide-prep').hidden=g.stage!=='setup';
 $('guide-save-again').hidden=g.stage!=='saved';$('guide-new-test').hidden=g.stage!=='saved';
 $('guide-word-review').hidden=g.stage!=='check_words';
 $('guide-check-words').hidden=!optionalReview||g.stage!=='review'||!g.data.word_reviews.length;
 $('guide-download-copy').hidden=!optionalReview||!['review','check_words','saved'].includes(g.stage);
 const wordItem=g.currentWords();
 if(wordItem){
  renderWordAudio(wordItem);
  text('guide-word-count',`Request ${g.wordIndex+1} of ${g.data.word_reviews.length}`);
  text('guide-word-prompt',wordItem.prompt||(wordItem.position==='first'?'Paprika, tell me a short story about a dragon.':'Wait, make it a space adventure instead.'));
  text('guide-word-heard',turnTexts.get(wordItem.response_id)?.request||'No complete text is available. Choose Not sure.');
  for(const [id,rating] of [['guide-words-yes','correct'],['guide-words-no','incorrect_or_incomplete'],['guide-words-unsure','unknown']])$(id).setAttribute('aria-pressed',String(wordItem.rating===rating));
  $('guide-word-next').disabled=active||starting||!wordItem.rating;
  text('guide-word-next',g.wordIndex+1<g.data.word_reviews.length?'Next request':'Next: conversation result');
 }else if(wordAudioUrl||wordAudioKey)clearWordAudio();
 if(['memory-v1','learning-v1'].includes(g.variant)){for(const [id,value] of [['pilot-wait-ok','usable'],['pilot-wait-not','disruptive'],['pilot-wait-unsure','unknown']])$(id).setAttribute('aria-pressed',String(g.data?.wait_rating===value));}
 const audioEnabled=!!guideRun?.local_audio_recording?.enabled&&g.stage!=='setup';
 const hasAudio=audioEnabled&&diagnosticAudio?.run===guideRun&&diagnosticAudio.recorder.frames.length>0;
 text('guide-save',optionalReview?(hasAudio?'Save results + local audio':'Save results on this Mac'):hasAudio?'Save results + local audio':g.data?.replacement_playback_end?'Save test results':'Save partial results');
 text('guide-save-help',optionalReview?(hasAudio?'Saves this test’s recording, words and timings in the project’s private local folder for analysis. Nothing is uploaded.':'Saves this test’s words and timings in the project’s private local folder for analysis. No microphone audio was retained.'):hasAudio?'Downloads this test’s microphone recording, words, replies, scores and timings. Audio stays on this Mac.':'Downloads the available words, reviews, timings and error details. No microphone audio was retained.');
 $('guide-save').disabled=active||starting||!canSaveGuide(g);
 $('guide-save-private').disabled=active||starting||!canSaveGuide(g);
 for(const result of ['worked','problem','unsure'])$('guide-'+result).setAttribute('aria-pressed',String(g.data?.result===result));
 $('guide-note-label').hidden=optionalReview?false:g.data?.result!=='problem';
 text('guide-heard',turnTexts.get(g.data?.replacement_response_id)?.request||'No replacement request was accepted.');
 text('guide-finished',g.stage==='review'?(g.data?.finished_reason||''):'');
 text('guide-outcome-question',g.variant==='learning-v1'?'Did Paprika suggest gliders first and stick bridges after the change? Mention wrong or invented memories and how the replies felt.':['memory-v1','learning-v1'].includes(g.variant)?'Did the replies feel personal and relevant? Mention incorrect memories, repetitive suggestions, missed follow-ups, interruptions, or waits that broke the flow.':g.data?.variant==='turbo-v1'?'Did Paprika hear each whole request, finish quiet replies, and stop for your interruption? Mention missed words, long waits, unwanted stops or pauses in the voice.':g.data?.variant==='latency-v1'?'Did K start promptly, speak smoothly through sentence boundaries, finish quiet replies and stop when you interrupted? Mention awkward pauses, missing words or changes in the voice below.':g.data?.protocol==='k-live-conversation-v1'?'Did quiet replies finish, follow-ups work without the name, and the interruption switch the story? Include slow responses or unwanted replies in your note.':g.data?.replacement_playback_end?'Did Paprika stop when you spoke and switch to a space story?':'This attempt ended early. Choose Something went wrong if there was a problem, or Not sure if you stopped before you could judge.');
 text('guide-download-name',g.stage==='saved'&&lastDownloadName?(optionalReview?lastDownloadName:'File: '+lastDownloadName):'');
 if(lastGuideStage!==g.stage&&g.stage!=='setup')$('guide-card').scrollIntoView?.({block:'start',behavior:'smooth'});
 lastGuideStage=g.stage;
}
function finishPlaybackTrace(reason){
 if(!playbackTrace)return;
 const elapsed=(ctx.currentTime-playbackTrace.started_context_seconds)*1000;
 currentRun.events.push({kind:'playback_gate_summary',...playbackTrace,ended_reason:reason,
  elapsed_audio_ms:Math.round(elapsed),at:performance.now()});
 playbackTrace=null;
}
function inspectInterruption(packet,result){
 const accepted=gate.accept(packet,result,ctx.sampleRate,ctx.currentTime),trace=playbackTrace;
 if(trace){
  trace.frames++;trace.peak_probability=Math.max(trace.peak_probability,result.probability);
  trace.gate_reasons[gate.reason]=(trace.gate_reasons[gate.reason]||0)+1;
  trace.max_confirmation_frames=Math.max(trace.max_confirmation_frames,gate.high);
  const at=Math.round((packet.endFrame/ctx.sampleRate-trace.started_context_seconds)*1000);
  if(result.probability>=.5&&trace.first_vad_candidate_ms===null)trace.first_vad_candidate_ms=at;
  if(gate.reason==='confirmed'&&trace.confirmed_at_ms===null)trace.confirmed_at_ms=at;
 }
 return accepted;
}
function text(id,value){if($(id).textContent!==String(value))$(id).textContent=value;if(id==='error'&&$('guide-error'))$('guide-error').textContent=value;}
function controls(){
 $('start').disabled=active||starting;$('mute').disabled=!active&&!starting;
 $('stop-reply').disabled=!active||(!source&&!latest?.audio&&!['generating','ready'].includes(latest?.output));
 $('end').disabled=!active||latest?.engagement!=='active';$('download').disabled=active||starting||runs.length===0;
 $('online').disabled=starting;
 $('guide-save').disabled=active||starting||!canSaveGuide(guide);
 $('guide-save-private').disabled=active||starting||!canSaveGuide(guide);
 $('guide-start').disabled=active||starting||guide.running;$('guide-start-no-audio').disabled=active||starting||guide.running;
 if(diagnosticAudio?.run===currentRun){
  text('local-audio-status',active?'Local microphone recording on · saved only when you choose results + audio':'Local microphone recording stopped · ready to save');
  $('local-audio-status').hidden=false;
 }else $('local-audio-status').hidden=true;
}
function face(){
 let kind='off',title='Microphone off',help='Start when you’re ready.',listening='Not listening';
 if(starting){kind='thinking';title='Starting Paprika';help='Allow microphone access if asked. The local model may take a moment.';}
 else if(active){
  listening=latest?.engagement==='active'?'Listening too · you can interrupt':'Listening locally for Paprika';
  if(source){kind='talking';title='Talking';help='You can speak over me to interrupt.';}
  else if(latest?.input==='capturing'||latest?.pending_input||(latest?.engagement==='active'&&pendingSpeech.size)){kind='listening';title='Listening to you';help='Keep speaking naturally.';}
  else if(['generating','ready'].includes(latest?.output)||loadingId){kind='thinking';title='Thinking';help=latest?.output==='ready'?'Preparing the voice.':'Working on your reply.';}
  else if(latest?.engagement==='active'){kind='listening';title='Your turn';help='No need to say Paprika again.';}
  else{kind='listening';title='Listening for Paprika';help='Call my name to begin.';}
 }
 if($('face-card').dataset.state!==kind)$('face-card').dataset.state=kind;
 text('state',title);text('status-help',help);text('input-state',listening);controls();
}
async function json(path,options={},timeout=1000){
 const controller=new AbortController();requests.add(controller);const timer=setTimeout(()=>controller.abort(),timeout);
 try{const response=await fetch(path,{...options,signal:controller.signal});const data=await response.json();if(!response.ok)throw Error(data.error||'Local conversation request failed');return data;}
 catch(error){error.stage=path;throw error;}finally{clearTimeout(timer);requests.delete(controller);}
}
function block(id){if(id)blocked.add(id);while(blocked.size>80)blocked.delete(blocked.values().next().value);}
function clearOutput(reason){
 audioPrefetch.clear();
 const id=playingId||loadingId||chunkReplyId;if(reason!=='checking_new_speech')chunkReplyId=null;loadVersion++;loadingId=null;
 finishPlaybackTrace(reason);
 if(source){source.onended=null;try{source.stop()}catch{}source.disconnect();source=null;}
 if(outputGain){outputGain.disconnect();outputGain=null;}playingId=null;block(id);
 if(currentRun&&id)currentRun.events.push({kind:'local_audio_stopped',response_id:id,reason,at:performance.now()});
 if(id)text('playback-status',reason==='speech'?'Stopped because I detected your interruption.':reason==='manual'?'Reply stopped with the button.':'Reply stopped · '+reason.replaceAll('_',' '));
 if(id&&!['checking_new_speech','mute','new capture'].includes(reason))guide.playbackEnded(id,reason);
 return id;
}
async function mute(message='Microphone off'){
 const oldLease=lease,oldContext=ctx;gen++;active=false;starting=false;queue=[];lease=null;
 requests.forEach(c=>c.abort());clearOutput('mute');
 ctx=null;
 if(node){node.port.onmessage=null;node.disconnect();node=null;}if(input){input.disconnect();input=null;}if(sink){sink.disconnect();sink=null;}
 if(mic){mic.getTracks().forEach(t=>{t.onended=null;t.stop()});mic=null;}
 if(diagnosticAudio?.run===currentRun){diagnosticAudio.recorder.close();currentRun.local_audio_recording={...currentRun.local_audio_recording,...diagnosticAudio.recorder.metadata()};}
 if(currentRun&&!currentRun.ended_at){currentRun.ended_at=new Date().toISOString();currentRun.duration_ms=currentRun.started_ms===null?0:performance.now()-currentRun.started_ms;}
 face();text('status-help',message);
 if(oldLease)fetch('/api/conversation/stop',{method:'POST',headers:{'X-Audio-Stream':oldLease},signal:AbortSignal.timeout(1000)}).catch(()=>{});
 if(oldContext)await oldContext.close();
 if(guide.running)guide.finish(message,false);
}
async function fail(error){
 if(currentRun)currentRun.faults.push({message:error.message,stage:error.stage||'endpoint',at:new Date().toISOString()});
 text('error',error.message);await mute('Stopped · '+error.message);
}
async function action(command,body={}){
 const captured=gen;
 try{const result=await json('/api/conversation/'+command,{method:'POST',headers:{'Content-Type':'application/json','X-Audio-Stream':lease},body:JSON.stringify(body)},command==='online'?20000:1000);
  if(active&&gen===captured&&result.conversation)reconcile(result.conversation);return result;
 }catch(error){if(gen===captured)await fail(error);}
}
function stopReply(utterance=null){
 const id=playingId||loadingId||latest?.token?.response_id;
 clearOutput(utterance===null?'manual':'speech');block(id);face();
 if(active&&id)action('interrupt',{response_id:id,utterance});
}
function reconcile(state){
 if(latest&&Number.isFinite(latest.revision)&&state.revision<latest.revision)return;
 latest=state;
 text('voice-name',state.voice||'Mac Samantha (local)');
 if(!state.lease_active){fail(Error('Conversation lease expired'));return;}
 const liveId=state.token?.response_id;
 if(playingId&&playingId!==liveId)clearOutput('server_cancelled');
 if(loadingId&&loadingId!==liveId)clearOutput('obsolete_audio');
 if(chunkReplyId&&chunkReplyId!==liveId&&state.completed_response_id!==chunkReplyId)clearOutput('server_cancelled');
 if(loadingId&&(state.pending_input||pendingSpeech.size)){const heldId=clearOutput('checking_new_speech');blocked.delete(heldId);}
 text('you',state.heard||'');text('reply',state.reply||'');
 text('budget',`Spent or conservatively reserved: $${state.spent_or_reserved_usd.toFixed(4)} of $${state.budget_usd.toFixed(2)}`);
 text('error',state.error||'');
 const acceptedId=state.accepted_response_id;
 if(state.heard&&acceptedId&&(acceptedId===liveId||state.failure?.response_id===acceptedId)){
  turnTexts.set(acceptedId,{request:state.heard,reply:state.reply||'',recognition_id:state.accepted_recognition_id??null});while(turnTexts.size>50)turnTexts.delete(turnTexts.keys().next().value);
  if(reviewId!==acceptedId){reviewId=acceptedId;$('review').hidden=false;for(const id of ['review-yes','review-no','review-unsure'])$(id).setAttribute('aria-pressed','false');}
  guide.accepted(acceptedId);
 }
 guide.observe?.(state);
 if(chunkReplyId&&state.completed_response_id===chunkReplyId&&!playingId&&!loadingId){
  const id=chunkReplyId;chunkReplyId=null;block(id);
  currentRun.events.push({kind:'playback_ended',response_id:id,at:performance.now()});
  text('playback-status','Reply audio reached its end.');guide.playbackEnded(id,'source_ended');
 }
 text('details',JSON.stringify({engagement:state.engagement,input:state.input,output:source?'playing_in_browser':state.output,
  connectivity:state.connectivity,online_replies:state.online_replies,session_seconds_left:state.remaining_session_seconds,
  recognition_models:state.asr_models??null,reply_delivery:state.reply_delivery??'whole',
  max_waiting_frames:currentRun?.max_queue||0,transport:currentRun?.transport||{},notice:state.notice},null,2));
 if(active&&state.audio&&!state.pending_input&&!pendingSpeech.size&&!blocked.has(state.audio.id)&&!playedChunks.has(`${state.audio.id}:${state.audio.sequence}`)&&!playingId&&!loadingId)playAudio(state.audio,state.accepted_utterance);
 if(active&&source&&!state.pending_input&&!pendingSpeech.size&&state.prefetch_audio?.id===playingId){
  const context=ctx,stream=lease;
  audioPrefetch.offer(state.prefetch_audio,`${gen}:${stream}`, (audio,signal)=>loadAudioBuffer(audio,context,stream,signal));
 }else if(state.pending_input||pendingSpeech.size){audioPrefetch.clear();}
 face();
}
async function loadAudioBuffer(audio,context,stream,signal){
 const headers={'X-Audio-Stream':stream,'X-Response-Id':audio.id};
 if(Number.isInteger(audio.sequence))headers['X-Audio-Sequence']=String(audio.sequence);
 const response=await fetch('/api/conversation/audio',{headers,signal:signal??AbortSignal.timeout(3000)});
 if(!response.ok)throw Error('Reply audio expired before playback');
 return context.decodeAudioData(await response.arrayBuffer());
}
async function playAudio(audio,utterance){
 const captured=gen,version=++loadVersion,context=ctx;loadingId=audio.id;face();
 try{
  let buffer=await audioPrefetch.take(audio,`${captured}:${lease}`);
  if(captured!==gen||version!==loadVersion||!active||blocked.has(audio.id))return;
  if(!buffer)buffer=await loadAudioBuffer(audio,context,lease);
  if(captured!==gen||version!==loadVersion||!active||blocked.has(audio.id)||latest?.token?.response_id!==audio.id)return;
  source=context.createBufferSource();source.buffer=buffer;outputGain=context.createGain();outputGain.gain.value=Number($('volume').value);source.connect(outputGain);outputGain.connect(context.destination);
  const chunked=Number.isInteger(audio.sequence),first=!chunked||chunkReplyId!==audio.id;
  if(chunked)chunkReplyId=audio.id;
  playingId=audio.id;loadingId=null;if(first)gate.reset(context.currentTime);
  playbackTrace={response_id:audio.id,sequence:audio.sequence??null,started_context_seconds:context.currentTime,
   buffer_duration_ms:Math.round(buffer.duration*1000),advertised_duration_ms:audio.duration_ms,
   frames:0,peak_probability:0,max_confirmation_frames:0,first_vad_candidate_ms:null,
   confirmed_at_ms:null,gate_reasons:{}};
  source.onended=async()=>{
   if(captured!==gen||playingId!==audio.id)return;
   finishPlaybackTrace('source_ended');text('playback-status',chunked?'Continuing the reply…':'Reply audio reached its end.');
   source.disconnect();source=null;outputGain.disconnect();outputGain=null;playingId=null;
   if(chunked){
    playedChunks.add(`${audio.id}:${audio.sequence}`);while(playedChunks.size>160)playedChunks.delete(playedChunks.values().next().value);
    currentRun.events.push({kind:'playback_chunk_ended',response_id:audio.id,sequence:audio.sequence,at:performance.now()});
    await action('played',{response_id:audio.id,sequence:audio.sequence});return;
   }
   block(audio.id);
   currentRun.events.push({kind:'playback_ended',response_id:audio.id,at:performance.now()});face();await action('played',{response_id:audio.id});
   if(captured===gen)guide.playbackEnded(audio.id,'source_ended');
  };
  source.start();
  if(first)guide.playbackStarted(audio.id);
  text('playback-status','Reply playing · speak to interrupt.');
  const speechEnd=speechEnds.get(utterance);
  currentRun.events.push({kind:first?'playback_started':'playback_chunk_started',response_id:audio.id,sequence:audio.sequence??null,at:performance.now(),
   estimated_ms_since_vad_speech_end:speechEnd===undefined?null:(context.currentTime-(origin+speechEnd)/16000)*1000});
  face();action('started',{response_id:audio.id,...(chunked?{sequence:audio.sequence}:{})});
 }catch(error){if(captured===gen&&version===loadVersion)await fail(error);}
 finally{if(version===loadVersion)loadingId=null;}
}
async function pump(){
 if(sending||!active)return;sending=true;const captured=gen;
 try{while(active&&captured===gen&&queue.length){
  const packet=queue.shift(),start=performance.now();
  const result=await json('/api/conversation/frame',{method:'POST',headers:{'Content-Type':'application/octet-stream','X-Audio-Stream':lease,'X-Audio-Sequence':String(packet.sequence)},body:packet.pcm});
  if(!active||captured!==gen)break;lastContact=performance.now();
  const rtt=lastContact-start,t=currentRun.transport;t.frames++;t.sum_rtt_ms+=rtt;t.max_rtt_ms=Math.max(t.max_rtt_ms,rtt);
  const bucket=[5,10,20,50,100,200,Infinity].findIndex(limit=>rtt<=limit);t.rtt_buckets[bucket]++;
  for(const e of result.events){
   if(e.type==='recognition'&&e.final){
    currentRun.recognition_results.push({utterance:e.utterance,asr_run_id:e.asr_run_id,recognition_id:e.recognition_id,
     address_verification:e.address_verification??null,
     confidence:e.confidence??null,audio_start_sample:e.audio_start_sample,audio_samples:e.audio_samples,
     worker_timing:e.worker_timing??null,
     speech_onset_sample:e.speech_onset_sample,snapshot_end_sample:e.snapshot_end_sample,
     decode_ms:e.decode_ms,queue_wait_ms:e.queue_wait_ms,job_age_ms:e.job_age_ms,deadline_remaining_ms:e.deadline_remaining_ms});
    if(currentRun.recognition_results.length>120){currentRun.recognition_results.shift();currentRun.recognition_results_dropped++;}
   }
   // Frame ACKs can precede the actor's state update. Hold locally from the
   // onset event as well, so cached ready state cannot play over new speech.
   if(e.type==='speech_started'&&!source)pendingSpeech.add(e.utterance);
   if(e.type==='recognition'&&e.final)pendingSpeech.delete(e.utterance);
   if(e.type==='speech_ended'){speechEnds.set(e.utterance,e.speech_end_sample);while(speechEnds.size>80)speechEnds.delete(speechEnds.keys().next().value);}
   if(e.type==='speech_started'||e.type==='speech_ended')currentRun.events.push({kind:e.type,utterance:e.utterance,
    response_id:playingId,at:performance.now(),speech_onset_sample:e.speech_onset_sample,speech_end_sample:e.speech_end_sample});
  }
  if((source||chunkReplyId)&&inspectInterruption(packet,result))stopReply(result.utterance);
  reconcile(result.conversation);
  if(currentRun.events.length>200)currentRun.events.splice(0,currentRun.events.length-200);
 }}catch(error){if(captured===gen)await fail(error);}finally{sending=false;if(active&&queue.length)pump();}
}
$('start').onclick=async()=>{
 if(active||starting)return;if(document.body.dataset.memoryPilot==='true'&&!memoryPilotConsent())return;if(runs.length>=12){text('error','Download these twelve test runs, then reload to continue.');return;}
 starting=true;const captured=++gen;origin=null;latest=null;speechEnds.clear();pendingSpeech.clear();reviewId=null;$('review').hidden=true;clearOutput('new capture');text('playback-status','No reply played yet.');
 currentRun={created_at:new Date().toISOString(),started_ms:null,online:$('online').checked,settings:{},events:[],recognition_results:[],recognition_results_dropped:0,faults:[],max_queue:0,
  transport:{frames:0,sum_rtt_ms:0,max_rtt_ms:0,rtt_buckets:[0,0,0,0,0,0,0],bucket_upper_ms:[5,10,20,50,100,200,'over 200']}};runs.push(currentRun);text('error','');text('you','');text('reply','');face();
 if(guide.running){
  diagnosticAudio=null;
  const enabled=guidedAudioOptIn;
  currentRun.local_audio_recording={enabled,consent:enabled?'Explicit Start test with local recording button':null};
  if(enabled)diagnosticAudio={run:currentRun,recorder:new LocalAudioRecording()};
 }
 try{
  const context=new AudioContext({sampleRate:16000});ctx=context;
  context.onstatechange=()=>{if(captured===gen&&currentRun)currentRun.events.push({kind:'audio_context_state',state:context.state,response_id:playingId,at:performance.now()});};
  await Promise.race([context.resume(),new Promise((_,reject)=>setTimeout(()=>reject(Error('Audio startup timed out; try Chrome or Safari')),5000))]);if(captured!==gen)return;
  if(context.sampleRate!==16000)throw Error('This test needs a 16 kHz audio context');
  await context.audioWorklet.addModule('/capture.js');if(captured!==gen)return;
  const acquired=await navigator.mediaDevices.getUserMedia({audio:{channelCount:1,echoCancellation:true,noiseSuppression:true,autoGainControl:false},video:false});
  if(captured!==gen){acquired.getTracks().forEach(t=>t.stop());return;}mic=acquired;currentRun.settings=mic.getAudioTracks()[0].getSettings();
  const result=await json('/api/conversation/start',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({online:$('online').checked,...(document.body.dataset.memoryPilot==='true'?{adult:$('pilot-adult').checked,record_audio:guidedAudioOptIn,pilot_consent:document.body.dataset.learningPilot==='true'?'adult-fictional-learning-local-speech-cloud-text-v1':'adult-fictional-local-asr-cloud-text-v1'}:{})})},document.body.dataset.learningPilot==='true'?60000:20000);
  if(captured!==gen){fetch('/api/conversation/stop',{method:'POST',headers:{'X-Audio-Stream':result.stream_id},signal:AbortSignal.timeout(1000)}).catch(()=>{});return;}
  lease=result.stream_id;latest=result.conversation;currentRun.asr_run_id=result.asr_run_id;currentRun.asr_profiles=result.recognition_models??null;currentRun.reply_delivery=result.conversation.reply_delivery??'whole';currentRun.voice=result.conversation.voice||'Mac Samantha (local)';
  input=context.createMediaStreamSource(mic);node=new AudioWorkletNode(context,'tavi-capture');sink=context.createGain();sink.gain.value=0;input.connect(node);node.connect(sink);sink.connect(context.destination);
  active=true;starting=false;queue=[];lastContact=lastPacket=performance.now();currentRun.started_ms=performance.now();
  node.port.onmessage=e=>{
   if(!active||captured!==gen)return;lastPacket=performance.now();const packet=e.data;
   if(packet.sampleRate!==16000||packet.pcm.byteLength!==1024){fail(Error('Unexpected microphone format'));return;}
   if(diagnosticAudio?.run===currentRun){
    try{diagnosticAudio.recorder.append(packet);}catch(error){error.stage='local_audio';fail(error);return;}
   }
   if(origin===null)origin=packet.endFrame-(packet.sequence+1)*512;
   if(queue.length>=4){fail(Error('Capture backlog exceeded 128 ms'));return;}
   queue.push(packet);currentRun.max_queue=Math.max(currentRun.max_queue,queue.length);pump();
  };
  mic.getTracks().forEach(t=>t.onended=()=>fail(Error('Microphone disconnected')));reconcile(result.conversation);$(guide.running?'guide-card':'face-card').scrollIntoView?.({block:'start',behavior:'smooth'});
 }catch(error){if(captured===gen)await fail(error);}
};
$('mute').onclick=()=>mute();$('stop-reply').onclick=()=>stopReply();
$('end').onclick=()=>{clearOutput('end chat');block(latest?.token?.response_id);action('end');};
$('online').onchange=()=>{clearOutput('online toggle');block(latest?.token?.response_id);if(active)action('online',{enabled:$('online').checked});};
$('volume').oninput=()=>{text('volume-value',Math.round(Number($('volume').value)*100)+'%');if(outputGain)outputGain.gain.value=Number($('volume').value);};
for(const [id,rating] of [['review-yes','correct'],['review-no','incorrect_or_incomplete'],['review-unsure','unknown']])$(id).onclick=()=>{
 if(!reviewId)return;reviews.push({response_id:reviewId,recognition_id:turnTexts.get(reviewId)?.recognition_id??null,rating,at:performance.now()});if(reviews.length>100)reviews.shift();
 for(const key of ['review-yes','review-no','review-unsure'])$(key).setAttribute('aria-pressed',String(key===id));
};
async function downloadReport({includeText=$('include-text').checked,responseIds=null,runScope=null,includeAudio=false,localSave=false}={}){
 try{
  let server;
  try{server=await json('/api/conversation/diagnostics');}
  catch(error){server={model:latest?.model??null,spent_or_reserved_usd:latest?.spent_or_reserved_usd??null,budget_usd:latest?.budget_usd??25,metrics:[],unavailable:error.message};}
  if(includeAudio&&diagnosticAudio?.run!==runScope)throw Error('The local recording is no longer available. Save timings only.');
  const safeRuns=(runScope?[runScope]:runs).map(run=>({...run,...(run.guided_test?{guided_test:{...run.guided_test,note:includeText?run.guided_test.note:''}}:{}),
   ...(includeAudio&&diagnosticAudio?.run===run&&diagnosticAudio.recorder.frames.length?{local_audio:diagnosticAudio.recorder.export()}:{})}));
  const safeReviews=responseIds?reviews.filter(r=>responseIds.includes(r.response_id)):reviews;
  const report={schema_version:1,kind:'paprika_controlled_conversation_diagnostics',runs:safeRuns,reviews:safeReviews,
   server:{model:server.model,asr_models:server.asr_models,inference_schedule:server.inference_schedule??null,reply_delivery:server.reply_delivery??'whole',spent_or_reserved_usd:server.spent_or_reserved_usd,budget_usd:server.budget_usd,metrics:server.metrics,...(server.unavailable?{unavailable:server.unavailable}:{})},
   timing_note:'Browser playback-start minus VAD speech-end is an estimate, not independently measured human-end-to-audible-response latency.',
   audio_included:safeRuns.some(run=>!!run.local_audio),
   transcripts_included:includeText,...(includeText?{accepted_text:Array.from(turnTexts,([response_id,data])=>({response_id,...data})).filter(turn=>!responseIds||responseIds.includes(turn.response_id))}:{})};
  if(localSave){
   report.local_save_consent={destination:'project_private_local',explicit_save:true};
   const saved=await json('/api/conversation/save-test',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(report)},10000);
   lastDownloadName='Saved privately on this Mac: '+saved.filename;return true;
  }
  const link=document.createElement('a');link.href=URL.createObjectURL(new Blob([JSON.stringify(report,null,2)],{type:'application/json'}));link.download='paprika-conversation-diagnostics-'+crypto.randomUUID()+'.json';link.click();setTimeout(()=>URL.revokeObjectURL(link.href),1000);
  lastDownloadName=link.download;
  return true;
 }catch(error){text('error','Could not save: '+error.message+' Your results are still here. Try Save again, or use Download a copy.');return false;}
}
$('download').onclick=()=>downloadReport();
async function startGuided(recordAudio){
 if(active||starting)return;
 if(runs.length>=12){text('error','This page has reached twelve test runs. Save the current results, then reload for a new test.');return;}
 try{
  guidedAudioOptIn=recordAudio;
  $('online').checked=true;$('volume').value='.35';text('volume-value','35%');$('guide-note').value='';
  await guide.start();
 }catch(error){text('error','Could not start the voice test: '+error.message);await mute('Test could not start · microphone off');}
}
$('guide-start').onclick=()=>startGuided(true);
$('guide-start-no-audio').onclick=()=>startGuided(false);
$('guide-word-audio').onerror=()=>text('guide-word-audio-help','This browser could not play the listening copy. Choose Not sure if needed, then save the result for inspection.');
$('guide-stop').onclick=()=>guide.finish();
for(const [id,rating] of [['guide-words-yes','correct'],['guide-words-no','incorrect_or_incomplete'],['guide-words-unsure','unknown']])$(id).onclick=()=>guide.rateWords(rating);
$('guide-word-next').onclick=()=>{
 const item=guide.currentWords();if(active||starting||!item?.rating)return;
 reviews.push({response_id:item.response_id,recognition_id:turnTexts.get(item.response_id)?.recognition_id??null,rating:item.rating,at:performance.now()});
 if(reviews.length>100)reviews.shift();guide.nextWords();
};
for(const result of ['worked','problem','unsure'])$('guide-'+result).onclick=()=>guide.report(result);
async function saveGuided(includeText){
 if(active||starting||!canSaveGuide(guide))return;
 const item=guide.currentWords();
 if(item?.rating&&!reviews.some(r=>r.response_id===item.response_id&&r.rating===item.rating))reviews.push({response_id:item.response_id,recognition_id:turnTexts.get(item.response_id)?.recognition_id??null,rating:item.rating,at:performance.now()});
 guide.data.note=$('guide-note').value.slice(0,500);
 const ok=await downloadReport({includeText,responseIds:guide.responseIds?.()||[guide.data.first_response_id,guide.data.replacement_response_id],runScope:guideRun,includeAudio:includeText&&!!guideRun?.local_audio_recording?.enabled,localSave:guide.data.protocol==='k-live-conversation-v1'});
 if(ok){lastGuideSaveIncludeText=includeText;if(!includeText&&diagnosticAudio?.run===guideRun){diagnosticAudio=null;text('local-audio-status','Local audio discarded · timings only were saved');}guide.saved();}
}
for(const [id,includeText] of [['guide-save',true],['guide-save-private',false]])$(id).onclick=()=>saveGuided(includeText);
$('guide-check-words').onclick=()=>guide.beginWordReview?.();
$('guide-download-copy').onclick=()=>downloadReport({includeText:lastGuideSaveIncludeText,responseIds:guide.responseIds?.()||null,runScope:guideRun,includeAudio:lastGuideSaveIncludeText&&!!guideRun?.local_audio_recording?.enabled&&diagnosticAudio?.run===guideRun});
$('guide-save-again').onclick=()=>saveGuided(lastGuideSaveIncludeText);
$('guide-new-test').onclick=()=>{guide.reset();text('error','');};
$('guide-open-chat').onclick=()=>{document.body.dataset.mode='chat';text('page-title','Let’s talk.');};
$('open-guide').onclick=()=>{if(active||starting){text('error','Mute free chat before starting the guided test.');return;}document.body.dataset.mode='guided';text('page-title','Try K in a conversation.');};
setInterval(()=>{
 if(!active)return;const now=performance.now();
 if(now-lastPacket>1000||ctx?.state!=='running')fail(Error('Microphone frames stalled'));
 else if(now-lastContact>1500)fail(Error('Conversation service is unresponsive'));
 else if(now-currentRun.started_ms>600000)mute('Ten-minute capture limit reached · download diagnostics');
},500);
window.addEventListener('pagehide',()=>mute());if(guide.variant==='latency-v1')text('page-title','Try a faster conversation.');if(guide.variant==='turbo-v1')text('page-title','Try clearer listening with K.');if(['memory-v1','learning-v1'].includes(guide.variant))text('page-title','A personal conversation with Paprika');if(guide.variant==='learning-v1')text('page-title','Teach Paprika something new');face();renderGuide(guide);

// Read configured voice without opening a microphone or making a paid call.
json('/api/conversation/diagnostics').then(state=>{if(state.voice)text('voice-name',state.voice);}).catch(()=>{});

if(['memory-v1','learning-v1'].includes(guide.variant))for(const [id,value] of [['pilot-wait-ok','usable'],['pilot-wait-not','disruptive'],['pilot-wait-unsure','unknown']])$(id).onclick=()=>{if(guide.data){guide.data.wait_rating=value;renderGuide(guide);}};

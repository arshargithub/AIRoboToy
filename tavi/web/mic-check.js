'use strict';
const $=id=>document.getElementById(id),collector=new SampleCollector(6,250);
const profiles=[{id:'current',echoCancellation:true,noiseSuppression:true,autoGainControl:false},
 {id:'echo_only',echoCancellation:true,noiseSuppression:false,autoGainControl:false},
 {id:'unprocessed_request',echoCancellation:false,noiseSuppression:false,autoGainControl:false}];
let context=null,mic=null,node=null,input=null,sink=null,session=null,round=0,generation=0,starting=false;
let roundStart=0,lastFrame=0,openedAt=0,roundFirstClip=0,stoppedEarly=false,playbackURLs=[];
const rounds=[],ratings=new Map();
function stopListening(){for(const audio of document.querySelectorAll('#clips audio')){audio.pause();}playbackURLs.forEach(url=>URL.revokeObjectURL(url));playbackURLs=[];}
async function closeMic(){
 generation++;starting=false;
 if(node){node.port.onmessage=null;node.disconnect();node=null;}if(input){input.disconnect();input=null;}if(sink){sink.disconnect();sink=null;}
 if(mic){mic.getTracks().forEach(t=>{t.onended=null;t.stop()});mic=null;}
 const old=context;context=null;if(old&&old.state!=='closed')await old.close();
}
function fail(error){
 $('error').textContent=error.message;
 if(session?.active)session.finish(false);else{closeMic();showReview();}
}
function show(phase,trial,index){
 $('recording').dataset.phase=phase;$('step').textContent=`Round ${round+1} of 3 · clip ${index+1} of 2`;
 const copy={read:['Read this first','Get ready. Recording begins in three seconds.'],wait:['Wait…','Stay quiet until the card turns green.'],speak:['Your turn — say it now','Say the full sentence once, then stay quiet.']}[phase];
 $('phase').textContent=copy[0];$('help').textContent=copy[1];
 $('status').textContent=phase==='read'?'Microphone on · preparation is not saved':'Microphone on · recording this eight-second clip locally';
}
function bytesFor(frames){const bytes=new Uint8Array(frames.length*1024);frames.forEach((frame,index)=>bytes.set(frame,index*1024));return bytes;}
function peakOf(bytes){const view=new DataView(bytes.buffer);let peak=0;for(let i=0;i<bytes.length;i+=2)peak=Math.max(peak,Math.abs(view.getInt16(i,true)));return peak;}
function wav(bytes,gain){
 const data=new ArrayBuffer(44+bytes.length),view=new DataView(data),pcm=new DataView(bytes.buffer);
 const chars=(at,text)=>{for(let i=0;i<text.length;i++)view.setUint8(at+i,text.charCodeAt(i));};
 chars(0,'RIFF');view.setUint32(4,36+bytes.length,true);chars(8,'WAVE');chars(12,'fmt ');view.setUint32(16,16,true);view.setUint16(20,1,true);view.setUint16(22,1,true);view.setUint32(24,16000,true);view.setUint32(28,32000,true);view.setUint16(32,2,true);view.setUint16(34,16,true);chars(36,'data');view.setUint32(40,bytes.length,true);
 for(let i=0;i<bytes.length;i+=2)view.setInt16(44+i,Math.round(pcm.getInt16(i,true)*gain),true);
 return new Blob([data],{type:'audio/wav'});
}
function showReview(){
 $('setup').hidden=true;$('recording').hidden=true;$('review').hidden=false;
 $('status').textContent='Microphone off · listen and rate';$('review-step').textContent=`Round ${round+1} of 3`;
 stopListening();$('clips').replaceChildren();
 const clips=collector.clips.slice(roundFirstClip),bytes=clips.map(c=>bytesFor(c.frames));
 const peak=Math.max(0,...bytes.map(peakOf)),gain=peak?Math.min(8,30000/peak):1;
 if(rounds[round])rounds[round].listening_gain=gain;
 for(let i=0;i<clips.length;i++){
  const clip=clips[i],section=document.createElement('section');section.className='clip';
  const title=document.createElement('h3');title.textContent=i===0?'First clip':'Later clip';section.append(title);
  const audio=document.createElement('audio');audio.controls=true;audio.preload='metadata';audio.setAttribute('aria-label',title.textContent);
  audio.onplay=()=>{for(const other of document.querySelectorAll('#clips audio'))if(other!==audio)other.pause();};
  audio.src=URL.createObjectURL(wav(bytes[i],gain));playbackURLs.push(audio.src);section.append(audio);
  audio.onerror=()=>{$('error').textContent='This browser could not play the local clip. You can still finish here and save it for local inspection.';};
  const row=document.createElement('div');row.className='row ratings';
  for(const [value,label] of [['clear','Sounds clear'],['impaired','Fades or distorts'],['unsure','Not sure']]){
   const button=document.createElement('button');button.textContent=label;button.setAttribute('aria-pressed',String(ratings.get(clip.number)===value));
   button.onclick=()=>{ratings.set(clip.number,value);for(const b of row.children)b.setAttribute('aria-pressed',String(b===button));reviewControls();};row.append(button);
  }
  section.append(row);$('clips').append(section);
 }
 $('continue').hidden=clips.length!==2||stoppedEarly;
 $('save-partial').disabled=!collector.clips.length;
 $('continue').textContent=round===2?'Finish and save':'Next round';reviewControls();
 if(!clips.length){$('error').textContent||= 'No complete clip was captured in this round. Save any earlier clips, then tell me what happened.';}
 $('review').scrollIntoView?.({block:'start',behavior:'smooth'});
}
function reviewControls(){const clips=collector.clips.slice(roundFirstClip);$('continue').disabled=!!context||starting||clips.length!==2||clips.some(c=>!ratings.has(c.number));}
async function finished(all){
 stoppedEarly=!all;
 if(rounds[round]){rounds[round].completed=all;rounds[round].ended_at=new Date().toISOString();}
 await closeMic();showReview();
}
async function openRound(){
 if(starting||context)return;stopListening();starting=true;stoppedEarly=false;$('error').textContent='';
 $('setup').hidden=true;$('review').hidden=true;$('recording').hidden=false;$('phase').textContent='Starting microphone…';$('help').textContent='Allow microphone access if asked.';$('step').textContent=`Round ${round+1} of 3`;
 $('stop').disabled=false;roundFirstClip=collector.clips.length;const captured=++generation;
 $('status').textContent='Opening microphone · allow access if asked';
 try{
  const audio=new AudioContext({sampleRate:16000});context=audio;await audio.resume();if(captured!==generation)return;
  if(audio.sampleRate!==16000)throw Error('This check needs a 16 kHz audio context.');
  await audio.audioWorklet.addModule('/capture.js');if(captured!==generation)return;
  const {id,...requested}=profiles[round];
  const stream=await navigator.mediaDevices.getUserMedia({audio:{channelCount:1,...requested},video:false});
  if(captured!==generation){stream.getTracks().forEach(t=>t.stop());return;}mic=stream;openedAt=performance.now();
  const actual=stream.getAudioTracks()[0].getSettings(),reported=Object.fromEntries(['sampleRate','channelCount','echoCancellation','noiseSuppression','autoGainControl','voiceIsolation','latency'].filter(k=>k in actual).map(k=>[k,actual[k]]));
  const record={round:round+1,profile:id,requested,reported,opened_at:new Date().toISOString(),settings_verified:Object.entries(requested).every(([key,value])=>reported[key]===value)};rounds.push(record);$('settings').textContent=JSON.stringify(rounds,null,2);
  input=audio.createMediaStreamSource(stream);node=new AudioWorkletNode(audio,'tavi-capture');sink=audio.createGain();sink.gain.value=0;input.connect(node);node.connect(sink);sink.connect(audio.destination);
  const trials=[0,1].map(index=>({number:round*2+index+1,round:round+1,profile:id,position:index===0?'first':'later',condition:'quiet',phrase:'Wait, make it a space adventure instead.'}));
  session=new SpeechCheckSession({plan:{trials,read_ms:3000,cue_frame:64,clip_frames:250},collector,show,play(){},stopAudio(){},done:finished});
  node.port.onmessage=e=>{if(captured!==generation)return;lastFrame=performance.now();try{
   const packet=e.data;
   if(session.recording&&collector.current){
    if(!collector.current.frames.length){collector.current.capture_start_frame=packet.endFrame-512;collector.current.ms_since_mic_open_at_capture=performance.now()-openedAt;}
    if(collector.current.frames.length+1===64)collector.current.cue_context_frame=packet.endFrame;
   }
   session.frame(packet);
  }catch(error){fail(error);}};
  mic.getTracks().forEach(t=>t.onended=()=>fail(Error('Microphone disconnected. The unfinished clip was discarded.')));
  roundStart=lastFrame=performance.now();starting=false;session.start();$('recording').scrollIntoView?.({block:'start',behavior:'smooth'});
 }catch(error){if(captured===generation)fail(error);}
}
$('start').onclick=()=>openRound();
$('stop').onclick=()=>{if(session?.active)session.finish(false);else{stoppedEarly=true;closeMic().then(showReview);}};
function showDone(){stopListening();$('review').hidden=true;$('recording').hidden=true;$('done').hidden=false;$('done-title').textContent=collector.clips.length===6?'All done.':'Partial check ready.';$('done-help').textContent=`${collector.clips.length} complete voice clips and your ratings are ready.`;$('download').disabled=!collector.clips.length;$('status').textContent='Microphone off';}
$('continue').onclick=()=>{if($('continue').disabled)return;if(round===2){showDone();$('download').onclick();}else{round++;session=null;return openRound();}};
$('save-partial').onclick=()=>{showDone();$('download').onclick();};
function encoded(frames){let text='';for(const frame of frames)text+=String.fromCharCode(...frame);return btoa(text);}
$('download').onclick=()=>{
 if(context||starting||!collector.clips.length)return;
 try{
  const report={schema_version:1,kind:'paprika_private_microphone_check',protocol_id:'microphone-quality-v1',consent:'Explicit Start recording on this Mac button',created_at:new Date().toISOString(),sample_rate:16000,format:'mono_pcm16le_base64',complete:collector.clips.length===6,ratings_complete:collector.clips.every(c=>ratings.has(c.number)),rounds,
   clips:collector.clips.map(({frames,...metadata})=>({...metadata,quality_rating:ratings.get(metadata.number)||'unrated',sample_count:frames.length*512,pcm_base64:encoded(frames)}))};
  const link=document.createElement('a');link.href=URL.createObjectURL(new Blob([JSON.stringify(report)],{type:'application/json'}));link.download='paprika-microphone-check-'+crypto.randomUUID()+'.json';link.click();setTimeout(()=>URL.revokeObjectURL(link.href),1000);$('saved').textContent='Download started. Tell me “Downloaded” in the chat.';
 }catch(error){$('error').textContent='Could not save results: '+error.message;}
};
setInterval(()=>{if(session?.active&&(performance.now()-lastFrame>1500||context?.state!=='running'))fail(Error('Microphone frames stalled. Save the completed clips.'));else if(session?.active&&performance.now()-roundStart>60000)fail(Error('One-minute round limit reached. Save the completed clips.'));},500);
window.addEventListener('pagehide',()=>{if(session?.active)session.finish(false);else closeMic();stopListening();});

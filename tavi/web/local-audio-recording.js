'use strict';
// Browser memory only. The caller must obtain explicit opt-in and serialize
// only after capture stops. No network, disk, model or transcript handling.
class LocalAudioRecording {
 constructor(maxFrames=5625){if(!Number.isInteger(maxFrames)||maxFrames<1||maxFrames>5625)throw Error('Invalid local recording bound');this.maxFrames=maxFrames;this.frames=[];this.last=-1;this.startFrame=null;this.endFrame=null;this.closed=false;this.limitReached=false;}
 append(packet){
  if(this.closed)throw Error('Local recording is closed');
  if(packet.sampleRate!==16000||packet.pcm.byteLength!==1024||packet.sequence!==this.last+1||
    !Number.isInteger(packet.endFrame)||packet.endFrame<512||this.endFrame!==null&&packet.endFrame!==this.endFrame+512)throw Error('Local recording detected an audio gap or invalid format');
  if(this.frames.length>=this.maxFrames){this.limitReached=true;throw Error('Three-minute local recording limit reached. Save the partial test.');}
  if(this.startFrame===null)this.startFrame=packet.endFrame-512;
  this.frames.push(new Uint8Array(packet.pcm).slice());this.last=packet.sequence;this.endFrame=packet.endFrame;
 }
 close(){this.closed=true;}
 listeningWave(start,stop){
  const count=this.frames.length*512;
  if(!this.closed||!Number.isInteger(start)||!Number.isInteger(stop)||start<0||stop<=start||stop>count)throw Error('Recorded audio is not available for this request');
  const bytes=new Uint8Array(count*2);this.frames.forEach((frame,index)=>bytes.set(frame,index*1024));
  const input=new DataView(bytes.buffer),size=(stop-start)*2,out=new ArrayBuffer(44+size),view=new DataView(out);
  let peak=0;for(let i=start;i<stop;i++)peak=Math.max(peak,Math.abs(input.getInt16(i*2,true)));
  const gain=peak?Math.min(8,30000/peak):1;
  const chars=(at,text)=>{for(let i=0;i<text.length;i++)view.setUint8(at+i,text.charCodeAt(i));};
  chars(0,'RIFF');view.setUint32(4,36+size,true);chars(8,'WAVE');chars(12,'fmt ');view.setUint32(16,16,true);view.setUint16(20,1,true);view.setUint16(22,1,true);view.setUint32(24,16000,true);view.setUint32(28,32000,true);view.setUint16(32,2,true);view.setUint16(34,16,true);chars(36,'data');view.setUint32(40,size,true);
  for(let i=start;i<stop;i++)view.setInt16(44+(i-start)*2,Math.round(input.getInt16(i*2,true)*gain),true);
  return {blob:new Blob([out],{type:'audio/wav'}),gain};
 }
 metadata(){return {sample_rate:16000,format:'mono_pcm16le_base64',sample_count:this.frames.length*512,
  start_context_frame:this.startFrame,end_context_frame:this.endFrame,first_sequence:this.frames.length?0:null,
  last_sequence:this.last,duration_ms:this.frames.length*32,limit_reached:this.limitReached,
  source:'browser-processed microphone',closed:this.closed};}
 export(){
  if(!this.closed)throw Error('Mute before saving the local recording');
  const parts=this.frames.map(frame=>String.fromCharCode(...frame));
  return {...this.metadata(),pcm_base64:btoa(parts.join(''))};
 }
}
if(typeof module!=='undefined')module.exports={LocalAudioRecording};

'use strict';
const {contextBridge,ipcRenderer}=require('electron');
contextBridge.exposeInMainWorld('paprika',{
 status:()=>ipcRenderer.invoke('paprika:status'),
 reconnect:()=>ipcRenderer.invoke('paprika:reconnect'),
 call:(command,body={},stream=null)=>ipcRenderer.invoke('paprika:call',{command,body,stream}),
 frame:(pcm,sequence,stream)=>ipcRenderer.invoke('paprika:frame',{pcm,sequence,stream}),
 audio:(id,sequence,stream)=>ipcRenderer.invoke('paprika:audio',{id,sequence,stream}),
 diagnostics:()=>ipcRenderer.invoke('paprika:diagnostics'),
 saveReview:report=>ipcRenderer.invoke('paprika:save-review',report),
 voices:()=>ipcRenderer.invoke('paprika:voices'),
 openVoices:()=>ipcRenderer.invoke('paprika:open-voices'),
 openHome:()=>ipcRenderer.invoke('paprika:open-home'),
 voiceAction:(action,body={},person=null,session=null)=>ipcRenderer.invoke('paprika:voice-action',{action,body,person,session}),
 voiceAttempt:(pcm,meta)=>ipcRenderer.invoke('paprika:voice-attempt',{pcm,meta}),
 voiceQuestion:id=>ipcRenderer.invoke('paprika:voice-question',id),
 voiceSample:meta=>ipcRenderer.invoke('paprika:voice-sample',meta),
 micIntent:enabled=>ipcRenderer.invoke('paprika:mic-intent',enabled),
 microphoneStatus:()=>ipcRenderer.invoke('paprika:microphone-status'),
 onPause:fn=>{ipcRenderer.on('paprika:pause',()=>fn());},
 onVisibility:fn=>{ipcRenderer.on('paprika:visibility',(_,hidden)=>fn(hidden));}
});

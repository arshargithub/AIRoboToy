'use strict';
// One presentation mapping shared by the Mac face and future small displays.
// These states never infer identity, authorize memory, or hold up real audio.
function companionState(view,{pendingSpeech=false}={}){
 const s=view.state;
 if(view.starting)return{kind:'starting',title:'Waking up',cue:'Getting my voice ready. One little moment.',mic:'Microphone starting'};
 if(!view.active)return{kind:'paused',title:'Taking a little break',cue:'Listen again whenever you’re ready.',mic:'Microphone off'};
 const mic='Microphone on';
 if(view.playing)return s?.closing_after_playback?{kind:'farewell',title:'See you soon',cue:'I’ll be here when you need me.',mic}:{kind:'talking',title:'A little thought, out loud',cue:'You can interrupt me any time.',mic};
 if(s?.input==='capturing'||s?.pending_input||pendingSpeech)return{kind:'listening',title:'I’m listening',cue:'Take your time. I’m here.',mic};
 if(view.loading||['generating','ready'].includes(s?.output))return{kind:'thinking',title:'Let me think',cue:'Finding the words.',mic};
 if(s?.engagement==='active')return{kind:'attentive',title:'Your turn',cue:'No need to say my name again.',mic};
 return{kind:'standby',title:'Here when you need me',cue:'Say “Paprika” to start a new chat.',mic:'Listening locally for my name'};
}
if(typeof module!=='undefined')module.exports={companionState};

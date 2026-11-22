const {test}=require('node:test'),assert=require('node:assert/strict'),{companionState}=require('../tavi/web/companion-state.js');
test('sleep, name listening, active listening, thinking, speech and farewell have distinct states',()=>{
 assert.equal(companionState({active:false}).kind,'paused');
 assert.equal(companionState({starting:true}).kind,'starting');
 assert.equal(companionState({active:true,state:{engagement:'idle'}}).kind,'standby');
 assert.equal(companionState({active:true,state:{engagement:'active'}}).kind,'attentive');
 assert.equal(companionState({active:true,state:{engagement:'active',input:'capturing'}}).kind,'listening');
 assert.equal(companionState({active:true,state:{engagement:'active',output:'generating'}}).kind,'thinking');
 assert.equal(companionState({active:true,playing:true,state:{engagement:'active'}}).kind,'talking');
 assert.equal(companionState({active:true,playing:true,state:{engagement:'active',closing_after_playback:true}}).kind,'farewell');
});
test('waiting for the name never claims the microphone is off, while muted does',()=>{
 const idle=companionState({active:true,state:{engagement:'idle'}});assert(idle.mic.includes('Listening locally'));assert(idle.cue.includes('start a new chat'));
 assert.equal(companionState({active:false,state:{engagement:'active',output:'playing'}}).mic,'Microphone off');
});
test('pending real speech takes precedence over a waiting reply',()=>{
 assert.equal(companionState({active:true,state:{output:'ready'}},{pendingSpeech:true}).kind,'listening');
 assert.equal(companionState({active:true,loading:true,state:{}}).kind,'thinking');
});

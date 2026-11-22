const assert=require('node:assert/strict');
const {LocalAudioRecording}=require('../tavi/web/local-audio-recording.js');
const packet=sequence=>({sequence,endFrame:16000+(sequence+1)*512,sampleRate:16000,pcm:new Int16Array(512).fill(123).buffer});
const audio=new LocalAudioRecording(2),first=packet(0);audio.append(first);new Int16Array(first.pcm).fill(999);
assert.throws(()=>audio.export(),/Mute/);audio.append(packet(1));assert.throws(()=>audio.append(packet(2)),/limit/);audio.close();
const saved=audio.export();assert.equal(saved.sample_count,1024);assert.equal(saved.limit_reached,true);assert.equal(Buffer.from(saved.pcm_base64,'base64').readInt16LE(0),123,'capture must own a copy of mutable transport buffers');
assert.throws(()=>audio.append(packet(2)),/closed/);
const gap=new LocalAudioRecording();gap.append(packet(0));assert.throws(()=>gap.append(packet(2)),/gap/);
const shifted=new LocalAudioRecording();shifted.append(packet(0));assert.throws(()=>shifted.append({...packet(1),endFrame:99999}),/gap/);
console.log('Local audio: explicit bounded capture, immutable copy, exact frame timeline, mute-before-export and visible limits passed');
(async()=>{
 const copy=audio.listeningWave(512,1024),view=new DataView(await copy.blob.arrayBuffer());
 assert.equal(view.getUint32(24,true),16000);assert.equal(view.getUint32(40,true),1024);
 assert.equal(view.getInt16(44,true),984);assert.equal(copy.gain,8);
 assert.throws(()=>audio.listeningWave(-1,1024),/available/);
 assert.equal(Buffer.from(audio.export().pcm_base64,'base64').readInt16LE(0),123,'listening gain cannot alter original capture');
})().catch(error=>{console.error(error);process.exitCode=1});

const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),{webcrypto}=require('node:crypto');
const {SampleCollector}=require('../tavi/web/sample-collector.js');
function harness({late=false,failSave=false}={}){
 const els=new Map(),tracks=[],calls=[],intervals=[];let node,seq=0,resolvePermission;
 function make(tag='div'){return {tag,children:[],value:'',textContent:'',checked:false,hidden:false,disabled:false,dataset:{},style:{},append(...x){this.children.push(...x)},replaceChildren(...x){this.children=x},pause(){},click(){}};}
 const el=id=>{if(!els.has(id))els.set(id,make());return els.get(id);};
 const choices=[{value:'local',checked:false},{value:'cloud',checked:false}];
 const plan={phrases:['one','two','three','four']};
 function stream(){const t={stops:0,stop(){this.stops++},getSettings:()=>({sampleRate:48000,echoCancellation:true,deviceId:'private'})};tracks.push(t);return {getTracks:()=>[t],getAudioTracks:()=>[t]};}
 const sandbox={console,crypto:webcrypto,Blob,ArrayBuffer,Uint8Array,DataView,btoa,SampleCollector,
  performance:{now:()=>1000},setTimeout(){},setInterval(fn){intervals.push(fn)},window:{addEventListener(){}},location:{reload(){}},
  URL:{createObjectURL(){return 'blob:local'},revokeObjectURL(){}},
  document:{getElementById:el,querySelector:()=>choices.find(c=>c.checked),querySelectorAll:()=>choices,createElement:make,createTextNode:text=>({text})},
  fetch:async(path,options)=>{const body=options?JSON.parse(options.body):null;calls.push({path,body});
   if(path==='/protocol')return {ok:true,json:async()=>plan};
   if(path==='/prepare')return {ok:true,json:async()=>({protocol:plan,session_id:body.session_id})};
   if(path==='/compare'){assert.equal(tracks.at(-1).stops,1,'microphone must stop before comparison/upload');return {ok:true,json:async()=>({index:body.index,candidates:{A:{text:'words'},...(choices[1].checked?{B:{text:'other words'}}:{})}})};}
   if(path==='/save')return {ok:!failSave,json:async()=>failSave?{error:'Temporary service failure'}:{completed_clips:body.clips.length,mapping:{A:'local',B:'cloud'}}};
   if(path==='/stop')return {ok:true,json:async()=>({stopped:true})};throw Error('Unexpected network path '+path);
  },
  navigator:{mediaDevices:{getUserMedia(){return late?new Promise(r=>{resolvePermission=()=>r(stream())}):Promise.resolve(stream())}}},
  AudioContext:class{constructor(){this.sampleRate=16000;this.state='running';this.audioWorklet={addModule:async()=>{}}}async resume(){}async close(){this.state='closed'}createMediaStreamSource(){return {connect(){},disconnect(){}}}createGain(){return {gain:{value:0},connect(){},disconnect(){}}}},
  AudioWorkletNode:class{constructor(){this.port={};node=this}connect(){}disconnect(){}}
 };
 vm.createContext(sandbox);vm.runInContext(fs.readFileSync('tavi/web/asr-review.js','utf8'),sandbox);
 return {el,tracks,calls,async settle(){for(let i=0;i<8;i++)await new Promise(r=>setImmediate(r));},
  choose(cloud){el('adult').checked=true;el('record-consent').checked=true;choices[cloud?1:0].checked=true;choices[cloud?1:0].onchange();},
  frame(){node.port.onmessage?.({data:{sequence:seq++,sampleRate:16000,pcm:new ArrayBuffer(1024)}})},
  rate(){for(const card of el('candidates').children)card.children[2].children[0].children[0].onchange();},
  permission(){resolvePermission();}
 };
}
(async()=>{
 const h=harness();await h.settle();assert.equal(h.tracks.length,0);h.el('practice').onclick();h.el('practice-cue').onclick();assert.match(h.el('practice-title').textContent,/Your turn/);assert.equal(h.tracks.length,0);h.el('practice-back').onclick();
 h.choose(true);assert.equal(h.el('prepare').disabled,false);await h.el('prepare').onclick();assert.equal(h.tracks.length,0,'prepare must not open microphone');
 for(let turn=0;turn<4;turn++){
  await h.el('record-next').onclick();for(let i=0;i<94;i++)h.frame();assert.equal(h.el('record').dataset.phase,'speak');
  for(let i=0;i<250;i++)h.frame();await h.settle();assert.equal(h.tracks[turn].stops,1);
  assert.equal(h.el('next').disabled,true,'word ratings cannot be inferred');h.rate();assert.equal(h.el('next').disabled,false);await h.el('next').onclick();
 }
 assert.equal(h.el('done').hidden,false);await h.el('save-audio').onclick();
 const saved=h.calls.find(c=>c.path==='/save').body;assert.equal(saved.clips.length,4);assert.equal(Buffer.from(saved.clips[0].pcm,'base64').length,256000);assert.equal(saved.include_audio,true);
 assert.match(h.el('saved').textContent,/Saved on this Mac/);assert.match(h.el('saved').textContent,/A: on this Mac/);
 const local=harness({failSave:true});await local.settle();local.choose(false);await local.el('prepare').onclick();await local.el('record-next').onclick();for(let i=0;i<344;i++)local.frame();await local.settle();await local.el('stop-review').onclick();await local.el('save-results').onclick();
 assert.equal(local.calls.find(c=>c.path==='/prepare').body.cloud,false);assert.equal(local.calls.find(c=>c.path==='/save').body.reviews[0].A,null,'unreviewed stays null');assert.equal(local.el('download').hidden,false,'failed save offers local recovery');
 const late=harness({late:true});await late.settle();late.choose(false);await late.el('prepare').onclick();const pending=late.el('record-next').onclick();await late.settle();await late.el('stop').onclick();late.permission();await pending;assert.equal(late.tracks[0].stops,1,'late microphone permission cannot restart capture');
 console.log('Fresh ASR UI: explicit choices, no microphone at load/prepare/practice, bounded cues, mute before upload/review, independent labels, partial save, recovery and late permission passed');
})().catch(e=>{console.error(e);process.exitCode=1});

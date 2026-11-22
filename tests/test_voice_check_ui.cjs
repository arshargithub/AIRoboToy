const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const {webcrypto}=require('node:crypto');
const sourcePlan=JSON.parse(fs.readFileSync('tavi/web/voice-husky-protocol.json','utf8'));
function harness({failLoad=false,failSave=false,deferAudio=false,badPlan=false}={}){
 const elements=new Map(),calls=[],audios=[];let output;
 const el=id=>{if(!elements.has(id))elements.set(id,{hidden:false,disabled:false,textContent:'',value:'',dataset:{},setAttribute(k,v){this[k]=v}});return elements.get(id)};
 el('save').disabled=true;el('saved').hidden=true;el('comparison').hidden=true;el('volume').value='.35';el('decision').value='still_looking';
 const sandbox={console,Blob,Date,AbortSignal,crypto:webcrypto,setTimeout(){},window:{addEventListener(){}},
  Audio:class{constructor(src){this.src=src;this.pauses=0;audios.push(this)}pause(){this.pauses++}play(){this.played=true;return deferAudio?new Promise((resolve,reject)=>{this.resolve=resolve;this.reject=reject}):Promise.resolve()}},
  URL:{createObjectURL(blob){if(failSave)throw Error('Synthetic download error');output=blob;return 'blob:test'},revokeObjectURL(){}},
  document:{getElementById:el,createElement:()=>({click(){}})},
  async fetch(path){calls.push(path);const plan=JSON.parse(JSON.stringify(sourcePlan));if(badPlan)plan.trials[2].text='different words';return {ok:!failLoad,json:async()=>plan}}};
 vm.createContext(sandbox);vm.runInContext(fs.readFileSync('tavi/web/voice-check.js','utf8'),sandbox);
 return {el,calls,audios,get output(){return output},async settle(){for(let i=0;i<8;i++)await Promise.resolve()}};
}
(async()=>{
 const h=harness();await h.settle();assert.equal(h.el('comparison').hidden,false);assert.equal(h.audios.length,0,'No autoplay');assert.equal(h.el('save').disabled,true);
 await h.el('play-k').onclick();const b=h.audios[0],lateEnd=b.onended;assert.equal(b.src,sourcePlan.trials[0].src);
 await h.el('play-m').onclick();const c=h.audios[1];assert.ok(b.pauses>0);assert.equal(c.src,sourcePlan.trials[2].src);lateEnd();assert.match(h.el('play-status').textContent,/Playing voice M/);
 h.el('prefer-m').onclick();assert.equal(h.el('card-m').dataset.favorite,'true');assert.equal(h.el('save').disabled,false);
 h.el('volume').value='.5';h.el('volume').oninput();assert.equal(c.volume,.5);c.onended();
 h.el('tone-huskiness-m').value='none';h.el('tone-huskiness-m').onchange();h.el('tone-humanlike-m').value='humanlike';h.el('tone-humanlike-m').onchange();
 h.el('opinion-m').value='love';h.el('opinion-m').onchange();h.el('passage-greeting').onclick();
 assert.equal(h.el('opinion-m').value,'');assert.equal(h.el('tone-huskiness-m').value,'');assert.match(h.el('phrase').textContent,/Paprika/);assert.equal(h.el('card-m').dataset.favorite,'true');
 h.el('opinion-m').value='like';h.el('opinion-m').onchange();await h.el('play-n').onclick();assert.equal(h.audios[2].src,sourcePlan.trials[5].src);h.audios[2].onended();
 h.el('passage-short_story').onclick();assert.equal(h.el('opinion-m').value,'love','Separate opinions survive passage switching');assert.equal(h.el('tone-huskiness-m').value,'none');assert.equal(h.el('tone-humanlike-m').value,'humanlike');
 h.el('trait-confident').onclick();h.el('trait-youthful').onclick();h.el('note').value='Synthetic direction';h.el('save').onclick();
 const result=JSON.parse(await h.output.text());assert.equal(result.closest_voice,'m');assert.equal(result.opinions.length,2);assert.equal(result.opinions[0].rating,'love');assert.equal(result.opinions_complete,false);assert.deepEqual(result.character_observations,[{trial_id:sourcePlan.trials[2].id,voice:'M',huskiness:'none',humanlike:'humanlike'}]);
 assert.deepEqual(result.design_model,sourcePlan.design_model);assert.equal(result.pronunciation.target,'puh-PREE-kuh','Pronunciation target travels with feedback');
 assert.equal(result.selection_status,'still_looking');assert.equal(result.accepted_voice,null,'Closest is not acceptance');assert.deepEqual(result.direction_tags,['confident','youthful']);assert.equal(result.microphone_used,false);assert.equal(result.api_spend_usd,0);assert.equal(result.kind,'paprika_voice_character_check');assert.equal('reviews' in result,false,'Opinions cannot become accuracy labels');assert.equal(h.el('comparison').hidden,false);
 h.el('decision').value='accepted';h.el('decision').onchange();h.el('save').onclick();assert.equal(JSON.parse(await h.output.text()).accepted_voice,'m');
 h.el('prefer-k').onclick();assert.equal(h.el('decision').value,'still_looking','Changing closest candidate cannot carry approval');h.el('save').onclick();assert.equal(JSON.parse(await h.output.text()).accepted_voice,null);
 h.el('prefer-none').onclick();assert.equal(h.el('decision').disabled,true);h.el('save').onclick();assert.equal(JSON.parse(await h.output.text()).closest_voice,'none');
 assert.deepEqual(h.calls,['/voice-husky-protocol.json'],'Only local protocol; no microphone/cloud requests');
 const late=harness({deferAudio:true});await late.settle();const pendingB=late.el('play-k').onclick();const old=late.audios[0];const pendingC=late.el('play-m').onclick();const fresh=late.audios[1];old.reject(Error('obsolete failure'));await pendingB;assert.match(late.el('play-status').textContent,/Playing voice M/);assert.equal(late.el('error').textContent,'');fresh.resolve();await pendingC;fresh.onerror();assert.match(late.el('error').textContent,/Voice M could not play/);late.el('prefer-none').onclick();late.el('save').onclick();assert.deepEqual(JSON.parse(await late.output.text()).completed_samples,[]);
 for(const options of [{failLoad:true},{badPlan:true}]){const bad=harness(options);await bad.settle();assert.equal(bad.el('retry').hidden,false);assert.match(bad.el('error').textContent,/could not load/)}
 const blocked=harness({failSave:true});await blocked.settle();blocked.el('prefer-none').onclick();blocked.el('save').onclick();assert.match(blocked.el('error').textContent,/choices are still here/);assert.equal(blocked.el('comparison').hidden,false);
 const all=harness();await all.settle();for(const code of ['K','M','N','O']){const before=all.audios.at(-1);await all.el('play-'+code.toLowerCase()).onclick();assert.equal(all.audios.at(-1).src,sourcePlan.trials.find(t=>t.voice===code&&t.case==='short_story').src);if(before)assert.ok(before.pauses>0)}
 console.log('Voice character: liking ratings, closest vs acceptance, none-fit feedback, per-passage preservation, switching and error recovery passed.');
})().catch(error=>{console.error(error);process.exitCode=1});

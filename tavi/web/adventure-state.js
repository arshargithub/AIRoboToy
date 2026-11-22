'use strict';
// Microphone-free preview state. These are fictional outcomes, never voices.
((root)=>{
 const prompts=[
  ['destination','moon','Where should our spaceship go?','What do you think we might find there?',['The moon','A jungle planet','Somewhere I invent']],
  ['packing','bag','What should we pack for our trip?','Tell Paprika what we could use it for.',['A blanket','A torch','My own idea']],
  ['creature','creature','What friendly creature might we meet?','What does it look like?',['A little dragon','A fluffy giant','Something new']],
  ['house','home','What kind of little home could we build?','What would you put inside?',['A tree house','A cosy tent','A space castle']],
  ['rescue','tools','Our spaceship is stuck! What could we try?','What might help us get moving?',['Build a ramp','Ask our new friend','Another idea']],
  ['memory','star','What was your favourite part of our trip?','Tell Paprika a little about it.',['Our new friend','Exploring','Something else']],
  ['garden','garden','What should we grow in our space garden?','What would it look like when it grows?',['Giant flowers','Funny fruit','My own plant']],
  ['vehicle','rover','How could we travel around our new planet?','Tell Paprika about a vehicle we could make.',['A little rover','A flying boat','Something I invent']],
  ['picnic','bag','Where could we have a pretend picnic?','What would make it a good spot?',['Under a tree','Beside a crater','Somewhere else']],
  ['weather','moon','What is the weather like on our planet?','What would we wear outside?',['Snowy','Warm and sunny','Something surprising']],
  ['gift','creature','What could we make for our new friend?','How would we make it?',['A little house','A drawing','My own idea']],
  ['homecoming','star','What would you tell someone about our trip?','What should we explore next time?',['The creatures','Our spaceship','The next adventure']]
 ].map(([id,scene,question,help,ideas])=>({id,scene,question,help,ideas}));
 const defaults=['clear','short','clear','noise','clear','clear','clear','clear','short','clear','noise','clear'];
 const clone=s=>JSON.parse(JSON.stringify(s));
 const id=()=>globalThis.crypto.randomUUID();
 function create(makeId=id){return {version:1,revision:0,id:makeId(),stage:'welcome',attempts:[],current:null,segmentEnd:6,reviewed:false,resumeStage:null,simulation:true,realProfileCreated:false};}
 function counts(s){return {played:s.attempts.length,eligible:s.attempts.filter(a=>a.outcome==='clear'&&a.review!=='exclude').length,kept:s.attempts.filter(a=>a.outcome==='clear'&&a.review==='keep').length};}
 function next(s,makeId){
  if(s.attempts.length>=12)throw Error('This adventure has reached its twelve-turn limit.');
  s.current={id:makeId(),promptId:prompts[s.attempts.length].id,number:s.attempts.length+1};s.stage='turn';
 }
 function apply(state,event,makeId=id){
  const s=clone(state);
  switch(event.type){
   case 'start':if(s.stage!=='welcome')return s;s.stage='practice';break;
   case 'practised':if(s.stage!=='practice')return s;next(s,makeId);break;
   case 'answered':
    if(s.stage!=='turn')return s;
    if(event.outcome&&!['clear','short','noise'].includes(event.outcome))throw Error('Unknown pretend result.');
    s.current.simulatedOutcome=event.outcome||defaults[s.current.number-1];s.stage='checking';break;
   case 'checked':
    if(s.stage!=='checking'||event.attemptId!==s.current.id)return s;
    if(!['clear','short','noise'].includes(event.outcome))throw Error('Unknown pretend voice result.');
    s.attempts.push({...s.current,outcome:event.outcome,review:'pending',exclusion:null});s.stage='celebrate';break;
   case 'next':
    if(s.stage!=='celebrate')return s;
    if(s.attempts.length>=s.segmentEnd){s.stage='child_done';break;}
    next(s,makeId);break;
   case 'review':if(s.stage!=='child_done')return s;s.stage='review';break;
   case 'exclude':{
    if(s.stage!=='review')return s;
    const a=s.attempts.find(a=>a.id===event.attemptId);
    if(!a||!['keep','other_voice','silly_voice','skip'].includes(event.reason))throw Error('Choose a pretend example to review.');
    if(event.reason==='keep'){
     if(a.outcome!=='clear')throw Error('A short or noisy pretend example cannot become eligible.');
     a.review='pending';a.exclusion=null;
    }else{a.review='exclude';a.exclusion=event.reason;}
    break;
   }
   case 'approve':
    if(s.stage!=='review')return s;
    for(const a of s.attempts)if(a.outcome==='clear'&&a.review!=='exclude')a.review='keep';
    s.reviewed=true;s.stage='summary';break;
   case 'more':
    if(!['summary','saved'].includes(s.stage)||counts(s).kept>=6||s.attempts.length>=12)return s;
    s.segmentEnd=Math.min(12,s.attempts.length+Math.max(2,6-counts(s).kept));next(s,makeId);break;
   case 'finish':if(s.stage!=='summary')return s;s.stage='saved';break;
   case 'pause':
    if(!['practice','turn','checking','celebrate','child_done','review','summary'].includes(s.stage))return s;
    s.resumeStage=s.stage;s.stage='paused';break;
   case 'resume':if(s.stage!=='paused')return s;s.stage=s.resumeStage;s.resumeStage=null;break;
   default:throw Error('Unknown adventure action.');
  }
  s.revision=state.revision+1;return s;
 }
 function restore(raw){
  const s=JSON.parse(raw),stages=['welcome','practice','turn','checking','celebrate','child_done','review','summary','paused','saved'];
  if(s?.version!==1||!Number.isInteger(s.revision)||s.revision<0||s.revision>1000||s.simulation!==true||s.realProfileCreated!==false||typeof s.id!=='string'||!s.id||s.id.length>80||!stages.includes(s.stage)||!Array.isArray(s.attempts)||s.attempts.length>12||!Number.isInteger(s.segmentEnd)||s.segmentEnd<6||s.segmentEnd>12)throw Error('This preview save could not be reopened.');
  const ids=new Set();
  for(let n=0;n<s.attempts.length;n++){
   const a=s.attempts[n];
   if(typeof a.id!=='string'||ids.has(a.id)||a.promptId!==prompts[n].id||a.number!==n+1||!['clear','short','noise'].includes(a.outcome)||!['pending','keep','exclude'].includes(a.review)||(a.review==='keep'&&a.outcome!=='clear'))throw Error('This preview has inconsistent pretend examples.');
   ids.add(a.id);
  }
  const active=s.stage==='paused'?s.resumeStage:s.stage;
  if(s.stage==='paused'&&!['practice','turn','checking','celebrate','child_done','review','summary'].includes(s.resumeStage))throw Error('This preview pause cannot be reopened.');
  if(['turn','checking','celebrate'].includes(active)){
   const n=s.attempts.length+(active==='celebrate'?0:1);
   if(!s.current||typeof s.current.id!=='string'||s.current.number!==n||s.current.promptId!==prompts[n-1]?.id||(active==='celebrate'&&s.current.id!==s.attempts.at(-1)?.id)||(active!=='celebrate'&&ids.has(s.current.id)))throw Error('This preview turn cannot be reopened.');
  }
  if(['review','summary','saved','child_done'].includes(active)&&s.attempts.length<s.segmentEnd)throw Error('This preview stopped before its story was finished.');
  return s;
 }
 class Store{
  constructor(storage){this.storage=storage;this.key='paprika-adventure-preview-v1';}
  read(){
   const raw=this.storage.getItem(this.key);if(!raw)return {version:1,active:null,sessions:{}};
   const data=JSON.parse(raw);
   if(data.version!==1||!data.sessions||typeof data.sessions!=='object'||Array.isArray(data.sessions)||Object.keys(data.sessions).length>10||!Object.hasOwn(data.sessions,data.active))throw Error('This browser preview save cannot be reopened.');
   for(const [key,s] of Object.entries(data.sessions))if(restore(JSON.stringify(s)).id!==key)throw Error('Preview save identity mismatch.');
   return data;
  }
  save(s){
   restore(JSON.stringify(s));const data=this.read();
   const old=data.sessions[s.id];
   if(old&&(old.revision>s.revision||(old.revision===s.revision&&JSON.stringify(old)!==JSON.stringify(s))))throw Error('Another preview tab has different progress. Earlier examples are kept; reopen this preview before continuing.');
   if(!Object.hasOwn(data.sessions,s.id)&&Object.keys(data.sessions).length>=10)throw Error('Ten previews are already saved. Download this visit instead; earlier previews are kept.');
   data.sessions={...data.sessions,[s.id]:clone(s)};data.active=s.id;const raw=JSON.stringify(data);
   try{this.storage.setItem(this.key,raw);}
   catch(error){if(this.storage.getItem(this.key)!==raw)throw error;}
   return clone(s);
  }
 }
 root.PaprikaAdventure={prompts,defaults,create,apply,restore,counts,Store};
})(typeof module==='object'?module.exports:globalThis);

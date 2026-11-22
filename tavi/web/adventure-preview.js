'use strict';
(()=>{
 const M=PaprikaAdventure,$=id=>document.getElementById(id);
 let repository,state,pending=null,saveError='',loadError=false,mode='browser',timer=null,lastStage=null;
 const captions=['Every little idea belongs here.','A new world is waiting.','There is room for your ideas.','A new friend for our crew.','A cosy place among the stars.','Together, we can figure it out.','What a lovely little adventure.'];
 const sceneArt={
  moon:'<circle cx="175" cy="93" r="63" fill="#f8edbd" stroke="#c5b575" stroke-width="2"/><circle cx="150" cy="68" r="13" fill="#e5d594"/><circle cx="195" cy="110" r="20" fill="#e5d594"/><circle cx="153" cy="117" r="8" fill="#e5d594"/><path d="M55 170l35-56 35 56z" fill="#779372"/><path d="M84 119l7-29 8 28" stroke="#45694e" stroke-width="3" fill="#f4f0ce"/>',
  bag:'<path d="M104 78c0-48 82-48 82 0" fill="none" stroke="#b5845b" stroke-width="13"/><rect x="75" y="73" width="145" height="112" rx="22" fill="#ce9563" stroke="#9f704c" stroke-width="3"/><rect x="87" y="88" width="121" height="82" rx="12" fill="#edc590"/><path d="M117 73v112m62-112v112" stroke="#b5845b" stroke-width="9"/><path d="M146 104l7 16 18 2-13 12 3 18-15-9-16 9 3-18-13-12 18-2z" fill="#f9efb5"/>',
  creature:'<path d="M100 152c-27-72 8-107 51-75 30-42 75-9 58 39 25 33 1 67-43 67-36 0-56-9-66-31" fill="#91ad8b" stroke="#628564" stroke-width="3"/><path d="M106 91l-10-28 33 16m45 0 26-23 1 34" fill="#bfd2a0" stroke="#628564" stroke-width="3"/><circle cx="137" cy="119" r="5" fill="#374d3d"/><circle cx="174" cy="119" r="5" fill="#374d3d"/><path d="M143 140q12 10 24-1" fill="none" stroke="#45654a" stroke-width="3" stroke-linecap="round"/>',
  home:'<path d="M84 112l68-60 68 60" fill="#c47d59" stroke="#956045" stroke-width="3"/><path d="M99 111h106v77H99z" fill="#f2d6a5" stroke="#ba9b70" stroke-width="2"/><path d="M139 188v-45q15-15 30 0v45" fill="#9da97a"/><rect x="110" y="126" width="19" height="22" rx="5" fill="#a5bdad"/><rect x="180" y="126" width="16" height="22" rx="5" fill="#a5bdad"/>',
  tools:'<path d="M69 165l134-79 17 31-134 79z" fill="#ceaa70" stroke="#a1804c" stroke-width="2"/><path d="M96 148l70-44 22 38-70 43z" fill="#9aaf9f"/><circle cx="133" cy="181" r="13" fill="#5d7562"/><circle cx="190" cy="146" r="13" fill="#5d7562"/><path d="M120 117l-8-43 61-14 8 46" fill="#e5d7ab" stroke="#9d9670" stroke-width="2"/>',
  star:'<path d="M153 41l25 53 59 8-43 42 10 60-51-28-52 28 10-60-43-42 59-8z" fill="#e7c77d" stroke="#bc9e53" stroke-width="3"/><circle cx="138" cy="121" r="4" fill="#73623e"/><circle cx="170" cy="121" r="4" fill="#73623e"/><path d="M140 141q15 12 27-1" stroke="#917941" stroke-width="3" fill="none" stroke-linecap="round"/>',
  garden:'<path d="M148 187V93m0 51q-55 5-48-38 37 0 48 38m0 17q50 7 49-34-36 2-49 34" fill="#96b080" stroke="#627f56" stroke-width="4"/><circle cx="148" cy="75" r="37" fill="#dfac81"/><circle cx="148" cy="75" r="14" fill="#f0d79a"/>',
  rover:'<path d="M80 125h140v51H80z" fill="#b2c1a0" stroke="#708768" stroke-width="3"/><path d="M112 124V91h67v33" fill="#e7d6a7" stroke="#9b9e77" stroke-width="3"/><circle cx="110" cy="180" r="18" fill="#617761"/><circle cx="190" cy="180" r="18" fill="#617761"/><path d="M166 90V61l30-12" fill="none" stroke="#708768" stroke-width="4"/>'
 };
 function load(){
  try{repository=new M.Store(localStorage);const data=repository.read();state=data.active?M.restore(JSON.stringify(data.sessions[data.active])):M.create();saveError='';loadError=false;pending=null;}
  catch(error){state=state||M.create();saveError='This browser could not reopen the preview. Your earlier saved previews have not been replaced. Try again, or play for this visit without saving.';loadError=true;}
  render();
 }
 function commit(next){
  if(mode==='visit'){state=next;pending=null;saveError='';render();return;}
  try{repository.save(next);state=next;pending=null;saveError='';render();}
  catch(error){pending=next;saveError='Your adventure is still here, but this browser could not save the latest step. Try saving again, or continue for this visit. If you reload, unsaved progress may be lost.';render();}
 }
 function act(event){if(saveError)return;try{commit(M.apply(state,event));}catch(error){$('error').textContent=error.message;}}
 function button(id,label,fn){const b=$(id);b.hidden=!label;if(label){b.textContent=label;b.onclick=fn;}}
 function text(id,value){$(id).textContent=value;}
 function draw(scene){
  $('scene').innerHTML='<svg viewBox="0 0 300 230"><g fill="#81966b"><circle cx="45" cy="65" r="3"/><circle cx="241" cy="43" r="3"/><circle cx="255" cy="163" r="2"/></g><path d="M58 95v12m-6-6h12m175 3v16m-8-8h16" stroke="#8a9d72" stroke-width="2" stroke-linecap="round"/>'+sceneArt[scene]+'</svg>';
 }
 function review(){
  const host=$('review-list');host.replaceChildren();
  for(const a of state.attempts){
   const row=document.createElement('div');row.className='review-row';
   const title=document.createElement('strong');title.textContent=`Turn ${a.number} · ${M.prompts[a.number-1].question}`;row.append(title);
   const p=document.createElement('p');p.textContent=a.outcome==='clear'?'Pretend clear example · eligible for your review':a.outcome==='short'?'Pretend short turn · not counted':'Pretend noisy turn · not counted';row.append(p);
   if(a.outcome==='clear'){
    const select=document.createElement('select');select.setAttribute('aria-label',`Review pretend turn ${a.number}`);
    for(const [value,label] of [['keep','Keep this pretend example'],['other_voice','Someone else answered · leave out'],['silly_voice','A silly voice · leave out'],['skip','Leave this one out']]){const option=document.createElement('option');option.value=value;option.textContent=label;select.append(option);}
    select.value=a.exclusion||'keep';select.onchange=()=>act({type:'exclude',attemptId:a.id,reason:select.value});row.append(select);
   }
   host.append(row);
  }
 }
 function render(){
  if(timer!==null){clearTimeout(timer);timer=null;}
  const s=state,c=M.counts(s),p=s.current?M.prompts.find(p=>p.id===s.current.promptId):M.prompts[0];
  const stop=['practice','turn','checking','celebrate','child_done','review','summary'].includes(s.stage);
  $('pause').hidden=!stop||!!saveError;$('hint').hidden=s.stage!=='turn'||!!saveError;$('ideas').hidden=true;
  $('review-list').hidden=s.stage!=='review';$('coverage').hidden=!['review','summary','saved'].includes(s.stage);
  text('error',saveError);$('recovery').hidden=!saveError;$('actions').hidden=!!saveError;
  $('outcome').disabled=s.stage==='checking'||!!saveError;
  text('save-mode',mode==='visit'?'This visit only. Reloading may lose this preview. No recordings exist.':'Pretend progress saves in this browser. No recordings exist.');
  $('journey').replaceChildren();
  for(let n=1;n<=s.segmentEnd;n++){const li=document.createElement('li');li.textContent=n<=c.played?'✓':String(n);li.className=n<=c.played?'done':n===s.current?.number?'current':'';li.setAttribute('aria-label',`Stop ${n}${n<=c.played?' complete':''}`);$('journey').append(li);}
  draw(['turn','checking','celebrate'].includes(s.stage)?p.scene:s.stage==='practice'?'bag':s.stage==='welcome'?'moon':'star');
  text('world-caption',captions[Math.min(c.played,6)]);
  const remaining=Math.max(0,6-c.kept),more=Math.min(12-c.played,Math.max(2,remaining));
  const copy={
   welcome:['WELCOME, EXPLORER','No voice is being recorded','Shall we go on an adventure?','','Help Paprika imagine a little trip through space. Six little questions. No right or wrong answers.','In this preview, tap the buttons instead of speaking.'],
   practice:['ONE LITTLE PRACTICE','Microphone off · pretend turn','First, let’s try one together.','What would you put in a space backpack?','Think of an idea, then tap “I’ve answered”. You do not need to say anything out loud.','A grown-up can read the questions for this preview.'],
   turn:[`STOP ${s.current?.number} OF ${s.segmentEnd}`,'YOUR TURN · pretend answer','What do you think?',p.question,p.help,'Tap “I’ve answered” instead of speaking. No microphone is used.'],
   checking:[`STOP ${s.current?.number} OF ${s.segmentEnd}`,'A LITTLE MOMENT · microphone off','Getting our next stop ready…',p.question,p.help,'This is a pretend check. Your question stays here.'],
   celebrate:[`STOP ${s.current?.number} COMPLETE`,'NICE EXPLORING · microphone off','Another part of our story!',p.question,'All sorts of ideas make an adventure. Let’s see what happens next.','Every turn moves the story forward.'],
   child_done:['ADVENTURE COMPLETE','Microphone off · no voices collected','Thanks for exploring with me!','','Our little space adventure is finished. A grown-up can look at the pretend examples now.','You do not need to repeat anything.'],
   review:['GROWN-UP REVIEW','Pretend examples only · microphone off','Keep the useful examples.','','Some turns were deliberately short or noisy. They still moved the story forward. Check the clear examples together; there is no need to make the child redo a sentence.','This is batch review, not a voice-recognition result.'],
   summary:['GROWN-UP SUMMARY','No real profile has been made',c.kept>=6?'A pretend example set is ready.':'A little more voice would be needed.','',c.kept>=6?'In the real flow, these would form an unqualified candidate for later testing. Recognition would stay off.':'The useful examples are kept. Finish for now, or try a mini-adventure with fresh questions. There are no repeated sentences.',c.played>=12&&c.kept<6?'This preview has reached its twelve-turn limit. Finish for now; another session would be needed.':'The child has already finished the adventure. Extra questions are optional.'],
   paused:['TAKE A BREAK','Microphone off · nothing is listening','We can come back later.','','Your useful pretend examples and place in the story are kept. Continue when you are ready.',mode==='visit'?'Keep this page open. You chose to play without saving.':'You can reload this page and continue. Only pretend progress is stored.'],
   saved:['PREVIEW FINISHED','Microphone off · no voice profile',c.kept>=6?'Thanks, explorer. All done!':'Thanks, explorer. That’s enough for today.','',c.kept>=6?'The pretend examples were reviewed. Real recognition would still need a fresh-session check and other voices.':'The usable pretend examples are kept. A later mini-adventure could collect more, without repeating today’s questions.','This was a design preview. No voice, identity or personal memory was collected.']
  }[s.stage];
  for(const [n,id] of ['step','cue','title','question','help','notice'].entries())text(id,copy[n]);
  text('coverage',`${c.kept} of 6 proposed examples kept${s.stage==='review'?` · ${c.eligible} eligible for your review`:''}. Fictional outcomes only.`);
  if(s.stage==='review')review();
  const actions={welcome:["Let's explore",()=>act({type:'start'})],practice:['I’ve answered · let’s go',()=>act({type:'practised'})],turn:['I’ve answered',()=>act({type:'answered',...($('outcome').value!=='script'?{outcome:$('outcome').value}:{})})],celebrate:[c.played>=s.segmentEnd?'Finish our adventure':'Next stop',()=>act({type:'next'})],child_done:['Grown-up: review pretend examples',()=>act({type:'review'})],review:['Keep the usable pretend examples',()=>act({type:'approve'})],summary:['Finish for now',()=>act({type:'finish'})],paused:['Continue our adventure',()=>act({type:'resume'})],saved:['Start a separate preview',newPreview]};
  button('primary',actions[s.stage]?.[0],actions[s.stage]?.[1]);
  button('secondary',['summary','saved'].includes(s.stage)&&remaining&&c.played<12?`Try ${more} fresh questions`:null,()=>act({type:'more'}));
  if(s.stage==='checking'&&!saveError)timer=setTimeout(()=>{timer=null;act({type:'checked',attemptId:s.current.id,outcome:s.current.simulatedOutcome});},650);
  if(lastStage!==s.stage){$('title').focus({preventScroll:true});lastStage=s.stage;}
 }
 function newPreview(){if(saveError)return;commit(M.create());}
 $('pause').onclick=()=>act({type:'pause'});
 $('hint').onclick=()=>{$('ideas').replaceChildren();const list=document.createElement('ul');for(const idea of M.prompts.find(p=>p.id===state.current.promptId).ideas){const li=document.createElement('li');li.textContent=idea;list.append(li);}$('ideas').append(list);$('ideas').hidden=false;};
 $('retry').onclick=()=>{if(loadError){load();return;}if(pending)commit(pending);};
 $('temporary').onclick=()=>{mode='visit';state=pending||state;pending=null;saveError='';loadError=false;render();};
 $('download').onclick=()=>{const raw=JSON.stringify({preview:true,realVoiceCollected:false,state:pending||state},null,2);const url=URL.createObjectURL(new Blob([raw],{type:'application/json'}));const a=document.createElement('a');a.href=url;a.download='paprika-pretend-adventure.json';a.click();URL.revokeObjectURL(url);};
 $('new').onclick=newPreview;
 window.addEventListener('pagehide',()=>{if(timer!==null)clearTimeout(timer);});
 window.addEventListener('pageshow',event=>{if(event.persisted)render();});
 load();
})();

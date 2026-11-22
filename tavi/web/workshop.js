'use strict';
(()=>{
 const $=id=>document.getElementById(id);let busy=false;
 const names=['adult','adventure','family'],urls={adult:'http://127.0.0.1:8780/',adventure:'http://127.0.0.1:8781/',family:'http://127.0.0.1:8783/'};
 async function request(path,options={}){
  const r=await fetch(path,{...options,signal:AbortSignal.timeout(8000)});const data=await r.json();
  if(!r.ok)throw Error(data.error||'The local check could not finish.');return data;
 }
 function render(s){
  for(const name of names){
   const service=s.services[name],open=$(`${name}-open`),prepare=$(`${name}-prepare`);
   const usable=service.recognized&&service.ready&&service.url===urls[name];
   open.hidden=!usable;if(usable){if(name==='family')for(const person of ['childone','childtwo','adulttwo'])$('family-'+person).href=urls.family+person;else open.href=urls[name];}
   prepare.hidden=service.reachable||service.recognized;prepare.disabled=busy;
   $(`${name}-state`).textContent=usable?'Ready when you are':service.recognized?'Setup found · reconnect the drive or ask for local-file review':service.reachable?'Local page present · readiness not verified. Choose Check again.':'Not running · prepare this local page when ready';
  }
  $('drive').textContent=s.drive_connected?'Connected':'Reconnect the external drive';
  $('model').textContent=s.voice_model_file_present?'File found · loading not checked':'Local file unavailable';
  $('budget').textContent=s.budget.available?`$${s.budget.spent_reserved_usd.toFixed(2)} of $${s.budget.cap_usd.toFixed(2)}`:'Ledger unavailable · no spending started';
  $('help').textContent=s.drive_connected?'These checks do not start models, recording or online requests. File presence does not prove a model is loaded or qualified.':'Reconnect the external drive, then choose Check again. The pretend adventure can still run without it.';
 }
 async function refresh(){
  if(busy)return;busy=true;$('refresh').disabled=true;$('error').textContent='';$('loading').textContent='Checking the local preparation pages…';
  try{render(await request('/api/status'));$('loading').textContent='Checked. Nothing is recording through this page.';}
  catch(error){$('error').textContent='The workshop could not check readiness. Your other pages and saved files are kept. Choose Check again.';$('loading').textContent='Check unavailable';for(const name of names){$(`${name}-open`).hidden=true;$(`${name}-prepare`).hidden=true;$(`${name}-state`).textContent='Readiness unavailable · choose Check again';}}
  finally{busy=false;$('refresh').disabled=false;for(const name of names)$(`${name}-prepare`).disabled=false;}
 }
 for(const name of names)$(`${name}-prepare`).onclick=async()=>{
  if(busy)return;busy=true;$('error').textContent='';$('refresh').disabled=true;
  for(const n of names)$(`${n}-prepare`).disabled=true;
  $(`${name}-state`).textContent='Preparing the local page… No recording has begun.';
  try{await request('/api/prepare',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({service:name})});}
  catch(error){$('error').textContent=error.message;}
  finally{busy=false;$('refresh').disabled=false;for(const n of names)$(`${n}-prepare`).disabled=false;}
  const error=$('error').textContent;await refresh();if(error)$('error').textContent=error;
 };
 $('refresh').onclick=refresh;refresh();
})();

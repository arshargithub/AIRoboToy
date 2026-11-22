'use strict';
// Actual guided-page QA. Fictional prerecorded audio only, accelerated/muted QA
// playback, separate QA feedback store, no owner ratings or production app.
const fs=require('node:fs'),path=require('node:path'),http=require('node:http'),assert=require('node:assert/strict');
const {spawn}=require('node:child_process');const {app,BrowserWindow,session}=require('electron');
const root=path.resolve(__dirname,'../..'),folder=process.env.PAPRIKA_CADENCE_QA_FOLDER;
if(!folder)throw Error('Private QA folder required');
app.setPath('userData',path.join(folder,'qa-chromium'));app.setPath('sessionData',path.join(folder,'qa-chromium-session'));
app.commandLine.appendSwitch('autoplay-policy','no-user-gesture-required');
const sleep=ms=>new Promise(resolve=>setTimeout(resolve,ms));let child,win,permissionRequests=0;
async function until(fn,ms=12000){const end=Date.now()+ms;while(Date.now()<end){if(await fn())return;await sleep(50);}throw Error('QA wait expired');}
app.whenReady().then(async()=>{
 const report={qa_only:true,real_microphone:false,physical_audio:false,accelerated_playback:true,cloud_calls:0};
 try{
  const reserve=http.createServer();await new Promise(resolve=>reserve.listen(0,'127.0.0.1',resolve));const port=reserve.address().port;await new Promise(resolve=>reserve.close(resolve));
  child=spawn(path.join(root,'.venv-tavi/bin/python'),['-m','tavi.voice_continuity_review','--qa','--manifest',path.join(root,'experiments/speech/cadence-preview-v1.json'),'--port',String(port)],{cwd:root,stdio:['ignore','pipe','pipe']});
  let log='';child.stdout.on('data',b=>log+=b);child.stderr.on('data',b=>log+=b);
  await until(()=>log.includes('"qa": true')||child.exitCode!==null);if(child.exitCode!==null)throw Error(log);
  const isolated=session.fromPartition('cadence-qa-'+Date.now());isolated.setPermissionRequestHandler((w,p,callback)=>{permissionRequests++;callback(false);});isolated.setPermissionCheckHandler(()=>false);
  win=new BrowserWindow({show:false,width:1100,height:900,webPreferences:{session:isolated,nodeIntegration:false,contextIsolation:true,sandbox:true}});win.webContents.setAudioMuted(true);
  const js=code=>win.webContents.executeJavaScript(code,true);
  await win.loadURL('http://127.0.0.1:'+port+'/');await until(()=>js(`document.querySelector('#app h1')?.textContent==='Does K still sound smooth?'`));
  assert(await js(`document.body.textContent.includes('No microphone, recording, cloud request or extra spending.')`));
  await js(`(()=>{const fetchOriginal=window.fetch;let failed=false;window.fetch=(...args)=>{if(!failed&&String(args[0]).includes('/audio/')){failed=true;return Promise.reject(Error('QA audio connection interruption'));}return fetchOriginal(...args);};const button=[...document.querySelectorAll('button')].find(b=>b.textContent==='Start listening check');button.click();})()`);
  await until(()=>js(`document.querySelector('#error')?.textContent.includes('Start to retry')`));report.audio_retry_guided=true;
  await js(`document.querySelector('button').click()`);await until(()=>js(`document.querySelectorAll('section.card').length===3`));
  await js(`(()=>{const make=AudioContext.prototype.createBufferSource;AudioContext.prototype.createBufferSource=function(){const source=make.call(this);source.playbackRate.value=4;return source;};document.querySelector('section.card button').click();})()`);
  await sleep(100);await js(`[...document.querySelectorAll('button')].find(b=>b.textContent==='Stop playback').click()`);
  assert.equal(await js(`JSON.parse(localStorage.getItem('paprika-voice-continuity-v1')).completed.length`),0);report.stop_not_completion=true;
  await js(`(()=>{const input=document.querySelector('input[type=range]');input.value=32;input.dispatchEvent(new Event('input'));})()`);
  assert.equal(await js(`document.querySelector('output').textContent`),'32%');report.numeric_volume=true;
  for(let n=0;n<3;n++)for(let v=0;v<2;v++){
   const previous=await js(`JSON.parse(localStorage.getItem('paprika-voice-continuity-v1')).completed.length`);
   await js(`document.querySelectorAll('section.card')[${n}].querySelectorAll('button')[${v}].click()`);
   await until(()=>js(`JSON.parse(localStorage.getItem('paprika-voice-continuity-v1')).completed.length===${previous+1}`));
  }
  report.six_actual_audio_completions=true;
  await js(`document.querySelectorAll('textarea').forEach((t,i)=>{t.value='QA only: example '+i+' — pause review\\nSecond line.';t.dispatchEvent(new Event('input'));})`);
  assert.equal(await js(`document.querySelector('#save').disabled`),false);report.text_only_feedback=true;
  fs.writeFileSync(path.join(folder,'guided-comparison.png'),(await win.webContents.capturePage()).toPNG(),{mode:0o600});
  await js(`(()=>{const fetchOriginal=window.fetch;let failed=false;window.fetch=(...args)=>{if(!failed&&args[0]==='/save'){failed=true;return Promise.resolve(new Response(JSON.stringify({error:'QA temporary save failure'}),{status:503,headers:{'Content-Type':'application/json'}}));}return fetchOriginal(...args);};document.querySelector('#save').click();})()`);
  await until(()=>js(`document.querySelector('#error')?.textContent.includes('Your answers are still here')`));report.save_retry_guided=true;
  await win.webContents.reload();await until(()=>js(`document.querySelectorAll('textarea').length===3`));
  assert.equal(await js(`document.querySelector('textarea').value`),'QA only: example 0 — pause review\nSecond line.');
  assert.equal(await js(`JSON.parse(localStorage.getItem('paprika-voice-continuity-v1')).completed.length`),6);report.reload_preserves_reviews_and_completions=true;
  await js(`document.querySelector('#save').click()`);await until(()=>js(`document.querySelector('#app h1')?.textContent==='Your feedback is saved.'`));
  const draft=await js(`JSON.parse(localStorage.getItem('paprika-voice-continuity-v1'))`);
  const directory=path.join(root,'.tavi/qa/voice-continuity');const names=fs.readdirSync(directory).filter(n=>n.startsWith(draft.id+'-'));
  assert.equal(names.length,1);const record=JSON.parse(fs.readFileSync(path.join(directory,names[0])));assert.equal(record.qa,true);assert.equal(record.kind,'speech_cadence_preview');
  assert.equal(record.reviews.boat.notes,'QA only: example 0 — pause review\nSecond line.');report.direct_qa_save=true;
  await js(`document.querySelector('button').click()`);await until(()=>js(`document.querySelector('#save')&&!document.querySelector('#save').disabled`));report.revisit_feedback=true;
  assert.equal(permissionRequests,0);report.permission_requests=permissionRequests;report.passed=true;
 }catch(error){report.error=error.stack;process.exitCode=1;}
 finally{
  fs.writeFileSync(path.join(folder,'guided-qa.json'),JSON.stringify(report,null,2)+'\n',{mode:0o600});
  if(win&&!win.isDestroyed())win.destroy();
  if(child&&child.exitCode===null){child.kill('SIGTERM');await new Promise(resolve=>{child.once('exit',resolve);setTimeout(()=>{if(child.exitCode===null)child.kill('SIGKILL');resolve();},2000);});}
  console.log(JSON.stringify(report));app.quit();
 }
});

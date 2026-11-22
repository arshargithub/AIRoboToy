// Real Chromium + real local models, synthetic microphone ONLY, offline and muted.
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const {app,BrowserWindow}=require('electron');
app.commandLine.appendSwitch('use-fake-device-for-media-stream');
// Do not bypass the app's permission handlers: exercise them with fake hardware.
require('../main.cjs');
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
app.whenReady().then(async()=>{
 const report={synthetic_microphone:true,cloud_replies:false,volume:0,real_microphone:false,started:false,completed:false};
 try{
  let win;
  for(let n=0;n<150;n++){
   win=BrowserWindow.getAllWindows()[0];
   if(win&&!win.webContents.isLoading()&&await win.webContents.executeJavaScript(`document.querySelector('#readiness')?.textContent.toLowerCase().includes('ready')`))break;
   await sleep(100);
  }
  assert(win);
  await win.webContents.executeJavaScript(`(()=>{document.querySelector('#adult').checked=true;document.querySelector('#adult').dispatchEvent(new Event('change'));const offline=document.querySelector('input[value=offline]');offline.checked=true;offline.dispatchEvent(new Event('change'));const volume=document.querySelector('#volume');volume.value=0;volume.dispatchEvent(new Event('input'));document.querySelector('#start').click();})()`,true);
  for(let n=0;n<500;n++){
   const state=await win.webContents.executeJavaScript(`({mic:document.querySelector('#mic-state').textContent,error:document.querySelector('#error-card').hidden?'':document.querySelector('#error').textContent})`);
   if(state.error)throw Error(state.error);
   if(['Microphone on','Listening locally for my name'].includes(state.mic)){report.started=true;break;}
   await sleep(100);
  }
  assert(report.started,'Local model/audio startup timed out');
  await sleep(1800);
  const diagnostic=await win.webContents.executeJavaScript(`window.paprika.diagnostics()`);
  report.local_asr=diagnostic.asr_models;report.voice=diagnostic.voice;report.model=diagnostic.model;report.memory_enabled=diagnostic.memory_enabled;report.online_replies=diagnostic.online_replies;
  assert.equal(diagnostic.lease_active,true);assert.equal(diagnostic.online_replies,false);assert.equal(diagnostic.memory_enabled,false);
  await win.webContents.executeJavaScript(`document.querySelector('#mute').click()`);
  for(let n=0;n<50;n++){if(await win.webContents.executeJavaScript(`document.querySelector('#mic-state').textContent==='Microphone off'`))break;await sleep(100);}
  assert.equal(await win.webContents.executeJavaScript(`document.querySelector('#mic-state').textContent`),'Microphone off');
  const stopped=await win.webContents.executeJavaScript(`window.paprika.diagnostics()`);assert.equal(stopped.lease_active,false);
  report.completed=true;console.log('Synthetic microphone smoke passed: local turbo/K startup, IPC PCM, active lease and explicit mute; no cloud or real microphone.');
 }catch(error){report.error=error.message;console.error(error);process.exitCode=1;}
 finally{fs.writeFileSync(path.resolve(__dirname,'../../.tavi/mac/audio-smoke.json'),JSON.stringify(report,null,2));app.quit();}
});

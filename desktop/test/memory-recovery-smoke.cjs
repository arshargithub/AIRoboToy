// Actual renderer/restricted bridge, synthetic error only. Never start capture.
'use strict';
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const {app,BrowserWindow}=require('electron');require('../main.cjs');
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
const expectedBudget=Number(process.env.PAPRIKA_EXPECTED_BUDGET_USD||31);
app.whenReady().then(async()=>{try{
 let win;
 for(let n=0;n<150;n++){
  win=BrowserWindow.getAllWindows()[0];
  if(win&&!win.webContents.isLoading()&&await win.webContents.executeJavaScript(`document.querySelector('#readiness')?.textContent==='Ready when you are.'`))break;
  await sleep(100);
 }
 if(!win)throw Error('No renderer window');
 const before=await win.webContents.executeJavaScript(`(async()=>({status:await window.paprika.status(),diag:await window.paprika.diagnostics(),adult:document.querySelector('#adult').checked,choice:document.querySelector('input[name=processing]:checked')?.value||null}))()`);
 assert.equal(before.diag.lease_active,false);assert.equal(before.adult,false);assert.equal(before.choice,null);
 assert.equal(before.status.family.family_memory_requested,false);assert.equal(before.status.family.family_voice_enabled,false);
 assert.equal(before.status.budget_usd,expectedBudget);
 assert(await win.webContents.executeJavaScript(`document.querySelector('#budget').textContent.includes('of $${expectedBudget.toFixed(2)}.')`));
 await win.webContents.executeJavaScript(`(()=>{
  const original=MacAudioEndpoint.prototype.setVolume;
  MacAudioEndpoint.prototype.setVolume=function(v){window.fixtureEndpoint=this;return original.call(this,v);};
  document.querySelector('#volume').dispatchEvent(new Event('input'));
  window.fixtureEndpoint.onState({active:false,starting:false,playing:false,loading:false,state:{engagement:'idle',output:'silent',error:'Memory is unavailable',failure:{code:'memory_worker_unavailable'}}});
 })()`);
 await sleep(100);
 const recovery=await win.webContents.executeJavaScript(`(()=>({text:document.querySelector('#error').textContent,buttonHidden:document.querySelector('#memory-return').hidden,retryHidden:document.querySelector('#retry').hidden,focus:document.activeElement.id,mic:document.querySelector('#mic-state').textContent}))()`);
 assert.match(recovery.text,/Listening is off/);assert.match(recovery.text,/without using or learning memories/);
 assert.equal(recovery.buttonHidden,false);assert.equal(recovery.retryHidden,true);assert.equal(recovery.focus,'memory-return');assert.equal(recovery.mic,'Microphone off');
 const report=process.env.PAPRIKA_RECOVERY_REPORT;if(!report)throw Error('Report path required');
 fs.writeFileSync(path.join(path.dirname(report),'memory-recovery.png'),(await win.webContents.capturePage()).toPNG(),{mode:0o600,flag:'wx'});
 await win.webContents.executeJavaScript(`document.querySelector('#memory-return').click();true`);
 await sleep(150);
 const after=await win.webContents.executeJavaScript(`(async()=>({page:document.body.dataset.page,adult:document.querySelector('#adult').checked,choice:document.querySelector('input[name=processing]:checked')?.value||null,startDisabled:document.querySelector('#start').disabled,memoryDisabled:document.querySelector('#family-memory').disabled,note:document.querySelector('#family-note').textContent,diag:(await window.paprika.diagnostics()).lease_active}))()`);
 assert.equal(after.page,'setup');assert.equal(after.adult,false);assert.equal(after.choice,null);assert.equal(after.startDisabled,true);assert.equal(after.memoryDisabled,true);assert.equal(after.diag,false);assert.match(after.note,/paused for this visit/);
 fs.writeFileSync(report,JSON.stringify({passed:true,recovery,after,budget_usd:before.status.budget_usd,live_prompt_sha256:before.status.reply_prompt_sha256,real_microphone:false,cloud_calls:0,calibration_started:false},null,2)+'\n',{mode:0o600,flag:'wx'});
 console.log(JSON.stringify({renderer_recovery:'pass',report}));app.quit();
}catch(e){console.error(e.message);process.exitCode=1;app.quit();}});

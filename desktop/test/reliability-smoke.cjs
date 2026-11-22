'use strict';
// Actual renderer + owned core lifecycle; never open microphone or inference.
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const {app,BrowserWindow,powerMonitor}=require('electron'),{CoreOwner}=require('../owner.cjs');
require('../main.cjs');const sleep=ms=>new Promise(r=>setTimeout(r,ms));
async function until(test){for(let i=0;i<150;i++){if(await test())return;await sleep(100);}throw Error('Renderer lifecycle deadline');}
app.whenReady().then(async()=>{try{
 console.log('Phase: window readiness');
 let win;await until(async()=>{win=BrowserWindow.getAllWindows()[0];return win&&!win.webContents.isLoading()&&await win.webContents.executeJavaScript(`document.querySelector('#readiness')?.textContent==='Ready when you are.'&&document.querySelector('#retry').disabled===false`);});
 console.log('Phase: window ready');
 const owner=new CoreOwner(path.resolve(__dirname,'../..'));await owner.verify(owner.read());const first=owner.record.instance;
 const off=()=>win.webContents.executeJavaScript(`(async()=>({adult:document.querySelector('#adult').checked,choice:document.querySelector('input[name=processing]:checked')?.value||null,disabled:document.querySelector('#start').disabled,mic:(await window.paprika.diagnostics()).lease_active}))()`);
 let state=await off();assert.equal(state.mic,false);assert.equal(state.adult,false);assert.equal(state.choice,null);
 console.log('Phase: simulated power events');
 powerMonitor.emit('suspend');powerMonitor.emit('resume');powerMonitor.emit('lock-screen');powerMonitor.emit('unlock-screen');await sleep(250);
 state=await off();assert.equal(state.mic,false);assert.equal(state.adult,false);assert.equal(state.choice,null);assert.equal(state.disabled,true);
 console.log('Phase: stopping owned core');
 await owner.stop();console.log('Phase: core stopped');await until(async()=>!owner.read());
 console.log('Phase: requesting reconnect');
 await win.webContents.executeJavaScript(`document.querySelector('#retry').click();true`);
 await until(async()=>{const r=owner.read();if(!r||r.instance===first)return false;try{await owner.verify(r);return true;}catch{return false;}});
 console.log('Phase: replacement core ready');
 await until(()=>win.webContents.executeJavaScript(`document.querySelector('#readiness').textContent==='Ready when you are.'&&document.querySelector('#error-card').hidden&&document.querySelector('#retry').disabled===false`));
 state=await off();assert.equal(state.mic,false);assert.equal(state.adult,false);assert.equal(state.choice,null);assert.equal(state.disabled,true);
 const report=process.env.PAPRIKA_RELIABILITY_RENDERER_REPORT;if(!report)throw Error('Report required');
 fs.writeFileSync(report,JSON.stringify({passed:true,actual_renderer:true,simulated_power_events:true,physical_sleep:false,owned_core_restart:true,instance_changed:owner.record.instance!==first,state,real_microphone:false,cloud_calls:0},null,2)+'\n',{mode:0o600,flag:'wx'});
 console.log('Actual renderer suspend/reconnect passed with microphone off');app.quit();
}catch(e){console.error(e.message);process.exitCode=1;app.quit();}});

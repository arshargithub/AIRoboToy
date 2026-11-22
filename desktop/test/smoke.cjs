// Run with Electron, not node. Negative consent + actual Chromium worklet only.
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const {app,BrowserWindow}=require('electron');
require('../main.cjs');
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
app.whenReady().then(async()=>{
 for(let n=0;n<150;n++){
  const win=BrowserWindow.getAllWindows()[0];
  if(win&&!win.webContents.isLoading()&&win.webContents.getURL()==='http://127.0.0.1:8785/'){
   try{
    const page=await win.webContents.executeJavaScript(`(()=>{try{return ({title:document.title,ready:document.querySelector('#readiness')?.textContent,startDisabled:document.querySelector('#start')?.disabled,adult:document.querySelector('#adult')?.checked,processing:document.querySelector('input[name=processing]:checked')?.value||null,node:typeof require,mic:document.querySelector('#mic-state')?.textContent,styled:getComputedStyle(document.body).fontFamily.includes('apple-system'),page:document.body.dataset.page,displayHidden:document.querySelector('#companion-screen')?.hidden})}catch(e){return {error:e.stack}}})()`);
    if(page.error)throw Error(page.error);
    if(!page.ready?.toLowerCase().includes('ready')){await sleep(100);continue;}
    assert.equal(page.title,'Paprika');assert.equal(page.startDisabled,true);assert.equal(page.adult,false);assert.equal(page.processing,null);assert.equal(page.node,'undefined');assert.equal(page.mic,'Microphone off');assert.equal(page.styled,true);assert.equal(page.page,'setup');assert.equal(page.displayHidden,true);
    console.log('Setup renderer inspected.');
    const worklet=await win.webContents.executeJavaScript(`(async()=>{const c=new AudioContext({sampleRate:16000});await c.audioWorklet.addModule('/capture.js');const n=new AudioWorkletNode(c,'tavi-capture');n.disconnect();await c.close();return 'registered';})()`);
    assert.equal(worklet,'registered');console.log('Actual worklet registered.');
    const security=win.webContents.getLastWebPreferences();assert(security.contextIsolation);assert(security.sandbox);assert.equal(security.nodeIntegration,false);
    win.close();assert.equal(win.isDestroyed(),false);assert.equal(win.isVisible(),false);win.show();
    const png=await win.webContents.capturePage();const dir=path.resolve(__dirname,'../../.tavi/mac');fs.writeFileSync(path.join(dir,'ui-smoke.png'),png.toPNG());
    // Presentation fixtures only: never start an endpoint or change consent.
    console.log('Setup screenshot captured.');
    for(const kind of ['standby','listening','thinking','talking','farewell','paused']){
     const fixture=await win.webContents.executeJavaScript(`(()=>{try{document.querySelector('#setup-screen').hidden=true;document.querySelector('#companion-screen').hidden=false;document.body.dataset.page='companion';document.querySelector('#face-card').dataset.state=${JSON.stringify(kind)};document.querySelector('#face-card').style.setProperty('--speech','.45');const p=companionState({active:${kind!=='paused'},playing:${['talking','farewell'].includes(kind)},state:{engagement:${JSON.stringify(kind==='standby'?'idle':'active')},input:${JSON.stringify(kind==='listening'?'capturing':'wake_only')},output:${JSON.stringify(kind==='thinking'?'generating':'silent')},closing_after_playback:${kind==='farewell'}}});document.querySelector('#state').textContent=p.title;document.querySelector('#cue').textContent=p.cue;document.querySelector('#mic-state').textContent=p.mic;return true;}catch(e){return e.stack;}})()`);
     assert.equal(fixture,true);
     await win.webContents.executeJavaScript(`(()=>{document.querySelector('#mute').hidden=${kind==='paused'};document.querySelector('#resume').hidden=${kind!=='paused'};document.querySelector('#resume').textContent='Listen again';document.querySelector('#interrupt').hidden=${kind==='paused'};document.querySelector('#end').hidden=${kind==='paused'};})()`);
     await sleep(750); // Presentation fixture only: allow CSS morph to settle before capture.
     const screenshot=await win.webContents.capturePage();fs.writeFileSync(path.join(dir,'face-'+kind+'.png'),screenshot.toPNG());
    }
    fs.writeFileSync(path.join(dir,'ui-smoke.json'),JSON.stringify({page,worklet,isolated:true,hidden_window_preserved:true,real_microphone:false,cloud_requests:0},null,2));
    console.log('Desktop smoke passed: guided unchecked setup, real Chromium worklet, sandbox, window hide/reopen; microphone never requested.');app.quit();return;
   }catch(error){console.error(error);process.exitCode=1;app.quit();return;}
  }
  await sleep(100);
 }
 console.error('Desktop readiness timed out');process.exitCode=1;app.quit();
});

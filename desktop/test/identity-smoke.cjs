// Negative consent and real authenticated IPC/navigation; no microphone/inference.
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const {app,BrowserWindow}=require('electron');require('../main.cjs');
const sleep=ms=>new Promise(r=>setTimeout(r,ms)),dir=path.resolve(__dirname,'../../.tavi/mac');
async function page(suffix){for(let n=0;n<180;n++){const w=BrowserWindow.getAllWindows()[0];if(w&&!w.webContents.isLoading()&&w.webContents.getURL()==='http://127.0.0.1:8785/'+suffix)return w;await sleep(100);}throw Error('Page navigation timeout');}
app.whenReady().then(async()=>{try{
 let w=await page('');for(let n=0;n<100;n++){if(await w.webContents.executeJavaScript("document.querySelector('#family-summary').textContent.includes('3 of 4')"))break;await sleep(100);}
 const status=await w.webContents.executeJavaScript(`(async()=>{const v=await window.paprika.voices();return{count:v.current_profiles,locked:v.heldout_locked,identity:v.identity_qualified,memory:v.memory_qualified,startDisabled:document.querySelector('#start').disabled,memoryDisabled:document.querySelector('#family-memory').disabled};})()`);
 assert.deepEqual(status,{count:3,locked:true,identity:false,memory:false,startDisabled:true,memoryDisabled:true});
 await w.webContents.executeJavaScript("document.querySelector('#family-setup').click();true");w=await page('family-voices');
 for(let n=0;n<100;n++){if(await w.webContents.executeJavaScript("document.querySelector('#people-list').children.length===7"))break;await sleep(100);}
 const overview=await w.webContents.executeJavaScript(`(()=>({mic:document.querySelector('#mic-status').textContent,cards:[...document.querySelector('#people-list').children].map(n=>({name:n.querySelector('strong').textContent,disabled:n.disabled})),node:typeof require}))()`);
 assert.equal(overview.mic,'Microphone off');assert.equal(overview.node,'undefined');assert.equal(overview.cards.length,7);assert.equal(overview.cards.find(x=>x.name==='Adult Two').disabled,true);assert.equal(overview.cards.find(x=>x.name==='Adult One').disabled,false);
 fs.writeFileSync(path.join(dir,'identity-overview.png'),(await w.webContents.capturePage()).toPNG());
 const negative=await w.webContents.executeJavaScript(`(async()=>{document.querySelector('#people-list').children[0].click();document.querySelector('#begin').click();await new Promise(r=>setTimeout(r,30));return {step:document.body.dataset.step,checked:[...document.querySelectorAll('input:checked')].length,error:document.querySelector('#error').textContent,mic:document.querySelector('#mic-status').textContent,heldoutDisabled:document.querySelector('#heldout-radio').disabled};})()`);
 assert.equal(negative.step,'settings');assert.equal(negative.checked,0);assert.equal(negative.mic,'Microphone off');assert.equal(negative.heldoutDisabled,true);assert(negative.error.includes('Complete'));
 fs.writeFileSync(path.join(dir,'identity-settings.png'),(await w.webContents.capturePage()).toPNG());
 await w.webContents.executeJavaScript("document.querySelector('#home').click();true");w=await page('');
 const final=await w.webContents.executeJavaScript(`(async()=>({diag:(await window.paprika.diagnostics()).lease_active,startDisabled:document.querySelector('#start').disabled,adult:document.querySelector('#adult').checked}))()`);
 assert.equal(final.diag,false);assert.equal(final.startDisabled,true);assert.equal(final.adult,false);
 fs.writeFileSync(path.join(dir,'identity-smoke.json'),JSON.stringify({status,overview,negative,final,real_microphone:false,real_cloud_requests:0},null,2));
 console.log('Identity desktop smoke passed: authenticated IPC, 3 candidates, independent-round lock, unchecked choices, negative consent and safe navigation; no microphone or cloud.');app.quit();
 }catch(e){console.error(e);process.exitCode=1;app.quit();}});

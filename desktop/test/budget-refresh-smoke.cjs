// Real renderer/bridge check only. Never choose consent or request a microphone.
'use strict';
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const {app,BrowserWindow}=require('electron');
const expectedBudget=Number(process.env.PAPRIKA_EXPECTED_BUDGET_USD||27);
assert(Number.isFinite(expectedBudget)&&expectedBudget>0);
require('../main.cjs');
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
app.whenReady().then(async()=>{
 try{
  for(let n=0;n<150;n++){
   const win=BrowserWindow.getAllWindows()[0];
   if(!win||win.webContents.isLoading()){await sleep(100);continue;}
   const page=await win.webContents.executeJavaScript(`(()=>({
    budget:document.querySelector('#budget')?.textContent,
    page:document.body.dataset.page,mic:document.querySelector('#mic-state')?.textContent,
    adult:document.querySelector('#adult')?.checked,
    processing:document.querySelector('input[name=processing]:checked')?.value||null,
    startDisabled:document.querySelector('#start')?.disabled
   }))()`);
   if(!page.budget?.includes('of $'+expectedBudget.toFixed(2)+'.')){await sleep(100);continue;}
   assert.equal(page.page,'setup');assert.equal(page.mic,'Microphone off');
   assert.equal(page.adult,false);assert.equal(page.processing,null);assert.equal(page.startDisabled,true);
   const dir=path.resolve(__dirname,'../../.tavi/mac/budget-checks');fs.mkdirSync(dir,{recursive:true,mode:0o700});
   const filename=path.join(dir,new Date().toISOString().replace(/[-:.]/g,'')+'.json');
   fs.writeFileSync(filename,JSON.stringify({page,microphone_requested:false,cloud_requests:0},null,2),{mode:0o600,flag:'wx'});
   console.log(JSON.stringify({rendererBudgetCheck:'pass',report:filename,page}));app.quit();return;
  }
  throw Error('Budget/setup renderer check timed out');
 }catch(error){console.error(error.message);process.exitCode=1;app.quit();}
});

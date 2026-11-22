'use strict';
const {app,BrowserWindow,Menu,Tray,nativeImage,ipcMain,powerMonitor,systemPreferences}=require('electron');
const fs=require('node:fs'),path=require('node:path');
const {CoreOwner}=require('./owner.cjs');
const config=path.join(__dirname,'development.json');
const root=fs.existsSync(config)?JSON.parse(fs.readFileSync(config,'utf8')).projectRoot:path.resolve(__dirname,'..');
const owner=new CoreOwner(root);let win,tray,micIntent=false,quitting=false;
const origin='http://127.0.0.1:8785';
if(!app.requestSingleInstanceLock())app.quit();
function trusted(event){if(!win||event.sender!==win.webContents||event.senderFrame!==win.webContents.mainFrame||new URL(event.senderFrame.url).origin!==origin)throw Error('Untrusted app frame');}
function icon(){return nativeImage.createFromDataURL('data:image/svg+xml;base64,'+Buffer.from('<svg xmlns="http://www.w3.org/2000/svg" width="22" height="22"><circle cx="11" cy="11" r="9" fill="#bf5b38"/><circle cx="8" cy="9" r="1.5" fill="white"/><circle cx="14" cy="9" r="1.5" fill="white"/><path d="M7 14q4 3 8 0" fill="none" stroke="white" stroke-width="1.4"/></svg>').toString('base64'));}
function menu(){
 const status=micIntent?'Microphone on · Paprika listening':'Microphone off';
 tray?.setToolTip('Paprika · '+status);
 tray?.setContextMenu(Menu.buildFromTemplate([{label:status,enabled:false},{label:'Show Paprika',click:()=>{win.show();win.focus();}},
 {label:'Mute Paprika',click:()=>pause('menu')},{type:'separator'},
 {label:'Quit Paprika and stop core',click:()=>app.quit()}]));
}
async function pause(){micIntent=false;win?.webContents.send('paprika:pause');menu();try{await owner.pause();}catch{}}
function safeCommand(value){
 if(!value||!['start','stop','started','played','interrupt','end','online'].includes(value.command))throw Error('Unknown app command');
 if(value.stream!==null&&(typeof value.stream!=='string'||value.stream.length>128))throw Error('Invalid capture lease');
 const body=JSON.stringify(value.body);if(body.length>2048)throw Error('Command too large');return body;
}
ipcMain.handle('paprika:status',async e=>{trusted(e);const s=await owner.request('/api/desktop/status');delete s.instance;return s;});
ipcMain.handle('paprika:reconnect',async e=>{trusted(e);await pause();const s=await owner.ensure();delete s.instance;return s;});
ipcMain.handle('paprika:mic-intent',(e,v)=>{trusted(e);if(typeof v!=='boolean')throw Error('Invalid microphone choice');micIntent=v;menu();});
ipcMain.handle('paprika:microphone-status',e=>{trusted(e);return systemPreferences.getMediaAccessStatus('microphone');});
ipcMain.handle('paprika:call',async(e,v)=>{trusted(e);const body=safeCommand(v);return owner.request('/api/conversation/'+v.command,{method:'POST',headers:{'Content-Type':'application/json','X-Audio-Stream':v.stream||''},body,timeout:v.command==='stop'?2500:25000});});
ipcMain.handle('paprika:frame',async(e,v)=>{trusted(e);if(!(v.pcm instanceof Uint8Array)||v.pcm.byteLength!==1024||!Number.isSafeInteger(v.sequence)||v.sequence<0||typeof v.stream!=='string'||v.stream.length>128)throw Error('Invalid audio frame');return owner.request('/api/conversation/frame',{method:'POST',headers:{'Content-Type':'application/octet-stream','X-Audio-Stream':v.stream,'X-Audio-Sequence':String(v.sequence)},body:v.pcm,timeout:1000});});
ipcMain.handle('paprika:audio',async(e,v)=>{trusted(e);if(typeof v.id!=='string'||v.id.length>128||!Number.isInteger(v.sequence)||v.sequence<0||v.sequence>999||typeof v.stream!=='string'||v.stream.length>128)throw Error('Invalid playback receipt');return owner.request('/api/conversation/audio',{headers:{'X-Audio-Stream':v.stream,'X-Response-Id':v.id,'X-Audio-Sequence':String(v.sequence)},binary:true,timeout:4000});});
ipcMain.handle('paprika:diagnostics',e=>{trusted(e);return owner.request('/api/conversation/diagnostics');});
ipcMain.handle('paprika:voices',e=>{trusted(e);return owner.request('/api/voices/status');});
ipcMain.handle('paprika:open-voices',async e=>{trusted(e);await pause();await win.loadURL(origin+'/family-voices');});
ipcMain.handle('paprika:open-home',async e=>{trusted(e);await pause();await win.loadURL(origin+'/');});
ipcMain.handle('paprika:voice-action',async(e,v)=>{trusted(e);if(!['begin','review','fit','qualify','state','skip'].includes(v.action))throw Error('Unknown voice action');const body=JSON.stringify(v.body);if(body.length>8192||v.person!==null&&!['adultone','adulttwo','childtwo','childone','guest','short','overlap'].includes(v.person)||v.session!==null&&(typeof v.session!=='string'||v.session.length>100))throw Error('Invalid voice action');return owner.request('/api/voices/'+v.action,{method:v.action==='state'?'GET':'POST',headers:{'Content-Type':'application/json','X-Voice-Person':v.person||'','X-Voice-Session':v.session||''},...(v.action==='state'?{}:{body})});});
ipcMain.handle('paprika:voice-attempt',async(e,v)=>{trusted(e);if(!(v.pcm instanceof Uint8Array)||v.pcm.byteLength>160000||!v.pcm.byteLength)throw Error('One short local recording required');const m=v.meta;if(!m||!['adultone','adulttwo','childtwo','childone','guest','short','overlap'].includes(m.person)||typeof m.session!=='string'||m.session.length>100||typeof m.id!=='string'||m.id.length>64||typeof m.prompt!=='string'||m.prompt.length>64)throw Error('Invalid recording binding');const settings=JSON.stringify(m.settings||{});if(settings.length>512)throw Error('Microphone settings too large');return owner.request('/api/voices/attempt',{method:'POST',headers:{'Content-Type':'application/octet-stream','X-Voice-Person':m.person,'X-Voice-Session':m.session,'X-Voice-Attempt':m.id,'X-Voice-Prompt':m.prompt,'X-Voice-Settings':settings},body:v.pcm,timeout:30000});});
ipcMain.handle('paprika:voice-question',async(e,id)=>{trusted(e);if(typeof id!=='string'||!/^[a-z-]{1,40}$/.test(id))throw Error('Unknown question');return owner.request('/api/voices/question/'+id,{binary:true});});
ipcMain.handle('paprika:voice-sample',async(e,m)=>{trusted(e);if(!m||typeof m.session!=='string'||m.session.length>100||typeof m.id!=='string'||!/^[a-f0-9]{32}$/.test(m.id)||!['adultone','adulttwo','childtwo','childone','guest','short','overlap'].includes(m.person))throw Error('Invalid listening copy');return owner.request('/api/voices/audio',{headers:{'X-Voice-Person':m.person,'X-Voice-Session':m.session,'X-Voice-Sample':m.id},binary:true});});
ipcMain.handle('paprika:save-review',async(e,report)=>{trusted(e);const diagnostic=await owner.request('/api/conversation/diagnostics');if(diagnostic.lease_active)throw Error('Mute before saving.');const body=JSON.stringify(report);if(body.length>16384)throw Error('Feedback is too large.');return owner.request('/api/desktop/save-review',{method:'POST',headers:{'Content-Type':'application/json'},body});});
async function createWindow(){
 win=new BrowserWindow({width:760,height:850,minWidth:540,minHeight:650,title:'Paprika',backgroundColor:'#faf5ed',show:false,
  webPreferences:{preload:path.join(__dirname,'preload.cjs'),nodeIntegration:false,contextIsolation:true,sandbox:true,backgroundThrottling:false}});
 win.webContents.setWindowOpenHandler(()=>({action:'deny'}));
 win.webContents.on('will-navigate',(event,url)=>{if(![origin+'/',origin+'/family-voices'].includes(url))event.preventDefault();});
 const ses=win.webContents.session;
 ses.setPermissionCheckHandler((contents,permission,requestingOrigin,details)=>contents===win.webContents&&permission==='media'&&requestingOrigin===origin&&micIntent&&details.mediaType==='audio');
 ses.setPermissionRequestHandler((contents,permission,callback,details)=>callback(contents===win.webContents&&permission==='media'&&new URL(details.requestingUrl||origin).origin===origin&&micIntent&&details.mediaTypes?.length===1&&details.mediaTypes[0]==='audio'));
 win.webContents.on('render-process-gone',()=>pause());
 win.on('close',event=>{if(!quitting){event.preventDefault();win.hide();win.webContents.send('paprika:visibility',true);}});
 win.on('show',()=>win.webContents.send('paprika:visibility',false));
 await win.loadURL(origin+'/');win.show();
}
app.on('second-instance',()=>{win?.show();win?.focus();});
app.on('activate',()=>win?.show());
app.on('window-all-closed',()=>{});
app.on('before-quit',event=>{
 if(quitting)return;event.preventDefault();
 pause().then(()=>owner.stop()).then(()=>{quitting=true;app.quit();}).catch(error=>{win?.show();win?.webContents.send('paprika:pause');require('electron').dialog.showErrorBox('Paprika is finishing cleanup',error.message+' The microphone has been told to stop. Keep Paprika open, then choose Quit again.');});
});
app.whenReady().then(async()=>{
 app.setName('Paprika');tray=new Tray(icon());menu();
 Menu.setApplicationMenu(Menu.buildFromTemplate([{label:'Paprika',submenu:[{label:'Show Paprika',click:()=>win?.show()},{label:'Mute',click:pause},{type:'separator'},{role:'quit',label:'Quit Paprika and stop core'}]},{role:'editMenu'},{role:'windowMenu'}]));
 powerMonitor.on('suspend',pause);powerMonitor.on('lock-screen',pause);
 await owner.ensure();await createWindow();
}).catch(error=>{console.error(error.message);const {dialog}=require('electron');dialog.showErrorBox('Paprika could not start',error.message+' No microphone was opened. Reopen Paprika to retry.');quitting=true;app.quit();});

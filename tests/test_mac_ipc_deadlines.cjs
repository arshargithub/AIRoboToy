'use strict';
const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),http=require('node:http');
const {CoreOwner}=require('../desktop/owner.cjs');
async function fixture(){
 const handlers=new Map(),calls=[];let window;
 class Window{
  constructor(){window=this;this.webContents={mainFrame:{url:'http://127.0.0.1:8785/'},session:{setPermissionCheckHandler(){},setPermissionRequestHandler(){}},setWindowOpenHandler(){},on(){},send(){}};}
  on(){}async loadURL(){}show(){}focus(){}
 }
 class Owner{async ensure(){return{};}async request(route,options){calls.push({route,options});return{};}}
 class Tray{setToolTip(){}setContextMenu(){}}
 const electron={app:{requestSingleInstanceLock:()=>true,on(){},whenReady:()=>Promise.resolve(),setName(){}},BrowserWindow:Window,Tray,
  Menu:{buildFromTemplate:x=>x,setApplicationMenu(){}},nativeImage:{createFromDataURL:x=>x},ipcMain:{handle:(name,fn)=>handlers.set(name,fn)},powerMonitor:{on(){}},systemPreferences:{}};
 vm.runInNewContext(fs.readFileSync('desktop/main.cjs','utf8'),{require:n=>n==='electron'?electron:n==='./owner.cjs'?{CoreOwner:Owner}:require(n),__dirname:path.resolve('desktop'),Buffer,URL,console});
 await new Promise(r=>setImmediate(r));const event={sender:window.webContents,senderFrame:window.webContents.mainFrame};
 return{handlers,calls,event};
}
test('trusted stop IPC has a short deadline while ordinary setup retains its existing bound',async()=>{
 const t=await fixture();for(const command of ['stop','start'])await t.handlers.get('paprika:call')(t.event,{command,stream:'fixture',body:{}});
 assert.equal(t.calls[0].route,'/api/conversation/stop');assert(t.calls[0].options.timeout<=3000);assert(t.calls[0].options.timeout>0);
 assert.equal(t.calls[1].options.timeout,25000);
 await assert.rejects(t.handlers.get('paprika:call')({...t.event,senderFrame:{}},{command:'stop',stream:'fixture',body:{}}),/Untrusted/);
});
test('the actual owner transport abandons a stalled stop within the IPC deadline',async()=>{
 const t=await fixture();await t.handlers.get('paprika:call')(t.event,{command:'stop',stream:'fixture',body:{}});const timeout=t.calls[0].options.timeout;
 // This check is executed only after the deadline patch is applied.
 assert(timeout<=3000);
 let seen=false;const server=http.createServer(()=>{seen=true;});await new Promise(r=>server.listen(0,'127.0.0.1',r));
 const owner=new CoreOwner('/private/tmp/unused-deadline-fixture');owner.record={port:server.address().port,token:'a'.repeat(64)};const start=performance.now();
 try{await assert.rejects(owner.request('/api/conversation/stop',{method:'POST',body:'{}',timeout}));assert(seen);assert(performance.now()-start<5000);}
 finally{server.closeAllConnections();await new Promise(r=>server.close(r));}
});

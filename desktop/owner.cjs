'use strict';
const fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto'),{spawn}=require('node:child_process');
const sleep=ms=>new Promise(resolve=>setTimeout(resolve,ms));
class CoreOwner{
 constructor(root){this.root=root;this.directory=path.join(root,'.tavi/mac');this.record=null;this.starting=null;}
 read(){
  const file=path.join(this.directory,'core.json');
  if(!fs.existsSync(file))return null;
  const stat=fs.lstatSync(file);
  if(!stat.isFile()||stat.isSymbolicLink()||(stat.mode&0o077)||stat.size>2048)throw Error('Local core ownership file needs review. Existing files are kept.');
  const r=JSON.parse(fs.readFileSync(file,'utf8'));
  if(!Number.isInteger(r.pid)||r.pid<=1||r.port!==8785||r.protocol!==1||!/^[a-f0-9]{64}$/.test(r.token)||!/^[a-f0-9]{32}$/.test(r.instance))throw Error('Local core ownership is invalid.');
  return r;
 }
 async request(route,{method='GET',body,headers={},binary=false,timeout=25000}={}){
  if(!this.record)throw Error('Core is not connected. Choose Reconnect.');
  const response=await fetch(`http://127.0.0.1:${this.record.port}${route}`,{method,headers:{...headers,Authorization:'Bearer '+this.record.token},body,signal:AbortSignal.timeout(timeout)});
  if(!response.ok){let message='Local service unavailable';try{message=(await response.json()).error||message;}catch{}throw Error(message);}
  return binary?new Uint8Array(await response.arrayBuffer()):response.json();
 }
 async verify(record){this.record=record;const s=await this.request('/api/desktop/status',{timeout:6000});if(s.service!=='paprika-core'||s.protocol!==1||s.instance!==record.instance)throw Error('Another service owns this address.');return s;}
 async ensure(){if(this.starting)return this.starting;this.starting=this._ensure().finally(()=>this.starting=null);return this.starting;}
 async _ensure(){
  const existing=this.read();
  if(existing){try{return await this.verify(existing);}catch(error){
   try{process.kill(existing.pid,0);throw Error('The saved core is still running but unavailable. It was left intact; try Reconnect.');}
   catch(check){if(check.code!=='ESRCH')throw check;}
  }}
  fs.mkdirSync(this.directory,{recursive:true,mode:0o700});fs.chmodSync(this.directory,0o700);
  const log=fs.openSync(path.join(this.directory,'core.log'),fs.constants.O_CREAT|fs.constants.O_APPEND|fs.constants.O_WRONLY|fs.constants.O_NOFOLLOW,0o600);
  const token=crypto.randomBytes(32).toString('hex');
  const child=spawn(path.join(this.root,'.venv-tavi/bin/python'),['-m','tavi.mac_service'],{cwd:this.root,detached:true,stdio:['ignore',log,log],env:{...process.env,PAPRIKA_CORE_TOKEN:token,HF_HUB_OFFLINE:'1',HF_HUB_DISABLE_TELEMETRY:'1'}});
  let spawnError=null;child.on('error',()=>{spawnError=Error('Python could not start. Keep the project folder and local environment available.');});child.unref();fs.closeSync(log);
  for(let n=0;n<80;n++){
   if(spawnError)throw spawnError;
   const record=this.read();
   if(record&&record.token===token){try{return await this.verify(record);}catch{}}
   if(child.exitCode!==null)throw Error('Core could not start. No microphone was opened.');
   await sleep(125);
  }
  throw Error('Core startup timed out. No microphone was opened; choose Reconnect.');
 }
 async pause(){if(this.record)await this.request('/api/desktop/pause',{method:'POST',timeout:6000});}
 async stop(){
  const record=this.record||this.read();if(!record)return;
  try{await this.verify(record);}catch(error){
   // A crashed/already-stopped owned core needs no shutdown request. Never
   // signal an unverifiable live PID or remove another instance's record.
   try{process.kill(record.pid,0);}catch(check){
    if(check.code==='ESRCH'){
     const current=this.read();
     if(current&&current.instance===record.instance&&current.token===record.token)fs.unlinkSync(path.join(this.directory,'core.json'));
     this.record=null;return;
    }
    throw check;
   }
   throw error;
  }
  await this.pause();
  process.kill(record.pid,'SIGTERM');
  for(let n=0;n<60;n++){if(!fs.existsSync(path.join(this.directory,'core.json'))){this.record=null;return;}await sleep(100);}
  throw Error('Core is still finishing cleanup. It was not force-killed.');
 }
}
module.exports={CoreOwner};

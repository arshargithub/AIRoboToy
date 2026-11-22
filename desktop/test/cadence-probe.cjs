'use strict';
// Isolated Chromium, real Web Audio and localhost fetch. Controlled ACK server;
// no live core, microphone, actual sound, cloud or household identities.
const fs=require('node:fs'),path=require('node:path'),http=require('node:http'),assert=require('node:assert/strict');
const {app,BrowserWindow,session}=require('electron');
const folder=process.env.PAPRIKA_CADENCE_FOLDER;if(!folder)throw Error('Private run folder required');
app.setPath('userData',path.join(folder,'chromium'));app.setPath('sessionData',path.join(folder,'chromium-session'));
app.commandLine.appendSwitch('autoplay-policy','no-user-gesture-required');
const data=JSON.parse(fs.readFileSync(path.join(folder,'renderer-input.json'))),root=path.resolve(__dirname,'../..');
let permissionRequests=0,server,win;
app.whenReady().then(async()=>{
 try{
  const partition=session.fromPartition('cadence-'+Date.now());partition.setPermissionRequestHandler((webContents,permission,callback)=>{permissionRequests++;callback(false);});
  partition.setPermissionCheckHandler(()=>false);
  server=http.createServer((req,res)=>{
   const url=new URL(req.url,'http://127.0.0.1');
   if(url.pathname==='/'){res.writeHead(200,{'Content-Type':'text/html'});res.end('<!doctype html><title>Muted Paprika timing diagnostic</title>');return;}
   if(url.pathname==='/audio'){
    const n=Number(url.searchParams.get('n')),delay=Number(url.searchParams.get('delay'));
    if(!Number.isInteger(n)||!data.clips[n]||![0,120].includes(delay)){res.writeHead(400);res.end();return;}
    setTimeout(()=>{res.writeHead(200,{'Content-Type':'audio/wav','Cache-Control':'no-store'});res.end(fs.readFileSync(data.clips[n]));},delay);return;
   }
   if(url.pathname==='/ack'){
    const delay=Number(url.searchParams.get('delay'));
    if(![0,120].includes(delay)){res.writeHead(400);res.end();return;}
    setTimeout(()=>{res.writeHead(200,{'Content-Type':'application/json','Cache-Control':'no-store'});res.end('{}');},delay);return;
   }
   res.writeHead(404);res.end();
  });await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
  win=new BrowserWindow({show:false,webPreferences:{session:partition,nodeIntegration:false,contextIsolation:true,sandbox:true}});
  await win.loadURL('http://127.0.0.1:'+server.address().port+'/');win.webContents.setAudioMuted(true);
  for(const name of ['interruption.js','chunk-audio-prefetch.js','mac-audio-endpoint.js'])await win.webContents.executeJavaScript(fs.readFileSync(path.join(root,'tavi/web',name),'utf8'));
  const result=await win.webContents.executeJavaScript(`(async()=>{
   const conditions=${JSON.stringify(data.conditions)},durations=${JSON.stringify(data.durations_ms)},runs=[];
   for(const condition of conditions){
    const report={condition,starts:[],fetches:[],decodes:[],acks:[],errors:[]};
    let index=0,revision=0;const context=new AudioContext({sampleRate:16000});await context.resume();
    const sourceFactory=context.createBufferSource.bind(context);
    context.createBufferSource=()=>{const source=sourceFactory(),start=source.start.bind(source);source.start=(...args)=>{report.starts.push({sequence:index,context_seconds:context.currentTime,wall_ms:performance.now(),duration_seconds:source.buffer.duration});return start(...args);};return source;};
    const decode=context.decodeAudioData.bind(context);context.decodeAudioData=async bytes=>{const at=performance.now(),buffer=await decode(bytes);report.decodes.push({elapsed_ms:performance.now()-at});return buffer;};
    const state=()=>({lease_active:true,revision:++revision,token:{response_id:'cadence'},pending_input:false,
      audio:index<durations.length?{id:'cadence',sequence:index,duration_ms:durations[index]}:null,
      prefetch_audio:condition.prefetch&&index+1<durations.length?{id:'cadence',sequence:index+1,duration_ms:durations[index+1]}:null});
    const bridge={micIntent:async()=>{throw Error('Microphone intent forbidden');},audio:async(id,n)=>{
     const at=performance.now(),response=await fetch('/audio?n='+n+'&delay='+condition.fetch_delay_ms),bytes=await response.arrayBuffer();if(!response.ok)throw Error('Local audio fetch failed');
     report.fetches.push({sequence:n,elapsed_ms:performance.now()-at});return new Uint8Array(bytes);
    },call:async(command,body)=>{
     if(command==='played'||command==='started'){
      if(body.sequence!==index)throw Error('Out of order receipt');
      if(command==='played'){
       const at=performance.now(),context_seconds=context.currentTime;
       const response=await fetch('/ack?delay='+condition.ack_delay_ms,{method:'POST'});if(!response.ok)throw Error('Local receipt failed');
       report.acks.push({sequence:index,called_context_seconds:context_seconds,elapsed_ms:performance.now()-at});index++;
      }
      return{conversation:state()};
     }
     if(command==='stop')return{};
     throw Error('Unexpected controlled command '+command);
    }};
    const endpoint=new MacAudioEndpoint(bridge,()=>{},error=>report.errors.push(error.message));
    endpoint.active=true;endpoint.stream='synthetic-no-microphone';endpoint.context=context;endpoint.volume=0;
    endpoint.reconcile(state());
    const deadline=performance.now()+30000;
    while(index<durations.length&&performance.now()<deadline&&!report.errors.length)await new Promise(resolve=>setTimeout(resolve,10));
    if(index!==durations.length)throw Error('Muted renderer playback did not finish');
    report.gaps_ms=report.starts.slice(1).map((start,i)=>1000*(start.context_seconds-report.starts[i].context_seconds-report.starts[i].duration_seconds));
    report.base_latency_ms=context.baseLatency*1000;await endpoint.stop();report.context_closed=context.state==='closed';runs.push(report);
   }
   return{actual_chromium:true,actual_web_audio:true,actual_localhost_fetch:true,controlled_ack_server:true,
    actual_core_ipc:false,real_microphone:false,physical_audio:false,muted:true,runs};
  })()`);
  assert.equal(permissionRequests,0);assert.equal(result.runs.length,3);
  for(const r of result.runs){assert.equal(r.errors.length,0);assert(r.context_closed);assert.equal(r.starts.length,data.clips.length);assert.equal(r.acks.length,data.clips.length);}
  result.permission_requests=permissionRequests;fs.writeFileSync(path.join(folder,'renderer-observations.json'),JSON.stringify(result,null,2)+'\n',{mode:0o600,flag:'wx'});
  console.log(JSON.stringify({completed:true,gaps:result.runs.map(r=>({condition:r.condition.id,gaps_ms:r.gaps_ms}))}));
 }catch(error){console.error(error.stack);process.exitCode=1;}
 finally{if(win&&!win.isDestroyed())win.destroy();if(server)await new Promise(resolve=>server.close(resolve));app.quit();}
});

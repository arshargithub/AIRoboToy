// Synthetic output goes only to a MediaStreamDestination, never physical speakers.
const {app,BrowserWindow}=require('electron'),fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
require('../main.cjs');const sleep=ms=>new Promise(r=>setTimeout(r,ms));
app.whenReady().then(async()=>{
 try{
  let win;
  for(let n=0;n<150;n++){win=BrowserWindow.getAllWindows()[0];if(win&&!win.webContents.isLoading()&&await win.webContents.executeJavaScript(`typeof MacAudioEndpoint==='function'&&!!document.querySelector('#start')`))break;await sleep(100);}
  const result=await win.webContents.executeJavaScript(`(async()=>{
   const real=new AudioContext({sampleRate:16000});await real.resume();const sink=real.createMediaStreamDestination(),calls=[];
   const fixture=new MacAudioEndpoint({call:async command=>{calls.push(command);return{};},micIntent:async()=>{}},()=>{},e=>{throw e;});
   fixture.context={get currentTime(){return real.currentTime;},sampleRate:16000,destination:sink,createBufferSource:()=>real.createBufferSource(),createGain:()=>real.createGain(),createAnalyser:()=>real.createAnalyser(),close:()=>real.close()};
   fixture.active=true;fixture.stream='synthetic';fixture.latest={token:{response_id:'synthetic-output'}};
   const buffer=real.createBuffer(1,16000,16000),data=buffer.getChannelData(0);for(let i=0;i<data.length;i++)data[i]=.25*Math.sin(2*Math.PI*220*i/16000);
   fixture.load=async()=>buffer;await fixture.play({id:'synthetic-output',sequence:0});await new Promise(r=>setTimeout(r,180));
   const level=fixture.speechLevel();await fixture.stop();sink.stream.getTracks().forEach(t=>t.stop());
   return {level,afterMute:fixture.speechLevel(),started:calls.includes('started'),interruptedMarkedPlayed:calls.includes('played'),realMicrophone:false,physicalSpeakers:false};
  })()`,true);
  assert(result.level>0&&result.level<=1);assert.equal(result.afterMute,0);assert.equal(result.started,true);assert.equal(result.interruptedMarkedPlayed,false);
  fs.writeFileSync(path.resolve(__dirname,'../../.tavi/mac/output-meter.json'),JSON.stringify(result,null,2));console.log('Synthetic output meter passed; no physical microphone, speakers or paid inference.');app.quit();
 }catch(error){console.error(error);process.exitCode=1;app.quit();}
});

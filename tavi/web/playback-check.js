'use strict';
document.getElementById('run').onclick=async()=>{
 const button=document.getElementById('run'),status=document.getElementById('status'),output=document.getElementById('result');button.disabled=true;let ctx,players=[];
 try{
  ctx=new AudioContext({sampleRate:16000});await ctx.resume();
  const report={kind:'paprika_silent_browser_playback',microphone:false,cloud:false,source:'synthetic zeros; total frame counts match the four prior replies, partitioning is synthetic',sample_rate:ctx.sampleRate,previous:[],repaired:[],previous_end_clock_differences_ms:[]};
  const old=new PreviousNativePlayback(ctx,{volume:0,onComplete:id=>report.previous.push(id)}),fixed=new NativePlayback(ctx,{volume:0,onComplete:id=>report.repaired.push(id)});players=[old,fixed];
  const frames=[357600,294000,339600,342000];
  for(let i=0;i<frames.length;i++){
   for(let offset=0;offset<frames[i];offset+=9600){const silence=new Int16Array(Math.min(9600,frames[i]-offset));old.add('reply'+i,silence);fixed.add('reply'+i,silence);}
   old.done('reply'+i);fixed.done('reply'+i);
   const r=old.rows.get('reply'+i),chunk=r.chunks.at(-1),handler=chunk.source.onended;
   chunk.source.onended=()=>{report.previous_end_clock_differences_ms.push({id:'reply'+i,clock_minus_end_ms:(ctx.currentTime-chunk.end)*1000});handler();};
  }
  status.textContent='Running silently · microphone off';
  const end=Math.max(...Array.from(fixed.rows.values()).map(r=>r.next));
  await new Promise((resolve,reject)=>{const began=performance.now(),timer=setInterval(()=>{if(ctx.currentTime>end+.1){clearInterval(timer);resolve();}else if(performance.now()-began>18000){clearInterval(timer);reject(Error('Audio clock did not finish'));}},50);});
  report.repaired_passed=report.repaired.length===frames.length;report.previous_race_observed=report.previous.length<frames.length;
  output.textContent=JSON.stringify(report,null,2);status.textContent=report.repaired_passed?'Repaired playback completed all four replies · microphone off':'Check failed · microphone off';
 }catch(error){status.textContent='Check failed · microphone off';output.textContent=JSON.stringify({error:error.message});}
 finally{players.forEach(p=>p.stopAll());if(ctx)await ctx.close();}
};

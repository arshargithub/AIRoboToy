'use strict';
// One private next-chunk buffer. Taking/fetching never acknowledges playback.
class ChunkAudioPrefetch{
 constructor(){this.entry=null;this.generation=0;}
 clear(){this.generation++;this.entry?.controller.abort();this.entry=null;}
 key(audio,scope){return `${scope}:${audio.id}:${audio.sequence}`;}
 offer(audio,scope,load){
  const key=this.key(audio,scope);
  if(this.entry?.key===key)return;
  this.clear();const generation=this.generation,controller=new AbortController();
  const timer=setTimeout(()=>controller.abort(),3000);
  const promise=Promise.resolve().then(()=>load(audio,controller.signal))
   .then(buffer=>this.generation===generation&&!controller.signal.aborted?buffer:null)
   .catch(()=>null).finally(()=>clearTimeout(timer));
  this.entry={key,controller,promise};
 }
 async take(audio,scope){
  if(this.entry?.key!==this.key(audio,scope))return null;
  const entry=this.entry;this.entry=null;
  return entry.promise;
 }
}
if(typeof module!=='undefined')module.exports={ChunkAudioPrefetch};

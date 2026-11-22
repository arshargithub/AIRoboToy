// Bounded browser-only PCM collection. No network or persistent storage.
class SampleCollector {
 constructor(maxClips=20,maxFrames=126){this.maxClips=maxClips;this.maxFrames=maxFrames;this.clips=[];this.current=null;this.lastSequence=-1;}
 begin(metadata){if(this.current||this.clips.length>=this.maxClips)throw Error('Clip limit or active recording');this.current={...metadata,frames:[]};this.lastSequence=-1;}
 append(packet){if(!this.current)return;if(packet.sampleRate!==16000||packet.pcm.byteLength!==1024)throw Error('Unexpected microphone format');if(this.lastSequence!==-1&&packet.sequence!==this.lastSequence+1)throw Error('Audio gap; restart this collection');if(this.current.frames.length>=this.maxFrames)throw Error('Clip size limit');this.lastSequence=packet.sequence;this.current.frames.push(new Uint8Array(packet.pcm).slice());}
 finish(){if(!this.current)return;const c=this.current;this.current=null;if(!c.frames.length)throw Error('No microphone frames received');this.clips.push(c);return c;}
 discard(){this.current=null;}
}
if(typeof module!=='undefined')module.exports={SampleCollector};

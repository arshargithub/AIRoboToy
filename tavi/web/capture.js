// Bounded 32 ms mono PCM16 packets. No recording or network in this worklet.
class Capture extends AudioWorkletProcessor {
  constructor(){super();this.buffer=new Int16Array(512);this.used=0;this.sequence=0;}
  process(inputs){const input=inputs[0]?.[0];if(!input)return true;
    for(let i=0;i<input.length;i++){const x=Math.max(-1,Math.min(1,input[i]));this.buffer[this.used++]=Math.round(x*(x<0?32768:32767));
      if(this.used===512){this.port.postMessage({pcm:this.buffer.buffer,sequence:this.sequence++,sampleRate,endFrame:currentFrame+i+1},[this.buffer.buffer]);this.buffer=new Int16Array(512);this.used=0;}}
    return true;
  }
}
registerProcessor('tavi-capture',Capture);

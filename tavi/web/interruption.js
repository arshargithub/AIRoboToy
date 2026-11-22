// Pure endpoint gate. No blanking period: speech may interrupt from the first
// post-playback frame, but stale packets and brief probability spikes cannot.
class SpeechInterruptionGate {
  constructor(threshold=.9, required=3){this.threshold=threshold;this.required=required;this.reset();}
  reset(start=Infinity){this.start=start;this.high=0;this.last=-1;this.reason='waiting';}
  accept(packet,result,sampleRate,now){
    const end=packet.endFrame/sampleRate,begin=end-512/sampleRate;
    if(begin<this.start || now-end>.2 || packet.sequence!==this.last+1 && this.last!==-1){this.reason=begin<this.start?'pre_playback':now-end>.2?'stale':'sequence_gap';this.high=0;this.last=packet.sequence;return false;}
    this.last=packet.sequence;
    this.high=result.probability>=this.threshold?this.high+1:0;
    this.reason=this.high>=this.required?'confirmed':this.high?'confirming':'below_threshold';
    return this.high>=this.required;
  }
}
if(typeof module!=='undefined')module.exports={SpeechInterruptionGate};

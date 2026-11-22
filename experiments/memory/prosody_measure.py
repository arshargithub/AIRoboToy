"""Read-only PCM diagnostics. Low energy is not proof of silence or a word boundary."""
import array
from io import BytesIO
import math
import sys
import wave


def pcm(raw):
    if not isinstance(raw, bytes) or len(raw)>3_000_000:
        raise ValueError('Bounded saved PCM WAV required')
    with wave.open(BytesIO(raw)) as audio:
        rate=audio.getframerate();frames=audio.getnframes()
        if (audio.getnchannels()!=1 or audio.getsampwidth()!=2 or audio.getcomptype()!='NONE'
                or rate not in (16000,24000) or not 0<frames<=rate*30):
            raise ValueError('Expected bounded mono16bit saved speech')
        data=audio.readframes(frames)
        if len(data)!=frames*2:raise ValueError('Truncated saved speech')
    values=array.array('h');values.frombytes(data)
    if sys.byteorder!='little':values.byteswap()
    return rate,values


def dbfs(rms):
    return 20*math.log10(rms/32768) if rms else None


def analyze(raw,thresholds=(-50,-45,-40),window_ms=5):
    rate,values=pcm(raw);step=round(rate*window_ms/1000)
    if window_ms!=5 or not step:raise ValueError('Frozen5ms window required')
    result={'frames':len(values),'sample_rate':rate,'duration_ms':len(values)*1000/rate,
        'peak':max(abs(x) for x in values)/32768,
        'rms_dbfs':dbfs(math.sqrt(math.fsum(x*x for x in values)/len(values))),
        'first_sample':values[0],'last_sample':values[-1],'thresholds':{}}
    windows=[(i,min(i+step,len(values)),math.sqrt(math.fsum(x*x for x in values[i:i+step])/len(values[i:i+step])))
             for i in range(0,len(values),step)]
    for threshold in thresholds:
        if type(threshold) not in (int,float) or not math.isfinite(threshold) or not -90<=threshold<=-10:
            raise ValueError('Bounded fixed energy threshold required')
        cutoff=32768*10**(threshold/20);active=[w for w in windows if w[2]>=cutoff]
        start=active[0][0] if active else None;end=active[-1][1] if active else None
        count=sum(b-a for a,b,_ in active)
        energy=math.fsum(rms*rms*(b-a) for a,b,rms in active)
        result['thresholds'][str(threshold)]={'all_low_energy':not active,
            'leading_low_energy_ms':start*1000/rate if active else None,
            'trailing_low_energy_ms':(len(values)-end)*1000/rate if active else None,
            'active_window_rms_dbfs':dbfs(math.sqrt(energy/count)) if count else None,
            'active_window_ms':count*1000/rate}
    return result


def join(left,right):
    if left['sample_rate']!=right['sample_rate']:raise ValueError('Different sample rates')
    results={}
    for threshold,a in left['thresholds'].items():
        b=right['thresholds'][threshold]
        valid=not(a['all_low_energy'] or b['all_low_energy'])
        results[threshold]={'low_energy_gap_ms':a['trailing_low_energy_ms']+b['leading_low_energy_ms'] if valid else None,
            'active_window_level_change_db':b['active_window_rms_dbfs']-a['active_window_rms_dbfs'] if valid else None}
    return {'thresholds':results,'sample_step_full_scale':abs(right['first_sample']-left['last_sample'])/32768}


def compare(raw_a,raw_b):
    rate,a=pcm(raw_a);rate_b,b=pcm(raw_b)
    aligned=rate==rate_b and len(a)==len(b)
    result={'same_rate_and_length':aligned,'pcm_identical':aligned and a==b,
        'duration_difference_ms':len(b)*1000/rate_b-len(a)*1000/rate}
    if not aligned:return result
    aa=math.fsum(x*x for x in a);bb=math.fsum(x*x for x in b);ab=math.fsum(x*y for x,y in zip(a,b))
    scale=ab/aa if aa else None
    result.update(cosine=ab/math.sqrt(aa*bb) if aa and bb else None,
        least_squares_gain_b_over_a=scale,
        normalized_residual_after_gain=math.sqrt(math.fsum((y-scale*x)**2 for x,y in zip(a,b))/bb) if scale is not None and bb else None)
    return result

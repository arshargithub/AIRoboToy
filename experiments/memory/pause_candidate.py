"""Offline audition material only. Remove a bounded amount of exact-zero join padding.

Never alter nonzero samples, first/last reply edges, voice gain or live defaults.
Kept zero margins are an engineering candidate, not a naturalness target.
"""
import array
from io import BytesIO
import sys
import wave
from experiments.memory.prosody_measure import pcm


def pack(rate,values):
    data=array.array('h',values)
    if sys.byteorder!='little':data.byteswap()
    out=BytesIO()
    with wave.open(out,'wb') as f:
        f.setnchannels(1);f.setsampwidth(2);f.setframerate(rate);f.writeframes(data.tobytes())
    return out.getvalue()


def prepare(raw_clips):
    if not isinstance(raw_clips,list) or not 2<=len(raw_clips)<=4:raise ValueError('Bounded multi-clip audition required')
    decoded=[pcm(raw) for raw in raw_clips];rate=decoded[0][0]
    if any(r!=rate for r,_ in decoded):raise ValueError('Sample rates must match')
    clips=[v for _,v in decoded]
    if sum(len(v) for v in clips)>rate*30:raise ValueError('Audition exceeds30seconds')
    starts=[0]*len(clips);ends=[len(v) for v in clips];joins=[]
    margin=round(rate*.1);cap=round(rate*.125)
    for index,(left,right) in enumerate(zip(clips,clips[1:])):
        trailing=next((i for i,v in enumerate(reversed(left)) if v),len(left))
        leading=next((i for i,v in enumerate(right) if v),len(right))
        # Entirely silent material supplies no safe speech boundary; leave it alone.
        valid=trailing<len(left) and leading<len(right)
        cut_left=min(cap,max(0,trailing-margin)) if valid else 0
        cut_right=min(cap,max(0,leading-margin)) if valid else 0
        ends[index]-=cut_left;starts[index+1]+=cut_right
        joins.append({'index':index,'left_trim_frames':cut_left,'right_trim_frames':cut_right,
            'removed_ms':(cut_left+cut_right)*1000/rate,
            'original_exact_zero_ms':(trailing+leading)*1000/rate if valid else None,
            'remaining_exact_zero_ms':(trailing+leading-cut_left-cut_right)*1000/rate if valid else None})
    before=array.array('h');after=array.array('h');integrity=[]
    for v,a,b in zip(clips,starts,ends):
        before.extend(v);after.extend(v[a:b])
        integrity.append({'start':a,'end':b,'original_frames':len(v),
            'removed_only_zeros':not any(v[:a]) and not any(v[b:])})
    # Validation works on the encoded output too, rather than assuming pack().
    control=pack(rate,before);candidate=pack(rate,after)
    _,roundtrip=pcm(candidate)
    return control,candidate,{'joins':joins,'slices':integrity,
        'only_zero_samples_removed':all(i['removed_only_zeros'] for i in integrity),
        'encoded_samples_exact':roundtrip==after,'outer_edges_untouched':starts[0]==0 and ends[-1]==len(clips[-1]),
        'nonzero_sequence_identical':[v for v in before if v]==[v for v in roundtrip if v],
        'sample_rate':rate,'original_frames':len(before),'candidate_frames':len(after)}

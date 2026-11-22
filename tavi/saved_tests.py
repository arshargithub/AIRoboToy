"""Explicit local-only test saves. Never called by capture or ordinary chat."""
import base64
import hashlib
import json
import os
from pathlib import Path
from uuid import uuid4

ROOT=Path('.tavi/private-conversation-results')
MAX_BYTES=16_000_000


def save_test(raw,root=ROOT):
    if not isinstance(raw,bytes) or not 0<len(raw)<=MAX_BYTES:raise ValueError('Invalid test result size')
    report=json.loads(raw)
    if (not isinstance(report,dict) or report.get('schema_version')!=1
            or report.get('kind')!='paprika_controlled_conversation_diagnostics'
            or report.get('local_save_consent')!={'destination':'project_private_local','explicit_save':True}):
        raise ValueError('Choose Save results on this Mac explicitly')
    runs=report.get('runs')
    if not isinstance(runs,list) or len(runs)!=1 or not isinstance(runs[0],dict) or not runs[0].get('ended_at'):
        raise ValueError('Finish or stop the guided test before saving')
    audio=runs[0].get('local_audio')
    if bool(audio)!=report.get('audio_included'):raise ValueError('Audio inclusion does not match the result')
    if audio:
        if runs[0].get('local_audio_recording',{}).get('enabled') is not True:
            raise ValueError('Microphone audio was not explicitly enabled')
        if (audio.get('sample_rate'),audio.get('format'),audio.get('closed'))!=(16000,'mono_pcm16le_base64',True):
            raise ValueError('Stop recording before saving audio')
        samples=audio.get('sample_count')
        if type(samples) is not int or not 0<samples<=5625*512 or samples%512:raise ValueError('Invalid recorded sample count')
        if len(base64.b64decode(audio.get('pcm_base64',''),validate=True))!=samples*2:raise ValueError('Recorded audio size mismatch')
    if report.get('transcripts_included') is not True and ('accepted_text' in report or audio):
        raise ValueError('Timings-only saves must exclude text and microphone audio')
    root.mkdir(parents=True,exist_ok=True,mode=0o700)
    filename='conversation-'+hashlib.sha256(raw).hexdigest()+'.json';target=root/filename
    if not target.exists():
        if sum(p.stat().st_size for p in root.glob('*.json'))+len(raw)>256_000_000:
            raise ValueError('Local test folder is full; download a copy instead')
        temporary=root/('.pending-'+uuid4().hex)
        try:
            fd=os.open(temporary,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
            with os.fdopen(fd,'wb') as out:out.write(raw);out.flush();os.fsync(out.fileno())
            os.replace(temporary,target)
        finally:
            if temporary.exists():temporary.unlink()
    return {'saved':True,'filename':filename,'audio_included':bool(audio)}

"""Owned offline embedding subprocess; no cloud clients or filesystem audio."""
import base64,json,sys
from tavi.speaker_profile import SpeakerEncoder
if __name__=='__main__':
 model=SpeakerEncoder();model.prepare();print(json.dumps({'ready':True,'protocol':1}),flush=True)
 for line in sys.stdin:
  try:
   if len(line)>400000:raise ValueError('Recording is too large. Record one phrase at a time.')
   request=json.loads(line);result=model.encode(base64.b64decode(request['pcm'],validate=True));reply={'id':request['id'],'ok':True,'result':result}
  except ValueError as e:reply={'id':request.get('id') if 'request' in locals() else None,'ok':False,'error':str(e)}
  except Exception:reply={'id':request.get('id') if 'request' in locals() else None,'ok':False,'error':'Local voice processing could not finish. Keep this recording and try again.'}
  print(json.dumps(reply),flush=True)
  # Do not retain a complete last input in the idle worker loop.
  if 'request' in locals():del request
  line='';model.vad.reset()

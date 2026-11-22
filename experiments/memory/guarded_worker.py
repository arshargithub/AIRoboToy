"""Candidate native-ingestion boundary; rich episode text is preserved verbatim.

Trusted identity/audience metadata is required before native extraction. This
does not recognize voices or prove the semantic truth of a known person's text.
Old experiment stores are never silently cleaned or promoted.
"""
import asyncio
from datetime import datetime
import json
import sys
from experiments.memory.worker import Worker


def source_rejection(source, people):
    if not isinstance(source,dict):return 'invalid_source'
    if (not isinstance(source.get('speaker_id'), str) or source['speaker_id']=='unknown'
            or source['speaker_id'] not in people):
        return 'unknown_speaker'
    audience=source.get('audience_ids')
    if (not isinstance(audience,list) or not audience
            or any(not isinstance(x,str) or x not in people for x in audience)
            or len(audience)!=len(set(audience))):return 'unknown_or_invalid_audience'
    if source['speaker_id'] not in audience:return 'speaker_absent_from_audience'
    if any(not isinstance(source.get(k),str) or not source[k].strip() for k in ['id','session','at','text']):
        return 'invalid_source'
    try:
        if datetime.fromisoformat(source['at'].replace('Z','+00:00')).tzinfo is None:return 'unanchored_timestamp'
    except ValueError:return 'invalid_timestamp'
    return None


class GuardedWorker(Worker):
    def __init__(self,engine,directory):
        super().__init__(engine,directory)
        self.db.execute('CREATE TABLE IF NOT EXISTS native_rejections(id TEXT PRIMARY KEY,body TEXT NOT NULL,reason TEXT NOT NULL)')

    def reject(self,source,reason):
        encoded=json.dumps(source,sort_keys=True)
        sid=source.get('id') if isinstance(source, dict) else None
        if not isinstance(sid,str) or not sid:raise ValueError('Quarantine needs a canonical source ID')
        prior=self.db.execute('SELECT body FROM native_rejections WHERE id=?',(sid,)).fetchone()
        if prior and prior[0]!=encoded:raise ValueError('Conflicting quarantined source ID')
        with self.db:
            self.db.execute('INSERT OR IGNORE INTO native_rejections VALUES (?,?,?)',(sid,encoded,reason))
        return {'source':sid,'quarantined':True,'reason':reason,'native_dispatched':False,'duplicate':bool(prior)}

    def assert_clean_generation(self,people):
        for body, in self.db.execute('SELECT body FROM episodes WHERE complete=1 AND deleted=0'):
            if source_rejection(json.loads(body),people):
                raise RuntimeError('Existing native generation contains unqualified sources; rebuild in a fresh generation before reading')

    async def ingest(self,episode,people,crash_before_dispatch=False):
        reason=source_rejection(episode,people)
        if reason:return self.reject(episode,reason)
        self.assert_clean_generation(people)
        if self.db.execute('SELECT 1 FROM native_rejections WHERE id=?',(episode['id'],)).fetchone():
            raise ValueError('Quarantined source cannot be silently reattributed; use a new reviewed source ID')
        return await super().ingest(episode,people,crash_before_dispatch)

    async def query(self,question,people):
        audience=question.get('audience_ids');speaker=question.get('asker')
        if (not isinstance(speaker,str) or speaker=='unknown' or speaker not in people or not isinstance(audience,list)
                or not audience or any(not isinstance(p,str) or p not in people for p in audience)
                or len(audience)!=len(set(audience)) or speaker not in audience):
            return {'question_id':question.get('id'),'native_context':[],'scopes_searched':[],
                    'retrieval_ms':0,'blocked':'unknown_identity_or_audience'}
        self.assert_clean_generation(people)
        return await super().query(question,people)


async def main():
    worker=GuardedWorker(sys.argv[1],sys.argv[2]);worker.observation_scopes='shared'
    for line in sys.stdin:
        try:
            r=json.loads(line)
            if r['op']=='initialize':value=await worker.initialize()
            elif r['op']=='ingest':value=await worker.ingest(r['episode'],r['people'])
            elif r['op']=='query':value=await worker.query(r['question'],r['people'])
            elif r['op']=='close':
                await worker.close();print(json.dumps({'ok':True,'result':{'closed':True}}),flush=True);return
            else:raise ValueError('Unknown operation')
            print(json.dumps({'ok':True,'result':value}),flush=True)
        except Exception as exc:
            print(json.dumps({'ok':False,'error':type(exc).__name__+': '+str(exc)}),flush=True)


if __name__=='__main__':asyncio.run(main())

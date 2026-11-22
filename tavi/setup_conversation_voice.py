"""Precompute only fixed, non-personal local greeting/offline/status phrases."""
import asyncio
from .conversation_providers import MacSpeech, LOCAL_REPLIES

async def main():
    voice=MacSpeech()
    for key,text in LOCAL_REPLIES.items():
        path=voice.cache_path(text)
        if not path.exists():
            result=await voice.synthesize(text,cache=False)
            path.parent.mkdir(parents=True,exist_ok=True)
            temporary=path.with_suffix('.tmp.wav');temporary.write_bytes(result.wav);temporary.replace(path)
        result=await voice.synthesize(text)
        print(f'{key}: ready ({result.duration_ms} ms of speech); fixed synthetic audio only',flush=True)

if __name__=='__main__':asyncio.run(main())

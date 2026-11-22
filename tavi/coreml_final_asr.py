"""Experimental local CoreML worker using the same killable PCM/lease adapter."""
import hashlib
import json
from pathlib import Path

from .mlx_final_asr import MlxFinalASR
from .asr_confidence import DecodedSpeech


class CoreMLFinalASR(MlxFinalASR):
    def __init__(self,schedule=None,*,compute='ane',startup_timeout=18,names_hint=False):
        if compute not in ('ane','gpu','ane-gpu'):raise ValueError('Unknown CoreML compute request')
        super().__init__(schedule)
        self.compute=compute
        self.startup_timeout=startup_timeout
        self.names_hint=names_hint

    def worker_command(self,root):
        return [str(root/'.tavi/coreml-build/release/paprika-coreml-asr'),
                str(root/'.tavi/models/coreml-turbo'),self.compute]+(['names'] if self.names_hint else [])

    def prepare(self):
        if self.process and self.process.poll() is None:return super().prepare()
        root=Path(__file__).resolve().parent.parent
        spec=json.loads((root/'experiments/coreml-asr/model-manifest.json').read_text())
        for info in spec['files']:
            path=root/info['path'];h=hashlib.sha256()
            if path.stat().st_size!=info['size']:raise ValueError('CoreML asset size changed')
            with path.open('rb') as f:
                for block in iter(lambda:f.read(1024*1024),b''):h.update(block)
            if h.hexdigest()!=info['sha256']:raise ValueError('CoreML asset checksum changed')
        super().prepare()

    def _request(self,pcm,deadline):
        result=super()._request(pcm,deadline)
        return DecodedSpeech(result.text,{**result.confidence,'decoder':self.profile,
            'prompt':self.profile['prompt'] if self.profile else None},result.timing)

"""Experimental native worker adapter; not a live backend selection."""
from .mlx_final_asr import MlxFinalASR


class StreamingFinalASR(MlxFinalASR):
    def __init__(self,*,mode='batch',paced=False):
        super().__init__()
        if mode not in ('batch','stream'):raise ValueError('Unknown experiment mode')
        self.mode,self.paced=mode,paced
        self.startup_timeout=30

    def worker_command(self,root):
        result=[str(root/'.venv-streaming-asr/bin/python'),'-m','tavi.streaming_asr_worker','--mode',self.mode]
        if self.paced:result.append('--paced')
        return result

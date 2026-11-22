"""Text-free error codes shared across the private speech-worker protocol."""


class SpeechWorkerError(ValueError):
    CODES=frozenset({'worker_ended','invalid_response','initialization_failed',
                    'unsupported_phoneme','invalid_phonemes','oversized_audio','synthesis_failed'})

    def __init__(self,code):
        self.code=code if isinstance(code,str) and code in self.CODES else 'invalid_response'
        super().__init__('Local speech worker: '+self.code)

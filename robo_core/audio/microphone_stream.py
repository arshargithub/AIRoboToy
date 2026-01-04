import sounddevice as sd

class MicrophoneStream:
    def __init__(self, rate=16000, chunk=512):
        self.rate = rate
        self.chunk = chunk

    def stream_chunks(self):
        with sd.InputStream(
            samplerate=self.rate,
            channels=1,
            blocksize=self.chunk,
            dtype='float32'
        ) as stream:
            while True:
                chunk, _ = stream.read(self.chunk)
                yield chunk.flatten()

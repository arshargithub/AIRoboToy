import time

class EndpointDetector:
    def __init__(self, silence_ms=800):
        self.silence_ms = silence_ms
        self.last_speech_time = time.time()

    def mark_speech_activity(self):
        self.last_speech_time = time.time()

    def is_endpoint(self):
        return (time.time() - self.last_speech_time) * 1000 > self.silence_ms

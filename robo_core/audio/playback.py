import sounddevice as sd
import threading

class AudioPlayer:
    def __init__(self):
        self._playback_thread = None
        self._current_stream = None
    
    def play(self, audio_array, samplerate=22050, blocking=False):
        """
        Play audio array.
        
        Args:
            audio_array: Numpy array of audio samples
            samplerate: Sample rate (default: 22050)
            blocking: If True, wait for playback to finish. If False, return immediately.
        """
        if blocking:
            # Blocking playback (original behavior)
            sd.play(audio_array, samplerate)
            sd.wait()
        else:
            # Non-blocking playback - start in background thread
            def _play_audio():
                sd.play(audio_array, samplerate)
                sd.wait()
            
            # Stop any currently playing audio
            self.stop()
            
            # Start playback in background thread
            self._playback_thread = threading.Thread(target=_play_audio, daemon=True)
            self._playback_thread.start()
    
    def stop(self):
        """Stop any currently playing audio."""
        try:
            sd.stop()
        except:
            pass
    
    def wait(self):
        """Wait for current playback to finish."""
        if self._playback_thread and self._playback_thread.is_alive():
            self._playback_thread.join()

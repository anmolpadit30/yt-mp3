from jnius import autoclass, PythonJavaClass, java_method
from kivy.logger import Logger

MediaPlayer = autoclass('android.media.MediaPlayer')
AudioManager = autoclass('android.media.AudioManager')

class OnCompletionListener(PythonJavaClass):
    __javainterfaces__ = ['android/media/MediaPlayer$OnCompletionListener']
    __javacontext__ = 'app'

    def __init__(self, callback):
        super().__init__()
        self.callback = callback

    @java_method('(Landroid/media/MediaPlayer;)V')
    def onCompletion(self, mp):
        self.callback()

class AndroidPlayer:
    def __init__(self, on_completion_callback=None):
        self.player = MediaPlayer()
        self.on_completion_callback = on_completion_callback
        if self.on_completion_callback:
            self.completion_listener = OnCompletionListener(self._on_completion)
            self.player.setOnCompletionListener(self.completion_listener)

    def _on_completion(self):
        Logger.info("AndroidPlayer: Playback completed.")
        if self.on_completion_callback:
            self.on_completion_callback()

    def play(self, file_path):
        try:
            if self.is_playing():
                self.player.stop()
            self.player.reset()
            self.player.setDataSource(file_path)
            self.player.setAudioStreamType(AudioManager.STREAM_MUSIC)
            self.player.prepare()
            self.player.start()
            Logger.info(f"AndroidPlayer: Playing {file_path}")
        except Exception as e:
            Logger.error(f"AndroidPlayer: Error in play: {e}")

    def pause(self):
        if self.is_playing():
            self.player.pause()
            Logger.info("AndroidPlayer: Paused.")

    def resume(self):
        if not self.is_playing():
            self.player.start()
            Logger.info("AndroidPlayer: Resumed.")

    def stop(self):
        if self.player:
            if self.is_playing():
                self.player.stop()
            self.player.release()
            self.player = None
            Logger.info("AndroidPlayer: Stopped and released.")

    def seek(self, position_ms):
        if self.player:
            self.player.seekTo(int(position_ms))

    def get_position(self):
        return self.player.getCurrentPosition() / 1000.0 if self.player else 0

    def get_duration(self):
        return self.player.getDuration() / 1000.0 if self.player else 0

    def is_playing(self):
        if self.player:
            try:
                return self.player.isPlaying()
            except Exception as e:
                # Player might be in an invalid state
                Logger.warning(f"AndroidPlayer: is_playing check failed: {e}")
                return False
        return False

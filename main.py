import os
import sys
import threading
import time
import json
from dataclasses import dataclass
from typing import List

# --- Kivy and platform setup ---
from kivy.config import Config
Config.set('kivy', 'keyboard_mode', 'system')
from kivy.core.window import Window
try:
    Window.softinput_mode = 'pan'
except Exception:
    pass

from kivy.app import App
from kivy.uix.boxlayout import BoxLayout
from kivy.clock import Clock
from kivy.metrics import dp
from kivy.logger import Logger
from kivy.lang import Builder
from kivy.uix.popup import Popup
from kivy.uix.button import Button
from kivy.uix.scrollview import ScrollView
from kivy.uix.label import Label

# --- Platform-specific imports and setup ---
try:
    from android.permissions import request_permissions, Permission, check_permission
    from jnius import autoclass
    ANDROID = True
    PythonService = autoclass('org.kivy.android.PythonService')
except Exception:
    ANDROID = False

if ANDROID:
    VLC_AVAILABLE = False
else:
    try:
        import vlc
        VLC_AVAILABLE = True
    except Exception:
        VLC_AVAILABLE = False
        Logger.warning("python-vlc not found, playback will not work on desktop.")

from yt_dlp import YoutubeDL

# ---------- Player Classes (Platform-specific) ----------

class WindowsPlayer:
    def __init__(self, on_completion_callback=None):
        if not VLC_AVAILABLE:
            raise RuntimeError("VLC is not available.")
        self.vlc_instance = vlc.Instance()
        self.player = self.vlc_instance.media_player_new()
        self.on_completion_callback = on_completion_callback
        
        if self.on_completion_callback:
            events = self.player.event_manager()
            events.event_attach(vlc.EventType.MediaPlayerEndReached, self._on_completion)

    def _on_completion(self, event):
        Logger.info("WindowsPlayer: Playback completed.")
        if self.on_completion_callback:
            Clock.schedule_once(lambda dt: self.on_completion_callback())

    def play(self, file_path):
        media = self.vlc_instance.media_new(file_path)
        self.player.set_media(media)
        self.player.play()

    def pause(self):
        self.player.pause()

    def resume(self):
        self.player.play()

    def stop(self):
        self.player.stop()

    def seek(self, position_sec):
        self.player.set_time(int(position_sec * 1000))

    def get_position(self):
        return self.player.get_time() / 1000.0

    def get_duration(self):
        return self.player.get_length() / 1000.0

    def is_playing(self):
        return self.player.get_state() == vlc.State.Playing
        
    def set_volume(self, volume):
        self.player.audio_set_volume(volume)

    def release(self):
        if self.player:
            self.player.release()
            self.player = None

class AndroidPlayerInterface:
    def __init__(self):
        self.app_files_dir = App.get_running_app().user_data_dir
        self.cmd_file = os.path.join(self.app_files_dir, "service_cmd.txt")

    def _send_command(self, command):
        Logger.info(f"Sending command to service: {command}")
        try:
            with open(self.cmd_file, "w") as f:
                f.write(command)
            os.utime(self.cmd_file, None)
        except Exception as e:
            Logger.error(f"Failed to send command to service: {e}")

    def play(self, file_path):
        self._send_command(f"PLAY|{file_path}")

    def pause(self):
        self._send_command("PAUSE")

    def resume(self):
        self._send_command("RESUME")

    def stop(self):
        self._send_command("STOP")

    def seek(self, position_sec):
        self._send_command(f"SEEK|{position_sec}")

    def release(self):
        self.stop()

# ---------- Utility & helpers ----------

@dataclass
class DownloadTask:
    url: str
    output_dir: str
    is_playlist: bool

def get_app_files_dir() -> str:
    if ANDROID:
        return App.get_running_app().user_data_dir
    else:
        target = os.path.join(os.path.abspath(os.getcwd()), "data")
        os.makedirs(target, exist_ok=True)
        return target

def get_public_downloads_dir() -> str:
    if ANDROID:
        try:
            Environment = autoclass('android.os.Environment')
            return Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_DOWNLOADS).getAbsolutePath()
        except Exception as e:
            Logger.error(f"get_public_downloads_dir: {e}")
            # Fallback to a public but app-specific directory if the above fails
            context = autoclass('org.kivy.android.PythonActivity').mActivity.getApplicationContext()
            return context.getExternalFilesDir(None).getAbsolutePath()
    else:
        target = os.path.join(os.path.abspath(os.getcwd()), "downloads")
        os.makedirs(target, exist_ok=True)
        return target

def get_temp_dir() -> str:
    temp_dir = os.path.join(get_app_files_dir(), "temp_streaming")
    os.makedirs(temp_dir, exist_ok=True)
    return temp_dir

class YDLLogger:
    def debug(self, msg): Logger.info(f"yt_dlp: {msg}")
    def warning(self, msg): Logger.warning(f"yt_dlp: {msg}")
    def error(self, msg): Logger.error(f"yt_dlp: {msg}")

def is_playlist_url(url: str) -> bool: return "playlist" in url.lower() or "list=" in url.lower()

def extract_playlist_info(playlist_url: str) -> (list, list):
    opts = {"quiet": True, "extract_flat": "in_playlist", "skip_download": True}
    urls, titles = [], []
    with YoutubeDL(opts) as ydl:
        info = ydl.extract_info(playlist_url, download=False)
        if info and 'entries' in info:
            for e in info.get('entries', []):
                if e and e.get('id'):
                    urls.append(f"https://www.youtube.com/watch?v={e['id']}")
                    titles.append(e.get('title', 'Unknown Title'))
    return urls, titles

def download_for_streaming(video_url: str):
    try:
        temp_dir = get_temp_dir()
        opts_info = {"quiet": True, "no_warnings": True, "format": "bestaudio[ext=m4a]/bestaudio/best", "skip_download": True, "logger": YDLLogger()}
        with YoutubeDL(opts_info) as ydl:
            info = ydl.extract_info(video_url, download=False)
            if not info: return None, None, None
            title, duration, ext = info.get('title', 'unknown'), info.get('duration', 0), info.get('ext', 'm4a')
        
        safe_title = "".join(c if c.isalnum() or c in " ._-" else "_" for c in title)
        temp_path = os.path.join(temp_dir, f"temp_{safe_title}.{ext}")
        
        if os.path.exists(temp_path):
            return temp_path, title, duration
            
        opts = {"quiet": True, "no_warnings": True, "format": "bestaudio[ext=m4a]/bestaudio/best", "outtmpl": temp_path, "logger": YDLLogger()}
        with YoutubeDL(opts) as ydl:
            ydl.extract_info(video_url, download=True)
            
        return (temp_path, title, duration) if os.path.exists(temp_path) else (None, None, None)
    except Exception as e:
        Logger.error(f"download_for_streaming: {e}")
        return None, None, None

# ---------- Service Management ----------
service_running = False
def start_music_service():
    global service_running
    if ANDROID and not service_running:
        try:
            activity = autoclass('org.kivy.android.PythonActivity').mActivity
            intent = autoclass('android.content.Intent')(activity, PythonService)
            
            app_root = os.path.dirname(os.path.abspath(__file__))
            intent.putExtra('android.PythonService.ARGUMENT', app_root)
            intent.putExtra('android.PythonService.ENTRYPOINT', 'service.py')
            
            activity.startService(intent)
            service_running = True
            Logger.info("start_music_service: Service intent sent.")
        except Exception as e:
            Logger.error(f"start_music_service: {e}")

def stop_music_service():
    global service_running
    if ANDROID and service_running:
        try:
            activity = autoclass('org.kivy.android.PythonActivity').mActivity
            intent = autoclass('android.content.Intent')(activity, PythonService)
            activity.stopService(intent)
            service_running = False
        except Exception as e:
            Logger.error(f"stop_music_service: {e}")

# ---------- Main App ----------

class Root(BoxLayout):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.player = None
        self.is_playing = False
        self.current_file = None
        self.current_title = None
        self.current_duration = 0
        self.playlist_urls = []
        self.playlist_titles = []
        self.current_index = 0
        self._worker = None
        self.autoplay_enabled = True
        self.progress_event = None
        
        self.status_file = None
        self.last_status_mtime = 0
        self.last_status_data = {}

        if ANDROID:
            self.player = AndroidPlayerInterface()
            self.status_file = os.path.join(App.get_running_app().user_data_dir, "service_status.json")
            ensure_android_permissions()
            start_music_service()
        elif VLC_AVAILABLE:
            self.player = WindowsPlayer(on_completion_callback=self.on_playback_finished)
        else:
            Logger.error("No player available for this platform.")

    def on_kv_post(self, base_widget):
        self.input = self.ids.input
        self.stream_btn = self.ids.stream_btn
        self.download_btn = self.ids.download_btn
        self.play_btn = self.ids.play_btn
        self.stop_btn = self.ids.stop_btn
        self.prev_btn = self.ids.prev_btn
        self.next_btn = self.ids.next_btn
        self.volume_slider = self.ids.volume_slider
        self.progress_bar = self.ids.progress_bar
        self.track_title = self.ids.track_title
        self.current_time = self.ids.current_time
        self.total_time = self.ids.total_time
        self.status = self.ids.status
        self.autoplay_btn = self.ids.autoplay_btn
        
        self.volume_slider.bind(value=self.on_volume_change)
        self.track_title.text = "No track loaded"
        self.status.text = "Welcome!"
        self.total_time.text = "0:00"
        self.current_time.text = "0:00"
        
        self.progress_event = Clock.schedule_interval(self.update_progress, 0.5)

    def set_status(self, msg: str):
        Clock.schedule_once(lambda *_: setattr(self.status, "text", msg))

    def format_time(self, seconds: int) -> str:
        return f"{int(seconds // 60)}:{int(seconds % 60):02d}"

    def on_playback_finished(self):
        Logger.info("Root: Playback finished.")
        self.stop_playback_ui()
        if self.autoplay_enabled:
            self.on_next()

    def on_stream(self, *_):
        url = (self.input.text or "").strip()
        if not url: return
        if is_playlist_url(url):
            threading.Thread(target=self._load_playlist, args=(url,), daemon=True).start()
        else:
            threading.Thread(target=self._load_track, args=(url, True), daemon=True).start()

    def _load_playlist(self, playlist_url):
        self.set_status("Loading playlist...")
        urls, titles = extract_playlist_info(playlist_url)
        if not urls:
            self.set_status("❌ Could not load playlist")
            return
        self.playlist_urls = urls
        self.playlist_titles = titles
        self.current_index = 0
        self.set_status(f"Playlist: {len(urls)} tracks")
        self._load_track(urls[0], is_new_stream=True)

    def _load_track(self, video_url, is_new_stream=False):
        self.set_status("Downloading...")
        file_path, title, duration = download_for_streaming(video_url)
        if file_path and title:
            Clock.schedule_once(lambda *_: self._on_track_loaded(file_path, title, duration, is_new_stream))
        else:
            self.set_status("❌ Failed to load track")

    def _on_track_loaded(self, file_path, title, duration, is_new_stream=False):
        self.on_stop()
        self.current_file = file_path
        self.current_title = title
        self.current_duration = duration
        self.track_title.text = f"{self.current_index + 1}. {title[:50]}"
        self.total_time.text = self.format_time(duration)
        self.progress_bar.value = 0
        self.current_time.text = "0:00"
        self.set_status("✅ Track loaded.")
        if self.autoplay_enabled and is_new_stream:
            self.on_play_pause()

    def on_play_pause(self, *_):
        if not self.current_file:
            self.set_status("❌ No track loaded")
            return
            
        if self.is_playing:
            self.player.pause()
            self.set_status("⏸ Paused")
        else:
            current_pos = self.get_current_position()
            if current_pos > 1 and current_pos < self.current_duration -1:
                 self.player.resume()
            else:
                 self.player.play(self.current_file)
            self.set_status("▶ Playing")
        
        self.is_playing = not self.is_playing
        self.play_btn.text = "||" if self.is_playing else ">"

    def on_stop(self, *_):
        if self.player:
            self.player.stop()
        self.stop_playback_ui()
        self.set_status("⏹ Stopped")

    def stop_playback_ui(self):
        self.is_playing = False
        self.play_btn.text = ">"
        self.progress_bar.value = 0
        self.current_time.text = "0:00"

    def update_progress(self, dt):
        if ANDROID:
            self.update_progress_android()
        elif self.player:
            self.update_progress_windows()

    def update_progress_windows(self):
        if not self.player or not self.current_file: return

        was_playing = self.is_playing
        self.is_playing = self.player.is_playing()

        if was_playing != self.is_playing:
            self.play_btn.text = "||" if self.is_playing else ">"
            self.set_status("▶ Playing" if self.is_playing else "⏸ Paused")

        if self.is_playing:
            pos = self.player.get_position()
            if self.current_duration > 0:
                self.progress_bar.value = (pos / self.current_duration) * 100
            self.current_time.text = self.format_time(pos)

    def update_progress_android(self):
        if not self.status_file or not os.path.exists(self.status_file): return
        
        try:
            current_mtime = os.path.getmtime(self.status_file)
            if current_mtime <= self.last_status_mtime: return
            
            self.last_status_mtime = current_mtime
            with open(self.status_file, "r") as f:
                status = json.load(f)

            if status.get("completed"):
                if self.last_status_data.get("file_path") == status.get("file_path"):
                    self.last_status_data = {}
                    self.on_playback_finished()
                return

            self.last_status_data = status
            
            was_playing = self.is_playing
            self.is_playing = status.get("is_playing", False)
            
            if was_playing != self.is_playing:
                self.play_btn.text = "||" if self.is_playing else ">"
                self.set_status("▶ Playing" if self.is_playing else "⏸ Paused")

            pos = status.get("position", 0)
            duration = status.get("duration", 0)
            
            if duration > 0:
                self.progress_bar.value = (pos / duration) * 100
                self.total_time.text = self.format_time(duration)
            
            self.current_time.text = self.format_time(pos)

        except Exception as e:
            Logger.error(f"Error reading status file: {e}")

    def on_seek(self, instance, touch):
        if instance.collide_point(*touch.pos) and self.current_duration > 0:
            pct = max(0.0, min(1.0, (touch.pos[0] - instance.pos[0]) / instance.size[0]))
            seek_time_sec = self.current_duration * pct
            self.player.seek(seek_time_sec)
            self.current_time.text = self.format_time(seek_time_sec)
            self.progress_bar.value = pct * 100

    def on_volume_change(self, instance, value):
        if isinstance(self.player, WindowsPlayer):
            self.player.set_volume(int(value))

    def get_current_position(self) -> float:
        if isinstance(self.player, WindowsPlayer):
            return self.player.get_position()
        elif ANDROID and self.last_status_data:
            return self.last_status_data.get("position", 0)
        return 0.0

    def on_next(self, *_):
        if not self.playlist_urls or self.current_index >= len(self.playlist_urls) - 1: return
        self.current_index += 1
        threading.Thread(target=self._load_track, args=(self.playlist_urls[self.current_index], True), daemon=True).start()

    def on_previous(self, *_):
        if not self.playlist_urls or self.current_index <= 0: return
        self.current_index -= 1
        threading.Thread(target=self._load_track, args=(self.playlist_urls[self.current_index], True), daemon=True).start()

    def on_download(self, *_):
        url = (self.input.text or "").strip()
        if not url: return
        ensure_android_permissions()
        output_dir = get_public_downloads_dir()
        task = DownloadTask(url=url, output_dir=output_dir, is_playlist=is_playlist_url(url))
        if self._worker and self._worker.is_alive():
            self.set_status("⚠️ A download is already running.")
            return
        self.set_status("Starting download…")
        self._worker = threading.Thread(target=self._run_task, args=(task,), daemon=True)
        self._worker.start()

    def _run_task(self, task: DownloadTask):
        try:
            ydl_opts = {
                "format": "bestaudio/best",
                "outtmpl": os.path.join(task.output_dir, "%(title)s.%(ext)s"),
                "noplaylist": not task.is_playlist,
                "ignoreerrors": True,
                "logger": YDLLogger(),
                "quiet": True,
            }
            with YoutubeDL(ydl_opts) as ydl:
                ydl.download([task.url])
            self.set_status(f"✅ Done. Saved to: {task.output_dir}")
        except Exception as e:
            Logger.error(f"_run_task: {e}")
            self.set_status(f"❌ Error: {e}")
            
    def open_playlist_popup(self):
        if not self.playlist_titles:
            self.set_status("No playlist loaded.")
            return
        popup_layout = BoxLayout(orientation='vertical', spacing=dp(5), padding=dp(10))
        top_bar = BoxLayout(orientation='horizontal', size_hint_y=None, height=dp(48))
        top_bar.add_widget(Label(text="Playlist", size_hint_x=0.9))
        close_btn = Button(text="X", size_hint_x=0.1)
        top_bar.add_widget(close_btn)
        popup_layout.add_widget(top_bar)
        scroll = ScrollView()
        song_list = BoxLayout(orientation='vertical', size_hint_y=None, spacing=dp(5))
        song_list.bind(minimum_height=song_list.setter('height'))
        for idx, title in enumerate(self.playlist_titles):
            btn = Button(text=f"{idx+1}. {title}", size_hint_y=None, height=dp(60), halign="left", valign="middle")
            btn.bind(width=lambda inst, val: setattr(inst, "text_size", (val - dp(20), None)))
            btn.bind(on_press=lambda inst, i=idx: self.select_playlist_song(i, popup))
            if idx == self.current_index:
                btn.background_color = (0.2, 0.6, 1, 1)
            song_list.add_widget(btn)
        scroll.add_widget(song_list)
        popup_layout.add_widget(scroll)
        popup = Popup(title="", content=popup_layout, size_hint=(.9, 0.9), auto_dismiss=False)
        close_btn.bind(on_press=popup.dismiss)
        popup.open()

    def select_playlist_song(self, index, popup):
        popup.dismiss()
        self.current_index = index
        threading.Thread(target=self._load_track, args=(self.playlist_urls[self.current_index], True), daemon=True).start()

def ensure_android_permissions():
    if not ANDROID: return
    try:
        perms = [Permission.WRITE_EXTERNAL_STORAGE, Permission.READ_EXTERNAL_STORAGE]
        missing = [p for p in perms if not check_permission(p)]
        if missing:
            request_permissions(perms)
    except Exception as e:
        Logger.error(f"Error requesting permissions: {e}")

class YouTubeMP3App(App):
    def build(self):
        kv_path = os.path.join(os.path.dirname(__file__), "main.kv")
        if os.path.exists(kv_path):
            Builder.load_file(kv_path)
        else:
            Logger.warning("main.kv not found!")
        return Root()

    def on_stop(self):
        if ANDROID:
            # The app is stopping, tell the service to stop as well
            if self.root and self.root.player:
                self.root.player.stop()
            stop_music_service()
        elif self.root and self.root.player:
            self.root.player.release()

if __name__ == "__main__":
    YouTubeMP3App().run()

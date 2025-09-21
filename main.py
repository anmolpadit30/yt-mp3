import os
import sys
import threading
import traceback
import time
from dataclasses import dataclass
from typing import List

# Configure Kivy before importing other Kivy modules
try:
    from kivy.config import Config
    Config.set('kivy', 'keyboard_mode', 'system')
except Exception:
    pass

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

from jnius import autoclass

# Audio playback (desktop) - optional: python-vlc
try:
    import vlc
    VLC_AVAILABLE = True
except Exception:
    VLC_AVAILABLE = False
    Logger.warning("python-vlc not available, audio playback will be limited on desktop; on Android you should use ffpyplayer or Android native APIs")

# yt-dlp core
from yt_dlp import YoutubeDL

# ---------- Utility & helpers (unchanged logic, slightly adapted) ----------

@dataclass
class DownloadTask:
    url: str
    output_dir: str
    is_playlist: bool

# Android guard (keeps code runnable on desktop)
try:
    from android.permissions import request_permissions, Permission, check_permission
    from jnius import autoclass
    ANDROID = True
    PythonService = autoclass('org.kivy.android.PythonService')
except Exception:
    ANDROID = False
    class MockPermission:
        INTERNET = "android.permission.INTERNET"
        WRITE_EXTERNAL_STORAGE = "android.permission.WRITE_EXTERNAL_STORAGE"
        READ_EXTERNAL_STORAGE = "android.permission.READ_EXTERNAL_STORAGE"
    Permission = MockPermission()
    autoclass = None
    PythonService = None

def get_download_root() -> str:
    if ANDROID:
        try:
            Environment = autoclass('android.os.Environment')
            downloads_dir_obj = Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_DOWNLOADS)
            if downloads_dir_obj is not None:
                target = downloads_dir_obj.getAbsolutePath()
            else:
                storage_root_obj = Environment.getExternalStorageDirectory()
                storage_root = storage_root_obj.getAbsolutePath() if storage_root_obj else "/sdcard"
                target = os.path.join(storage_root, "Download")
        except Exception as e:
            Logger.error(f"get_download_root: {e}")
            target = "/sdcard/Download"
    else:
        target = os.path.join(os.path.abspath(os.getcwd()), "downloads")
    os.makedirs(target, exist_ok=True)
    return target

def ensure_android_permissions():
    if not ANDROID:
        return
    perms = [Permission.INTERNET, Permission.WRITE_EXTERNAL_STORAGE, Permission.READ_EXTERNAL_STORAGE]
    missing = [p for p in perms if not check_permission(p)]
    if missing:
        request_permissions(perms)

def get_temp_dir() -> str:
    temp_dir = os.path.join(get_download_root(), "temp_streaming")
    os.makedirs(temp_dir, exist_ok=True)
    return temp_dir

def cleanup_temp_files():
    try:
        temp_dir = get_temp_dir()
        now = time.time()
        for f in os.listdir(temp_dir):
            if f.startswith("temp_"):
                path = os.path.join(temp_dir, f)
                try:
                    if now - os.path.getmtime(path) > 1800:
                        os.remove(path)
                        Logger.info(f"cleanup_temp_files: removed {f}")
                except Exception:
                    pass
    except Exception as e:
        Logger.warning(f"cleanup_temp_files: {e}")

def manage_storage_size():
    try:
        temp_dir = get_temp_dir()
        max_size = 1024 * 1024 * 1024
        files = []
        total = 0
        for f in os.listdir(temp_dir):
            if f.startswith("temp_"):
                path = os.path.join(temp_dir, f)
                try:
                    size = os.path.getsize(path)
                    mtime = os.path.getmtime(path)
                    files.append((path, size, mtime))
                    total += size
                except Exception:
                    pass
        if total > max_size:
            files.sort(key=lambda x: x[2])
            freed = 0
            for path, size, _ in files:
                if total - freed <= max_size:
                    break
                try:
                    os.remove(path)
                    freed += size
                    Logger.info(f"manage_storage_size: removed {os.path.basename(path)}")
                except Exception:
                    pass
    except Exception as e:
        Logger.warning(f"manage_storage_size: {e}")

# yt-dlp helpers
class YDLLogger:
    def debug(self, msg): Logger.info(f"yt_dlp: {msg}")
    def warning(self, msg): Logger.warning(f"yt_dlp: {msg}")
    def error(self, msg): Logger.error(f"yt_dlp: {msg}")

def is_playlist_url(url: str) -> bool:
    return "playlist" in url.lower() or "list=" in url.lower()

def extract_playlist_urls(playlist_url: str) -> List[str]:
    opts = {"quiet": True, "extract_flat": True, "skip_download": True}
    urls = []
    with YoutubeDL(opts) as ydl:
        info = ydl.extract_info(playlist_url, download=False)
        entries = info.get("entries") or []
        for e in entries:
            vid = e.get("url")
            if vid and 'watch?v=' in vid:
                urls.append(vid)
            else:
                urls.append(f"https://www.youtube.com/watch?v={vid}")
    return urls

def download_for_streaming(video_url: str, progress_callback=None) -> tuple:
    """
    Downloads the best audio into a temp file and returns (file_path, title, duration)
    This function avoids FFmpeg postprocessing for streaming.
    """
    try:
        temp_dir = get_temp_dir()

        # get safe title & extension without downloading
        opts_info = {"quiet": True, "no_warnings": True, "format": "bestaudio/best", "skip_download": True}
        with YoutubeDL(opts_info) as ydl:
            info = ydl.extract_info(video_url, download=False)
            if not info:
                return None, None, None
            title = info.get('title', 'unknown')
            duration = info.get('duration', 0)
            ext = info.get('ext', 'm4a')

        safe_title = "".join(c if c.isalnum() or c in " ._-" else "_" for c in title)
        temp_filename = f"temp_{safe_title}.{ext}"
        temp_path = os.path.join(temp_dir, temp_filename)

        if os.path.exists(temp_path):
            return temp_path, title, duration

        def _progress(d):
            if progress_callback:
                progress_callback(d)

        opts = {
            "quiet": True,
            "no_warnings": True,
            "format": "bestaudio/best",
            "outtmpl": temp_path,
            "progress_hooks": [lambda d: _progress(d)],
        }

        with YoutubeDL(opts) as ydl:
            info = ydl.extract_info(video_url, download=True)
            if not info:
                return None, None, None

        if os.path.exists(temp_path):
            return temp_path, title, duration
        return None, None, None

    except Exception as e:
        Logger.error(f"download_for_streaming: {e}")
        return None, None, None

# ---------- KV & Root wiring ----------
# We'll load main.kv explicitly in App.build() so user can name the file "main.kv".

class Root(BoxLayout):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # playback state
        self.media_player = None
        self.is_playing = False
        self.current_file = None
        self.current_title = None
        self.current_duration = 0
        self.progress_event = None
        self.playlist_urls = ['https://www.youtube.com/watch?v=CprWhVqZFPA', 'https://www.youtube.com/watch?v=-kt1yB3Lk9g', 'https://www.youtube.com/watch?v=t36HlL4A7m0']
        self.current_index = 0
        self._worker = None
        self.autoplay_enabled = True  # Add autoplay state

    def on_kv_post(self, base_widget):
        """
        Called after KV has been applied. Grab references from ids.
        """
        # grab commonly used widgets as attributes for old code compatibility
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
        self.progress = self.ids.progress
        self.autoplay_btn = self.ids.autoplay_btn  # Add autoplay button reference

        # ensure the volume slider changes audio volume
        try:
            self.volume_slider.bind(value=self.on_volume_change)
        except Exception:
            pass

        # initial UI
        self.track_title.text = "No track loaded"
        self.status.text = ""
        self.progress.text = ""
        self.total_time.text = "0:00"
        self.current_time.text = "0:00"

    # UI-safe updaters
    def set_status(self, msg: str):
        Clock.schedule_once(lambda *_: setattr(self.status, "text", msg))

    def set_progress(self, percent: int):
        Clock.schedule_once(lambda *_: setattr(self.progress, "text", f"Progress: {percent}%"))

    def format_time(self, seconds: int) -> str:
        minutes = int(seconds // 60)
        seconds = int(seconds % 60)
        return f"{minutes}:{seconds:02d}"

    # streaming / playback handlers (adapted to use the ids attributes)
    def on_stream(self, *_):
        url = (self.input.text or "").strip()
        if not url:
            self.set_status("❌ Please paste a YouTube URL first.")
            return
        if not VLC_AVAILABLE:
            self.set_status("❌ python-vlc not available. Install it for desktop testing.")
            return

        # stop existing
        self.stop_playback()

        if is_playlist_url(url):
            self.set_status("Loading playlist...")
            threading.Thread(target=self._load_playlist_for_streaming, args=(url,), daemon=True).start()
        else:
            self.set_status("Loading track...")
            threading.Thread(target=self._load_track_for_streaming, args=(url,), daemon=True).start()

    def _load_playlist_for_streaming(self, playlist_url):
        try:
            urls = extract_playlist_urls(playlist_url)
            titles = []
            with YoutubeDL({"quiet": True, "extract_flat": True, "skip_download": True}) as ydl:
                info = ydl.extract_info(playlist_url, download=False)
                entries = info.get("entries") or []
                for e in entries:
                    titles.append(e.get("title", "Unknown"))
            self.playlist_urls = urls
            self.playlist_titles = titles
            self.current_index = 0
            self.set_status(f"Playlist: {len(urls)} tracks")
            # auto-load first track
            file_path, title, duration = download_for_streaming(urls[0], lambda d: None)
            if file_path:
                Clock.schedule_once(lambda *_: self._on_track_loaded(file_path, title, duration))
        except Exception as e:
            Logger.error(f"_load_playlist_for_streaming: {e}")
            self.set_status(f"❌ Error: {e}")

    def _load_track_for_streaming(self, video_url):
        def progress_callback(d):
            status = d.get("status", "")
            if status == "downloading":
                total = d.get("total_bytes") or d.get("total_bytes_estimate")
                downloaded = d.get("downloaded_bytes", 0)
                if total:
                    pct = int(downloaded * 100 / total)
                    Clock.schedule_once(lambda *_: self.set_status(f"Downloading... {pct}%"))

        file_path, title, duration = download_for_streaming(video_url, progress_callback)
        if file_path and title:
            Clock.schedule_once(lambda *_: self._on_track_loaded(file_path, title, duration))
        else:
            Clock.schedule_once(lambda *_: self.set_status("❌ Failed to load track"))

    def _on_track_loaded(self, file_path, title, duration):
        self.current_file = file_path
        self.current_title = title
        self.current_duration = duration

        self.track_title.text = str(self.current_index+1)+'. '+(title[:50] + "..." if len(title) > 50 else title)
        self.total_time.text = self.format_time(duration)
        self.progress_bar.value = 0
        self.current_time.text = "0:00"

        try:
            # Wait for file to be ready
            for _ in range(10):
                if os.path.exists(file_path) and os.path.getsize(file_path) > 4 * 1024:
                    break
                time.sleep(0.1)

            # Create VLC player
            if self.media_player:
                try:
                    self.media_player.stop()
                    self.media_player.release()
                except Exception:
                    pass
            self.media_player = vlc.MediaPlayer(file_path)
            self.media_player.audio_set_volume(int(self.volume_slider.value))
            self.play_btn.text = ">"
            self.is_playing = False
            self.set_status("✅ Track loaded. Click play to start.")

            # --- FIX: Auto-play if enabled ---
            Logger.info(f"Autoplay enabled: {hasattr(self, 'autoplay_enabled')}, {self.autoplay_enabled}")
            if hasattr(self, "autoplay_enabled") and self.autoplay_enabled:
                self.on_play_pause()
        except Exception as e:
            Logger.error(f"_on_track_loaded: {e}")
            self.set_status(f"❌ Error loading: {e}")
            self.media_player = None

    def on_play_pause(self, *_):
        if not self.media_player:
            self.set_status("❌ No track loaded")
            return
        try:
            state = self.media_player.get_state()
            if state in [vlc.State.Paused, vlc.State.Stopped, vlc.State.Ended]:
                self.media_player.play()
                self.is_playing = True
                self.play_btn.text = "||"
                if not self.progress_event:
                    self.progress_event = Clock.schedule_interval(self.update_progress, 0.5)
                self.set_status("▶ Playing")
            elif state == vlc.State.Playing:
                self.media_player.pause()
                self.is_playing = False
                self.play_btn.text = ">"
                if self.progress_event:
                    Clock.unschedule(self.progress_event)
                    self.progress_event = None
                self.set_status("⏸ Paused")
            else:
                self.media_player.play()
                self.is_playing = True
                self.play_btn.text = "||"
                if not self.progress_event:
                    self.progress_event = Clock.schedule_interval(self.update_progress, 0.5)
                self.set_status("▶ Playing")
        except Exception as e:
            Logger.error(f"on_play_pause: {e}")
            self.set_status(f"❌ Error: {e}")

    def update_progress(self, dt):
        if not self.media_player:
            return
        try:
            state = self.media_player.get_state()
            if state == vlc.State.Playing:
                pos = self.media_player.get_time() / 1000.0
                duration = self.media_player.get_length() / 1000.0
                if duration > 0 and pos >= 0:
                    prog = (pos / duration) * 100
                    self.ids.progress_bar.value = min(prog, 100)
                    self.ids.current_time.text = self.format_time(int(pos))
                    self.ids.total_time.text = self.format_time(int(duration))
                    self.set_status("▶ Playing")
            elif state == vlc.State.Paused:
                self.set_status("⏸ Paused")
            elif state in (vlc.State.Stopped, vlc.State.Ended):
                self.stop_playback()
                self.set_status("✅ Track finished")
                # --- Auto-play next song if enabled and playlist exists ---
                if getattr(self, "autoplay_enabled", False) and self.playlist_urls and self.current_index < len(self.playlist_urls) - 1:
                    self.current_index += 1
                    self.set_status("Auto-playing next track...")
                    self._load_track_for_streaming(self.playlist_urls[self.current_index])
        except Exception as e:
            Logger.warning(f"update_progress: {e}")

    def on_stop(self, *_):
        self.stop_playback()

    def stop_playback(self):
        if self.media_player:
            try:
                self.media_player.stop()
                self.media_player.release()
            except Exception:
                pass
            self.media_player = None
        self.is_playing = False
        self.play_btn.text = ">"
        self.progress_bar.value = 0
        self.current_time.text = "0:00"
        if self.progress_event:
            Clock.unschedule(self.progress_event)
            self.progress_event = None

    def on_previous(self, *_):
        if not self.playlist_urls or self.current_index <= 0:
            self.set_status("❌ No previous track")
            return
        self.current_index -= 1
        self.set_status("Loading previous track...")
        threading.Thread(target=self._load_track_for_streaming, args=(self.playlist_urls[self.current_index],), daemon=True).start()

    def on_next(self, *_):
        if not self.playlist_urls or self.current_index >= len(self.playlist_urls) - 1:
            self.set_status("❌ No next track")
            return
        self.current_index += 1
        self.set_status("Loading next track...")
        threading.Thread(target=self._load_track_for_streaming, args=(self.playlist_urls[self.current_index],), daemon=True).start()

    def on_volume_change(self, instance, value):
        if self.media_player:
            try:
                self.media_player.audio_set_volume(int(value))
            except Exception as e:
                Logger.warning(f"on_volume_change: {e}")

    def on_download(self, *_):
        url = (self.input.text or "").strip()
        if not url:
            self.set_status("❌ Please paste a YouTube URL first.")
            return
        ensure_android_permissions()
        output_dir = get_download_root()
        task = DownloadTask(url=url, output_dir=output_dir, is_playlist=is_playlist_url(url))
        if self._worker and self._worker.is_alive():
            self.set_status("⚠️ A download is already running.")
            return
        self.set_status("Starting download…")
        self.set_progress(0)
        self._worker = threading.Thread(target=self._run_task, args=(task,), daemon=True)
        self._worker.start()

    def on_seek(self, instance, touch):
        # Called from KV progress_bar on_touch_up
        if instance.collide_point(*touch.pos) and self.media_player and self.current_duration > 0:
            rel_x = touch.pos[0] - instance.pos[0]
            pct = rel_x / instance.size[0]
            pct = max(0.0, min(1.0, pct))
            seek_time = int(self.current_duration * pct)
            try:
                self.media_player.set_time(seek_time * 1000)
                self.current_time.text = self.format_time(seek_time)
                self.progress_bar.value = pct * 100
            except Exception as e:
                Logger.warning(f"on_seek: {e}")

    def schedule_cleanup(self):
        Clock.schedule_interval(lambda *_: cleanup_temp_files(), 300)
        Clock.schedule_interval(lambda *_: manage_storage_size(), 600)

    def toggle_autoplay(self, *_):
        self.autoplay_enabled = not self.autoplay_enabled
        self.autoplay_btn.text = f"Auto-Play: {'ON' if self.autoplay_enabled else 'OFF'}"

    def cleanup_all_temp_files(self):
        try:
            temp_dir = get_temp_dir()
            for filename in os.listdir(temp_dir):
                if filename.startswith("temp_"):
                    file_path = os.path.join(temp_dir, filename)
                    try:
                        os.remove(file_path)
                        Logger.info(f"cleanup_all_temp_files: Removed {filename}")
                    except Exception as e:
                        Logger.warning(f"cleanup_all_temp_files: Could not remove {filename}: {e}")
        except Exception as e:
            Logger.error(f"cleanup_all_temp_files: Error during cleanup: {e}")

    def open_playlist_popup(self):
        if not self.playlist_urls:
            self.set_status("No playlist loaded.")
            return

        popup_layout = BoxLayout(orientation='vertical', spacing=5, padding=10)

        # Top bar with close button
        top_bar = BoxLayout(orientation='horizontal', size_hint_y=None, height=40)
        top_bar.add_widget(Label(text="Playlist", size_hint_x=0.9))
        close_btn = Button(text="X", size_hint_x=0.1)
        top_bar.add_widget(close_btn)
        popup_layout.add_widget(top_bar)

        # Song list
        scroll = ScrollView(size_hint=(1, 1))
        song_list = BoxLayout(orientation='vertical', size_hint_y=None)
        song_list.bind(minimum_height=song_list.setter('height'))
        # Logger.info(f"Opening playlist popup with {self.playlist_urls} songs")
        for idx, url in enumerate(self.playlist_urls):
            title = f"{idx+1}. {url}"
            if hasattr(self, "playlist_titles") and self.playlist_titles and idx < len(self.playlist_titles):
                title = f"{idx+1}. {self.playlist_titles[idx]}"
            btn = Button(
                text=title,
                size_hint_y=None,
                height=60,  # bigger so wrapping is visible
                background_color=(0.2, 0.6, 1, 1) if idx == self.current_index else (1, 1, 1, 1),
                color=(1, 1, 1, 1) if idx == self.current_index else (.9, .9, .9, 1),
                halign="left",
                valign="middle"
            )

            # enable wrapping
            btn.text_size = (btn.width - 20, None)
            btn.bind(width=lambda inst, val: setattr(inst, "text_size", (val - 20, None)))

            btn.bind(on_press=lambda inst, i=idx: self.select_playlist_song(i, popup))
            song_list.add_widget(btn)

        scroll.add_widget(song_list)
        popup_layout.add_widget(scroll)

        popup = Popup(title="", content=popup_layout, size_hint=(.9, 0.9), auto_dismiss=False)
        close_btn.bind(on_press=popup.dismiss)
        popup.open()
        self._playlist_popup = popup  # Save reference if needed

    def select_playlist_song(self, index, popup):
        popup.dismiss()
        self.current_index = index
        self.set_status(f"Loading track {index+1}...")
        threading.Thread(target=self._load_track_for_streaming, args=(self.playlist_urls[index],), daemon=True).start()

    # background download task (unchanged)
    def _run_task(self, task: DownloadTask):
        def update_status(msg): self.set_status(msg)
        def update_progress(p): self.set_progress(p)
        try:
            if task.is_playlist:
                update_status("Fetching playlist…")
                urls = extract_playlist_urls(task.url)
                if not urls:
                    update_status("❌ No videos in playlist.")
                    return
                for idx, vurl in enumerate(urls, 1):
                    update_status(f"[{idx}/{len(urls)}] Downloading…")
                    ydl_opts = {
                        "format": "bestaudio/best",
                        "outtmpl": os.path.join(task.output_dir, "%(title)s.%(ext)s"),
                        "noplaylist": True,
                        "ignoreerrors": True,
                        "progress_hooks": [lambda d: progress_hook(d, update_status, update_progress)],
                        "logger": YDLLogger(),
                        "quiet": True,
                        "no_warnings": True,
                    }
                    with YoutubeDL(ydl_opts) as ydl:
                        ydl.download([vurl])
                update_status(f"✅ Done. Saved to: {task.output_dir}")
            else:
                ydl_opts = {
                    "format": "bestaudio/best",
                    "outtmpl": os.path.join(task.output_dir, "%(title)s.%(ext)s"),
                    "noplaylist": True,
                    "ignoreerrors": True,
                    "progress_hooks": [lambda d: progress_hook(d, update_status, update_progress)],
                    "logger": YDLLogger(),
                    "quiet": True,
                    "no_warnings": True,
                }
                with YoutubeDL(ydl_opts) as ydl:
                    ydl.download([task.url])
                update_status(f"✅ Done. Saved to: {task.output_dir}")
        except Exception as e:
            Logger.error(f"_run_task: {e}")
            update_status(f"❌ Error: {e}")

def progress_hook(d, update_status, update_progress):
    status = d.get("status", "")
    if status == "downloading":
        total = d.get("total_bytes") or d.get("total_bytes_estimate")
        downloaded = d.get("downloaded_bytes", 0)
        if total:
            pct = int(downloaded * 100 / total)
            update_progress(pct)
        update_status("Downloading…")
    elif status == "finished":
        update_status("Finished")
        update_progress(100)


def start_music_service():
    global service
    if not service:
        service = PythonService.start('musicservice', 'service.py')

def stop_music_service():
    global service
    if service:
        service.stop()
        service = None

# ---------- App ----------

class YouTubeMP3App(App):
    def build(self):
        # explicitly load main.kv (keep file name main.kv)
        kv_path = os.path.join(os.path.dirname(__file__), "main.kv")
        if os.path.exists(kv_path):
            Builder.load_file(kv_path)
        else:
            Logger.warning("main.kv not found next to main.py; make sure main.kv exists in the same folder")

        root = Root()
        root.schedule_cleanup()
        return root

    def on_stop(self):
        try:
            if hasattr(self, 'root') and self.root:
                self.root.stop_playback()
                self.root.cleanup_all_temp_files()
        except Exception:
            pass

if __name__ == "__main__":
    YouTubeMP3App().run()

# Example: call this in your play logic
if ANDROID:
    start_music_service()

def play_in_background(self, file_path):
    # Write command to a file
    cmd_file = os.path.join(get_download_root(), "service_cmd.txt")
    with open(cmd_file, "w") as f:
        f.write(f"PLAY|{file_path}")
    if ANDROID:
        start_music_service()

def pause_in_background(self):
    cmd_file = os.path.join(get_download_root(), "service_cmd.txt")
    with open(cmd_file, "w") as f:
        f.write("PAUSE")

def stop_in_background(self):
    cmd_file = os.path.join(get_download_root(), "service_cmd.txt")
    with open(cmd_file, "w") as f:
        f.write("STOP")
    if ANDROID:
        stop_music_service()

import os
import sys
import threading
import traceback
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
from kivy.uix.label import Label
from kivy.uix.textinput import TextInput
from kivy.uix.button import Button
from kivy.clock import Clock
from kivy.metrics import dp
from kivy.logger import Logger

# yt-dlp core
from yt_dlp import YoutubeDL

# Custom logger for yt-dlp -> Kivy Logger
class YDLLogger:
    def debug(self, msg):
        # yt-dlp can be very chatty at debug level; keep as info for visibility
        try:
            Logger.info(f"yt_dlp: {msg}")
        except Exception:
            pass

    def warning(self, msg):
        try:
            Logger.warning(f"yt_dlp: {msg}")
        except Exception:
            pass

    def error(self, msg):
        try:
            Logger.error(f"yt_dlp: {msg}")
        except Exception:
            pass

# Android-specific (safe to import; guarded at runtime)
try:
    from android.permissions import request_permissions, Permission, check_permission
    from jnius import autoclass
    ANDROID = True
except Exception:
    ANDROID = False
    # Mock classes for non-Android builds
    class MockPermission:
        INTERNET = "android.permission.INTERNET"
        WRITE_EXTERNAL_STORAGE = "android.permission.WRITE_EXTERNAL_STORAGE"
        READ_EXTERNAL_STORAGE = "android.permission.READ_EXTERNAL_STORAGE"
    
    class MockAutoclass:
        def __call__(self, class_name):
            class MockClass:
                @staticmethod
                def getExternalStoragePublicDirectory(directory):
                    class MockPath:
                        def getAbsolutePath(self):
                            return "/tmp/mock_music"
                    return MockPath()
            return MockClass()
    
    Permission = MockPermission()
    autoclass = MockAutoclass()

# ---------- Paths / Storage helpers ----------

def get_download_root() -> str:
    """
    Returns a writable folder:
    - On Android: /storage/emulated/0/Download
    - Elsewhere:  ./downloads
    """
    if ANDROID:
        try:
            Environment = autoclass('android.os.Environment')
            downloads_dir_obj = Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_DOWNLOADS)
            if downloads_dir_obj is not None:
                target = downloads_dir_obj.getAbsolutePath()
            else:
                # Fallback to external storage root
                storage_root_obj = Environment.getExternalStorageDirectory()
                storage_root = storage_root_obj.getAbsolutePath() if storage_root_obj else "/sdcard"
                target = os.path.join(storage_root, "Download")
        except Exception as e:
            Logger.error(f"get_download_root: Error resolving Android Downloads directory: {e}")
            target = "/sdcard/Download"
    else:
        target = os.path.join(os.path.abspath(os.getcwd()), "downloads")

    Logger.info(f"get_download_root: Using directory: {target}")
    try:
        os.makedirs(target, exist_ok=True)
    except Exception as e:
        Logger.error(f"get_download_root: Cannot create directory {target}: {e}")
    return target


def ensure_android_permissions():
    """
    Ask for storage + internet permissions at runtime on Android.
    """
    if not ANDROID:
        Logger.info("ensure_android_permissions: Not on Android, skipping")
        return
    
    Logger.info("ensure_android_permissions: Checking Android permissions")
    perms = [Permission.INTERNET, Permission.WRITE_EXTERNAL_STORAGE, Permission.READ_EXTERNAL_STORAGE]
    missing = [p for p in perms if not check_permission(p)]
    
    if missing:
        Logger.warning(f"ensure_android_permissions: Missing permissions: {missing}")
        request_permissions(perms)
    else:
        Logger.info("ensure_android_permissions: All permissions granted")


# ---------- yt-dlp helpers ----------

@dataclass
class DownloadTask:
    url: str
    output_dir: str
    is_playlist: bool
    # def __init__(self, url, output_dir, is_playlist):
    #     self.output_dir = output_dir
    #     self.is_playlist = is_playlist
    #     if is_playlist==True:
    #         self.urls = extract_playlist_urls(url)
    #     else:
    #         self.urls = [url]



def is_playlist_url(url: str) -> bool:
    return "playlist" in url.lower() or "list=" in url.lower()


def build_ydl_opts(output_dir: str, update_status, update_progress, single_video=True):
    """
    yt-dlp options configured to:
      - grab bestaudio
      - extract to MP3 via FFmpeg (non-Android)
      - write into output_dir
    """
    Logger.info(f"build_ydl_opts: Creating options for output_dir: {output_dir}")
    
    # Validate output_dir
    if not output_dir or not isinstance(output_dir, str):
        Logger.error(f"build_ydl_opts: Invalid output_dir: {output_dir}")
        raise ValueError(f"Invalid output directory: {output_dir}")
    
    # Ensure output directory exists
    try:
        os.makedirs(output_dir, exist_ok=True)
    except Exception as e:
        Logger.error(f"build_ydl_opts: Cannot create output directory {output_dir}: {e}")
        raise
    
    opts = {
        "format": "bestaudio/best",
        "outtmpl": os.path.join(output_dir, "%(title)s.%(ext)s"),
        "noplaylist": single_video,
        "ignoreerrors": True,
        "progress_hooks": [
            lambda d: progress_hook(d, update_status, update_progress)
        ],
        # Route logs through our logger to avoid file-like writes
        "logger": YDLLogger(),
        # Silence direct printing to stdout/stderr
        "quiet": True,
        "no_warnings": True,
        # Avoid carriage-return progress that some terminals mishandle
        "progress_with_newline": True,
        # Make output deterministic when metadata missing
        "outtmpl_na_placeholder": "unknown",
    }
    
    # Only add FFmpeg postprocessor off-Android
    if not ANDROID:
        opts["postprocessors"] = [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            }
        ]
    else:
        Logger.warning("build_ydl_opts: On Android, skipping FFmpeg postprocessor")
    
    return opts


def progress_hook(d, update_status, update_progress):
    # d['status'] in {'downloading','finished','error'}
    status = d.get("status", "")
    if status == "downloading":
        total = d.get("total_bytes") or d.get("total_bytes_estimate")
        downloaded = d.get("downloaded_bytes", 0)
        if total:
            pct = int(downloaded * 100 / total)
            update_progress(pct)
        speed = d.get("speed")
        eta = d.get("eta")
        if speed and eta:
            update_status(f"Downloading… {pct if total else ''}%  |  {int(speed/1024)} KB/s  |  ETA {eta}s")
        else:
            update_status("Downloading…")
    elif status == "finished":
        update_status("Converting to MP3…")
        update_progress(100)


def extract_playlist_urls(playlist_url: str) -> List[str]:
    """
    Extract all video URLs from a playlist without downloading media.
    """
    opts = {"quiet": True, "extract_flat": True, "skip_download": True}
    urls = []
    with YoutubeDL(opts) as ydl:
        info = ydl.extract_info(playlist_url, download=False)
        entries = info.get("entries") or []
        for e in entries:
            vid = e.get("url")
            if vid:
                urls.append(f"https://www.youtube.com/watch?v={vid}")
    return urls


# ---------- Kivy UI ----------

class Root(BoxLayout):
    def __init__(self, **kwargs):
        super().__init__(orientation="vertical", padding=dp(14), spacing=dp(10), **kwargs)
        
        # Set position hint to anchor content to top
        self.pos_hint = {'top': 1}

        self.title = Label(text="YouTube to MP3 Downloader", font_size="20sp", size_hint=(1, None), height=dp(32))
        self.add_widget(self.title)

        self.input = TextInput(hint_text="Paste a YouTube Video or Playlist URL", multiline=False,
                               size_hint=(1, None), height=dp(44))
        self.add_widget(self.input)

        self.btn_row = BoxLayout(size_hint=(1, None), height=dp(44), spacing=dp(10))
        self.download_btn = Button(text="Download MP3")
        self.download_btn.bind(on_press=self.on_download)
        self.btn_row.add_widget(self.download_btn)

        self.add_widget(self.btn_row)

        self.status = Label(text="", size_hint=(1, None), height=dp(26))
        self.add_widget(self.status)

        self.progress = Label(text="", size_hint=(1, None), height=dp(24))
        self.add_widget(self.progress)

        # Add spacer to push content to top
        self.spacer = Label(text="", size_hint=(1, 1))
        self.add_widget(self.spacer)

        # keep a reference to worker thread
        self._worker = None

    # UI-safe updaters
    def set_status(self, msg: str):
        Clock.schedule_once(lambda *_: setattr(self.status, "text", msg))

    def set_progress(self, percent: int):
        Clock.schedule_once(lambda *_: setattr(self.progress, "text", f"Progress: {percent}%"))

    def on_download(self, *_):
        url = (self.input.text or "").strip()
        if not url:
            self.set_status("❌ Please paste a YouTube URL first.")
            return

        ensure_android_permissions()

        output_dir = get_download_root()
        task = DownloadTask(url=url, output_dir=output_dir, is_playlist=is_playlist_url(url))

        if self._worker and self._worker.is_alive():
            self.set_status("⚠️ A download is already running. Please wait…")
            return

        self.set_status("Starting…")
        self.set_progress(0)
        self._worker = threading.Thread(target=self._run_task, args=(task,), daemon=True)
        self._worker.start()

    # heavy work -> background thread
    def _run_task(self, task: DownloadTask):
        def update_status(msg): self.set_status(msg)
        def update_progress(p): self.set_progress(p)

        try:
            Logger.info(f"DownloadTask: Starting task for URL: {task.url}")
            Logger.info(f"DownloadTask: Output directory: {task.output_dir}")
            Logger.info(f"DownloadTask: Is playlist: {task.is_playlist}")
            if task.is_playlist:
                update_status("Fetching playlist…")
                urls = extract_playlist_urls(task.url)
                if not urls:
                    update_status("❌ No videos found in playlist.")
                    return
                count = len(urls)
                update_status(f"Found {count} videos. Downloading…")
                # Download each video to MP3
                for idx, vurl in enumerate(urls, start=1):
                    update_status(f"[{idx}/{count}] Downloading…")
                    ydl_opts = build_ydl_opts(task.output_dir, update_status, update_progress, single_video=True)
                    with YoutubeDL(ydl_opts) as ydl:
                        ydl.download([vurl])
                update_status(f"✅ Done. Saved to: {task.output_dir}")
            else:
                ydl_opts = build_ydl_opts(task.output_dir, update_status, update_progress, single_video=True)
                with YoutubeDL(ydl_opts) as ydl:
                    ydl.download([task.url])
                update_status(f"✅ Done. Saved to: {task.output_dir}")
        except Exception as e:
            Logger.error(f"DownloadTask: Error occurred: {e}")
            Logger.error(f"DownloadTask: Traceback: {traceback.format_exc()}")
            update_status(f"❌ Error: {e}")


class YouTubeMP3App(App):
    def build(self):
        try:
            Logger.info("YouTubeMP3App: Starting app initialization")
            Logger.info(f"Python version: {sys.version}")
            Logger.info(f"Platform: {sys.platform}")
            Logger.info(f"Android detected: {ANDROID}")
            
            root = Root()
            Logger.info("YouTubeMP3App: Root widget created successfully")
            return root
        except Exception as e:
            Logger.error(f"YouTubeMP3App: Error in build(): {e}")
            Logger.error(f"YouTubeMP3App: Traceback: {traceback.format_exc()}")
            raise


if __name__ == "__main__":
    YouTubeMP3App().run()

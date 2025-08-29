import os
from yt_dlp import YoutubeDL
from kivy.app import App
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.label import Label
from kivy.uix.textinput import TextInput
from kivy.uix.button import Button


def download_youtube_mp3(url, output_path="downloads"):
    """Download a single YouTube video as MP3"""
    os.makedirs(output_path, exist_ok=True)

    ydl_opts = {
        'format': 'bestaudio/best',
        'outtmpl': os.path.join(output_path, '%(title)s.%(ext)s'),
        'postprocessors': [
            {
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }
        ],
        'noplaylist': True,
    }

    with YoutubeDL(ydl_opts) as ydl:
        ydl.download([url])


class YouTubeDownloader(BoxLayout):
    def __init__(self, **kwargs):
        super().__init__(orientation="vertical", **kwargs)

        self.add_widget(Label(text="Enter YouTube Video or Playlist URL:", size_hint=(1, 0.1)))

        self.url_input = TextInput(multiline=False, size_hint=(1, 0.1))
        self.add_widget(self.url_input)

        self.status_label = Label(text="", size_hint=(1, 0.1))
        self.add_widget(self.status_label)

        self.download_button = Button(text="Download MP3", size_hint=(1, 0.2))
        self.download_button.bind(on_press=self.start_download)
        self.add_widget(self.download_button)

    def start_download(self, instance):
        url = self.url_input.text.strip()
        if not url:
            self.status_label.text = "❌ Please enter a URL"
            return

        try:
            self.status_label.text = "⏳ Downloading..."
            download_youtube_mp3(url)
            self.status_label.text = "✅ Download completed!"
        except Exception as e:
            self.status_label.text = f"❌ Error: {e}"


class YouTubeApp(App):
    def build(self):
        return YouTubeDownloader()


if __name__ == "__main__":
    YouTubeApp().run()

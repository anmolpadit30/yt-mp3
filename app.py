import os
from yt_dlp import YoutubeDL

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
        'noplaylist': True,   # avoid accidentally grabbing whole playlist
    }

    with YoutubeDL(ydl_opts) as ydl:
        ydl.download([url])
    print("✅ Download completed!")

def get_playlist_urls(playlist_url):
    """Return a list of all video URLs in a YouTube playlist"""
    ydl_opts = {'quiet': True, 'extract_flat': True, 'skip_download': True}
    urls = []
    with YoutubeDL(ydl_opts) as ydl:
        info_dict = ydl.extract_info(playlist_url, download=False)
        if 'entries' in info_dict:
            for entry in info_dict['entries']:
                if entry and 'url' in entry:
                    # Construct full URL
                    urls.append(f"https://www.youtube.com/watch?v={entry['url']}")
    return urls


if __name__ == "__main__":
    link = input("Enter YouTube video or playlist URL: ").strip()
    if "playlist" in link.lower():  # crude check for playlist
        urls = get_playlist_urls(link)
        print(f"\nFound {len(urls)} videos in playlist:\n")
        for u in urls:
            print(u)
        # Example: download first video
        if urls:
            urlArray = str(urls[0]).split("watch?v=")
            print('downloading=====>',urlArray[1]+'watch?v='+urlArray[2])
            download_youtube_mp3(urlArray[1]+'watch?v='+urlArray[2])
    else:
        try:
            download_youtube_mp3(link)
        except Exception as e:
            print(f"❌ Failed: {e}")

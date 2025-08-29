# YouTube to MP3 Downloader

A Python application for downloading YouTube videos as MP3 files with both GUI and command-line interfaces.

## Features

- 🎵 Download YouTube videos as high-quality MP3 files
- 🖥️ **GUI Version**: User-friendly Kivy-based interface (`main.py`)
- 💻 **CLI Version**: Command-line interface (`app.py`)
- 📱 **Mobile Support**: Build Android APK using Buildozer
- 📂 **Playlist Support**: Extract and download from playlists
- ⚡ **Fast Downloads**: Uses yt-dlp for reliable video extraction
- 🎚️ **Quality Control**: 192 kbps MP3 output

## Requirements

- Python 3.7+
- FFmpeg (for audio conversion)
- Windows/Linux/macOS support

## Installation

### 1. Clone the Repository
```bash
git clone <your-repo-url>
cd yt-mp3
```

### 2. Create Virtual Environment
```bash
python -m venv myenv
# Windows
myenv\Scripts\activate
# Linux/macOS
source myenv/bin/activate
```

### 3. Install Dependencies
```bash
pip install -r requirements.txt
```

### 4. Install FFmpeg
- **Windows**: Download from [FFmpeg official site](https://ffmpeg.org/download.html) and add to PATH
- **Linux**: `sudo apt install ffmpeg` (Ubuntu/Debian) or `sudo yum install ffmpeg` (CentOS/RHEL)
- **macOS**: `brew install ffmpeg`

## Usage

### GUI Version (Recommended)
```bash
python main.py
```
- Enter YouTube video or playlist URL
- Click "Download MP3"
- Files will be saved in the `downloads/` folder

### Command Line Version
```bash
python app.py
```
- Enter URL when prompted
- For playlists: automatically detects and shows available videos
- Downloads are saved to `downloads/` folder

### Mobile App (Android)
Build an Android APK using Buildozer:
```bash
buildozer android debug
```

## Project Structure

```
yt-mp3/
├── main.py              # GUI version (Kivy)
├── app.py               # CLI version
├── requirements.txt     # Python dependencies
├── buildozer.spec       # Android build configuration
├── downloads/           # Downloaded MP3 files (created automatically)
├── myenv/              # Virtual environment (ignored by git)
└── README.md           # This file
```

## Key Dependencies

- **yt-dlp**: YouTube video downloading and metadata extraction
- **Kivy**: Cross-platform GUI framework
- **ffmpeg-python**: Audio format conversion
- **Buildozer**: Android app building

## Configuration

### Audio Quality
Edit the `preferredquality` setting in both files:
```python
'preferredquality': '192',  # Change to '128', '256', '320', etc.
```

### Output Directory
Change the default download folder:
```python
output_path = "your_custom_folder"  # Default: "downloads"
```

## Troubleshooting

### Common Issues

1. **FFmpeg not found**
   - Ensure FFmpeg is installed and added to your system PATH
   - Test with: `ffmpeg -version`

2. **Download fails**
   - Check if the YouTube URL is valid and accessible
   - Some videos may be geo-restricted or have download limitations

3. **GUI doesn't start**
   - Ensure all Kivy dependencies are installed
   - Try running: `pip install --upgrade kivy[base]`

4. **Android build fails**
   - Check Buildozer requirements: `buildozer android debug -v`
   - Ensure Android SDK and NDK are properly configured

### Error Messages

- **"❌ Please enter a URL"**: Enter a valid YouTube URL
- **"❌ Error: [details]"**: Check internet connection and URL validity
- **"FFmpeg not found"**: Install FFmpeg and add to PATH

## Legal Notice

⚠️ **Important**: This tool is for personal use only. Respect YouTube's Terms of Service and copyright laws. Only download content you have permission to download or that is in the public domain.

## Contributing

1. Fork the repository
2. Create a feature branch: `git checkout -b feature-name`
3. Make your changes and test thoroughly
4. Submit a pull request

## License

This project is for educational purposes. Please ensure compliance with local laws and YouTube's Terms of Service when using this software.

## Support

If you encounter issues:
1. Check the troubleshooting section above
2. Ensure all dependencies are properly installed
3. Verify FFmpeg installation
4. Check that your Python version is 3.7+

---

**Enjoy your music! 🎵**

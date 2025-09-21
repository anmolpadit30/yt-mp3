# service.py - background playback service for Android
import os
import sys
import time
import threading

from jnius import autoclass, cast
import vlc

# Android imports
PythonService = autoclass('org.kivy.android.PythonService')
Notification = autoclass('android.app.Notification')
NotificationManager = autoclass('android.app.NotificationManager')
PendingIntent = autoclass('android.app.PendingIntent')
Intent = autoclass('android.content.Intent')
Context = autoclass('android.content.Context')

# Globals
player = None
is_playing = False

def start_foreground_service(service, title="YouTube MP3", text="Playing in background"):
    """Show persistent notification to keep service alive"""
    notification = Notification.Builder(service) \
        .setContentTitle(title) \
        .setContentText(text) \
        .setSmallIcon(service.getApplicationInfo().icon) \
        .build()

    service.startForeground(1, notification)

def play_audio(file_path):
    global player, is_playing
    if player:
        player.stop()
    player = vlc.MediaPlayer(file_path)
    player.play()
    is_playing = True

def pause_audio():
    global player, is_playing
    if player:
        player.pause()
        is_playing = False

def stop_audio():
    global player, is_playing
    if player:
        player.stop()
        player.release()
        player = None
        is_playing = False

def run_service():
    service = PythonService.mService
    start_foreground_service(service)

    cmd_file = os.path.join(os.getenv("EXTERNAL_STORAGE", "/sdcard"), "Download", "service_cmd.txt")
    last_cmd = ""
    while True:
        if os.path.exists(cmd_file):
            with open(cmd_file, "r") as f:
                cmd = f.read().strip()
            if cmd != last_cmd:
                last_cmd = cmd
                if cmd.startswith("PLAY|"):
                    file_path = cmd.split("|", 1)[1]
                    play_audio(file_path)
                elif cmd == "PAUSE":
                    pause_audio()
                elif cmd == "STOP":
                    stop_audio()
        time.sleep(1)

if __name__ == "__main__":
    run_service()

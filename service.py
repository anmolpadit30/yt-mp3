# service.py - background playback service for Android
import os
import time
import json
from jnius import autoclass
from android_player import AndroidPlayer
from kivy.logger import Logger

# Android imports
PythonService = autoclass('org.kivy.android.PythonService')
Notification = autoclass('android.app.Notification')

# Globals
player = None

def start_foreground_service(service, title="YouTube MP3", text="Playing in background"):
    """Show persistent notification to keep service alive"""
    notification = Notification.Builder(service) \
        .setContentTitle(title) \
        .setContentText(text) \
        .setSmallIcon(service.getApplicationInfo().icon) \
        .build()

    service.startForeground(1, notification)

def run_service():
    global player
    service = PythonService.mService
    start_foreground_service(service)

    app_files_dir = service.getApplicationContext().getExternalFilesDir(None).getAbsolutePath()
    cmd_file = os.path.join(app_files_dir, "service_cmd.txt")
    status_file = os.path.join(app_files_dir, "service_status.json")

    def on_completion():
        Logger.info("Service: Track completed.")
        with open(status_file, "w") as f:
            json.dump({"completed": True, "file_path": player.current_file_path}, f)
        os.utime(status_file, None)

    player = AndroidPlayer(on_completion_callback=on_completion)
    
    last_mtime = 0
    
    while True:
        # Check for commands
        if os.path.exists(cmd_file):
            try:
                current_mtime = os.path.getmtime(cmd_file)
                if current_mtime > last_mtime:
                    last_mtime = current_mtime
                    with open(cmd_file, "r") as f:
                        cmd = f.read().strip()
                    
                    Logger.info(f"Service: Received command: {cmd}")
                    
                    if cmd.startswith("PLAY|"):
                        file_path = cmd.split("|", 1)[1]
                        player.play(file_path)
                    elif cmd == "PAUSE":
                        player.pause()
                    elif cmd == "RESUME":
                        player.resume()
                    elif cmd == "STOP":
                        player.stop()
                        if os.path.exists(status_file):
                            os.remove(status_file)
                        service.stopSelf()
                        break # Exit loop
                    elif cmd.startswith("SEEK|"):
                        position_ms = float(cmd.split("|")[1]) * 1000
                        player.seek(position_ms)
            except Exception as e:
                Logger.error(f"Service: Error processing command file: {e}")

        # Write status
        if player and player.player:
            try:
                status = {
                    "is_playing": player.is_playing(),
                    "position": player.get_position(),
                    "duration": player.get_duration(),
                    "file_path": player.current_file_path,
                    "completed": False
                }
                with open(status_file, "w") as f:
                    json.dump(status, f)
            except Exception as e:
                if player and not player.player:
                    pass
                else:
                    Logger.error(f"Service: Error writing status file: {e}")

        time.sleep(0.5)

if __name__ == "__main__":
    run_service()

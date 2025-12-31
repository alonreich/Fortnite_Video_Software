import sys
import os
import vlc
from PyQt5.QtWidgets import QFrame

class Player:
    def __init__(self, base_dir, parent=None):
        vlc_args = ['--no-xlib','--no-video-title-show','--no-plugins-cache','--file-caching=300','--verbose=-1']
        if os.name == 'nt':
            os.environ['VLC_PLUGIN_PATH'] = os.path.join(base_dir, "binaries", "plugins")
        self.vlc_instance = vlc.Instance(vlc_args)
        self.media_player = self.vlc_instance.media_player_new()
        self.video_frame = QFrame(parent)
        self.video_frame.setStyleSheet("background-color: #000;")
        if sys.platform.startswith('win'):
            self.media_player.set_hwnd(self.video_frame.winId())
        elif sys.platform.startswith('darwin'):
            self.media_player.set_nsobject(int(self.video_frame.winId()))
        else:
            self.media_player.set_xwindow(self.video_frame.winId())
    def set_media(self, file_path):
        media = self.vlc_instance.media_new(file_path)
        self.media_player.set_media(media)
    def play(self):
        self.media_player.play()
    def pause(self):
        self.media_player.pause()
    def stop(self):
        self.media_player.stop()
    def seek(self, time_ms):
        self.media_player.set_time(int(time_ms))
    def get_time(self):
        return self.media_player.get_time()
    def is_playing(self):
        return self.media_player.is_playing()
    def set_rate(self, rate):
        self.media_player.set_rate(rate)
    def set_volume(self, volume):
        self.media_player.audio_set_volume(int(volume))

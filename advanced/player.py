import sys
import os
import vlc
from PyQt5.QtWidgets import QFrame
class Player:
    def __init__(self, base_dir, parent=None):
        vlc_args=['--no-xlib','--no-video-title-show','--no-plugins-cache','--file-caching=300','--verbose=-1']
        if os.name=='nt':
            os.environ['VLC_PLUGIN_PATH']=os.path.join(base_dir,"binaries","plugins")
        self.vlc_instance=vlc.Instance(vlc_args)
        self.video_player=self.vlc_instance.media_player_new()
        self.audio_players={}
        self.active_video=None
        self.active_audio={}
        self.video_frame=QFrame(parent)
        self.video_frame.setStyleSheet("background-color: #000;")
        if sys.platform.startswith('win'):
            self.video_player.set_hwnd(self.video_frame.winId())
        elif sys.platform.startswith('darwin'):
            self.video_player.set_nsobject(int(self.video_frame.winId()))
        else:
            self.video_player.set_xwindow(self.video_frame.winId())
    def ensure_audio_player(self, key):
        if key not in self.audio_players:
            p=self.vlc_instance.media_player_new()
            self.audio_players[key]=p
        return self.audio_players[key]
    def set_media(self, file_path):
        self.set_video_media(file_path)
    def set_video_media(self, file_path):
        self.active_video=file_path
        media=self.vlc_instance.media_new(file_path) if file_path else None
        self.video_player.set_media(media)
    def set_audio_media(self, key, file_path):
        self.active_audio[key]=file_path
        p=self.ensure_audio_player(key)
        media=self.vlc_instance.media_new(file_path) if file_path else None
        p.set_media(media)
    def play(self):
        if self.active_video:
            self.video_player.play()
        for k,p in self.audio_players.items():
            if self.active_audio.get(k):
                p.play()
    def pause(self):
        self.video_player.pause()
        for p in self.audio_players.values():
            p.pause()
    def stop(self):
        self.video_player.stop()
        for p in self.audio_players.values():
            p.stop()
    def seek(self, time_ms):
        self.video_player.set_time(int(time_ms))
    def seek_audio(self, key, time_ms):
        p=self.ensure_audio_player(key)
        p.set_time(int(time_ms))
    def get_time(self):
        t=self.video_player.get_time()
        if t>=0 and self.active_video:
            return t
        best=-1
        for k,p in self.audio_players.items():
            if self.active_audio.get(k):
                pt=p.get_time()
                if pt>best:
                    best=pt
        return best
    def is_playing(self):
        if self.active_video and self.video_player.is_playing():
            return True
        for k,p in self.audio_players.items():
            if self.active_audio.get(k) and p.is_playing():
                return True
        return False
    def set_rate(self, rate):
        self.video_player.set_rate(rate)
    def set_audio_rate(self, key, rate):
        p=self.ensure_audio_player(key)
        p.set_rate(rate)
    def set_volume(self, volume):
        self.video_player.audio_set_volume(int(volume))
    def set_audio_volume(self, key, volume):
        p=self.ensure_audio_player(key)
        p.audio_set_volume(int(volume))
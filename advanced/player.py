import os
import logging
from PyQt5.QtWidgets import QFrame
os.environ["PATH"] = os.path.dirname(os.path.abspath(__file__)) + os.pathsep + os.environ["PATH"]
import mpv
class MPVPlayer(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.logger = logging.getLogger("ProEditor")
        opts = {
            "input_default_bindings": True,
            "input_vo_keyboard": True,
            "osc": True,
            "keep_open": "yes",
            "hr_seek": "yes",
            "hwdec": "auto",
            "vd_lavc_threads": 4
        }
        try:
            self.mpv = mpv.MPV(wid=str(int(self.winId())), **opts)
        except Exception as e:
            self.logger.critical(f"MPV Init Failed: {e}")
            raise

    def load(self, path):
        if not os.path.exists(path):
            self.logger.error(f"File not found: {path}")
            return
        self.mpv.play(path)
        self.mpv.pause = True

    def play(self): self.mpv.pause = False
    def pause(self): self.mpv.pause = True
    def stop(self): self.mpv.stop()
    
    def seek(self, time_s):
        self.mpv.seek(time_s, reference="absolute", precision="exact")
    
    def get_time(self):
        t = self.mpv.time_pos
        return t if t is not None else 0.0

    def is_playing(self):
        return not self.mpv.pause

    def set_speed(self, speed):
        self.mpv.speed = float(speed)

    def set_volume(self, vol):
        self.mpv.volume = int(vol)

    def apply_crop(self, crop_dict):
        if crop_dict:
            vf_str = f"crop={crop_dict['w']}:{crop_dict['h']}:{crop_dict['x']}:{crop_dict['y']}"
            self.mpv.vf = vf_str
        else:
            self.mpv.vf = ""

    def destroy(self):
        self.mpv.terminate()

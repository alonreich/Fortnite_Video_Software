from PyQt5.QtWidgets import QScrollArea, QVBoxLayout, QWidget
from PyQt5.QtCore import Qt, pyqtSignal
from tracks import TrackWidget
class TimelineWidget(QScrollArea):
    selection_changed = pyqtSignal(list)
    def __init__(self, parent_main):
        super().__init__()
        self.main = parent_main
        self.setWidgetResizable(True)
        self.container = QWidget()
        self.lay = QVBoxLayout(self.container)
        self.setWidget(self.container)
        self.tracks = []
        self.init_tracks()
    def init_tracks(self):
        for i in range(4): self.add_track()
    def add_track(self):
        t = TrackWidget(len(self.tracks), self)
        self.lay.addWidget(t)
        self.tracks.append(t)
    def add_clip_to_track(self, path):
        self.tracks[0].add_clip(path, 0.0)
    def get_state(self):
        return [t.get_state() for t in self.tracks]
    def set_state(self, state):
        pass
    def select_region(self, rect_px):
        pass

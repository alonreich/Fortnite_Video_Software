import os
import subprocess
import uuid
import logging
from PyQt5.QtWidgets import QScrollArea,QWidget,QVBoxLayout,QFrame,QApplication
from PyQt5.QtCore import Qt,pyqtSignal,QRect,QMimeData,QPoint,QTimer
from PyQt5.QtGui import QPainter,QColor,QPen,QBrush,QDrag

class Clip:
    def __init__(self, file_path, duration=0.0, start_time=0.0):
        self.uid = str(uuid.uuid4())
        self.file_path = file_path
        self.duration = duration
        self.start_time = start_time
        self.source_in = 0.0
        self.speed = 1.0
        self.volume = 100
    def to_dict(self):
        return {'uid': self.uid,'file_path': self.file_path,'duration': self.duration,'start_time': self.start_time,'source_in': self.source_in,'speed': self.speed,'volume': self.volume}
    @staticmethod
    def from_dict(data):
        c = Clip(data['file_path'], data['duration'], data['start_time'])
        c.uid = data['uid']
        c.source_in = data['source_in']
        c.speed = data['speed']
        c.volume = data['volume']
        return c

class RulerWidget(QWidget):
    seek_requested = pyqtSignal(float)
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(35)
        self.playhead_pos_px = 0
        self.pixels_per_second = 50
    def set_view_width(self, width):
        self.setMinimumWidth(width)
        self.update()
    def set_playhead_pos(self, px):
        self.playhead_pos_px = px
        self.update()
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#2c3e50"))
        painter.setPen(QPen(QColor(150, 150, 150), 1))
        pixels_per_tick = self.pixels_per_second
        if pixels_per_tick > 0:
            num_ticks = int(self.width() / pixels_per_tick)
            for i in range(num_ticks):
                x = int(i * pixels_per_tick)
                h = 10 if i % 5 == 0 else 5
                painter.drawLine(x, self.height() - h, x, self.height())
                if i % 5 == 0:
                    painter.drawText(x + 3, self.height() - 10, f"{i}s")
        painter.setPen(QPen(QColor("#e74c3c"), 2))
        painter.drawLine(int(self.playhead_pos_px), 0, int(self.playhead_pos_px), self.height())
    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._emit_seek(event.pos())
    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.LeftButton:
            self._emit_seek(event.pos())
    def _emit_seek(self, pos):
        time_sec = max(0, pos.x() / self.pixels_per_second)
        self.seek_requested.emit(time_sec)

class LayerWidget(QFrame):
    clip_selected = pyqtSignal(object)
    clip_modified = pyqtSignal()
    internal_clip_dropped = pyqtSignal(str, int, float)
    seek_requested = pyqtSignal(float)
    def __init__(self, layer_number, base_dir, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.layer_number = layer_number
        self.base_dir = base_dir
        self.clips = []
        self.selected_clip = None
        self.logger = logging.getLogger("Advanced_Video_Editor")
        self.setFrameShape(QFrame.StyledPanel)
        self.setFixedHeight(40)
        self.setStyleSheet(f"background-color: {'#34495e' if layer_number % 2 == 0 else '#2c3e50'}; border-bottom: 1px solid #1a252f;")
        self.drag_start_pos = QPoint()
        self.dash_offset = 0
    def get_clip_rect(self, clip):
        x = int(clip.start_time * TimelineView.PIXELS_PER_SECOND)
        w = int(clip.duration * TimelineView.PIXELS_PER_SECOND)
        if w < 1:
            w = 1
        return QRect(x, 2, w, self.height() - 4)
    def animate_ants(self):
        self.dash_offset = (self.dash_offset - 1) % 8
        self.update()
    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.drag_start_pos = event.pos()
            clicked_clip = None
            for clip in reversed(self.clips):
                if self.get_clip_rect(clip).contains(event.pos()):
                    clicked_clip = clip
                    break
            if self.selected_clip != clicked_clip:
                self.selected_clip = clicked_clip
                self.clip_selected.emit(self.selected_clip)
                self.update()
            if not clicked_clip:
                time_sec = max(0, event.pos().x() / TimelineView.PIXELS_PER_SECOND)
                self.seek_requested.emit(time_sec)
        super().mousePressEvent(event)
    def mouseMoveEvent(self, event):
        if not (event.buttons() & Qt.LeftButton):
            return
        if not self.selected_clip:
            return
        if (event.pos() - self.drag_start_pos).manhattanLength() < QApplication.startDragDistance():
            return
        drag = QDrag(self)
        mime_data = QMimeData()
        mime_data.setData("application/x-advanced-clip", self.selected_clip.uid.encode('utf-8'))
        drag.setMimeData(mime_data)
        rect = self.get_clip_rect(self.selected_clip)
        pixmap = self.grab(rect)
        drag.setPixmap(pixmap)
        drag.setHotSpot(event.pos() - rect.topLeft())
        drag.exec_(Qt.MoveAction)
    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls() or event.mimeData().hasFormat("application/x-advanced-clip"):
            event.accept()
        else:
            event.ignore()
    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls() or event.mimeData().hasFormat("application/x-advanced-clip"):
            event.accept()
        else:
            event.ignore()
    def dropEvent(self, event):
        if event.mimeData().hasFormat("application/x-advanced-clip"):
            event.accept()
            uid = event.mimeData().data("application/x-advanced-clip").data().decode('utf-8')
            drop_x = event.pos().x()
            new_start_time = max(0.0, drop_x / TimelineView.PIXELS_PER_SECOND)
            self.internal_clip_dropped.emit(uid, self.layer_number, new_start_time)
        elif event.mimeData().hasUrls():
            event.accept()
            files_to_load = []
            for url in event.mimeData().urls():
                file_path = url.toLocalFile()
                if os.path.isfile(file_path):
                    ext = file_path.lower()
                    if ext.endswith(('.mp4', '.mov', '.mkv', '.avi', '.mp3', '.wav', '.png', '.jpg')):
                        files_to_load.append(file_path)
            if files_to_load:
                for f in files_to_load:
                    self.logger.info(f"Dropped file: {f} on Layer {self.layer_number}")
                    duration = self.run_probe_sync(f)
                    self.add_clip(f, duration)
    def run_probe_sync(self, file_path):
        ffprobe_exe = os.path.join(self.base_dir, 'binaries', 'ffprobe.exe')
        duration = 15.0
        if not os.path.exists(ffprobe_exe):
            return duration
        try:
            cmd = [ffprobe_exe, "-v", "error", "-show_entries","format=duration", "-of", "default=noprint_wrappers=1:nokey=1", file_path]
            startupinfo = None
            if os.name == 'nt':
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            result = subprocess.run(cmd, text=True, capture_output=True, timeout=2, startupinfo=startupinfo)
            if result.returncode == 0:
                duration = float(result.stdout.strip())
        except Exception:
            pass
        return duration
    def add_clip(self, file_path, duration):
        start_time = 0.0
        if self.clips:
            last = max(self.clips, key=lambda c: c.start_time + c.duration)
            start_time = last.start_time + last.duration
        clip = Clip(file_path, duration, start_time)
        self.clips.append(clip)
        self.update()
        self.clip_modified.emit()
        self.logger.info(f"Added clip: {os.path.basename(file_path)} on Layer {self.layer_number}")
    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        for clip in self.clips:
            rect = self.get_clip_rect(clip)
            if clip == self.selected_clip:
                fill_color = QColor("#3498db")
                pen = QPen(QColor("#00008b"), 2)
                pen.setStyle(Qt.CustomDashLine)
                pen.setDashPattern([3, 3])
                pen.setDashOffset(self.dash_offset)
                width = 2
            else:
                fill_color = QColor("#2980b9")
                pen = QPen(QColor("#1abc9c"), 1)
                width = 1
            painter.setBrush(QBrush(fill_color))
            painter.setPen(pen)
            painter.drawRoundedRect(rect, 4, 4)
            painter.setPen(QColor("#ffffff"))
            fname = os.path.basename(clip.file_path)
            if rect.width() > 20:
                info = f"{fname}"
                painter.drawText(rect.adjusted(5, 0, -5, 0), Qt.AlignVCenter | Qt.AlignLeft, info)

class TimelineView(QScrollArea):
    PIXELS_PER_SECOND = 50
    clip_selected_on_timeline = pyqtSignal(object)
    seek_requested = pyqtSignal(float)
    pre_modification = pyqtSignal()
    def __init__(self, base_dir, parent=None):
        super().__init__(parent)
        self.base_dir = base_dir
        self.setWidgetResizable(True)
        self.container = QWidget()
        self.container.setStyleSheet("background-color: #2c3e50;")
        self.setWidget(self.container)
        self.main_layout = QVBoxLayout(self.container)
        self.main_layout.setSpacing(0)
        self.main_layout.setContentsMargins(0,0,0,0)
        self.ruler = RulerWidget()
        self.ruler.pixels_per_second = self.PIXELS_PER_SECOND
        self.ruler.seek_requested.connect(self.seek_requested)
        self.main_layout.addWidget(self.ruler)
        self.layers_layout = QVBoxLayout()
        self.layers_layout.setSpacing(1)
        self.main_layout.addLayout(self.layers_layout)
        self.main_layout.addStretch()
        self.layers = []
        for i in range(4):
            self.add_layer()
        self.ant_timer = QTimer(self)
        self.ant_timer.timeout.connect(self.update_ants)
        self.ant_timer.start(200)
    def update_ants(self):
        for layer in self.layers:
            if layer.selected_clip:
                layer.animate_ants()
    def add_layer(self):
        idx = len(self.layers)
        layer = LayerWidget(idx, self.base_dir)
        layer.clip_modified.connect(self.update_dimensions)
        layer.clip_modified.connect(self.notify_pre_mod)
        layer.clip_selected.connect(self.handle_selection)
        layer.internal_clip_dropped.connect(self.handle_clip_move)
        layer.seek_requested.connect(self.seek_requested)
        self.layers_layout.addWidget(layer)
        self.layers.append(layer)
    def notify_pre_mod(self):
        pass
    def handle_selection(self, clip):
        sender = self.sender()
        for layer in self.layers:
            if layer != sender:
                layer.selected_clip = None
                layer.update()
        self.clip_selected_on_timeline.emit(clip)
    def handle_clip_move(self, uid, target_layer_idx, new_time):
        self.pre_modification.emit()
        found_clip = None
        source_layer = None
        for layer in self.layers:
            for clip in layer.clips:
                if clip.uid == uid:
                    found_clip = clip
                    source_layer = layer
                    break
            if found_clip:
                break
        if found_clip and source_layer:
            source_layer.clips.remove(found_clip)
            source_layer.selected_clip = None
            source_layer.update()
            found_clip.start_time = new_time
            target_layer = self.layers[target_layer_idx]
            target_layer.clips.append(found_clip)
            target_layer.selected_clip = found_clip
            target_layer.update()
            self.clip_selected_on_timeline.emit(found_clip)
            self.update_dimensions()
    def update_dimensions(self):
        max_time = 0
        for layer in self.layers:
            for clip in layer.clips:
                end = clip.start_time + clip.duration
                if end > max_time:
                    max_time = end
        width = int(max(max_time * self.PIXELS_PER_SECOND + 200, self.width()))
        self.container.setMinimumWidth(width)
        self.ruler.set_view_width(width)
    def update_playhead(self, time_sec):
        self.ruler.set_playhead_pos(time_sec * self.PIXELS_PER_SECOND)
    def get_layer_of_clip(self, clip):
        for layer in self.layers:
            if clip in layer.clips:
                return layer
        return None
    def get_state(self):
        state = []
        for layer in self.layers:
            layer_data = [c.to_dict() for c in layer.clips]
            state.append(layer_data)
        return state
    def load_state(self, state):
        self.pre_modification.emit()
        for i, layer_data in enumerate(state):
            if i < len(self.layers):
                layer = self.layers[i]
                layer.clips = []
                for clip_data in layer_data:
                    layer.clips.append(Clip.from_dict(clip_data))
                layer.update()
        self.update_dimensions()
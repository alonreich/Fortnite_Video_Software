import os
import subprocess
import uuid
import logging
from PyQt5.QtWidgets import QScrollArea,QWidget,QVBoxLayout,QHBoxLayout,QGridLayout,QFrame,QApplication,QPushButton,QLabel,QMenu,QToolTip
from PyQt5.QtCore import Qt,pyqtSignal,QRect,QMimeData,QPoint,QTimer,QEvent,QThread
from PyQt5.QtGui import QPainter,QColor,QPen,QBrush,QDrag

class Clip:
    def __init__(self, file_path, duration=0.0, start_time=0.0):
        self.uid = str(uuid.uuid4())
        self.file_path = file_path
        self.original_duration = duration
        self.duration = duration
        self.start_time = start_time
        self.source_in = 0.0
        self.speed = 1.0
        self.volume = 100
    def to_dict(self):
        return {
            'uid': self.uid,
            'file_path': self.file_path,
            'original_duration': self.original_duration,
            'duration': self.duration,
            'start_time': self.start_time,
            'source_in': self.source_in,
            'speed': self.speed,
            'volume': self.volume
        }
    @staticmethod
    def from_dict(data):
        c = Clip(data['file_path'], data.get('original_duration', data['duration']), data['start_time'])
        c.uid = data['uid']
        c.duration = data['duration']
        c.source_in = data['source_in']
        c.speed = data['speed']
        c.volume = data['volume']
        return c

class ProbeWorker(QThread):
    finished = pyqtSignal(str, float)
    def __init__(self, file_path, ffprobe_path, parent=None):
        super().__init__(parent)
        self.file_path = file_path
        self.ffprobe_path = ffprobe_path

    def run(self):
        duration = 15.0
        if os.path.exists(self.ffprobe_path):
            try:
                cmd = [self.ffprobe_path, "-v", "error", "-show_entries","format=duration", "-of", "default=noprint_wrappers=1:nokey=1", self.file_path]
                startupinfo = None
                if os.name == 'nt':
                    startupinfo = subprocess.STARTUPINFO()
                    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                result = subprocess.run(cmd, text=True, capture_output=True, timeout=5, startupinfo=startupinfo)
                if result.returncode == 0:
                    duration = float(result.stdout.strip())
            except Exception:
                pass
        self.finished.emit(self.file_path, duration)

class RulerWidget(QWidget):
    seek_requested = pyqtSignal(float)
    def __init__(self, timeline_view, parent=None):
        super().__init__(parent)
        self.timeline_view = timeline_view
        self.setMinimumHeight(35)
        self.playhead_pos_px = 0
        self.snap_line_pos = None
        self.pixels_per_second = 50
        self.snap_threshold_px = 10

    def set_view_width(self, width):
        self.setMinimumWidth(width)
        self.update()
    def set_playhead_pos(self, px):
        self.playhead_pos_px = px
        self.update()
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#383838"))
        painter.setPen(QPen(QColor(150, 150, 150), 1))
        pixels_per_tick = self.pixels_per_second
        if pixels_per_tick > 0:
            num_ticks = int(self.width() / pixels_per_tick) + 1
            for i in range(num_ticks):
                x = int(i * pixels_per_tick)
                h = 10 if i % 5 == 0 else 5
                painter.drawLine(x, self.height() - h, x, self.height())
                if i % 5 == 0:
                    painter.drawText(x + 3, self.height() - 10, f"{i}s")
        if self.snap_line_pos is not None and self.snap_line_pos >= 0:
            painter.setPen(QPen(QColor("#3498db"), 2))
            painter.drawLine(self.snap_line_pos, 0, self.snap_line_pos, self.height())
        painter.setPen(QPen(QColor("#2196F3"), 3))
        painter.drawLine(int(self.playhead_pos_px), 0, int(self.playhead_pos_px), self.height())

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._emit_seek(event.pos())
    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.LeftButton:
            self._emit_seek(event.pos())
    def _emit_seek(self, pos):
        x = pos.x()
        snap_points = []
        for layer in self.timeline_view.layers:
            for clip in layer.clips:
                clip_start_px = clip.start_time * self.pixels_per_second
                clip_end_px = (clip.start_time + clip.duration) * self.pixels_per_second
                snap_points.append(clip_start_px)
                snap_points.append(clip_end_px)
        snapped = False
        for point_px in snap_points:
            if abs(x - point_px) < self.snap_threshold_px:
                x = point_px
                snapped = True
                break
        time_sec = max(0, x / self.pixels_per_second)
        self.seek_requested.emit(time_sec)

class LayerWidget(QFrame):
    clip_selected = pyqtSignal(object)
    clip_modified = pyqtSignal()
    internal_clip_dropped = pyqtSignal(str, int, float)
    seek_requested = pyqtSignal(float)
    remove_clip_requested = pyqtSignal(object)
    snap_preview_requested = pyqtSignal(int)

    def __init__(self, layer_number, base_dir, timeline_view, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setMouseTracking(True)
        self.layer_number = layer_number
        self.base_dir = base_dir
        self.timeline_view = timeline_view
        self.clips = []
        self.selected_clip = None
        self.logger = logging.getLogger("Advanced_Video_Editor")
        self.setFrameShape(QFrame.StyledPanel)
        self.setFixedHeight(40)
        self.setStyleSheet(f"background-color: {'#34495e' if layer_number % 2 == 0 else '#2c3e50'}; border-bottom: 1px solid #1a252f;")
        self.drag_start_pos = QPoint()
        self.dash_offset = 0
        self.is_muted = False
        self.is_solo = False
        self.is_locked = False

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        for clip in self.clips:
            rect = self.get_clip_rect(clip)
            if clip == self.selected_clip:
                fill_color = QColor("#2980b9") 
                border_color = QColor("#ecf0f1")
            else:
                fill_color = QColor("#3498db") 
                border_color = QColor("#2980b9")
            painter.setBrush(QBrush(fill_color))
            painter.setPen(QPen(border_color, 1))
            painter.drawRoundedRect(rect, 4, 4)
            painter.setPen(QColor("#ffffff"))
            text_rect = QRect(rect.x() + 5, rect.y(), rect.width() - 10, rect.height())
            filename = os.path.basename(clip.file_path)
            painter.drawText(text_rect, Qt.AlignVCenter | Qt.AlignLeft, filename)
            if clip == self.selected_clip:
                pen = QPen(Qt.white, 2, Qt.CustomDashLine)
                pen.setDashOffset(self.dash_offset)
                pen.setDashPattern([4, 4])
                painter.setPen(pen)
                painter.setBrush(Qt.NoBrush)
                painter.drawRoundedRect(rect, 4, 4)
    
    def event(self, event):
        if event.type() == QEvent.ToolTip:
            pos = event.pos()
            for clip in self.clips:
                if self.get_clip_rect(clip).contains(pos):
                    tooltip_text = f"File: {os.path.basename(clip.file_path)}\nDuration: {clip.duration:.2f}s"
                    QToolTip.showText(event.globalPos(), tooltip_text, self)
                    return True
        return super().event(event)

    def contextMenuEvent(self, event):
        if self.is_locked:
            return
        clicked_clip = None
        for clip in reversed(self.clips):
            if self.get_clip_rect(clip).contains(event.pos()):
                clicked_clip = clip
                break
        if clicked_clip:
            self.selected_clip = clicked_clip
            self.clip_selected.emit(self.selected_clip)
            self.update()
            menu = QMenu(self)
            remove_action = menu.addAction("Remove Clip")
            action = menu.exec_(self.mapToGlobal(event.pos()))
            if action == remove_action:
                self.remove_clip_requested.emit(self.selected_clip)

    def get_clip_rect(self, clip):
        x = int(clip.start_time * self.timeline_view.pixels_per_second)
        w = int(clip.duration * self.timeline_view.pixels_per_second)
        if w < 1:
            w = 1
        return QRect(x, 2, w, self.height() - 4)

    def animate_ants(self):
        self.dash_offset = (self.dash_offset - 1) % 8
        self.update()

    def mousePressEvent(self, event):
        if self.is_locked:
            return
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
                time_sec = max(0, event.pos().x() / self.timeline_view.pixels_per_second)
                self.seek_requested.emit(time_sec)
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self.is_locked:
            return
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
        self.snap_preview_requested.emit(-1)

    def dragEnterEvent(self, event):
        if self.is_locked:
            event.ignore()
            return
        if event.mimeData().hasUrls() or event.mimeData().hasFormat("application/x-advanced-clip"):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        if self.is_locked:
            event.ignore()
            return
        if event.mimeData().hasFormat("application/x-advanced-clip"):
            uid = event.mimeData().data("application/x-advanced-clip").data().decode('utf-8')
            drop_x = event.pos().x()
            snap_threshold_px = 25
            start_snap_threshold_px = 50
            snap_points = [0]
            for layer in self.timeline_view.layers:
                for clip in layer.clips:
                    if clip.uid != uid:
                        snap_points.append(clip.start_time * self.timeline_view.pixels_per_second)
                        snap_points.append((clip.start_time + clip.duration) * self.timeline_view.pixels_per_second)
            snapped_x = -1
            if abs(drop_x) < start_snap_threshold_px:
                snapped_x = 0
            else:
                closest_dist = snap_threshold_px + 1
                for point_px in snap_points:
                    dist = abs(drop_x - point_px)
                    if dist < snap_threshold_px and dist < closest_dist:
                        snapped_x = point_px
                        closest_dist = dist
            self.snap_preview_requested.emit(snapped_x)
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragLeaveEvent(self, event):
        self.snap_preview_requested.emit(-1)
        super().dragLeaveEvent(event)

    def dropEvent(self, event):
        if self.is_locked:
            return
        self.snap_preview_requested.emit(-1)
        if event.mimeData().hasFormat("application/x-advanced-clip"):
            event.acceptProposedAction()
            uid = event.mimeData().data("application/x-advanced-clip").data().decode('utf-8')
            drop_x = event.pos().x()
            snap_threshold_px = 25
            start_snap_threshold_px = 50
            snap_points = [0]
            for layer in self.timeline_view.layers:
                for clip in layer.clips:
                    if clip.uid != uid: 
                        snap_points.append(clip.start_time * self.timeline_view.pixels_per_second)
                        snap_points.append((clip.start_time + clip.duration) * self.timeline_view.pixels_per_second)
            snapped_x = drop_x
            if abs(drop_x) < start_snap_threshold_px:
                snapped_x = 0
            else:
                closest_dist = snap_threshold_px + 1
                for point_px in snap_points:
                    dist = abs(drop_x - point_px)
                    if dist < snap_threshold_px and dist < closest_dist:
                        snapped_x = point_px
                        closest_dist = dist
            new_start_time = max(0.0, snapped_x / self.timeline_view.pixels_per_second)
            self.internal_clip_dropped.emit(uid, self.layer_number, new_start_time)
        elif event.mimeData().hasUrls():
            event.acceptProposedAction()
            files_to_load = []
            for url in event.mimeData().urls():
                file_path = url.toLocalFile()
                if os.path.isfile(file_path):
                    ext = file_path.lower()
                    if ext.endswith(('.mp4', '.mov', '.mkv', '.avi', '.mp3', '.wav', '.png', '.jpg')):
                        files_to_load.append(file_path)
            if files_to_load:
                ffprobe_exe = os.path.join(self.base_dir, 'binaries', 'ffprobe.exe')
                for f in files_to_load:
                    self.logger.info(f"Dropped file (Async): {f} on Layer {self.layer_number}")
                    worker = ProbeWorker(f, ffprobe_exe, self)
                    worker.finished.connect(self.on_probe_finished)
                    worker.finished.connect(worker.deleteLater)
                    worker.start()

    def add_clip(self, file_path, duration, start_time=None):
        if start_time is None:
            max_end = 0.0
            for c in self.clips:
                if (c.start_time + c.duration) > max_end:
                    max_end = c.start_time + c.duration
            start_time = max_end
        new_clip = Clip(file_path, duration, start_time)
        self.clips.append(new_clip)
        self.selected_clip = new_clip
        self.clip_selected.emit(self.selected_clip)
        self.clip_modified.emit()
        self.update()

    def on_probe_finished(self, file_path, duration):
        self.add_clip(file_path, duration)

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

class TimelineView(QScrollArea):
    PIXELS_PER_SECOND = 50
    clip_selected_on_timeline = pyqtSignal(object)
    seek_requested = pyqtSignal(float)
    pre_modification = pyqtSignal()
    clip_remove_requested = pyqtSignal(object)

    def __init__(self, base_dir, parent=None):
        super().__init__(parent)
        self.base_dir = base_dir
        self.logger = logging.getLogger("Advanced_Video_Editor")
        self.setWidgetResizable(True)
        self.container = QWidget()
        self.container.setStyleSheet("background-color: #383838;")
        self.setWidget(self.container)
        self.main_layout = QVBoxLayout(self.container)
        self.main_layout.setSpacing(0)
        self.main_layout.setContentsMargins(0,0,0,0)
        self.ruler = RulerWidget(self)
        self.pixels_per_second = 50
        self.ruler.pixels_per_second = self.pixels_per_second
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

    def update_snap_preview(self, x_pos):
        self.ruler.snap_line_pos = x_pos
        self.ruler.update()

    def update_ants(self):
        for layer in self.layers:
            if layer.selected_clip:
                layer.animate_ants()
    def add_layer(self):
        idx = len(self.layers)
        layer = LayerWidget(idx, self.base_dir, self)
        layer.clip_modified.connect(self.update_dimensions)
        layer.clip_modified.connect(self.notify_pre_mod)
        layer.clip_selected.connect(self.handle_selection)
        layer.internal_clip_dropped.connect(self.handle_clip_move)
        layer.seek_requested.connect(self.seek_requested)
        layer.remove_clip_requested.connect(self.clip_remove_requested)
        layer.snap_preview_requested.connect(self.update_snap_preview)
        self.layers_layout.addWidget(layer)
        self.layers.append(layer)
        return layer

    def set_layer_muted(self, layer, muted):
        layer.is_muted = muted
        self.logger.info(f"Layer {layer.layer_number} muted: {muted}")

    def set_layer_solo(self, layer, solo):
        layer.is_solo = solo
        if solo:
            for other_layer in self.layers:
                if other_layer != layer:
                    other_layer.is_solo = False
        self.logger.info(f"Layer {layer.layer_number} solo: {solo}")
        
    def set_layer_locked(self, layer, locked):
        layer.is_locked = locked
        self.logger.info(f"Layer {layer.layer_number} locked: {locked}")

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
        width = int(max(max_time * self.pixels_per_second + 200, self.width()))
        self.container.setMinimumWidth(width)
        self.ruler.set_view_width(width)
    def update_playhead(self, time_sec):
        self.ruler.set_playhead_pos(time_sec * self.pixels_per_second)
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
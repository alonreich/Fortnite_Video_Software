import sys
import os
sys.dont_write_bytecode = True
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)
import copy
import vlc
import threading
import subprocess
import tempfile
import time
from PyQt5.QtWidgets import QApplication,QMainWindow,QWidget,QVBoxLayout,QFrame,QLabel,QPushButton,QHBoxLayout,QStyle,QShortcut,QFileDialog,QDoubleSpinBox,QSpinBox,QProgressBar
from PyQt5.QtCore import Qt,QSize,QTimer,pyqtSignal,QObject
from PyQt5.QtGui import QFont,QKeyEvent,QKeySequence
from advanced.logger import setup_logger
from advanced.config import ConfigManager
from advanced.timeline import TimelineView,Clip
from advanced.player import Player

class ExportWorker(QObject):
    progress = pyqtSignal(int,str)
    finished = pyqtSignal(str)
    error = pyqtSignal(str)
    def __init__(self, base_dir, timeline_state, output_path, parent=None):
        super().__init__(parent)
        self.base_dir = base_dir
        self.timeline_state = timeline_state
        self.output_path = output_path
        self._stop = False
    def stop(self):
        self._stop = True
    def _find_ffmpeg(self):
        exe = os.path.join(self.base_dir, 'binaries', 'ffmpeg.exe')
        if os.path.exists(exe):
            return exe
        return 'ffmpeg'
    def _atempo_chain(self, speed):
        speed = float(speed)
        if speed <= 0:
            return []
        filters = []
        remaining = speed
        while remaining > 2.0:
            filters.append('atempo=2.0')
            remaining /= 2.0
        while remaining < 0.5:
            filters.append('atempo=0.5')
            remaining /= 0.5
        filters.append(f'atempo={remaining:.6f}')
        return filters
    def _is_audio_only(self, path):
        ext = os.path.splitext(path.lower())[1]
        return ext in ['.mp3','.wav']
    def _build_segments(self):
        layers = []
        for layer_data in self.timeline_state:
            layer_clips = []
            for cd in layer_data:
                layer_clips.append(Clip.from_dict(cd))
            layers.append(layer_clips)
        cut_points = set([0.0])
        for layer in layers:
            for c in layer:
                cut_points.add(float(c.start_time))
                cut_points.add(float(c.start_time + c.duration))
        pts = sorted([p for p in cut_points if p >= 0.0])
        segments = []
        for i in range(len(pts) - 1):
            t0 = pts[i]
            t1 = pts[i + 1]
            if t1 <= t0:
                continue
            found = None
            for layer in layers:
                for c in layer:
                    if c.start_time <= t0 < c.start_time + c.duration:
                        found = c
                        break
                if found:
                    break
            if found is None:
                continue
            seg_dur = t1 - t0
            seg_off = t0 - found.start_time
            seg = {'file_path': found.file_path,'source_in': float(found.source_in) + seg_off * float(found.speed),'speed': float(found.speed),'volume': int(found.volume),'duration': float(seg_dur),'audio_only': self._is_audio_only(found.file_path)}
            segments.append(seg)
        return segments
    def run(self):
        try:
            ffmpeg = self._find_ffmpeg()
            segments = self._build_segments()
            if not segments:
                self.error.emit('No clips on timeline to export.')
                return
            tmp_dir = tempfile.mkdtemp(prefix='adv_export_')
            rendered = []
            for idx, seg in enumerate(segments):
                if self._stop:
                    self.error.emit('Export cancelled.')
                    return
                pct = int((idx / max(1, len(segments))) * 100)
                self.progress.emit(pct, f"Rendering segment {idx + 1}/{len(segments)}")
                in_path = seg['file_path']
                out_path = os.path.join(tmp_dir, f"seg_{idx:05d}.mp4")
                ss = max(0.0, seg['source_in'])
                src_dur = max(0.01, seg['duration'] * seg['speed'])
                vf = f"setpts=PTS/{seg['speed']:.6f}"
                vol = max(0.0, seg['volume'] / 100.0)
                af_filters = [f'volume={vol:.6f}'] + self._atempo_chain(seg['speed'])
                af = ','.join(af_filters)
                cmd = [ffmpeg,'-y','-ss',f'{ss:.6f}','-t',f'{src_dur:.6f}','-i',in_path]
                if seg['audio_only']:
                    cmd += ['-f','lavfi','-i','color=c=black:s=1280x720:r=30']
                    cmd += ['-shortest','-map','1:v:0','-map','0:a:0']
                cmd += ['-vf',vf,'-af',af,'-c:v','libx264','-preset','veryfast','-crf','18','-c:a','aac','-b:a','192k','-movflags','+faststart',out_path]
                startupinfo = None
                if os.name == 'nt':
                    startupinfo = subprocess.STARTUPINFO()
                    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                p = subprocess.run(cmd, capture_output=True, text=True, startupinfo=startupinfo)
                if p.returncode != 0:
                    msg = (p.stderr or '').strip()
                    if not msg:
                        msg = 'ffmpeg failed.'
                    self.error.emit(msg)
                    return
                rendered.append(out_path)
            self.progress.emit(100, 'Finalizing output')
            list_path = os.path.join(tmp_dir, 'concat.txt')
            with open(list_path, 'w', encoding='utf-8') as f:
                for rp in rendered:
                    safe_path=rp.replace("'", "\\'")
                    f.write(f"file '{safe_path}'\n")
            cmd2 = [ffmpeg,'-y','-f','concat','-safe','0','-i',list_path,'-c','copy',self.output_path]
            startupinfo = None
            if os.name == 'nt':
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            p2 = subprocess.run(cmd2, capture_output=True, text=True, startupinfo=startupinfo)
            if p2.returncode != 0:
                msg = (p2.stderr or '').strip()
                if not msg:
                    msg = 'ffmpeg concat failed.'
                self.error.emit(msg)
                return
            self.finished.emit(self.output_path)
        except Exception as e:
            self.error.emit(str(e))

class ClipInspector(QFrame):
    speed_changed = pyqtSignal(float)
    volume_changed = pyqtSignal(int)
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedWidth(320)
        self.setStyleSheet("background-color: #1a252f; color: white; border-left: 2px solid #000;")
        self.clip = None
        self._loading = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12,12,12,12)
        layout.setSpacing(8)
        self.title = QLabel("Clip Inspector")
        self.title.setStyleSheet("font-weight: bold; font-size: 16px;")
        layout.addWidget(self.title)
        self.lbl_name = QLabel("No clip selected")
        self.lbl_name.setWordWrap(True)
        layout.addWidget(self.lbl_name)
        self.lbl_speed = QLabel("Speed")
        layout.addWidget(self.lbl_speed)
        self.spin_speed = QDoubleSpinBox()
        self.spin_speed.setRange(0.25, 4.0)
        self.spin_speed.setSingleStep(0.25)
        self.spin_speed.valueChanged.connect(self._emit_speed)
        layout.addWidget(self.spin_speed)
        self.lbl_vol = QLabel("Volume")
        layout.addWidget(self.lbl_vol)
        self.spin_vol = QSpinBox()
        self.spin_vol.setRange(0, 200)
        self.spin_vol.setSingleStep(10)
        self.spin_vol.valueChanged.connect(self._emit_volume)
        layout.addWidget(self.spin_vol)
        self.lbl_status = QLabel("")
        self.lbl_status.setWordWrap(True)
        self.lbl_status.setStyleSheet("color: #bdc3c7;")
        layout.addWidget(self.lbl_status)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setTextVisible(True)
        self.progress.setStyleSheet("QProgressBar { background-color: #2c3e50; border: 1px solid #000; } QProgressBar::chunk { background-color: #27ae60; }")
        layout.addWidget(self.progress)
        layout.addStretch()
        self.setEnabled(False)
    def set_clip(self, clip):
        self._loading = True
        self.clip = clip
        if clip is None:
            self.lbl_name.setText("No clip selected")
            self.spin_speed.setValue(1.0)
            self.spin_vol.setValue(100)
            self.setEnabled(False)
        else:
            self.lbl_name.setText(os.path.basename(clip.file_path))
            self.spin_speed.setValue(float(clip.speed))
            self.spin_vol.setValue(int(clip.volume))
            self.setEnabled(True)
        self._loading = False
    def _emit_speed(self, v):
        if self._loading:
            return
        self.speed_changed.emit(float(v))
    def _emit_volume(self, v):
        if self._loading:
            return
        self.volume_changed.emit(int(v))
    def set_export_status(self, text, pct=None):
        self.lbl_status.setText(text)
        if pct is not None:
            self.progress.setValue(int(pct))

class AdvancedEditor(QMainWindow):
    def __init__(self):
        super().__init__()
        self.base_dir = parent_dir
        self.logger = setup_logger()
        self.config_manager = ConfigManager(os.path.join(self.base_dir, 'config', 'editor.conf'))
        self.selected_clip = None
        self.undo_stack = []
        self.export_worker = None
        self.export_thread = None
        self.setWindowTitle("Advanced Video Editor - Semi Pro")
        self.resize(1600, 900)
        self.setStyleSheet("QMainWindow { background-color: #2c3e50; } QPushButton { background-color: #34495e; color: white; border: none; padding: 8px; border-radius: 4px; font-weight: bold; } QPushButton:hover { background-color: #4e6d8d; } QPushButton:disabled { background-color: #2c3e50; color: #7f8c8d; }")
        self.setFocusPolicy(Qt.StrongFocus)
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setSpacing(0)
        layout.setContentsMargins(0,0,0,0)
        self.action_bar = QFrame()
        self.action_bar.setStyleSheet("background-color: #1a252f; border-bottom: 2px solid #000;")
        self.action_bar.setFixedHeight(60)
        ab_layout = QHBoxLayout(self.action_bar)
        self.btn_speed_down = self.create_action_btn("<< Slow", self.change_speed_down)
        self.btn_speed_up = self.create_action_btn("Fast >>", self.change_speed_up)
        self.btn_vol_down = self.create_action_btn("Vol -", self.change_vol_down)
        self.btn_vol_up = self.create_action_btn("Vol +", self.change_vol_up)
        self.btn_layer_up = self.create_action_btn("▲ Move Up", self.move_layer_up)
        self.btn_layer_down = self.create_action_btn("▼ Move Down", self.move_layer_down)
        self.btn_split = self.create_action_btn("✁ Split", self.split_clip)
        self.btn_split.setStyleSheet("background-color: #e67e22;")
        self.btn_process = self.create_action_btn("Process Video", self.process_video)
        self.btn_process.setStyleSheet("background-color: #2980b9;")
        self.btn_delete = self.create_action_btn("✖ Delete", self.delete_clip)
        self.btn_delete.setStyleSheet("background-color: #c0392b;")
        self.btn_undo = self.create_action_btn("⟲ Undo", self.undo_action)
        self.btn_undo.setStyleSheet("background-color: #8e44ad;")
        ab_layout.addWidget(QLabel("  Track Actions:  "))
        ab_layout.addWidget(self.btn_speed_down)
        ab_layout.addWidget(self.btn_speed_up)
        ab_layout.addSpacing(20)
        ab_layout.addWidget(self.btn_vol_down)
        ab_layout.addWidget(self.btn_vol_up)
        ab_layout.addSpacing(20)
        ab_layout.addWidget(self.btn_layer_up)
        ab_layout.addWidget(self.btn_layer_down)
        ab_layout.addSpacing(20)
        ab_layout.addWidget(self.btn_split)
        ab_layout.addSpacing(20)
        ab_layout.addWidget(self.btn_process)
        ab_layout.addStretch()
        ab_layout.addWidget(self.btn_undo)
        ab_layout.addWidget(self.btn_delete)
        ab_layout.addSpacing(10)
        layout.addWidget(self.action_bar)
        self.update_action_bar()
        self.player = Player(self.base_dir, self)
        self.inspector = ClipInspector(self)
        self.inspector.speed_changed.connect(self.set_selected_speed)
        self.inspector.volume_changed.connect(self.set_selected_volume)
        preview_frame = QFrame()
        preview_layout = QHBoxLayout(preview_frame)
        preview_layout.setContentsMargins(0,0,0,0)
        preview_layout.setSpacing(0)
        preview_layout.addWidget(self.player.video_frame, 1)
        preview_layout.addWidget(self.inspector, 0)
        layout.addWidget(preview_frame, 1)
        ctrl_frame = QFrame()
        ctrl_frame.setFixedHeight(50)
        ctrl_frame.setStyleSheet("background-color: #2c3e50;")
        cf_layout = QHBoxLayout(ctrl_frame)
        self.btn_play = QPushButton("PLAY")
        self.btn_play.setFixedWidth(100)
        self.btn_play.clicked.connect(self.toggle_playback)
        self.btn_play.setStyleSheet("background-color: #27ae60;")
        cf_layout.addWidget(self.btn_play)
        layout.addWidget(ctrl_frame)
        self.timeline = TimelineView(self.base_dir)
        self.timeline.setFixedHeight(300)
        self.timeline.seek_requested.connect(self.seek_timeline)
        self.timeline.clip_selected_on_timeline.connect(self.on_clip_selected)
        self.timeline.pre_modification.connect(self.save_state_from_timeline)
        layout.addWidget(self.timeline)
        self.timer = QTimer()
        self.timer.setInterval(50)
        self.timer.timeout.connect(self.sync_playback)
        self.current_playing_clip = None
        self.undo_shortcut = QShortcut(QKeySequence("Ctrl+Z"), self)
        self.undo_shortcut.activated.connect(self.undo_action)
        self.logger.info("Application started.")
    def keyPressEvent(self, event: QKeyEvent):
        if event.key() == Qt.Key_Left:
            current_pos = self.timeline.ruler.playhead_pos_px / self.timeline.PIXELS_PER_SECOND
            new_pos = max(0.0, current_pos - 1.0)
            self.seek_timeline(new_pos)
            self.logger.info(f"Seek Back: {new_pos:.2f}s")
        elif event.key() == Qt.Key_Right:
            current_pos = self.timeline.ruler.playhead_pos_px / self.timeline.PIXELS_PER_SECOND
            new_pos = current_pos + 1.0
            self.seek_timeline(new_pos)
            self.logger.info(f"Seek Fwd: {new_pos:.2f}s")
        elif event.key() == Qt.Key_Delete:
            if self.selected_clip:
                self.delete_clip()
        elif event.key() == Qt.Key_Space:
            self.toggle_playback()
        else:
            super().keyPressEvent(event)
    def create_action_btn(self, text, slot):
        btn = QPushButton(text)
        btn.clicked.connect(slot)
        return btn
    def on_clip_selected(self, clip):
        self.selected_clip = clip
        self.inspector.set_clip(clip)
        self.update_action_bar()
    def update_action_bar(self):
        enabled = self.selected_clip is not None
        for btn in [self.btn_speed_down,self.btn_speed_up,self.btn_vol_down,self.btn_vol_up,self.btn_layer_up,self.btn_layer_down,self.btn_split,self.btn_delete]:
            btn.setEnabled(enabled)
        if enabled:
            layer = self.timeline.get_layer_of_clip(self.selected_clip)
            if layer:
                self.btn_layer_up.setEnabled(layer.layer_number > 0)
                self.btn_layer_down.setEnabled(layer.layer_number < len(self.timeline.layers) - 1)
        self.btn_undo.setEnabled(len(self.undo_stack) > 0)
    def save_state(self):
        state = self.timeline.get_state()
        self.undo_stack.append(state)
        if len(self.undo_stack) > 50:
            self.undo_stack.pop(0)
        self.update_action_bar()
    def save_state_from_timeline(self):
        self.save_state()
    def undo_action(self):
        if self.undo_stack:
            state = self.undo_stack.pop()
            self.timeline.pre_modification.disconnect(self.save_state_from_timeline)
            self.timeline.load_state(state)
            self.timeline.pre_modification.connect(self.save_state_from_timeline)
            self.selected_clip = None
            self.inspector.set_clip(None)
            self.update_action_bar()
            self.logger.info("Undo performed")
    def set_selected_speed(self, speed):
        if self.selected_clip:
            self.save_state()
            self.selected_clip.speed = float(speed)
            self.logger.info(f"Speed set to {self.selected_clip.speed}x for clip {self.selected_clip.uid}")
            self.refresh_layer()
    def set_selected_volume(self, volume):
        if self.selected_clip:
            self.save_state()
            self.selected_clip.volume = int(volume)
            self.logger.info(f"Volume set to {self.selected_clip.volume} for clip {self.selected_clip.uid}")
            self.refresh_layer()
    def change_speed_up(self):
        if self.selected_clip:
            self.save_state()
            self.selected_clip.speed = min(4.0, self.selected_clip.speed + 0.25)
            self.inspector.set_clip(self.selected_clip)
            self.logger.info(f"Speed increased to {self.selected_clip.speed}x for clip {self.selected_clip.uid}")
            self.refresh_layer()
    def change_speed_down(self):
        if self.selected_clip:
            self.save_state()
            self.selected_clip.speed = max(0.25, self.selected_clip.speed - 0.25)
            self.inspector.set_clip(self.selected_clip)
            self.logger.info(f"Speed decreased to {self.selected_clip.speed}x for clip {self.selected_clip.uid}")
            self.refresh_layer()
    def change_vol_up(self):
        if self.selected_clip:
            self.save_state()
            self.selected_clip.volume = min(200, self.selected_clip.volume + 10)
            self.inspector.set_clip(self.selected_clip)
            self.logger.info(f"Volume increased to {self.selected_clip.volume} for clip {self.selected_clip.uid}")
            self.refresh_layer()
    def change_vol_down(self):
        if self.selected_clip:
            self.save_state()
            self.selected_clip.volume = max(0, self.selected_clip.volume - 10)
            self.inspector.set_clip(self.selected_clip)
            self.logger.info(f"Volume decreased to {self.selected_clip.volume} for clip {self.selected_clip.uid}")
            self.refresh_layer()
    def move_layer_up(self):
        self.save_state()
        self._move_layer(-1)
    def move_layer_down(self):
        self.save_state()
        self._move_layer(1)
    def _move_layer(self, offset):
        if not self.selected_clip:
            return
        current_layer = self.timeline.get_layer_of_clip(self.selected_clip)
        if not current_layer:
            return
        target_idx = current_layer.layer_number + offset
        if 0 <= target_idx < len(self.timeline.layers):
            target_layer = self.timeline.layers[target_idx]
            current_layer.clips.remove(self.selected_clip)
            target_layer.clips.append(self.selected_clip)
            current_layer.selected_clip = None
            target_layer.selected_clip = self.selected_clip
            current_layer.update()
            target_layer.update()
            self.update_action_bar()
            self.logger.info(f"Moved clip from layer {current_layer.layer_number} to {target_layer.layer_number}")
    def delete_clip(self):
        if not self.selected_clip:
            return
        self.save_state()
        layer = self.timeline.get_layer_of_clip(self.selected_clip)
        if layer:
            self.logger.info(f"Deleted clip {self.selected_clip.uid} from layer {layer.layer_number}")
            layer.clips.remove(self.selected_clip)
            layer.selected_clip = None
            self.selected_clip = None
            self.inspector.set_clip(None)
            layer.update()
            self.update_action_bar()
    def split_clip(self):
        if not self.selected_clip:
            return
        self.save_state()
        playhead_sec = self.timeline.ruler.playhead_pos_px / self.timeline.PIXELS_PER_SECOND
        clip = self.selected_clip
        if not (clip.start_time < playhead_sec < clip.start_time + clip.duration):
            self.logger.info("Split failed: Playhead not within selected clip duration")
            return
        split_offset = playhead_sec - clip.start_time
        new_clip = Clip(clip.file_path, clip.duration - split_offset, playhead_sec)
        new_clip.source_in = clip.source_in + split_offset
        new_clip.speed = clip.speed
        new_clip.volume = clip.volume
        clip.duration = split_offset
        layer = self.timeline.get_layer_of_clip(clip)
        layer.clips.append(new_clip)
        layer.update()
        self.logger.info(f"Split clip {clip.uid} at offset {split_offset}")
    def refresh_layer(self):
        if self.selected_clip:
            layer = self.timeline.get_layer_of_clip(self.selected_clip)
            if layer:
                layer.update()
            if self.player.is_playing() and self.current_playing_clip == self.selected_clip:
                self.player.set_rate(self.selected_clip.speed)
                self.player.set_volume(self.selected_clip.volume)
    def toggle_playback(self):
        if self.player.is_playing():
            self.player.pause()
            self.timer.stop()
            self.btn_play.setText("PLAY")
            self.logger.info("Playback paused")
        else:
            self.btn_play.setText("PAUSE")
            self.timer.start()
            self.player.play()
            self.sync_playback()
            self.logger.info("Playback started")
    def seek_timeline(self, time_sec):
        self.timeline.update_playhead(time_sec)
        self.check_media_at_time(time_sec, force_seek=True)
    def sync_playback(self):
        if self.player.is_playing() and self.current_playing_clip:
            current_media_time = self.player.get_time() / 1000.0
            effective_progress = (current_media_time - self.current_playing_clip.source_in) * self.current_playing_clip.speed
            timeline_time = self.current_playing_clip.start_time + effective_progress
            self.timeline.update_playhead(timeline_time)
        current_playhead = self.timeline.ruler.playhead_pos_px / self.timeline.PIXELS_PER_SECOND
        self.check_media_at_time(current_playhead)
    def check_media_at_time(self, time_sec, force_seek=False):
        found_clip = None
        for layer in self.timeline.layers:
            for clip in layer.clips:
                if clip.start_time <= time_sec < clip.start_time + clip.duration:
                    found_clip = clip
                    break
            if found_clip:
                break
        if found_clip != self.current_playing_clip or force_seek:
            if found_clip:
                self.current_playing_clip = found_clip
                self.player.set_media(found_clip.file_path)
                offset_into_clip = time_sec - found_clip.start_time
                source_pos_ms = (found_clip.source_in + offset_into_clip) * 1000
                self.player.seek(source_pos_ms)
                self.player.set_rate(found_clip.speed)
                self.player.set_volume(found_clip.volume)
                if self.timer.isActive():
                    self.player.play()
            else:
                self.current_playing_clip = None
                self.player.stop()
    def process_video(self):
        if self.export_thread and self.export_thread.is_alive():
            return
        out_path, _ = QFileDialog.getSaveFileName(self, "Export Video", os.path.expanduser("~"), "MP4 Video (*.mp4)")
        if not out_path:
            return
        if not out_path.lower().endswith('.mp4'):
            out_path += '.mp4'
        state = self.timeline.get_state()
        self.export_worker = ExportWorker(self.base_dir, state, out_path)
        self.export_worker.progress.connect(self.on_export_progress)
        self.export_worker.finished.connect(self.on_export_finished)
        self.export_worker.error.connect(self.on_export_error)
        self.inspector.set_export_status("Starting export", 0)
        self.export_thread = threading.Thread(target=self.export_worker.run, daemon=True)
        self.export_thread.start()
        self.logger.info(f"Export started: {out_path}")
    def on_export_progress(self, pct, text):
        self.inspector.set_export_status(text, pct)
    def on_export_finished(self, out_path):
        self.inspector.set_export_status(f"Export complete: {os.path.basename(out_path)}", 100)
        self.logger.info(f"Export finished: {out_path}")
    def on_export_error(self, msg):
        self.inspector.set_export_status(f"Export error: {msg}", 0)
        self.logger.info(f"Export error: {msg}")

def main():
    app = QApplication(sys.argv)
    editor = AdvancedEditor()
    editor.show()
    sys.exit(app.exec_())
if __name__ == '__main__':
    main()
import sys
import os
import shutil
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
from PyQt5.QtWidgets import QApplication,QMainWindow,QWidget,QVBoxLayout,QFrame,QLabel,QPushButton,QHBoxLayout,QStyle,QShortcut,QFileDialog,QDoubleSpinBox,QSpinBox,QProgressBar,QSlider,QCheckBox
from PyQt5.QtCore import Qt,QSize,QTimer,pyqtSignal,QObject
from PyQt5.QtGui import QFont,QKeyEvent,QKeySequence,QCursor
from advanced.logger import setup_logger
from advanced.config import ConfigManager
from advanced.timeline import TimelineView,Clip
from advanced.player import Player
from ui.parts.phase_overlay_mixin import PhaseOverlayMixin

class ExportWorker(QObject):
    progress = pyqtSignal(int, str)
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

    def _escape_filter_path(self, path):
        path = path.replace('\\', '/')
        path = path.replace(':', '\\:')
        return path

    def run(self):
        try:
            ffmpeg = self._find_ffmpeg()
            all_clips = []
            unique_files = []
            file_map = {}
            total_duration = 0.0
            for layer_idx, layer_data in enumerate(self.timeline_state):
                for clip_data in layer_data:
                    clip = Clip.from_dict(clip_data)
                    clip.layer_idx = layer_idx
                    all_clips.append(clip)
                    if clip.file_path not in unique_files:
                        file_map[clip.file_path] = len(unique_files)
                        unique_files.append(clip.file_path)
                    end_time = clip.start_time + clip.duration
                    if end_time > total_duration:
                        total_duration = end_time
            if not all_clips:
                self.error.emit("Timeline is empty.")
                return
            if total_duration <= 0:
                self.error.emit("Invalid duration.")
                return
            filter_chains = []
            filter_chains.append(f"color=c=black:s=1280x720:d={total_duration:.3f}[bg]")
            last_bg_label = "bg"
            audio_labels = []
            self.progress.emit(10, "Generating render graph...")
            sorted_clips = sorted(all_clips, key=lambda c: (c.layer_idx, c.start_time))
            for idx, clip in enumerate(sorted_clips):
                if self._stop:
                    self.error.emit("Export cancelled.")
                    return
                inp_idx = file_map[clip.file_path]
                src_dur = clip.duration * clip.speed
                v_label = f"v{idx}"
                v_processed = f"v{idx}_out"
                filters = [
                    f"[{inp_idx}:v]trim=start={clip.source_in:.3f}:duration={src_dur:.3f}",
                    "setpts=PTS-STARTPTS"
                ]
                if abs(clip.speed - 1.0) > 0.001:
                    filters.append(f"setpts=PTS/{clip.speed:.4f}")
                filters.append("scale=1280:720:force_original_aspect_ratio=decrease")
                filters.append("pad=1280:720:(ow-iw)/2:(oh-ih)/2")
                filters.append(f"setpts=PTS+{clip.start_time:.3f}/TB")
                chain_str = ",".join(filters)
                filter_chains.append(f"{chain_str}[{v_processed}]")
                next_bg_label = f"bg_{idx}"
                overlay_cmd = f"[{last_bg_label}][{v_processed}]overlay=enable='between(t,{clip.start_time:.3f},{clip.start_time + clip.duration:.3f})':eof_action=pass:shortest=0[{next_bg_label}]"
                filter_chains.append(overlay_cmd)
                last_bg_label = next_bg_label
                a_label = f"a{idx}"
                afilters = [
                    f"[{inp_idx}:a]atrim=start={clip.source_in:.3f}:duration={src_dur:.3f}",
                    "asetpts=PTS-STARTPTS"
                ]
                if abs(clip.speed - 1.0) > 0.001:
                    speed = clip.speed
                    while speed > 2.0:
                        afilters.append("atempo=2.0")
                        speed /= 2.0
                    while speed < 0.5:
                        afilters.append("atempo=0.5")
                        speed /= 0.5
                    afilters.append(f"atempo={speed:.4f}")
                vol_factor = clip.volume / 100.0
                afilters.append(f"volume={vol_factor:.2f}")
                start_ms = int(clip.start_time * 1000)
                afilters.append(f"adelay={start_ms}|{start_ms}")
                chain_str_a = ",".join(afilters)
                filter_chains.append(f"{chain_str_a}[{a_label}]")
                audio_labels.append(f"[{a_label}]")
            if audio_labels:
                filter_chains.append(f"{ ''.join(audio_labels)}amix=inputs={len(audio_labels)}:dropout_transition=0:normalize=0[a_out]")
            else:
                filter_chains.append(f"anullsrc=channel_layout=stereo:sample_rate=44100:d={total_duration:.3f}[a_out]")
            filter_script = ";\n".join(filter_chains)
            tmp_script_fd, tmp_script_path = tempfile.mkstemp(suffix='.txt', text=True)
            with os.fdopen(tmp_script_fd, 'w') as f:
                f.write(filter_script)
            self.progress.emit(50, "Encoding...")
            cmd = [
                ffmpeg,
                '-y',
            ]
            for fpath in unique_files:
                cmd.extend(['-i', fpath])
            cmd.extend(['-filter_complex_script', tmp_script_path])
            cmd.extend(['-map', f'[{last_bg_label}]', '-map', '[a_out]'])
            cmd.extend([
                '-c:v', 'libx264',
                '-preset', 'medium',
                '-crf', '23',
                '-c:a', 'aac',
                '-b:a', '192k',
                '-movflags', '+faststart',
                self.output_path
            ])
            startupinfo = None
            if os.name == 'nt':
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            self.progress.emit(60, "FFmpeg running...")
            process = subprocess.Popen(
                cmd, 
                stdout=subprocess.PIPE, 
                stderr=subprocess.PIPE, 
                universal_newlines=True,
                startupinfo=startupinfo
            )
            stdout, stderr = process.communicate()
            os.remove(tmp_script_path)
            if process.returncode != 0:
                self.error.emit(f"FFmpeg Error: {stderr[-200:] if stderr else 'Unknown'}")
                return
            self.progress.emit(100, "Done!")
            self.finished.emit(self.output_path)
        except Exception as e:
            self.error.emit(f"Critical Error: {str(e)}")

class ClipInspector(QFrame):
    speed_changed = pyqtSignal(float)
    volume_changed = pyqtSignal(int)
    layer_up = pyqtSignal()
    layer_down = pyqtSignal()
    split_clip = pyqtSignal()
    mute_toggled = pyqtSignal(bool)
    solo_toggled = pyqtSignal(bool)
    lock_toggled = pyqtSignal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedWidth(320)
        self.setStyleSheet("background-color: #1a252f; color: white; border-left: 2px solid #000;")
        self.clip = None
        self._loading = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)
        self.title = QLabel("File Properties")
        self.title.setStyleSheet("font-weight: bold; font-size: 16px;")
        layout.addWidget(self.title)
        self.lbl_name = QLabel("No clip selected")
        self.lbl_name.setWordWrap(True)
        layout.addWidget(self.lbl_name)
        self.lbl_speed = QLabel("Speed Multiplier")
        self.lbl_speed.setStyleSheet("font-size: 11px; font-weight: bold;")
        layout.addWidget(self.lbl_speed)
        self.spin_speed = QDoubleSpinBox()
        self.spin_speed.setRange(0.25, 4.0)
        self.spin_speed.setSingleStep(0.25)
        self.spin_speed.setStyleSheet("font-size: 11px;")
        self.spin_speed.setFixedHeight(20)
        self.spin_speed.valueChanged.connect(self._emit_speed)
        layout.addWidget(self.spin_speed)
        self.lbl_vol = QLabel("Volume")
        layout.addWidget(self.lbl_vol)
        vol_layout = QHBoxLayout()
        self.slider_vol = QSlider(Qt.Horizontal)
        self.slider_vol.setRange(0, 200)
        self.slider_vol.setSingleStep(1)
        self.slider_vol.setStyleSheet("""
            QSlider::groove:horizontal {
                border: 1px solid #bbb;
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #e64c4c, stop:0.5 #f2f2f2, stop:1 #009b00);
                height: 10px;
                border-radius: 4px;
            }
            QSlider::handle:horizontal {
                background: #3498db;
                border: 1px solid #5c5c5c;
                width: 18px;
                margin: -4px 0;
                border-radius: 8px;
            }
        """)
        self.slider_vol.valueChanged.connect(self._emit_volume)
        vol_layout.addWidget(self.slider_vol)
        self.lbl_vol_value = QLabel("100%")
        self.lbl_vol_value.setFixedWidth(40)
        vol_layout.addWidget(self.lbl_vol_value)
        layout.addLayout(vol_layout)
        btn_layout = QHBoxLayout()
        self.btn_layer_up = self._create_action_button("▲ Move Up", self.layer_up)
        self.btn_layer_down = self._create_action_button("▼ Move Down", self.layer_down)
        self.btn_split = self._create_action_button("✁ Split", self.split_clip)
        btn_layout.addWidget(self.btn_layer_up)
        btn_layout.addWidget(self.btn_layer_down)
        btn_layout.addWidget(self.btn_split)
        layout.addLayout(btn_layout)
        track_controls_layout = QHBoxLayout()
        self.mute_btn = self._create_track_control_button("Mute", self.mute_toggled)
        self.solo_btn = self._create_track_control_button("Solo", self.solo_toggled)
        self.lock_btn = self._create_track_control_button("Lock", self.lock_toggled)
        track_controls_layout.addWidget(self.mute_btn)
        track_controls_layout.addWidget(self.solo_btn)
        track_controls_layout.addWidget(self.lock_btn)
        layout.addLayout(track_controls_layout)
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

    def _create_action_button(self, text, signal):
        btn = QPushButton(text)
        btn.setStyleSheet("""
            QPushButton {
                background-color: #266b89;
                color: #ffffff;
                border: none;
                padding: 10px 18px;
                border-radius: 8px;
                font-weight: bold;
            }
            QPushButton:hover { background-color: #2980b9; }
        """)
        btn.setCursor(QCursor(Qt.PointingHandCursor))
        btn.clicked.connect(signal)
        return btn

    def _create_track_control_button(self, text, signal):
        btn = QPushButton(text)
        btn.setCheckable(True)
        btn.setStyleSheet("""
            QPushButton {
                background-color: #7f8c8d;
            }
            QPushButton:checked {
                background-color: #e74c3c;
            }
        """)
        btn.toggled.connect(signal)
        return btn

    def set_clip(self, clip, layer=None):
        self._loading = True
        self.clip = clip
        if clip is None:
            self.lbl_name.setText("No clip selected")
            self.spin_speed.setValue(1.0)
            self.slider_vol.setValue(100)
            self.lbl_vol_value.setText("100%")
            self.setEnabled(False)
        else:
            self.lbl_name.setText(os.path.basename(clip.file_path))
            self.spin_speed.setValue(float(clip.speed))
            self.slider_vol.setValue(int(clip.volume))
            self.lbl_vol_value.setText(f"{int(clip.volume)}%")
            self.setEnabled(True)
            if layer:
                self.mute_btn.setChecked(layer.is_muted)
                self.solo_btn.setChecked(layer.is_solo)
                self.lock_btn.setChecked(layer.is_locked)
        self._loading = False

    def _emit_speed(self, v):
        if self._loading:
            return
        self.speed_changed.emit(float(v))
    def _emit_volume(self, v):
        if self._loading:
            return
        self.lbl_vol_value.setText(f"{v}%")
        self.volume_changed.emit(int(v))
    def set_export_status(self, text, pct=None):
        self.lbl_status.setText(text)
        if pct is not None:
            self.progress.setValue(int(pct))

class AdvancedEditor(QMainWindow, PhaseOverlayMixin):
    def __init__(self, initial_file=None):
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
        self.setStyleSheet("QMainWindow { background-color: #34495e; } QPushButton { background-color: #34495e; color: white; border: none; padding: 8px; border-radius: 4px; font-weight: bold; } QPushButton:hover { background-color: #4e6d8d; } QPushButton:disabled { background-color: #2c3e50; color: #7f8c8d; }")
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
        self.btn_process = QPushButton("Process Video")
        self.btn_process.setCursor(QCursor(Qt.PointingHandCursor))
        self.btn_process.setStyleSheet("""
            QPushButton {
                background-color: #2ab22a;
                color: black;
                font-weight: bold;
                font-size: 16px;
                border-radius: 15px;
                margin-bottom: 6px;
            }
            QPushButton:hover { background-color: #c8f7c5; }
        """)
        self.btn_process.clicked.connect(self.process_video)
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setCursor(QCursor(Qt.PointingHandCursor))
        self.cancel_button.setStyleSheet("""
            QPushButton {
                background-color: #c0392b;
                color: white;
                font-weight: bold;
                font-size: 16px;
                border-radius: 15px;
                margin-bottom: 6px;
            }
            QPushButton:hover { background-color: #e74c3c; }
        """)
        self.cancel_button.clicked.connect(self.stop_export)
        self.cancel_button.hide()
        self.btn_delete = self.create_action_btn("✖ Delete", self.delete_clip)
        self.btn_undo = self.create_action_btn("⟲ Undo", self.undo_action)
        self.btn_upload = QPushButton("📂  Upload File  📂")
        self.btn_upload.setCursor(QCursor(Qt.PointingHandCursor))
        self.btn_upload.setStyleSheet("""
            QPushButton {
                background-color: #266b89;
                color: #ffffff;
                border: none;
                padding: 10px 18px;
                border-radius: 8px;
                font-weight: bold;
                margin-bottom: 6px;
            }
            QPushButton:hover { background-color: #2980b9; }
        """)
        self.btn_upload.clicked.connect(self.upload_file)
        ab_layout.addWidget(self.btn_upload)
        ab_layout.addStretch()
        ab_layout.addWidget(self.btn_process)
        ab_layout.addWidget(self.cancel_button)
        ab_layout.addWidget(self.btn_undo)
        ab_layout.addWidget(self.btn_delete)
        ab_layout.addSpacing(10)
        layout.addWidget(self.action_bar)
        self.player = Player(self.base_dir, self)
        self.inspector = ClipInspector(self)
        self.inspector.speed_changed.connect(self.set_selected_speed)
        self.inspector.volume_changed.connect(self.set_selected_volume)
        self.inspector.layer_up.connect(self.move_layer_up)
        self.inspector.layer_down.connect(self.move_layer_down)
        self.inspector.split_clip.connect(self.split_clip)
        self.inspector.mute_toggled.connect(self.toggle_mute)
        self.inspector.solo_toggled.connect(self.toggle_solo)
        self.inspector.lock_toggled.connect(self.toggle_lock)
        self.update_action_bar()
        self.video_frame = self.player.video_frame
        preview_frame = QFrame()
        preview_layout = QHBoxLayout(preview_frame)
        preview_layout.setContentsMargins(0,0,0,0)
        preview_layout.setSpacing(0)
        preview_layout.addWidget(self.video_frame, 1)
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
        self.timeline.clip_remove_requested.connect(self.on_clip_remove_requested)
        layout.addWidget(self.timeline)
        self.timer = QTimer()
        self.timer.setInterval(50)
        self.timer.timeout.connect(self.sync_playback)
        self.current_playing_clip = None
        self.undo_shortcut = QShortcut(QKeySequence("Ctrl+Z"), self)
        self.undo_shortcut.activated.connect(self.undo_action)
        self._ensure_overlay_widgets()
        self.logger.info("Application started.")
        if initial_file:
            self.load_initial_file(initial_file)

    def stop_export(self):
        if self.export_worker:
            self.export_worker.stop()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._resize_overlay()

    def on_clip_remove_requested(self, clip):
        self.selected_clip = clip
        self.delete_clip()

    def load_initial_file(self, file_path):
        if not self.input_file_path:
            QMessageBox.warning(self, "No Video Loaded", "Please load a video file before opening the advanced editor.")
            return
        if not os.path.exists(file_path):
            self.logger.error(f"Initial file not found: {file_path}")
            return
        duration = self.timeline.layers[0].run_probe_sync(file_path)
        if duration <= 0:
            self.logger.error(f"Could not get duration for {file_path}")
            return
        target_layer = self.timeline.layers[0]
        target_layer.add_clip(file_path, duration)
        self.logger.info(f"Loaded initial file {file_path} to layer 0")

    def upload_file(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "Open Media File", os.path.expanduser("~"), "Media Files (*.mp4 *.mov *.mkv *.avi *.mp3 *.wav)")
        if not file_path:
            return
        duration = self.timeline.layers[0].run_probe_sync(file_path)
        if duration <= 0:
            self.logger.error(f"Could not get duration for {file_path}")
            return
        target_layer = None
        for layer in self.timeline.layers:
            if not layer.clips:
                target_layer = layer
                break
        if target_layer is None:
            target_layer = self.timeline.add_layer()
        target_layer.add_clip(file_path, duration)
        self.logger.info(f"Uploaded {file_path} to layer {target_layer.layer_number}")

    def keyPressEvent(self, event: QKeyEvent):
        if event.key() == Qt.Key_Left or event.key() == Qt.Key_Right:
            modifiers = event.modifiers()
            if modifiers == Qt.ShiftModifier:
                seek_ms = 3000
            elif modifiers == Qt.ControlModifier:
                seek_ms = 100
            else:
                seek_ms = 1000
            if event.key() == Qt.Key_Left:
                seek_ms = -seek_ms
            current_pos_sec = self.timeline.ruler.playhead_pos_px / self.timeline.PIXELS_PER_SECOND
            new_pos_sec = max(0.0, current_pos_sec + (seek_ms / 1000.0))
            self.seek_timeline(new_pos_sec)
            self.logger.info(f"Seek {'Fwd' if seek_ms > 0 else 'Back'}: {new_pos_sec:.2f}s")
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
        layer = self.timeline.get_layer_of_clip(clip)
        self.inspector.set_clip(clip, layer)
        self.update_action_bar()

    def update_action_bar(self):
        enabled = self.selected_clip is not None
        self.inspector.btn_layer_up.setEnabled(enabled)
        self.inspector.btn_layer_down.setEnabled(enabled)
        self.inspector.btn_split.setEnabled(enabled)
        if enabled:
            layer = self.timeline.get_layer_of_clip(self.selected_clip)
            if layer:
                self.inspector.btn_layer_up.setEnabled(layer.layer_number > 0)
                self.inspector.btn_layer_down.setEnabled(layer.layer_number < len(self.timeline.layers) - 1)
        self.btn_undo.setEnabled(len(self.undo_stack) > 0)
        self.btn_delete.setEnabled(enabled)

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
            self.selected_clip.duration = self.selected_clip.original_duration / self.selected_clip.speed
            self.logger.info(f"Speed set to {self.selected_clip.speed}x for clip {self.selected_clip.uid}")
            layer = self.timeline.get_layer_of_clip(self.selected_clip)
            if layer:
                sorted_clips = sorted(layer.clips, key=lambda c: c.start_time)
                layer.clips = sorted_clips
                last_end_time = 0.0
                for clip in layer.clips:
                    clip.start_time = last_end_time
                    last_end_time += clip.duration
                layer.update()
                self.timeline.update_dimensions()
            self.refresh_layer()

    def set_selected_volume(self, volume):
        if self.selected_clip:
            self.save_state()
            self.selected_clip.volume = int(volume)
            self.logger.info(f"Volume set to {self.selected_clip.volume} for clip {self.selected_clip.uid}")
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
            sorted_clips = sorted(layer.clips, key=lambda c: c.start_time)
            layer.clips = sorted_clips
            last_end_time = 0.0
            for clip in layer.clips:
                clip.start_time = last_end_time
                last_end_time += clip.duration
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
        solo_layers = [l for l in self.timeline.layers if l.is_solo]
        search_layers = solo_layers if solo_layers else self.timeline.layers
        for layer in search_layers:
            if layer.is_muted:
                continue
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
        self.cancel_button.show()
        self._show_processing_overlay()
        self.export_worker = ExportWorker(self.base_dir, state, out_path)
        self.export_worker.progress.connect(self.on_export_progress)
        self.export_worker.progress.connect(lambda _, text: self._append_live_log(text))
        self.export_worker.finished.connect(self.on_export_finished)
        self.export_worker.error.connect(self.on_export_error)
        self.inspector.set_export_status("Starting export", 0)
        self.export_thread = threading.Thread(target=self.export_worker.run, daemon=True)
        self.export_thread.start()
        self.logger.info(f"Export started: {out_path}")

    def on_export_progress(self, pct, text):
        self.inspector.set_export_status(text, pct)

    def on_export_finished(self, out_path):
        self.cancel_button.hide()
        self._hide_processing_overlay()
        self.inspector.set_export_status(f"Export complete: {os.path.basename(out_path)}", 100)
        self.logger.info(f"Export finished: {out_path}")

    def on_export_error(self, msg):
        self.cancel_button.hide()
        self._hide_processing_overlay()
        self.inspector.set_export_status(f"Export error: {msg}", 0)
        self.logger.info(f"Export error: {msg}")

    def toggle_mute(self, checked):
        if self.selected_clip:
            layer = self.timeline.get_layer_of_clip(self.selected_clip)
            if layer:
                self.timeline.set_layer_muted(layer, checked)

    def toggle_solo(self, checked):
        if self.selected_clip:
            layer = self.timeline.get_layer_of_clip(self.selected_clip)
            if layer:
                self.timeline.set_layer_solo(layer, checked)

    def toggle_lock(self, checked):
        if self.selected_clip:
            layer = self.timeline.get_layer_of_clip(self.selected_clip)
            if layer:
                self.timeline.set_layer_locked(layer, checked)

def main():
    app = QApplication(sys.argv)
    initial_file = sys.argv[1] if len(sys.argv) > 1 else None
    editor = AdvancedEditor(initial_file=initial_file)
    editor.show()
    sys.exit(app.exec_())
if __name__ == '__main__':
    main()

# pip install PyQt5 python-vlc

import tempfile
import sys
import os
import subprocess
import json
import time
import re
import logging
from logging.handlers import RotatingFileHandler
import vlc
from PyQt5.QtGui import QFont, QColor, QPalette, QPainter
from PyQt5.QtWidgets import QSizePolicy
from PyQt5.QtCore import Qt, pyqtSignal, QThread, QUrl, QTimer, QCoreApplication
from PyQt5.QtWidgets import (QApplication, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
                             QLabel, QPushButton, QProgressBar, QSpinBox, QMessageBox,
                             QFrame, QFileDialog, QCheckBox, QDoubleSpinBox, QSlider, QStyle, QStyleOptionSlider, QDialog)

def setup_logger(base_dir):
    log_path = os.path.join(base_dir, "Fortnite-Video-Converter.log")
    logger = logging.getLogger("fvconv")
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        handler = RotatingFileHandler(log_path, maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8")
        fmt = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
        handler.setFormatter(fmt)
        logger.addHandler(handler)
    return logger
    
class ConfigManager:
    def __init__(self, file_path):
        self.file_path = file_path
        self.config = self.load_config()

    def load_config(self):
        try:
            with open(self.file_path, 'r') as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return {}

    def save_config(self, config_data):
        self.config = config_data
        try:
            with open(self.file_path, 'w') as f:
                json.dump(config_data, f, indent=4)
        except Exception as e:
            print(f"Error saving config file: {e}")

class TrimmedSlider(QSlider):
    def __init__(self, parent=None):
        super().__init__(Qt.Horizontal, parent)
        self.trimmed_start = None
        self.trimmed_end = None
        self.setStyleSheet("""
            QSlider::groove:horizontal {
                background: #4a667a;
                height: 8px;
                border-radius: 4px;
            }
            QSlider::handle:horizontal {
                background: #ffcc00;
                border: 2px solid #000000;
                width: 16px;
                margin: -6px 0;
                border-radius: 8px;
            }
            QSlider::sub-page:horizontal { background: transparent; border-radius: 4px; }
            QSlider::add-page:horizontal { background: transparent; border-radius: 4px; }
        """)
        self.sliderPressed.connect(self._on_pressed)
        self.sliderReleased.connect(self._on_released)
        self._is_pressed = False

    def _on_pressed(self):
        self._is_pressed = True

    def _on_released(self):
        self._is_pressed = False

    def set_trim_times(self, start, end):
        self.trimmed_start = start
        self.trimmed_end = end
        self.update()

    def paintEvent(self, event):
        super().paintEvent(event)
        if self.trimmed_start is None or self.trimmed_end is None:
            return
        opt = QStyleOptionSlider()
        self.initStyleOption(opt)
        groove = self.style().subControlRect(QStyle.CC_Slider, opt, QStyle.SC_SliderGroove, self)
        if groove.width() <= 0:
            h = 8
            top = (self.height() - h) // 2
            groove = QRect(8, top, self.width() - 16, h)
        minv, maxv = self.minimum(), self.maximum()
        def map_to_x(ms):
            if maxv == minv:
                return groove.left()
            ratio = (ms - minv) / float(maxv - minv)
            return int(groove.left() + ratio * groove.width())
        start_ms = int(self.trimmed_start * 1000)
        end_ms   = int(self.trimmed_end   * 1000)
        start_x  = map_to_x(start_ms)
        end_x    = map_to_x(end_ms)
        left_x, right_x = (start_x, end_x) if start_x <= end_x else (end_x, start_x)
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(200, 200, 200, 140))
        if left_x > groove.left():
            p.drawRect(groove.left(), groove.top(), left_x - groove.left(), groove.height())
        if right_x < groove.right():
            p.drawRect(right_x, groove.top(), groove.right() - right_x + 1, groove.height())
        p.setBrush(QColor(46, 204, 113, 180))
        p.drawRect(left_x, groove.top(), max(0, right_x - left_x), groove.height())
        bar_w = 3
        p.setBrush(QColor(30, 200, 255))  # start
        p.drawRect(start_x - bar_w // 2, groove.top() - 2, bar_w, groove.height() + 4)
        p.setBrush(QColor(255, 150, 30))  # end
        p.drawRect(end_x - bar_w // 2, groove.top() - 2, bar_w, groove.height() + 4)

    def map_value_to_pixel(self, value):
        style = QApplication.style()
        style_option = QStyleOptionSlider()
        self.initStyleOption(style_option)
        style_option.initFrom(self)
        style_option.orientation = self.orientation()
        style_option.minimum = self.minimum()
        style_option.maximum = self.maximum()
        style_option.sliderPosition = value
        return style.sliderPositionFromValue(style_option.minimum, style_option.maximum, value, self.width())

class VideoCompressorApp(QWidget):
    progress_update_signal = pyqtSignal(int)
    status_update_signal = pyqtSignal(str)
    process_finished_signal = pyqtSignal(bool, str)

    def __init__(self, file_path=None):
        super().__init__()
        self.trim_start = None
        self.trim_end = None
        self.input_file_path = None
        self.original_duration = 0.0
        self.original_resolution = ""
        self.is_processing = False
        self.script_dir = os.path.dirname(sys.executable) if getattr(sys, 'frozen', False) else os.path.dirname(
            os.path.abspath(__file__))
        self.logger = setup_logger(self.script_dir)
        self.logger.info("=== Application started ===")
        self.config_manager = ConfigManager(os.path.join(self.script_dir, 'config.json'))
        self.last_dir = self.config_manager.config.get('last_directory', os.path.expanduser('~'))
        vlc_args = ['--no-xlib', '--no-video-title-show', '--no-plugins-cache', '--verbose=-1']
        self.vlc_instance = vlc.Instance(vlc_args)
        self.vlc_player = self.vlc_instance.media_player_new()
        self.timer = QTimer(self)
        self.timer.setInterval(100)
        self.timer.timeout.connect(self.update_player_state)
        self.setWindowTitle("Fortnite Video Compressor")
        geom = self.config_manager.config.get('window_geometry')
        if geom and isinstance(geom, dict):
            x = geom.get('x', 100)
            y = geom.get('y', 100)
            w = geom.get('w', 700)
            h = geom.get('h', 700)
            self.setGeometry(x, y, w, h)
        else:
            self.setGeometry(100, 100, 900, 700)
        self.set_style()
        self.init_ui()
        if file_path:
            self.handle_file_selection(file_path)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Space:
            self.toggle_play()
            event.accept()
        else:
            super().keyPressEvent(event)

    def _on_trim_spin_changed(self):
        start = (self.start_minute_input.value() * 60) + self.start_second_input.value()
        end   = (self.end_minute_input.value()   * 60) + self.end_second_input.value()
        if self.original_duration:
            start = max(0.0, min(start, self.original_duration))
            end   = max(0.0, min(end,   self.original_duration))
        self.trim_start, self.trim_end = start, end
        self.positionSlider.set_trim_times(self.trim_start, self.trim_end)

    def set_style(self):
        self.setStyleSheet("""
            QWidget {
                background-color: #2c3e50;
                color: #ecf0f1;
                font-family: "Helvetica Neue", Arial, sans-serif;
            }
            QLabel {
                font-size: 14px;
                padding: 5px;
            }
            QFrame#dropArea {
                border: 3px dashed #3498db;
                border-radius: 10px;
                background-color: #34495e;
                padding: 20px;
            }
            QSpinBox, QDoubleSpinBox, QSlider {
                background-color: #4a667a;
                border: 1px solid #3498db;
                border-radius: 5px;
                padding: 6px;
                color: #ecf0f1;
                font-size: 13px;
            }
            QPushButton {
                background-color: #3498db;
                color: #ffffff;
                border: none;
                padding: 10px 18px;
                border-radius: 8px;
                font-weight: bold;
            }
            QPushButton:hover { background-color: #2980b9; }
            QPushButton#WhatsappButton { background-color: #25D366; }
            QPushButton#DoneButton { background-color: #e74c3c; }
            QProgressBar { border: 1px solid #3498db; border-radius: 5px; text-align: center; height: 22px; }
            QProgressBar::chunk { background-color: #2ecc71; }
        """)

    def init_ui(self):
        main_layout = QHBoxLayout()
        left_layout = QVBoxLayout()
        left_layout.setSpacing(12)
        self.video_frame = QFrame()
        self.video_frame.setStyleSheet("background-color: black;")
        self.video_frame.setMinimumSize(768, 576)
        self.video_frame.setFocusPolicy(Qt.StrongFocus)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setFocusProxy(self.video_frame)
        left_layout.addWidget(self.video_frame)
        self.positionSlider = TrimmedSlider(self)
        self.positionSlider.setRange(0, 0)
        self.positionSlider.sliderMoved.connect(self.set_vlc_position)
        left_layout.addWidget(self.positionSlider)
        self.playPauseButton = QPushButton("Play")
        self.playPauseButton.setIcon(self.style().standardIcon(QStyle.SP_MediaPlay))
        self.playPauseButton.clicked.connect(self.toggle_play)
        self.playPauseButton.setFocusPolicy(Qt.NoFocus)
        self.playPauseButton.setStyleSheet("""
            QPushButton {
                background-color: #59A06D;
                color: white;
                font-size: 16px;
                padding: 8px 16px;
                border-radius: 6px;
            }
            QPushButton:hover {
                background-color: #6fb57f;
            }
            QPushButton:pressed {
                background-color: #4a865a;
            }
        """)

        left_layout.addWidget(self.playPauseButton)
        trim_layout = QHBoxLayout()
        self.start_minute_input = QSpinBox()
        self.start_minute_input.setPrefix("Start Min: ")
        self.start_minute_input.setRange(0, 0)
        self.start_second_input = QSpinBox()
        self.start_second_input.setPrefix("Sec: ")
        self.start_second_input.setRange(0, 59)
        self.end_minute_input = QSpinBox()
        self.end_minute_input.setPrefix("End Min: ")
        self.end_minute_input.setRange(0, 0)
        self.end_second_input = QSpinBox()
        self.end_second_input.setPrefix("Sec: ")
        self.end_second_input.setRange(0, 59)
        self.start_minute_input.valueChanged.connect(self._on_trim_spin_changed)
        self.start_second_input.valueChanged.connect(self._on_trim_spin_changed)
        self.end_minute_input.valueChanged.connect(self._on_trim_spin_changed)
        self.end_second_input.valueChanged.connect(self._on_trim_spin_changed)
        self.start_trim_button = QPushButton("Set Start Trim")
        self.start_trim_button.clicked.connect(self.set_start_time)
        self.start_trim_button.setFocusPolicy(Qt.NoFocus)
        self.end_trim_button = QPushButton("Set End Trim")
        self.end_trim_button.clicked.connect(self.set_end_time)
        self.end_trim_button.setFocusPolicy(Qt.NoFocus)
        trim_layout.addWidget(self.start_minute_input)
        trim_layout.addWidget(self.start_second_input)
        trim_layout.addWidget(self.start_trim_button)
        trim_layout.addSpacing(20)
        trim_layout.addWidget(self.end_minute_input)
        trim_layout.addWidget(self.end_second_input)
        trim_layout.addWidget(self.end_trim_button)
        left_layout.addLayout(trim_layout)
        self.status_label = QLabel("Status: Ready")
        self.status_label.setStyleSheet("color: white; font-size: 13px; padding: 4px;")
        left_layout.addWidget(self.status_label)
        self.status_update_signal.connect(self.status_label.setText)
        self.duration_label = QLabel("Duration: N/A | Resolution: N/A")
        self.duration_label.setStyleSheet("color: lightgray; font-size: 13px; padding: 4px;")
        left_layout.addWidget(self.duration_label)
        process_controls = QHBoxLayout()
        self.mobile_checkbox = QCheckBox("Mobile Format (Portrait Video)")
        self.mobile_checkbox.setStyleSheet("font-size: 18px; font-weight: bold;")
        process_controls.addWidget(self.mobile_checkbox, alignment=Qt.AlignLeft)
        process_controls.addStretch(1)
        center_group = QHBoxLayout()
        self.process_button = QPushButton("Process Video")
        self.process_button.setFixedSize(240, 80)
        self.process_button.setStyleSheet("""
            QPushButton {
                background-color: #148c14;
                color: black;
                font-weight: bold;
                font-size: 16px;
                border-radius: 10px;
            }
            QPushButton:hover {
                background-color: #c8f7c5;
            }
        """)
        self.process_button.clicked.connect(self.start_processing)
        self.process_button.setEnabled(False)
        center_group.addWidget(self.process_button, alignment=Qt.AlignVCenter)
        self.speed_spinbox = QDoubleSpinBox()
        self.speed_spinbox.setPrefix("Speed x")
        self.speed_spinbox.setDecimals(1)
        self.speed_spinbox.setSingleStep(0.1)
        self.speed_spinbox.setValue(1.1)
        self.speed_spinbox.setStyleSheet("font-size: 14px;")
        center_group.addWidget(self.speed_spinbox, alignment=Qt.AlignVCenter)
        process_controls.addLayout(center_group)
        process_controls.addStretch(1)
        left_layout.addLayout(process_controls, stretch=0)
        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        left_layout.addWidget(self.progress_bar)
        self.progress_update_signal.connect(self.progress_bar.setValue)
        right_layout = QVBoxLayout()
        right_layout.setSpacing(12)
        right_inner_layout = QVBoxLayout()
        self.drop_area = DropAreaFrame()
        self.drop_area.setObjectName("dropArea")
        self.drop_area.file_dropped.connect(self.handle_file_selection)
        drop_layout = QVBoxLayout(self.drop_area)
        self.drop_label = QLabel("Drag & Drop\r\nVideo File Here:")
        self.drop_label.setAlignment(Qt.AlignCenter)
        drop_layout.addWidget(self.drop_label)
        self.drop_area.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Expanding)
        right_inner_layout.addWidget(self.drop_area, stretch=10)
        self.upload_button = QPushButton("📂 Click Here\r\n to Upload a Video File")
        self.upload_button.clicked.connect(self.select_file)
        self.upload_button.setFocusPolicy(Qt.NoFocus)
        self.upload_button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        right_inner_layout.addWidget(self.upload_button, alignment=Qt.AlignBottom)
        right_layout.addLayout(right_inner_layout)
        main_layout.addLayout(left_layout, stretch=6)
        main_layout.addLayout(right_layout, stretch=0)
        self.setLayout(main_layout)

    def update_player_state(self):
        if self.vlc_player:
            current_time = self.vlc_player.get_time()
            if current_time >= 0:
                if not getattr(self.positionSlider, "_is_pressed", False):
                    self.positionSlider.blockSignals(True)
                    self.positionSlider.setValue(current_time)
                    self.positionSlider.blockSignals(False)
            if self.vlc_player.is_playing():
                self.playPauseButton.setText("Pause")
                self.playPauseButton.setIcon(self.style().standardIcon(QStyle.SP_MediaPause))
            else:
                self.playPauseButton.setText("Play")
                self.playPauseButton.setIcon(self.style().standardIcon(QStyle.SP_MediaPlay))

    def toggle_play(self):
        if self.vlc_player.is_playing():
            self.vlc_player.pause()
            self.playPauseButton.setText("Play")
            self.playPauseButton.setIcon(self.style().standardIcon(QStyle.SP_MediaPlay))
        else:
            self.vlc_player.play()
            self.playPauseButton.setText("Pause")
            self.playPauseButton.setIcon(self.style().standardIcon(QStyle.SP_MediaPause))
        if not self.timer.isActive():
            self.timer.start(100)

    def set_vlc_position(self, position):
        try:
            p = int(position)
        except Exception:
            p = position
        self.vlc_player.set_time(p)

    def set_start_time(self):
        pos_ms = self.vlc_player.get_time()
        pos_s = pos_ms / 1000.0
        if self.original_duration and pos_s >= self.original_duration:
            pos_s = max(0.0, self.original_duration - 0.1)
        self.trim_start = pos_s
        self._update_trim_widgets_from_trim_times()
        self.positionSlider.set_trim_times(self.trim_start, self.trim_end)

    def set_end_time(self):
        pos_ms = self.vlc_player.get_time()
        pos_s = pos_ms / 1000.0
        if self.original_duration and pos_s > self.original_duration:
            pos_s = self.original_duration
        self.trim_end = pos_s
        self._update_trim_widgets_from_trim_times()
        self.positionSlider.set_trim_times(self.trim_start, self.trim_end)
        if self.vlc_player.is_playing():
            self.vlc_player.pause()
            self.playPauseButton.setText("Play")
            self.playPauseButton.setIcon(self.style().standardIcon(QStyle.SP_MediaPlay))

    def _update_trim_widgets_from_trim_times(self):
        if self.trim_start is not None:
            start_total = int(round(self.trim_start))
            sm = start_total // 60
            ss = start_total % 60
            self.start_minute_input.setValue(sm)
            self.start_second_input.setValue(ss)
        if self.trim_end is not None:
            end_total = int(round(self.trim_end))
            em = end_total // 60
            es = end_total % 60
            self.end_minute_input.setValue(em)
            self.end_second_input.setValue(es)

    def select_file(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "Select Video File", self.last_dir,
                                                   "Video Files (*.mp4 *.mkv *.mov *.avi)")
        if file_path:
            self.handle_file_selection(file_path)

    def handle_file_selection(self, file_path):
        self.input_file_path = file_path
        self.drop_label.setWordWrap(True)
        self.drop_label.setText(f"{os.path.basename(self.input_file_path)}")
        #self.file_label.setText(f"File: {self.input_file_path}")
        dir_path = os.path.dirname(file_path)
        if os.path.isdir(dir_path):
            self.last_dir = dir_path
        cfg = dict(self.config_manager.config)
        cfg['last_directory'] = self.last_dir
        self.config_manager.save_config(cfg)
        media = self.vlc_instance.media_new(QUrl.fromLocalFile(self.input_file_path).toLocalFile())
        self.vlc_player.set_media(media)
        if sys.platform == 'win32':
            self.vlc_player.set_hwnd(self.video_frame.winId())
        elif sys.platform == 'darwin':
            self.vlc_player.set_nsobject(int(self.video_frame.winId()))
        else:
            self.vlc_player.set_xid(int(self.video_frame.winId()))
        self.vlc_player.play()
        time.sleep(0.5)
        video_duration_ms = self.vlc_player.get_length()
        if video_duration_ms > 0:
            self.positionSlider.setRange(0, video_duration_ms)
            self.original_duration = video_duration_ms / 1000.0
            total_minutes = int(self.original_duration) // 60
            self.start_minute_input.setRange(0, total_minutes)
            self.end_minute_input.setRange(0, total_minutes)
        self.timer.start(100)
        self.get_video_info()
        self.video_frame.setFocus()  # ensure Space goes to keyPressEvent/toggle_play

    def set_status_text_with_color(self, text, color="white"):
        self.status_label.setStyleSheet(f"color: {color};")
        self.status_label.setText(text)

    def get_video_info(self):
        if not self.input_file_path or not os.path.exists(self.input_file_path):
            self.show_message("Error", "No valid video file selected.")
            return
        self.set_status_text_with_color("Analyzing video...", "white")
        try:
            ffprobe_path = os.path.join(self.script_dir, 'ffprobe.exe')
            cmd = [
                ffprobe_path, '-v', 'error', '-select_streams', 'v:0',
                '-show_entries', 'stream=width,height', '-of', 'csv=p=0:s=x',
                self.input_file_path
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, check=True,
                                    creationflags=subprocess.CREATE_NO_WINDOW)
            self.original_resolution = result.stdout.strip()
            if self.original_resolution not in ["1920x1080", "2560x1440", "3840x2160"]:
                error_message = "This software is designed for 1080p/1440p/4K inputs."
                self.set_status_text_with_color(error_message, "red")
                self.process_button.setEnabled(False)
                self.duration_label.setText(f"Duration: N/A | Resolution: {self.original_resolution}")
                return
            self.duration_label.setText(
                f"Duration: {self.original_duration:.0f} s | Resolution: {self.original_resolution}")
            self.trim_start = 0.0
            self.trim_end = self.original_duration
            self._update_trim_widgets_from_trim_times()
            self.positionSlider.set_trim_times(self.trim_start, self.trim_end)
            self.set_status_text_with_color("Video loaded successfully.", "white")
        except subprocess.CalledProcessError as e:
            self.set_status_text_with_color(f"Error running ffprobe: {e}", "red")
        except FileNotFoundError:
            self.set_status_text_with_color("ffprobe.exe not found.", "red")
        self.process_button.setEnabled(True)

    def show_message(self, title, message):
        msg_box = QMessageBox()
        msg_box.setIcon(QMessageBox.Information)
        msg_box.setWindowTitle(title)
        msg_box.setText(message)
        msg_box.exec_()

    def start_processing(self):
        """
        Starts the video processing sequence in a separate process to keep the UI responsive.
        """
        if self.is_processing:
            self.show_message("Info", "A video is already being processed. Please wait.")
            return
        if not self.input_file_path or not os.path.exists(self.input_file_path):
            self.show_message("Error", "Please select a valid video file first.")
            return
        if self.original_resolution not in ["1920x1080", "2560x1440", "3840x2160"]:
            self.set_status_text_with_color("Unsupported input resolution.", "red")
            return
        start_time = (self.start_minute_input.value() * 60) + self.start_second_input.value()
        end_time = (self.end_minute_input.value() * 60) + self.end_second_input.value()
        is_mobile_format = self.mobile_checkbox.isChecked()
        speed_factor = self.speed_spinbox.value()
        if start_time < 0 or end_time < 0 or start_time >= end_time or end_time > self.original_duration:
            self.show_message("Error",
                              "Invalid start and end times. Please ensure end time > start time and within video duration.")
            return
        self.is_processing = True
        self.process_button.setEnabled(False)
        self.set_status_text_with_color("Processing video... Please wait.", "white")
        self.progress_update_signal.emit(0)
        self.process_thread = ProcessThread(
            self.input_file_path,
            start_time,
            end_time,
            self.original_resolution,
            is_mobile_format,
            speed_factor,
            self.script_dir,
            self.progress_update_signal,
            self.status_update_signal,
            self.process_finished_signal,
            self.logger
        )
        self.process_thread.finished_signal.connect(self.on_process_finished)
        self.process_thread.start()

    def reset_app_state(self):
        """Resets the UI and state so a new file can be loaded fresh."""
        self.input_file_path = None
        self.original_resolution = None
        self.trim_start = 0.0
        self.trim_end = 0.0
        self.duration_label.setText("Duration: N/A | Resolution: N/A")
        self.process_button.setEnabled(False)
        self.progress_update_signal.emit(0)
        self.set_status_text_with_color("Please upload a new video file.", "white")
        try:
            self.positionSlider.setRange(0, 0)
            self.positionSlider.setValue(0)
            self.positionSlider.set_trim_times(0, 0)
        except AttributeError:
            pass
        self.drop_label.setText("Drag & Drop\r\nVideo File Here:")
    
    def handle_new_file(self):
        """Clear state and immediately open file picker."""
        self.reset_app_state()
        self.select_file()

    def on_process_finished(self, success, message):
        button_size = (185, 45)
        self.is_processing = False
        self.process_button.setEnabled(True)
        self.status_update_signal.emit("Ready to process another video.")
        try:
            if success:
                orig_size = os.path.getsize(self.input_file_path) if self.input_file_path and os.path.exists(self.input_file_path) else 0
                new_size  = os.path.getsize(message) if message and os.path.exists(message) else 0
                self.logger.info(f"RESULT: SUCCESS | file='{os.path.basename(self.input_file_path)}' | "
                                f"original_size_bytes={orig_size} | new_size_bytes={new_size}")
            else:
                self.logger.error(f"RESULT: FAILURE | file='{os.path.basename(self.input_file_path) if self.input_file_path else 'N/A'}' | details={message}")
        except Exception:
            pass
        if success:
            output_dir = os.path.dirname(message)
            dialog = QDialog(self)
            dialog.setWindowTitle("Done! Video Processed Successfully!")
            dialog.setModal(True)
            dialog.resize(int(self.width() * 0.5), 100)
            layout = QVBoxLayout(dialog)
            label = QLabel(f"File saved to:\n{message}")
            layout.addWidget(label)
            grid = QGridLayout()
            grid.setSpacing(40)
            grid.setContentsMargins(30, 50, 30, 50)
            whatsapp_button = QPushButton("✆   Share via Whatsapp   ✆")
            whatsapp_button.setFixedSize(*button_size)
            whatsapp_button.setStyleSheet("background-color: #328742; color: white;")
            whatsapp_button.clicked.connect(lambda: (self.share_via_whatsapp(), QTimer.singleShot(200, QCoreApplication.instance().quit)))
            open_folder_button = QPushButton("Open Output Folder")
            open_folder_button.setFixedSize(*button_size)
            open_folder_button.setStyleSheet("background-color: #6c5f9e; color: white;")
            open_folder_button.clicked.connect(lambda: (self.open_folder(os.path.dirname(message)), QTimer.singleShot(200, QCoreApplication.instance().quit)))
            new_file_button = QPushButton("📂   Upload a New File   📂")
            new_file_button.setFixedSize(*button_size)
            new_file_button.setStyleSheet("background-color: #6c5f9e; color: white;")
            new_file_button.clicked.connect(lambda: (self.handle_new_file(), dialog.accept()))
            grid.addWidget(whatsapp_button, 0, 0, alignment=Qt.AlignCenter)
            grid.addWidget(open_folder_button, 0, 1, alignment=Qt.AlignCenter)
            grid.addWidget(new_file_button, 0, 2, alignment=Qt.AlignCenter)
            done_button = QPushButton("Done")
            done_button.setFixedSize(*button_size)
            done_button.setStyleSheet("background-color: #821e1e; color: white; padding: 8px 16px;")
            done_button.clicked.connect(dialog.accept)
            grid.addWidget(done_button, 1, 0, 1, 3, alignment=Qt.AlignCenter)
            finished_button = QPushButton("Close The App!\r\n(Exit)")
            finished_button.setFixedSize(*button_size)
            finished_button.setStyleSheet("background-color: #c90e0e; color: white; padding: 8px 16px;")
            finished_button.clicked.connect(QCoreApplication.instance().quit)
            grid.addWidget(finished_button, 2, 0, 1, 3, alignment=Qt.AlignCenter)
            layout.addLayout(grid)
            dialog.setLayout(layout)
            dialog.exec_()
        else:
            self.show_message("Error", "Video processing failed.\n" + message)

    def closeEvent(self, event):
        """Saves the window position and size before closing."""
        cfg = self.config_manager.config
        cfg['window_geometry'] = {
            'x': self.geometry().x(),
            'y': self.geometry().y(),
            'w': self.geometry().width(),
            'h': self.geometry().height()
        }
        self.config_manager.save_config(cfg)
        super().closeEvent(event)

    def show_message(self, title, message):
        """
        Displays a custom message box instead of alert().
        """
        msg_box = QMessageBox(self)
        msg_box.setWindowTitle(title)
        msg_box.setText(message)
        msg_box.exec_()

    def open_folder(self, path):
        """
        Opens the specified folder using the default file explorer.
        """
        if os.path.exists(path):
            try:
                if sys.platform == 'win32':
                    os.startfile(path, 'explore')
                elif sys.platform == 'darwin':
                    subprocess.Popen(['open', path])
                else:
                    subprocess.Popen(['xdg-open', path])
            except Exception as e:
                self.show_message("Error", f"Failed to open folder. Please navigate to {path} manually. Error: {e}")

    def share_via_whatsapp(self):
        """
        Opens a web browser to the WhatsApp Web URL.
        """
        url = "https://web.whatsapp.com"
        try:
            if sys.platform == 'win32':
                os.startfile(url)
            elif sys.platform == 'darwin':
                subprocess.Popen(['open', url])
            else:
                subprocess.Popen(['xdg-open', url])
        except Exception as e:
            self.show_message("Error", f"Failed to open WhatsApp. Please visit {url} manually. Error: {e}")

class ProcessThread(QThread):
    def __init__(self, input_path, start_time, end_time, original_resolution, is_mobile_format, speed_factor,
                 script_dir, progress_update_signal, status_update_signal, finished_signal, logger):
        super().__init__()
        self.input_path = input_path
        self.start_time = start_time
        self.end_time = end_time
        self.duration = end_time - start_time
        self.original_resolution = original_resolution
        self.is_mobile_format = is_mobile_format
        self.speed_factor = speed_factor
        self.script_dir = script_dir
        self.progress_update_signal = progress_update_signal
        self.status_update_signal = status_update_signal
        self.finished_signal = finished_signal
        self.logger = logger
        self.start_time_corrected = self.start_time / self.speed_factor if self.speed_factor != 1.0 else self.start_time
        self.duration_corrected = (self.end_time - self.start_time) / self.speed_factor if self.speed_factor != 1.0 else (self.end_time - self.start_time)

    def get_total_frames(self):
        ffprobe_path = os.path.join(self.script_dir, 'ffprobe.exe')
        cmd = [
            ffprobe_path, '-v', 'error', '-select_streams', 'v:0',
            '-show_entries', 'stream=nb_frames', '-of', 'json',
            '-read_intervals', f'{self.start_time_corrected}%+{self.duration_corrected}',
            self.input_path
        ]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, check=True,
                                    creationflags=subprocess.CREATE_NO_WINDOW)
            data = json.loads(result.stdout)
            if 'streams' in data and len(data['streams']) > 0 and 'nb_frames' in data['streams'][0]:
                return int(data['streams'][0]['nb_frames'])
            elif 'format' in data and 'nb_streams' in data['format'] and 'nb_frames' in data['format']:
                return int(data['format']['nb_frames'])
            else:
                return None
        except (subprocess.CalledProcessError, json.JSONDecodeError, KeyError):
            return None

    def run(self):
        temp_dir = tempfile.gettempdir()
        temp_log_path = os.path.join(temp_dir, f"ffmpeg2pass-{os.getpid()}-{int(time.time())}.log")
        try:
            if self.speed_factor != 1.0:
                start_time_corrected = self.start_time / self.speed_factor
                end_time_corrected = self.end_time / self.speed_factor
                duration_corrected = end_time_corrected - start_time_corrected
                self.status_update_signal.emit(f"Adjusting trim times for speed factor {self.speed_factor}x.")
            else:
                start_time_corrected = self.start_time
                end_time_corrected = self.end_time
                duration_corrected = self.end_time - self.start_time
            self.start_time_corrected = start_time_corrected
            self.duration_corrected = duration_corrected
            TARGET_MB = 50.0
            AUDIO_KBPS = 128
            try:
                target_file_size_bits = TARGET_MB * 8 * 1024 * 1024
                audio_bits = AUDIO_KBPS * 1024 * duration_corrected
                video_bits = target_file_size_bits - audio_bits
                if video_bits < 0:
                    self.finished_signal.emit(False, "Video duration is too short for the target file size.")
                    return
                video_bitrate_kbps = video_bits / (1024 * duration_corrected)
            except ZeroDivisionError:
                self.finished_signal.emit(False, "Selected video duration is zero.")
                return
            self.status_update_signal.emit(f"Calculated target bitrate: {video_bitrate_kbps:.2f} kbps.")
            total_frames = self.get_total_frames()
            if total_frames is None:
                self.status_update_signal.emit("Could not determine total frames. Progress bar might be inaccurate.")
            video_filter_cmd = ""
            healthbar_crop_string = ""
            loot_area_crop_string = ""
            stats_area_crop_string = ""
            HB_UP_1440 = 8
            hb_1440   = (370, 65, 60, max(0, 1325 - HB_UP_1440))
            loot_1440 = (440, 133, 2160, 1288)
            stats_1440 = (280, 31, 2264, 270)
            def scale_box(box, s):
                return tuple(int(round(v * s)) for v in box)
            if self.original_resolution == "1920x1080":
                hb    = scale_box(hb_1440, 0.75)
                loot  = scale_box(loot_1440, 0.75)
                stats = scale_box(stats_1440, 0.75)
            elif self.original_resolution == "2560x1440":
                hb, loot, stats = hb_1440, loot_1440, stats_1440
            elif self.original_resolution == "3840x2160":
                hb    = scale_box(hb_1440, 1.5)
                loot  = scale_box(loot_1440, 1.5)
                stats = scale_box(stats_1440, 1.5)
            else:
                hb, loot, stats = hb_1440, loot_1440, stats_1440
            healthbar_crop_string  = f"{hb[0]}:{hb[1]}:{hb[2]}:{hb[3]}"
            loot_area_crop_string  = f"{loot[0]}:{loot[1]}:{loot[2]}:{loot[3]}"
            stats_area_crop_string = f"{stats[0]}:{stats[1]}:{stats[2]}:{stats[3]}"
            s = 0.75 if self.original_resolution == "1920x1080" else (1.5 if self.original_resolution == "3840x2160" else 1.0)
            healthbar_scaled_width  = int(round(370 * 0.85 * 2 * s))
            healthbar_scaled_height = int(round(65  * 0.85 * 2 * s))
            loot_scaled_width       = int(round(440 * 0.85 * 1.3 * 1.2 * s))
            loot_scaled_height      = int(round(133 * 0.85 * 1.3 * 1.2 * s))
            stats_scaled_width  = int(round(stats[0] * 1.8 * s))
            stats_scaled_height = int(round(stats[1] * 1.8 * s))
            main_width  = 1150
            main_height = 1920
            if self.is_mobile_format:
                HB_OVERLAY_UP_1440 = 14
                hb_overlay_up = int(round(HB_OVERLAY_UP_1440 * s))
                hb_overlay_y  = max(0, int(round(main_height - healthbar_scaled_height - hb_overlay_up)))
                loot_overlay_x = int(round(main_width - loot_scaled_width - 85))
                loot_overlay_y = int(round(main_height - loot_scaled_height + 70))
                STATS_MARGIN_ABOVE_1440 = 8
                stats_margin = int(round(STATS_MARGIN_ABOVE_1440 * s))
                stats_overlay_x = int(round((main_width - stats_scaled_width) / 2))
                base_y = min(hb_overlay_y, loot_overlay_y)
                stats_overlay_y = max(0, base_y - stats_scaled_height - stats_margin)
                video_filter_cmd = (
                    f"split=4[main][lootbar][healthbar][stats];"
                    f"[main]scale={main_width}:{main_height}:force_original_aspect_ratio=increase,crop={main_width}:{main_height}[main_cropped];"
                    f"[lootbar]crop={loot_area_crop_string},scale={loot_scaled_width * 1.2:.0f}:{loot_scaled_height * 1.2:.0f},format=yuva444p,colorchannelmixer=aa=0.8[lootbar_scaled];"
                    f"[healthbar]crop={healthbar_crop_string},scale={healthbar_scaled_width * 1.1:.0f}:{healthbar_scaled_height * 1.1:.0f},format=yuva444p,colorchannelmixer=aa=0.8[healthbar_scaled];"
                    f"[stats]crop={stats_area_crop_string},scale={stats_scaled_width}:{stats_scaled_height},format=yuva444p,colorchannelmixer=aa=0.7[stats_scaled];"
                    f"[main_cropped][lootbar_scaled]overlay={loot_overlay_x}:{loot_overlay_y}[t1];"
                    f"[t1][healthbar_scaled]overlay=-100:{hb_overlay_y}[t2];"
                    f"[t2][stats_scaled]overlay={stats_overlay_x}:{stats_overlay_y}"
                )
                self.logger.info(f"Mobile portrait mode: loot={loot_area_crop_string}, health={healthbar_crop_string}, "
                                f"stats={stats_area_crop_string}, alpha=0.8, hb_up={hb_overlay_up}px, "
                                f"stats_xy=({stats_overlay_x},{stats_overlay_y})")
                self.status_update_signal.emit("Optimizing for mobile: Applying portrait crop.")
            else:
                original_width, original_height = map(int, self.original_resolution.split('x'))
                target_resolution = f"scale='min(1920,iw)':-2"
                if video_bitrate_kbps < 800 and original_height > 720:
                    target_resolution = f"scale='min(1280,iw)':-2"
                    self.status_update_signal.emit("Low bitrate detected. Scaling to 720p.")
                video_filter_cmd = f"fps=60,{target_resolution}"
            if self.speed_factor != 1.0:
                speed_filter = f"setpts=PTS/{self.speed_factor}"
                if video_filter_cmd:
                    video_filter_cmd = f"{video_filter_cmd},{speed_filter}"
                else:
                    video_filter_cmd = speed_filter
                self.status_update_signal.emit(f"Applying speed factor: {self.speed_factor}x to video.")
            audio_filter_cmd = ""
            if self.speed_factor != 1.0:
                audio_filter_cmd = f"atempo={self.speed_factor}"
                self.status_update_signal.emit(f"Applying speed factor: {self.speed_factor}x to audio.")
                self.logger.info(f"Audio atempo set to {self.speed_factor}")
            output_dir = os.path.join(self.script_dir, "Output_Video_Files")
            if not os.path.exists(output_dir):
                os.makedirs(output_dir)
            i = 1
            while True:
                output_file_name = f"Fortnite-Video-{i}.mp4"
                output_path = os.path.join(output_dir, output_file_name)
                if not os.path.exists(output_path):
                    break
                i += 1
            ffmpeg_path = os.path.join(self.script_dir, 'ffmpeg.exe')
            frame_regex = re.compile(r'frame=\s*(\d+)')
            self.progress_update_signal.emit(0)
            self.status_update_signal.emit("Processing video (NVENC VBR HQ)...")
            cmd = [
                ffmpeg_path, '-y',
                '-hwaccel', 'auto',
                '-i', self.input_path,
                '-ss', str(start_time_corrected), '-t', str(duration_corrected),
                '-c:v', 'h264_nvenc', '-rc', 'vbr_hq', '-b:v', f'{video_bitrate_kbps}k',
                '-maxrate', f'{int(video_bitrate_kbps*1.5)}k', '-bufsize', f'{int(video_bitrate_kbps*2)}k',
                '-c:a', 'aac', '-b:a', f'{AUDIO_KBPS}k',
                '-loglevel', 'info'
            ]
            if self.is_mobile_format:
                cmd.extend(['-filter_complex', video_filter_cmd])
            elif video_filter_cmd:
                cmd.extend(['-vf', video_filter_cmd])
            if audio_filter_cmd:
                cmd.extend(['-af', audio_filter_cmd])
            cmd.append(output_path)
            self.logger.info(f"FFmpeg CMD: {' '.join(map(str, cmd))}")
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                creationflags=(subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0)
            )
            for line in proc.stdout:
                self.logger.info(f"FFmpeg: {line.strip()}")
                frame_match = frame_regex.search(line)
                if frame_match and total_frames:
                    current_frame = int(frame_match.group(1))
                    progress = int((current_frame / total_frames) * 100)
                    self.progress_update_signal.emit(progress)
            proc.wait()
            if proc.returncode != 0:
                raise subprocess.CalledProcessError(proc.returncode, cmd)
            self.progress_update_signal.emit(100)
            if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
                self.logger.info(f"Job SUCCESS | start={self.start_time}s end={self.end_time}s | "
                                f"res={self.original_resolution} | mobile={self.is_mobile_format} | "
                                f"speed={self.speed_factor}x | output={output_path}")
                self.finished_signal.emit(True, output_path)
            else:
                self.logger.error("Job FAILURE: Output file missing or empty.")
                self.finished_signal.emit(False, "Output file was created, but it's empty.")
        except Exception as e:
            self.logger.exception(f"Job FAILURE with exception: {e}")
            self.finished_signal.emit(False, f"An unexpected error occurred: {e}.")
        finally:
            for ext in ["", "-0.log", "-1.log", ".log", ".log-0.log", ".log-1.log"]:
                try:
                    os.remove(temp_log_path.replace(".log", ext))
                except Exception:
                    pass

class DropAreaFrame(QFrame):
    file_dropped = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        for url in event.mimeData().urls():
            file_path = url.toLocalFile()
            if os.path.isfile(file_path):
                self.file_dropped.emit(file_path)
                return

if __name__ == "__main__":
    script_dir = os.path.dirname(sys.executable) if getattr(sys, 'frozen', False) else os.path.dirname(
        os.path.abspath(__file__))
    ffmpeg_path = os.path.join(script_dir, 'ffmpeg.exe')
    ffprobe_path = os.path.join(script_dir, 'ffprobe.exe')
    try:
        subprocess.run([ffmpeg_path, '-version'], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                       creationflags=subprocess.CREATE_NO_WINDOW)
        subprocess.run([ffprobe_path, '-version'], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                       creationflags=subprocess.CREATE_NO_WINDOW)
    except FileNotFoundError:
        msg_box = QMessageBox()
        msg_box.setIcon(QMessageBox.Critical)
        msg_box.setWindowTitle("Dependency Error")
        msg_box.setText(
            "FFmpeg or FFprobe not found. Please ensure both 'ffmpeg.exe' and 'ffprobe.exe' are in the same folder as this application.")
        msg_box.exec_()
        sys.exit(1)
    app = QCoreApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    file_arg = sys.argv[1] if len(sys.argv) > 1 else None
    ex = VideoCompressorApp(file_arg)
    ex.show()
    sys.exit(app.exec_())
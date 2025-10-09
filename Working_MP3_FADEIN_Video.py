# First, Install "VLC Media Player 64bit" (32bit will not work!).
# Then, in command prompt as administrator, run: "pip install PyQt5 python-vlc"
# In fortnite go to "Settings" and reduce the "HUD" size from 100% to 60% size.

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
from PyQt5.QtGui import QFont, QColor, QPalette, QPainter, QPixmap, QIcon
from PyQt5.QtWidgets import QSizePolicy
from PyQt5.QtCore import Qt, pyqtSignal, QThread, QUrl, QTimer, QCoreApplication, QRect, QEvent, QSize
from PyQt5.QtWidgets import (QApplication, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
                             QLabel, QPushButton, QProgressBar, QSpinBox, QMessageBox,
                             QFrame, QFileDialog, QCheckBox, QDoubleSpinBox, QSlider, QStyle, QStyleOptionSlider, QDialog,
                             QComboBox)

def setup_logger(base_dir):
    log_path = os.path.join(base_dir, "Fortnite-Video-Converter.log")
    logger = logging.getLogger("fvconv")
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        handler = RotatingFileHandler(log_path, maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8")
        fmt = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s", datefmt="%Y-%m-%d | %H:%M:%S")
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
                background: transparent;   /* hide default circle */
                border: none;
                width: 16px;
                margin: -6px 0;
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
        p.setBrush(QColor(30, 200, 255))
        p.drawRect(start_x - bar_w // 2, groove.top() - 2, bar_w, groove.height() + 4)
        p.setBrush(QColor(255, 150, 30))
        p.drawRect(end_x - bar_w // 2, groove.top() - 2, bar_w, groove.height() + 4)
        handle_rect = self.style().subControlRect(QStyle.CC_Slider, opt, QStyle.SC_SliderHandle, self)
        cx = handle_rect.center().x()
        orig_w = 4
        orig_h = groove.height() + 12
        bar_w  = int(round(orig_w * 1.7))
        bar_h  = int(round(orig_h * 1.5))
        cy   = groove.center().y()
        top  = cy - bar_h // 2
        bar  = QRect(cx - bar_w // 2, top, bar_w, bar_h)
        p.setPen(QColor(0, 0, 0))
        p.setBrush(QColor(30, 30, 30))
        p.drawRoundedRect(bar, 3, 3)

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

    def _set_spinner_glyph(self, glyph: str, px: int = 24):
        pm = QPixmap(px, px)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        f = QFont(self.font())
        f.setPointSize(px)       # makes the glyph ~px tall (bigger than button text)
        p.setFont(f)
        p.setPen(Qt.black)
        p.drawText(pm.rect(), Qt.AlignCenter, glyph)
        p.end()
        self.process_button.setIcon(QIcon(pm))
        self.process_button.setIconSize(QSize(px, px))
        self.process_button.setText(" Processing...")

    def _probe_audio_duration(self, path: str) -> float:
        """Return audio duration in seconds (float) or 0.0 on failure."""
        try:
            ffprobe_path = os.path.join(self.script_dir, 'ffprobe.exe')
            cmd = [ffprobe_path, "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path]
            r = subprocess.run(cmd, capture_output=True, text=True, check=True,
                               creationflags=(subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0))
            return max(0.0, float(r.stdout.strip()))
        except Exception:
            return 0.0

    def on_progress(self, value: int):
        if self.progress_bar.maximum() == 0:
            self.progress_bar.setRange(0, 100)
        v = int(max(0, min(100, value)))
        self.progress_bar.setValue(v)

    def _on_music_volume_changed(self, v: int):
        try:
            if hasattr(self, "music_volume_label"):
                self.music_volume_label.setText(f"{int(v)}%")
        except Exception:
            pass

    def eventFilter(self, obj, event):
        if obj is self.video_frame and event.type() == QEvent.KeyPress and event.key() == Qt.Key_Space:
            self.toggle_play()
            return True
        return super().eventFilter(obj, event)

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
        self._phase_is_processing = False
        self._phase_dots = 1
        self._base_title = "Fortnite Video Compressor"
        self.setWindowTitle(self._base_title)
        geom = self.config_manager.config.get('window_geometry')
        if geom and isinstance(geom, dict):
            x = geom.get('x', 100)
            y = geom.get('y', 100)
            w = geom.get('w', 700)
            h = geom.get('h', 700)
            self.setGeometry(x, y, w, h)
            self.setMinimumSize(1090, 720)
        else:
            self.setGeometry(100, 100, 900, 700)
            self.setMinimumSize(1090, 720)
        self._music_files = []
        self.set_style()
        self.init_ui()
        self._scan_mp3_folder()
        self._update_window_size_in_title()
        if file_path:
            self.handle_file_selection(file_path)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Space:
            self.toggle_play()
            event.accept()
        else:
            super().keyPressEvent(event)

    def _update_window_size_in_title(self):
        self.setWindowTitle(f"{self._base_title}  —  {self.width()}x{self.height()}")

    def resizeEvent(self, event):
        self._update_window_size_in_title()
        return super().resizeEvent(event)

    def on_phase_update(self, text: str):
        s = text.lower()
        if any(k in s for k in ("error", "fail", "aborted")):
            color, name = "#ff6b6b", "Error"
            self._phase_is_processing = False
        elif any(k in s for k in ("ready to process another video", "idle", "waiting", "ready")):
            color, name = "#00e5ff", "Idle"
            self._phase_is_processing = False
        elif any(k in s for k in ("prepare", "prob", "seek", "analy", "scan")):
            color, name = "#3da5ff", "Preparing"
            self._phase_is_processing = False
        elif any(k in s for k in ("processing", "encode", "transcod", "compress", "bitrate", "filter",
                                   "crop", "scale", "resize", "speed", "fps", "mux", "packag",
                                   "concat", "merge", "finaliz", "writing", "saving", "thumbnail")):
            color, name = "#ffd166", "Processing"
            self._phase_is_processing = True
            self._phase_dots = 1
        else:
            color, name = "#00e5ff", text
            self._phase_is_processing = False
        suffix = "." if self._phase_is_processing else ""
        self.phase_label.setText(f"Phase: {name}{suffix}")
        self.phase_label.setStyleSheet(f"color: {color}; font-size: 14px; font-weight: bold; padding: 2px;")

    def _pulse_button_tick(self):
        self._pulse_phase = (self._pulse_phase + 1) % 20
        spinner = "◐◓◑◒"
        glyph = spinner[(self._pulse_phase // 2) % len(spinner)]
        self._set_spinner_glyph(glyph, px=26)
        import math
        t = self._pulse_phase / 20.0
        k = (math.sin(4 * math.pi * t) + 1) / 2  # 2× speed
        g1 = (72, 235, 90)   # brighter green (wider range)
        g2 = (10,  80, 16)   # deeper green
        r = int(g1[0] * k + g2[0] * (1 - k))
        g = int(g1[1] * k + g2[1] * (1 - k))
        b = int(g1[2] * k + g2[2] * (1 - k))
        self.process_button.setStyleSheet(f"""
            QPushButton {{
                background-color: rgb({r},{g},{b});
                color: black;
                font-weight: bold;
                font-size: 16px;   /* button text unchanged */
                border-radius: 10px;
            }}
            QPushButton:hover {{ background-color: #c8f7c5; }}
        """)
        if getattr(self, "_phase_is_processing", False):
            self._phase_dots = 1 if self._phase_dots >= 8 else (self._phase_dots + 1)
            self.phase_label.setText(f"Phase: Processing{'.' * self._phase_dots}")

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

    def _mp3_dir(self):
        # Target: .\MP3 under the app directory
        d = os.path.join(self.script_dir, "MP3")
        try:
            os.makedirs(d, exist_ok=True)
        except Exception:
            pass
        return d

    def _scan_mp3_folder(self):
        r"""Scan .\MP3 for .mp3 files, sorted by modified time (newest first). Never raises."""
        try:
            d = self._mp3_dir()
            files = []
            for name in os.listdir(d):
                if name.lower().endswith(".mp3"):
                    p = os.path.join(d, name)
                    try:
                        mt = os.path.getmtime(p)
                    except Exception:
                        mt = 0
                    files.append((mt, name, p))
            files.sort(key=lambda x: x[0], reverse=True)
            self._music_files = [ (n, p) for _, n, p in files ]
        except Exception:
            self._music_files = []
        self._populate_music_combo()

    def _populate_music_combo(self):
        """Refresh the dropdown safely based on self._music_files."""
        if not hasattr(self, "music_combo"):
            return
        mf = getattr(self, "_music_files", [])
        self.music_combo.blockSignals(True)
        self.music_combo.clear()
        if not mf:
            self.music_combo.addItem("No MP3 files found in ./MP3", "")
            self.music_combo.setEnabled(False)
            self.music_combo.setVisible(False)
            self.add_music_checkbox.setChecked(False)
            self.music_volume_slider.setEnabled(False)
            self.music_volume_slider.setVisible(False)
            if hasattr(self, "music_volume_label"):
                self.music_volume_label.setVisible(False)
            if hasattr(self, "music_offset_input"):
                self.music_offset_input.setEnabled(False)
                self.music_offset_input.setVisible(False)
        else:
            self.music_combo.addItem("— Select an MP3 —", "")
            for name, path in mf:
                self.music_combo.addItem(name, path)
            self.music_combo.setCurrentIndex(0)
            self.music_combo.setEnabled(True)
            self.music_volume_slider.setEnabled(False)
            if hasattr(self, "music_volume_label"):
                self.music_volume_label.setVisible(False)
            if hasattr(self, "music_offset_input"):
                self.music_offset_input.setEnabled(False)
                self.music_offset_input.setVisible(False)
        self.music_combo.blockSignals(False)

    def _on_add_music_toggled(self, checked: bool):
        """Show/enable music controls only if files exist and checkbox checked."""
        have_files = bool(self._music_files)
        enable = checked and have_files
        self.music_combo.setEnabled(enable)
        self.music_volume_slider.setEnabled(enable)
        self.music_volume_slider.setVisible(enable)
        if hasattr(self, "music_volume_label"):
            self.music_volume_label.setVisible(enable)
        self.music_combo.setVisible(enable)
        self.music_offset_input.setVisible(enable)
        self.music_offset_input.setEnabled(enable)
        if enable:
            self.music_volume_slider.setValue(25)
            self.music_volume_slider.setEnabled(False)
            if hasattr(self, "music_volume_label"):
                self.music_volume_label.setVisible(False)
            self.music_offset_input.setEnabled(False)
            self.music_offset_input.setVisible(False)

    def _on_music_selected(self, index: int):
        """When user selects a track, keep volume default at 25% unless user changed it."""
        if not self._music_files:
            return
        if self.music_volume_slider.value() in (0, 25):
            self.music_volume_slider.setValue(25)
        try:
            p = self.music_combo.currentData()
            if not p:
                self.music_volume_slider.setEnabled(False)
                if hasattr(self, "music_volume_label"):
                    self.music_volume_label.setVisible(False)
                self.music_offset_input.setEnabled(False)
                self.music_offset_input.setVisible(False)
                return
            dur = self._probe_audio_duration(p)
            self.music_offset_input.setRange(0.0, max(0.0, dur - 0.01))
            self.music_volume_slider.setEnabled(True)
            if hasattr(self, "music_volume_label"):
                self.music_volume_label.setVisible(True)
            self.music_offset_input.setEnabled(True)
            self.music_offset_input.setVisible(True)
            self._open_music_offset_dialog(p)
        except Exception:
            pass

    def _open_music_offset_dialog(self, path: str):
        """Popup dialog to select music start (seconds) with a waveform image. Robust fallback if ffmpeg fails."""
        try:
            import tempfile
            dur = self._probe_audio_duration(path)
            if dur <= 0:
                dur = 0.0
            png = None
            try:
                ffmpeg_path = os.path.join(self.script_dir, 'ffmpeg.exe')
                tmp_png = os.path.join(tempfile.gettempdir(), "bg_waveform.png")
                cmd = [
                    ffmpeg_path, "-hide_banner", "-loglevel", "error",
                    "-i", path, "-frames:v", "1",
                    "-filter_complex", "showwavespic=s=1100x120:split_channels=0",
                    "-y", tmp_png
                ]
                subprocess.run(cmd, check=True,
                               creationflags=(subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0))
                if os.path.isfile(tmp_png):
                    png = tmp_png
            except Exception:
                png = None
            dlg = QDialog(self)
            dlg.setWindowTitle("Choose Background Music Start")
            v = QVBoxLayout(dlg)
            class _WaveformWithCaret(QLabel):
                def __init__(self, pix: QPixmap, *args, **kwargs):
                    super().__init__(*args, **kwargs)
                    self._pix = pix
                    # Effective size in *device-independent* pixels (accounts for HiDPI scaling)
                    self._dpr = float(getattr(pix, "devicePixelRatioF", lambda: 1.0)())
                    self._eff_w = int(round(pix.width()  / self._dpr))
                    self._eff_h = int(round(pix.height() / self._dpr))
                    self._x = 0  # caret x in effective pixels
                    self.setMinimumHeight(self._eff_h + 6)

                def set_frac(self, frac: float):
                    frac = max(0.0, min(1.0, float(frac)))
                    self._x = int(frac * max(1, self._eff_w - 1))
                    self.update()

                def paintEvent(self, e):
                    p = QPainter(self)
                    p.setRenderHint(QPainter.Antialiasing)
                    x0 = (self.width()  - self._eff_w) // 2
                    y0 = (self.height() - self._eff_h) // 2
                    p.drawPixmap(QRect(x0, y0, self._eff_w, self._eff_h), self._pix)
                    p.setPen(QColor(255, 255, 255))
                    cx = x0 + self._x
                    p.drawLine(cx, y0 - 2, cx, y0 + self._eff_h + 2)
                    p.end()
            if png:
                _pix = QPixmap(png)
                dpr = float(getattr(_pix, "devicePixelRatioF", lambda: 1.0)())
                eff_w = int(round(_pix.width()  / dpr))
                eff_h = int(round(_pix.height() / dpr))
                lbl = _WaveformWithCaret(_pix)
                lbl.setAlignment(Qt.AlignCenter)
                lbl.setMinimumWidth(eff_w)
                dlg.resize(max(dlg.width(), eff_w + 80), max(dlg.height(), eff_h + 140))
                v.addWidget(lbl)
            h = QHBoxLayout()
            slider = QSlider(Qt.Horizontal)
            slider.setRange(0, int(max(0.0, dur) * 1000))  # ms granularity
            slider.setSingleStep(50)
            current_ms = int(max(0.0, float(getattr(self.music_offset_input, "value", lambda: 0.0)()) * 1000.0))
            slider.setValue(min(slider.maximum(), current_ms))
            val_label = QLabel(f"{slider.value()/1000.0:.2f} s")
            h.addWidget(slider)
            h.addWidget(val_label)
            v.addLayout(h)
            def _sync_caret(ms):
                if png:
                    lbl.set_frac(ms / max(1, slider.maximum()))
                val_label.setText(f"{ms/1000.0:.2f} s")
            _sync_caret(slider.value())
            slider.valueChanged.connect(_sync_caret)
            btns = QHBoxLayout()
            ok = QPushButton("OK")
            cancel = QPushButton("Cancel")
            btns.addWidget(ok)
            btns.addWidget(cancel)
            v.addLayout(btns)
            def on_slide(x):
                val_label.setText(f"{x/1000.0:.2f} s")
            slider.valueChanged.connect(on_slide)
            ok.clicked.connect(dlg.accept)
            cancel.clicked.connect(dlg.reject)
            if dlg.exec_() == QDialog.Accepted:
                try:
                    self.music_offset_input.setValue(slider.value() / 1000.0)
                except Exception:
                    pass
        except Exception:
            pass

    def _get_music_offset(self) -> float:
        try:
            return float(self.music_offset_input.value())
        except Exception:
            return 0.0

    def _get_selected_music(self):
        """Return (path, volume_linear) or (None, None) if disabled/invalid."""
        if not self.add_music_checkbox.isChecked():
            return None, None
        if not self._music_files:
            return None, None
        path = self.music_combo.currentData() or ""
        if not path or not os.path.isfile(path):
            return None, None
        vol_pct = max(0, min(100, self.music_volume_slider.value()))
        return path, (vol_pct / 100.0)

    def init_ui(self):
        main_layout = QHBoxLayout()
        left_layout = QVBoxLayout()
        left_layout.setSpacing(12)
        self.video_frame = QFrame()
        self.video_frame.setStyleSheet("background-color: black;")
        self.video_frame.setMinimumHeight(360)
        self.video_frame.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.video_frame.setFocusPolicy(Qt.StrongFocus)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setFocusProxy(self.video_frame)
        self.video_frame.installEventFilter(self)
        top_row = QHBoxLayout()
        top_row.setSpacing(12)
        player_col = QVBoxLayout()
        player_col.setSpacing(6)
        self.video_frame.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        player_col.addWidget(self.video_frame)
        self.positionSlider = TrimmedSlider(self)
        self.positionSlider.setRange(0, 0)
        self.positionSlider.setFixedHeight(18)
        self.positionSlider.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.positionSlider.sliderMoved.connect(self.set_vlc_position)
        player_col.addWidget(self.positionSlider)
        player_col.setStretch(0, 1)
        player_col.setStretch(1, 0)
        top_row.addLayout(player_col, stretch=6)
        self._top_row = top_row
        left_layout.addLayout(self._top_row)
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
        status_phase_row = QHBoxLayout()
        self.status_label = QLabel("Status: Ready")
        self.status_label.setStyleSheet("color: white; font-size: 13px; padding: 4px;")
        status_phase_row.addWidget(self.status_label, stretch=1)
        self.phase_label = QLabel("Phase: Idle")
        self.phase_label.setStyleSheet("color: #00e5ff; font-size: 14px; font-weight: bold; padding: 2px;")
        status_phase_row.addWidget(self.phase_label, alignment=Qt.AlignRight)
        left_layout.addLayout(status_phase_row)
        self.status_update_signal.connect(self.status_label.setText)
        self.duration_label = QLabel("Duration: N/A | Resolution: N/A")
        self.duration_label.setStyleSheet("color: lightgray; font-size: 13px; padding: 4px;")
        left_layout.addWidget(self.duration_label)
        process_controls = QHBoxLayout()
        self.mobile_checkbox = QCheckBox("Mobile Format (Portrait Video)")
        self.mobile_checkbox.setStyleSheet("font-size: 18px; font-weight: bold;")
        self.mobile_checkbox.setChecked(bool(self.config_manager.config.get('mobile_checked', False)))
        self.teammates_checkbox = QCheckBox("Show Teammates Healthbar")
        self.teammates_checkbox.setStyleSheet("font-size: 14px;")
        self.teammates_checkbox.setChecked(bool(self.config_manager.config.get('teammates_checked', False)))
        self.lowerq_checkbox = QCheckBox("Set Video for a Quick Share (Low Quality)")
        self.lowerq_checkbox.setChecked(False)
        self.maxres_checkbox = QCheckBox("Keep Highest Resolution Possible(Harder to Share)")
        self.maxres_checkbox.setChecked(False)
        self._quality_guard = False
        def _on_lowerq_toggled(checked: bool):
            if self._quality_guard:
                return
            if checked:
                self._quality_guard = True
                self.maxres_checkbox.setChecked(False)
                self._quality_guard = False
        def _on_maxres_toggled(checked: bool):
            if self._quality_guard:
                return
            if checked:
                self._quality_guard = True
                self.lowerq_checkbox.setChecked(False)
                self._quality_guard = False
        self.lowerq_checkbox.toggled.connect(_on_lowerq_toggled)
        self.maxres_checkbox.toggled.connect(_on_maxres_toggled)
        def _on_mobile_toggled(checked: bool):
            self.teammates_checkbox.setEnabled(checked)
            if not checked:
                self.teammates_checkbox.setChecked(False)
        self.mobile_checkbox.toggled.connect(_on_mobile_toggled)
        self.teammates_checkbox.setEnabled(self.mobile_checkbox.isChecked())
        if not self.mobile_checkbox.isChecked():
            self.teammates_checkbox.setChecked(False)
        process_controls.addWidget(self.mobile_checkbox, alignment=Qt.AlignLeft)
        process_controls.addWidget(self.teammates_checkbox, alignment=Qt.AlignLeft)
        process_controls.addWidget(self.lowerq_checkbox, alignment=Qt.AlignLeft)
        process_controls.addWidget(self.maxres_checkbox, alignment=Qt.AlignLeft)
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
        self.speed_spinbox.setRange(0.5, 3.1)
        self.speed_spinbox.setValue(float(self.config_manager.config.get('last_speed', 1.1)))
        self.speed_spinbox.setMinimumWidth(140)
        self.speed_spinbox.setStyleSheet("font-size: 14px;")
        center_group.addWidget(self.speed_spinbox, alignment=Qt.AlignVCenter)
        process_controls.addLayout(center_group)
        process_controls.addStretch(1)
        left_layout.addLayout(process_controls, stretch=0)
        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        left_layout.addWidget(self.progress_bar)
        self._pulse_timer = QTimer(self)
        self._pulse_timer.setInterval(100)
        self._pulse_phase = 0
        self._pulse_timer.timeout.connect(self._pulse_button_tick)
        self.progress_update_signal.connect(self.on_progress)
        self.status_update_signal.connect(self.on_phase_update)
        self.process_finished_signal.connect(self.on_process_finished)
        right_col = QVBoxLayout()
        right_col.setSpacing(12)
        right_col.setContentsMargins(0, 0, 0, 0)
        self.drop_area = DropAreaFrame()
        self.drop_area.setObjectName("dropArea")
        self.drop_area.setFocusPolicy(Qt.NoFocus)
        self.drop_area.file_dropped.connect(self.handle_file_selection)
        drop_layout = QVBoxLayout(self.drop_area)
        drop_layout.setContentsMargins(12, 12, 12, 12)
        self.drop_label = QLabel("Drag & Drop\r\nVideo File Here:")
        self.drop_label.setAlignment(Qt.AlignCenter)
        drop_layout.addWidget(self.drop_label)
        self.drop_area.setMaximumWidth(180)
        self.drop_area.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
        right_col.addWidget(self.drop_area, stretch=1)
        self.upload_button = QPushButton("📂 Click Here\r\n to Upload a Video File")
        self.upload_button.clicked.connect(self.select_file)
        self.upload_button.setFocusPolicy(Qt.NoFocus)
        self.upload_button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.upload_button.setMaximumWidth(180)
        right_col.addWidget(self.upload_button, alignment=Qt.AlignBottom)
        self.add_music_checkbox = QCheckBox("Add Background Music")
        self.add_music_checkbox.setToolTip("Toggle background MP3 mixing from the ./MP3 folder.")
        self.add_music_checkbox.setChecked(False)
        right_col.addWidget(self.add_music_checkbox)
        self.music_combo = QComboBox()
        self.music_combo.setSizeAdjustPolicy(QComboBox.AdjustToContents)
        self.music_combo.setVisible(False)  # hidden until checkbox enables it
        right_col.addWidget(self.music_combo)
        self.music_volume_slider = QSlider(Qt.Vertical)
        self.music_volume_slider.setRange(0, 100)
        self.music_volume_slider.setValue(25)
        self.music_volume_slider.setTickInterval(5)
        self.music_volume_slider.setTickPosition(QSlider.TicksRight)
        self.music_volume_slider.setVisible(False)
        self.music_volume_slider.setStyleSheet("QSlider { min-height: 140px; }")
        self.music_offset_input = QDoubleSpinBox()
        self.music_offset_input.setPrefix("Music Start (s): ")
        self.music_offset_input.setDecimals(2)
        self.music_offset_input.setSingleStep(0.5)
        self.music_offset_input.setRange(0.0, 0.0)
        self.music_offset_input.setValue(0.0)
        self.music_offset_input.setVisible(False)
        right_col.addWidget(self.music_offset_input)
        right_col.addWidget(self.music_volume_slider, alignment=Qt.AlignHCenter)
        self.music_volume_label = QLabel("25%")
        self.music_volume_label.setAlignment(Qt.AlignHCenter)
        self.music_volume_label.setVisible(False)
        right_col.addWidget(self.music_volume_label, alignment=Qt.AlignHCenter)
        self.music_volume_slider.valueChanged.connect(self._on_music_volume_changed)
        self.add_music_checkbox.toggled.connect(self._on_add_music_toggled)
        self.music_combo.currentIndexChanged.connect(self._on_music_selected)
        self._populate_music_combo()
        self._top_row.addLayout(right_col, stretch=2)
        main_layout.addLayout(left_layout, stretch=1)
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
        self.video_frame.setFocus()
        self.activateWindow()

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
            if self.original_resolution not in ["1920x1080", "2560x1440", "3440x1440", "3840x2160"]:
                error_message = "This software is designed for 1080p/1440p/3440x1440/4K inputs."
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
        if self.original_resolution not in ["1920x1080", "2560x1440", "3440x1440", "3840x2160"]:
            self.set_status_text_with_color("Unsupported input resolution.", "red")
            return
        start_time = (self.start_minute_input.value() * 60) + self.start_second_input.value()
        end_time = (self.end_minute_input.value() * 60) + self.end_second_input.value()
        is_mobile_format = self.mobile_checkbox.isChecked()
        speed_factor = self.speed_spinbox.value()
        if speed_factor < 0.5 or speed_factor > 3.1:
            self.show_message("Invalid Speed", "Allowed speed range is 0.5x to 3.1x.")
            self.is_processing = False
            self.process_button.setEnabled(True)
            return
        if start_time < 0 or end_time < 0 or start_time >= end_time or end_time > self.original_duration:
            self.show_message("Error", "Invalid start and end times. Please ensure end time > start time and within video duration.")
            return
        self.is_processing = True
        self._proc_start_ts = time.time()
        self._pulse_phase = 0
        self.process_button.setEnabled(False)
        self.progress_bar.setRange(0, 0)
        self.progress_bar.setValue(0)
        self._pulse_timer.start()
        self.process_button.setText("Processing…")
        self.process_button.setIcon(self.style().standardIcon(QStyle.SP_BrowserReload))
        self.on_phase_update("Processing")
        self.set_status_text_with_color("Preparing… (probing/seek)…", "white")
        QApplication.setOverrideCursor(Qt.WaitCursor)
        self.progress_update_signal.emit(0)
        cfg = dict(self.config_manager.config)
        cfg['last_speed'] = float(speed_factor)
        cfg['mobile_checked'] = bool(is_mobile_format)
        cfg['teammates_checked'] = bool(self.teammates_checkbox.isChecked())
        self.config_manager.save_config(cfg)
        lowerq = self.lowerq_checkbox.isChecked()
        maxres = self.maxres_checkbox.isChecked()
        music_path, music_vol_linear = self._get_selected_music()
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
            self.logger,
            show_teammates_overlay=(is_mobile_format and self.teammates_checkbox.isChecked()),
            lower_quality=lowerq,
            keep_highest_res=maxres,
            bg_music_path=music_path,
            bg_music_volume=music_vol_linear,
            bg_music_offset=self._get_music_offset(),
            original_total_duration=self.original_duration
        )
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
        self._proc_start_ts = None
        self._phase_is_processing = False
        if hasattr(self, "_pulse_timer"):
            self._pulse_timer.stop()
        self.process_button.setEnabled(True)
        self.process_button.setText("Process Video")
        self.process_button.setIcon(self.style().standardIcon(QStyle.SP_DialogApplyButton))
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        if success:
            self.phase_label.setText("Phase: Done")
            self.phase_label.setStyleSheet("color: #06d6a0; font-size: 14px; font-weight: bold; padding: 2px;")
        else:
            self.phase_label.setText("Phase: Error")
            self.phase_label.setStyleSheet("color: #ff6b6b; font-size: 14px; font-weight: bold; padding: 2px;")
        QApplication.restoreOverrideCursor()
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
        cfg['last_speed'] = float(self.speed_spinbox.value())
        cfg['mobile_checked'] = bool(self.mobile_checkbox.isChecked())
        cfg['teammates_checked'] = bool(self.teammates_checkbox.isChecked())
        self.config_manager.save_config(cfg)
        super().closeEvent(event)
    
    def show_message(self, title, message):
        """
        Displays a custom message box instead of alert().
        """
        msg_box = QMessageBox(self)
        msg_box.setIcon(QMessageBox.Information)
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
                 script_dir, progress_update_signal, status_update_signal, finished_signal, logger,
                 show_teammates_overlay=False, lower_quality=False, keep_highest_res=False,
                 bg_music_path=None, bg_music_volume=None, bg_music_offset=0.0, original_total_duration=0.0):
        super().__init__()
        self.input_path = input_path
        self.start_time = start_time
        self.end_time = end_time
        self.duration = end_time - start_time
        self.original_resolution = original_resolution
        self.is_mobile_format = is_mobile_format
        self.speed_factor = speed_factor
        self.show_teammates_overlay = bool(show_teammates_overlay)
        self.lower_quality = bool(lower_quality)
        self.keep_highest_res = bool(keep_highest_res)
        self.script_dir = script_dir
        self.progress_update_signal = progress_update_signal
        self.status_update_signal = status_update_signal
        self.finished_signal = finished_signal
        self.logger = logger
        self.bg_music_path = bg_music_path if (bg_music_path and os.path.isfile(bg_music_path)) else None
        try:
            self.bg_music_volume = float(bg_music_volume) if bg_music_volume is not None else None
        except Exception:
            self.bg_music_volume = None
        try:
            self.bg_music_offset = float(bg_music_offset)
        except Exception:
            self.bg_music_offset = 0.0
        try:
            self.original_total_duration = float(original_total_duration)
        except Exception:
            self.original_total_duration = 0.0
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
            user_start = float(self.start_time)
            user_end   = float(self.end_time)
            total_orig = float(self.original_total_duration or 0.0)
            pad_pre  = 1.5
            pad_post = 1.5
            EPS = 0.01
            if total_orig > 0.0 and abs(user_end - total_orig) <= EPS:
                pad_post = 1.0
            adj_start = max(0.0, user_start - pad_pre)
            target_end = user_end + pad_post
            adj_end = target_end
            if total_orig > 0.0:
                adj_end = min(target_end, total_orig)
            if adj_end <= adj_start:
                adj_end = user_end
            in_ss = adj_start
            in_t  = max(0.0, adj_end - adj_start)
            if self.speed_factor != 1.0:
                duration_corrected = in_t / self.speed_factor
                self.status_update_signal.emit(f"Adjusting trim times for speed factor {self.speed_factor}x.")
            else:
                duration_corrected = in_t
            vfade_in_d   = min(1.5, duration_corrected)
            vfade_out_d  = min(1.5, duration_corrected)
            vfade_out_st = max(0.0, duration_corrected - vfade_out_d)
            start_time_corrected = in_ss      # (used only for -ss)
            self.start_time_corrected = in_ss # (for logs/progress)
            self.duration_corrected   = duration_corrected
            AUDIO_KBPS = 128
            TARGET_MB = 45.0
            if self.lower_quality:
                TARGET_MB = 15.0
            if self.keep_highest_res:
                try:
                    src_bytes = os.path.getsize(self.input_path)
                    target_file_size_bits = max(1, src_bytes) * 8
                    def _probe_audio_kbps():
                        try:
                            ffprobe_path = os.path.join(self.script_dir, 'ffprobe.exe')
                            cmd = [
                                ffprobe_path, "-v", "error",
                                "-select_streams", "a:0",
                                "-show_entries", "stream=bit_rate",
                                "-of", "default=nw=1:nk=1",
                                self.input_path
                            ]
                            r = subprocess.run(cmd, capture_output=True, text=True, check=True,
                                            creationflags=(subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0))
                            br = int(float(r.stdout.strip()))
                            return max(8, int(round(br / 1000.0)))
                        except Exception:
                            return None
                    probed = _probe_audio_kbps()
                    if probed:
                        AUDIO_KBPS = probed
                    if duration_corrected <= 0:
                        self.finished_signal.emit(False, "Selected video duration is zero.")
                        return
                    audio_bits = AUDIO_KBPS * 1024 * duration_corrected
                    video_bits = target_file_size_bits - audio_bits
                    min_video_kbps = 300
                    if video_bits <= 0:
                        video_bitrate_kbps = min_video_kbps
                    else:
                        video_bitrate_kbps = max(min_video_kbps, int(video_bits / (1024 * duration_corrected)))
                    self.status_update_signal.emit(
                        f"Keep Highest Resolution: matching source size; audio ~{AUDIO_KBPS} kbps; video ~{video_bitrate_kbps} kbps.")
                except Exception as e:
                    self.status_update_signal.emit(f"Keep Highest Resolution fallback: {e}. Using VBR target size.")
                    target_file_size_bits = TARGET_MB * 8 * 1024 * 1024
                    audio_bits = AUDIO_KBPS * 1024 * duration_corrected
                    video_bits = target_file_size_bits - audio_bits
                    if video_bits < 0:
                        self.finished_signal.emit(False, "Video duration is too short for the target file size.")
                        return
                    video_bitrate_kbps = int(video_bits / (1024 * duration_corrected))
            else:
                target_file_size_bits = TARGET_MB * 8 * 1024 * 1024
                if duration_corrected <= 0:
                    self.finished_signal.emit(False, "Selected video duration is zero.")
                    return
                audio_bits = AUDIO_KBPS * 1024 * duration_corrected
                video_bits = target_file_size_bits - audio_bits
                if video_bits < 0:
                    self.finished_signal.emit(False, "Video duration is too short for the target file size.")
                    return
                video_bitrate_kbps = int(video_bits / (1024 * duration_corrected))
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
            team_1440  = (160, 190, 74, 26)
            def scale_box(box, s):
                return tuple(int(round(v * s)) for v in box)
            def map_hud_box_to_input(box, in_w, in_h, base_w=2560, base_h=1440):
                w, h, x, y = box
                if x + w > base_w:
                    x = max(0, base_w - w)
                if y + h > base_h:
                    y = max(0, base_h - h)
                v      = in_h / float(base_h)
                safe_w = base_w * v
                pad_x  = max(0.0, (in_w - safe_w) / 2.0)
                w2 = int(round(w * v))
                h2 = int(round(h * v))
                x2 = int(round(pad_x + x * v))
                y2 = int(round(y * v))
                x2 = max(0, min(in_w - w2, x2))
                y2 = max(0, min(in_h - h2, y2))
                return (w2, h2, x2, y2)
            if self.original_resolution == "1920x1080":
                hb    = scale_box(hb_1440, 0.75)
                loot  = scale_box(loot_1440, 0.75)
                stats = scale_box(stats_1440, 0.75)
                team  = scale_box(team_1440, 0.75)
            elif self.original_resolution == "2560x1440":
                hb, loot, stats, team = hb_1440, loot_1440, stats_1440, team_1440
            elif self.original_resolution == "3440x1440":
                hb    = (350, 130,  720, 1260)
                loot  = (664, 135, 2890, 1205)
                stats = (360,  31, 3030,  440)
                team  = (260, 290,  110,   26)
            elif self.original_resolution == "3840x2160":
                hb    = scale_box(hb_1440, 1.5)
                loot  = scale_box(loot_1440, 1.5)
                stats = scale_box(stats_1440, 1.5)
                team  = scale_box(team_1440, 1.5)
            else:
                hb, loot, stats, team = hb_1440, loot_1440, stats_1440, team_1440
            healthbar_crop_string  = f"{hb[0]}:{hb[1]}:{hb[2]}:{hb[3]}"
            loot_area_crop_string  = f"{loot[0]}:{loot[1]}:{loot[2]}:{loot[3]}"
            stats_area_crop_string = f"{stats[0]}:{stats[1]}:{stats[2]}:{stats[3]}"
            team_crop_string       = f"{team[0]}:{team[1]}:{team[2]}:{team[3]}"
            s = 0.75 if self.original_resolution == "1920x1080" else (1.5 if self.original_resolution == "3840x2160" else 1.0)
            healthbar_scaled_width  = int(round(370 * 0.85 * 2 * s))
            healthbar_scaled_height = int(round(65  * 0.85 * 2 * s))
            loot_scaled_width       = int(round(440 * 0.85 * 1.3 * 1.2 * s))
            loot_scaled_height      = int(round(133 * 0.85 * 1.3 * 1.2 * s))
            stats_scaled_width      = int(round(stats[0] * 1.8 * s))
            stats_scaled_height     = int(round(stats[1] * 1.8 * s))
            team_scaled_width       = int(round(team[0]  * 1.32 * s))
            team_scaled_height      = int(round(team[1]  * 1.32 * s))
            if self.original_resolution == "3440x1440":
                healthbar_scaled_width,  healthbar_scaled_height  = 520, 125
                loot_scaled_width,       loot_scaled_height       = 715, 140
                stats_scaled_width,      stats_scaled_height      = 500,  50
                team_scaled_width,       team_scaled_height       = 211, 280
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
                TEAM_LEFT_MARGIN_1440 = 0
                TEAM_TOP_MARGIN_1440  = 0
                team_overlay_x = int(round(TEAM_LEFT_MARGIN_1440 * s))
                team_overlay_y = int(round(TEAM_TOP_MARGIN_1440  * s))
                if self.original_resolution == "3440x1440":
                    if self.show_teammates_overlay:
                        video_filter_cmd = (
                            "split=5[main][lootbar][healthbar][stats][team];"
                            f"[main]scale={main_width}:{main_height}:force_original_aspect_ratio=increase,crop={main_width}:{main_height}[main_cropped];"
                            "[lootbar]crop=664:135:2890:1205,scale=715:140,format=yuva444p,colorchannelmixer=aa=0.8[lootbar_scaled];"
                            "[healthbar]crop=350:130:720:1260,scale=520:125,format=yuva444p,colorchannelmixer=aa=0.8[healthbar_scaled];"
                            "[stats]crop=360:31:3030:440,scale=500:50,format=yuva444p,colorchannelmixer=aa=0.7[stats_scaled];"
                            "[team]crop=260:290:110:26,scale=211:280,format=yuva444p,colorchannelmixer=aa=0.8[team_scaled];"
                            "[main_cropped][lootbar_scaled]overlay=463:1790[t1];"
                            "[t1][healthbar_scaled]overlay=0:H-h-0[t2];"
                            "[t2][stats_scaled]overlay=323:1745[t3];"
                            "[t3][team_scaled]overlay=0:0"
                        )
                    else:
                        video_filter_cmd = (
                            "split=4[main][lootbar][healthbar][stats];"
                            f"[main]scale={main_width}:{main_height}:force_original_aspect_ratio=increase,crop={main_width}:{main_height}[main_cropped];"
                            "[lootbar]crop=664:135:2890:1205,scale=715:140,format=yuva444p,colorchannelmixer=aa=0.8[lootbar_scaled];"
                            "[healthbar]crop=350:130:720:1260,scale=520:125,format=yuva444p,colorchannelmixer=aa=0.8[healthbar_scaled];"
                            "[stats]crop=360:31:3030:440,scale=500:50,format=yuva444p,colorchannelmixer=aa=0.7[stats_scaled];"
                            "[main_cropped][lootbar_scaled]overlay=463:1790[t1];"
                            "[t1][healthbar_scaled]overlay=0:H-h-0[t2];"
                            "[t2][stats_scaled]overlay=323:1745"
                        )
                elif self.original_resolution == "1920x1080":
                    if self.show_teammates_overlay:
                        video_filter_cmd = (
                            "split=5[main][lootbar][healthbar][stats][team];"
                            f"[main]scale={main_width}:{main_height}:force_original_aspect_ratio=increase,crop={main_width}:{main_height}[main_cropped];"
                            "[lootbar]crop=330:120:1814:1082,scale=738:263,format=yuva444p,colorchannelmixer=aa=0.8[lootbar_scaled];"
                            "[healthbar]crop=278:49:45:988,scale=690:121,format=yuva444p,colorchannelmixer=aa=0.8[healthbar_scaled];"
                            "[stats]crop=210:23:1698:202,scale=497:54,format=yuva444p,colorchannelmixer=aa=0.7[stats_scaled];"
                            "[team]crop=120:142:56:20,scale=273:324,format=yuva444p,colorchannelmixer=aa=0.8[team_scaled];"
                            "[main_cropped][lootbar_scaled]overlay=445:1800[t1];"
                            "[t1][healthbar_scaled]overlay=-100:1795[t2];"
                            "[t2][stats_scaled]overlay=347:1745[t3];"
                            "[t3][team_scaled]overlay=0:0"
                        )
                    else:
                        video_filter_cmd = (
                            "split=4[main][lootbar][healthbar][stats];"
                            f"[main]scale={main_width}:{main_height}:force_original_aspect_ratio=increase,crop={main_width}:{main_height}[main_cropped];"
                            "[lootbar]crop=330:120:1814:1082,scale=738:263,format=yuva444p,colorchannelmixer=aa=0.8[lootbar_scaled];"
                            "[healthbar]crop=278:49:45:988,scale=690:121,format=yuva444p,colorchannelmixer=aa=0.8[healthbar_scaled];"
                            "[stats]crop=210:23:1698:202,scale=497:54,format=yuva444p,colorchannelmixer=aa=0.7[stats_scaled];"
                            "[main_cropped][lootbar_scaled]overlay=445:1800[t1];"
                            "[t1][healthbar_scaled]overlay=-100:1795[t2];"
                            "[t2][stats_scaled]overlay=347:1745"
                        )
                else:
                    if self.show_teammates_overlay:
                        video_filter_cmd = (
                            f"split=5[main][lootbar][healthbar][stats][team];"
                            f"[main]scale={main_width}:{main_height}:force_original_aspect_ratio=increase,crop={main_width}:{main_height}[main_cropped];"
                            f"[lootbar]crop={loot_area_crop_string},scale={loot_scaled_width * 1.2:.0f}:{loot_scaled_height * 1.2:.0f},format=yuva444p,colorchannelmixer=aa=0.8[lootbar_scaled];"
                            f"[healthbar]crop={healthbar_crop_string},scale={healthbar_scaled_width * 1.1:.0f}:{healthbar_scaled_height * 1.1:.0f},format=yuva444p,colorchannelmixer=aa=0.8[healthbar_scaled];"
                            f"[stats]crop={stats_area_crop_string},scale={stats_scaled_width}:{stats_scaled_height},format=yuva444p,colorchannelmixer=aa=0.7[stats_scaled];"
                            f"[team]crop={team_crop_string},scale={team_scaled_width}:{team_scaled_height},format=yuva444p,colorchannelmixer=aa=0.8[team_scaled];"
                            f"[main_cropped][lootbar_scaled]overlay={loot_overlay_x}:{loot_overlay_y}[t1];"
                            f"[t1][healthbar_scaled]overlay=-100:{hb_overlay_y}[t2];"
                            f"[t2][stats_scaled]overlay={stats_overlay_x}:{stats_overlay_y}[t3];"
                            f"[t3][team_scaled]overlay={team_overlay_x}:{team_overlay_y}"
                        )
                    else:
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
                if self.keep_highest_res:
                    target_resolution = "scale=iw:ih"
                    self.status_update_signal.emit("Highest Resolution: keeping source resolution.")
                else:
                    target_resolution = "scale='min(1920,iw)':-2"
                    if video_bitrate_kbps < 800 and original_height > 720 and not self.lower_quality:
                        target_resolution = "scale='min(1280,iw)':-2"
                        self.status_update_signal.emit("Low bitrate detected. Scaling to 720p.")
                    if self.lower_quality:
                        target_resolution = "scale='min(960,iw)':-2"  # extra downscale in Low Quality mode
                        self.status_update_signal.emit("Lower Quality: targeting ~15–20MB and smaller resolution.")
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
                s = float(self.speed_factor)
                chain = []
                if s >= 1.0:
                    while s > 2.0:
                        chain.append(2.0); s /= 2.0
                    chain.append(s)
                else:
                    while s < 0.5:
                        chain.append(0.5); s /= 0.5
                    chain.append(s)
                chain = [min(2.0, max(0.5, round(f, 3))) for f in chain if abs(f-1.0) > 1e-3]
                audio_filter_cmd = ",".join(f"atempo={f}" for f in chain)
                self.status_update_signal.emit(f"Applying speed factor: {self.speed_factor}x to audio.")
                self.logger.info(f"Audio atempo chain: {audio_filter_cmd or 'none (1.0x)'}")
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
            time_regex  = re.compile(r'time=(\d+):(\d+):(\d+(?:\.\d+)?)')  # HH:MM:SS.xx
            self.progress_update_signal.emit(0)
            self.status_update_signal.emit("Processing video (NVENC VBR HQ).")
            cmd = [
                ffmpeg_path, '-y',
                '-hwaccel', 'auto',
                '-ss', f"{in_ss:.3f}", '-t', f"{in_t:.3f}",
                '-i', self.input_path,  # input 0: video (and its audio)
            ]
            have_bg = bool(self.bg_music_path)
            if have_bg:
                cmd += ['-i', self.bg_music_path]  # input 1: bg music
                self.status_update_signal.emit("Background music: mixing enabled.")
            else:
                self.status_update_signal.emit("Background music: disabled or not found.")
            if video_bitrate_kbps is None:
                vcodec = ['-c:v', 'h264_nvenc', '-rc', 'constqp', '-qp', '0']
            else:
                vcodec = [
                    '-c:v', 'h264_nvenc', '-rc', 'vbr_hq',
                    '-b:v', f'{video_bitrate_kbps}k',
                    '-maxrate', f'{int(video_bitrate_kbps*1.5)}k',
                    '-bufsize', f'{int(video_bitrate_kbps*2)}k'
                ]
            cmd += vcodec
            cmd += ['-loglevel', 'info']
            filter_complex_parts = []
            need_map = False
            map_args = []
            if self.is_mobile_format:
                vgraph = video_filter_cmd
                vgraph = f"{vgraph},fade=t=in:st=0:d={vfade_in_d:.3f},fade=t=out:st={vfade_out_st:.3f}:d={vfade_out_d:.3f},format=yuv420p[vout]"
                filter_complex_parts.append(vgraph)
                need_map = True
                map_args += ['-map', '[vout]']
            elif video_filter_cmd:
                vf = f"{video_filter_cmd},fade=t=in:st=0:d={vfade_in_d:.3f},fade=t=out:st={vfade_out_st:.3f}:d={vfade_out_d:.3f}"
                cmd.extend(['-vf', vf])
            if have_bg:
                if audio_filter_cmd:
                    filter_complex_parts.append(f"[0:a]{audio_filter_cmd}[a0]")
                else:
                    filter_complex_parts.append(f"[0:a]anull[a0]")
                vol = self.bg_music_volume
                try:
                    vol = float(vol) if vol is not None else 0.25
                except Exception:
                    vol = 0.25
                vol = max(0.0, min(1.0, vol))
                mo = max(0.0, float(self.bg_music_offset or 0.0))
                filter_complex_parts.append(
                    f"[1:a]atrim=start={mo:.3f}:end={mo + duration_corrected:.3f},asetpts=PTS-STARTPTS,"
                    f"volume={vol:.4f},afade=t=in:st=0:d=1.5,afade=t=out:st={max(0.0, duration_corrected - 1.5):.3f}:d=1.5[a1]"
                )
                filter_complex_parts.append("[a0][a1]amix=inputs=2:duration=first:dropout_transition=3[aout]")
                need_map = True
                map_args += ['-map', '[aout]']
                cmd += ['-c:a', 'aac', '-b:a', '192k']
            else:
                if audio_filter_cmd:
                    cmd.extend(['-af', audio_filter_cmd])
                    cmd += ['-c:a', 'aac', '-b:a', f'{AUDIO_KBPS}k']
                else:
                    cmd += ['-c:a', 'aac', '-b:a', f'{AUDIO_KBPS}k']
                if filter_complex_parts:
                    cmd += ['-filter_complex', ';'.join(filter_complex_parts)]
                    if not self.is_mobile_format:
                        map_args += ['-map', '0:v:0']
                    has_audio_map = any(
                        (isinstance(v, str) and (v.startswith('[aout]') or v.startswith('0:a')))
                        for v in map_args
                    )
                    if not has_audio_map:
                        map_args += ['-map', '0:a:0']
                    cmd += map_args
                    cmd += ['-shortest']
                else:
                    cmd += ['-map', '0:v:0', '-map', '0:a:0']
            cmd.append(output_path)
            self.logger.info(f"FFmpeg CMD: {' '.join(map(str, cmd))}")
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                creationflags=(subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0)
            )
            last_output_ts = time.time()
            watchdog_sec = max(120, int(self.duration_corrected * 3) + 120)
            while True:
                line = proc.stdout.readline()
                if line:
                    last_output_ts = time.time()
                    s = line.strip()
                    self.logger.info(f"FFmpeg: {s}")
                    frame_match = frame_regex.search(s)
                    if frame_match and total_frames:
                        try:
                            current_frame = int(frame_match.group(1))
                            progress = int(max(0, min(100, (current_frame / float(total_frames)) * 100)))
                            self.progress_update_signal.emit(progress)
                        except Exception:
                            pass
                else:
                    if proc.poll() is not None:
                        break
                    if (time.time() - last_output_ts) > watchdog_sec:
                        self.logger.error("FFmpeg appears hung; killing process due to watchdog timeout.")
                        try:
                            proc.kill()
                        except Exception:
                            pass
                        self.finished_signal.emit(False, "FFmpeg stalled (watchdog timeout).")
                        return
                    time.sleep(0.2)
            rc = proc.wait()
            if rc != 0:
                self.finished_signal.emit(False, f"FFmpeg exited with code {rc}.")
                return
            self.progress_update_signal.emit(100)
            try:
                self.logger.info(
                    f"Job SUCCESS | start={self.start_time}s end={self.end_time}s | out='{output_path}'"
                )
            except Exception:
                pass
            self.finished_signal.emit(True, output_path)
            return
        except Exception as e:
            self.logger.exception(f"Job FAILURE with exception: {e}")
            self.finished_signal.emit(False, f"An unexpected error occurred: {e}.")
        finally:
            try:
                self.logger.info("------------------------------------------------------------")
                self.logger.info("------------------------------------------------------------")
            except Exception:
                pass
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
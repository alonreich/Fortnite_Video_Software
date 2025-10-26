from ui.widgets.trimmed_slider import TrimmedSlider
import json
import logging
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

if __name__ == "__main__":
    try:
        _proj_root_path = Path(__file__).resolve().parents[2]
        if str(_proj_root_path) not in sys.path:
            sys.path.insert(0, str(_proj_root_path))
            print(f"DEBUG [Standalone]: Added project root '{_proj_root_path}' to sys.path")
    except Exception as _path_err:
        print(f"ERROR [Standalone]: Failed to modify sys.path - {_path_err}", file=sys.stderr)
from PyQt5.QtCore import QProcess, Qt, QTimer, pyqtSignal, QEvent
from PyQt5.QtGui import QColor, QFontMetrics, QIcon, QPixmap
from PyQt5.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QDoubleSpinBox, QFileDialog, 
    QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QMainWindow, 
    QMessageBox, QPushButton, QSlider, QStyle, QStyleOptionSlider, 
    QVBoxLayout, QWidget, QSizePolicy
)

def _proj_root() -> Path:
    return Path(__file__).resolve().parents[2]

def _conf_path() -> Path:
    return _proj_root() / "ui" / "Video.conf"

def _human(n_bytes: int) -> str:
    units = ["B","KB","MB","GB","TB"]
    s = 0
    n = float(n_bytes)
    while n >= 1024.0 and s < len(units)-1:
        n /= 1024.0; s += 1
    return f"{n:.2f} {units[s]}"

def _get_logger():
    import logging
    logger = logging.getLogger("VideoMerger")
    if logger.handlers:
        return logger
    try:
        from logger import get_logger
        return get_logger("VideoMerger")
    except Exception:
        pass
    try:
        log_dir = _proj_root() / "logs"
        log_dir.mkdir(exist_ok=True)
        import logging
        logger.setLevel(logging.INFO)
        log_path = log_dir / "Fortnite-Video-Converter.log"
        fh = logging.FileHandler(str(log_path)) 
        fh.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
        logger.addHandler(fh)
    except Exception:
        pass
    return logger

def _load_conf() -> dict:
    p = _conf_path()
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}

def _save_conf(cfg: dict) -> None:
    p = _conf_path()
    try:
        p.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    except Exception:
        pass

import subprocess, tempfile, os, sys

try:
    import vlc as _vlc_mod
except Exception:
    _vlc_mod = None

AUDIO_LAG_COMPENSATION_MS = 0
PREVIEW_VISUAL_LEAD_MS = -2700

class VM_MusicOffsetDialog(QDialog):
    """
    Waveform preview + Play/Pause + caret + time slider,
    self-contained for use inside video_merger.py.
    Geometry is saved/loaded under parent._cfg['music_offset_dlg_geo'].
    """
    def __init__(self, parent, vlc_instance, audio_path: str, initial_offset: float, bin_dir: str):
        super().__init__(parent)
        self.setWindowTitle("Choose Background Music Start")
        self.setModal(True)
        self._vlc   = vlc_instance
        self._mpath = audio_path
        self._bin   = bin_dir
        self.selected_offset = float(initial_offset or 0.0)
        self._player = None
        self._total_ms = 0
        self._temp_png_path = None
        self._dragging = False
        v = QVBoxLayout(self)
        self.wave = QLabel("Generating waveform...")
        self.wave.setAlignment(Qt.AlignCenter)
        self.wave.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.wave.setScaledContents(True)
        v.addWidget(self.wave)
        self.wave.installEventFilter(self)
        self.slider = TrimmedSlider(self)
        self.slider.enable_trim_overlays(False)
        self.slider.setFixedHeight(50)
        v.addWidget(self.slider)
        self.sync_info_label = QLabel(
            "<i>Note: Audio preview sync may vary due to buffering.<br>"
            "Please rely on <b>listening</b> to choose the exact start time.</i>"
        )
        self.sync_info_label.setAlignment(Qt.AlignCenter)
        self.sync_info_label.setStyleSheet("font-size: 10px; color: #aabbcc; margin-top: 5px; margin-bottom: 10px;")
        self.sync_info_label.setWordWrap(True)
        v.insertWidget(1, self.sync_info_label)
        row = QHBoxLayout()
        self.ok_btn = QPushButton("OK")
        self.play_btn = QPushButton("▶ Play")
        self.cancel_btn = QPushButton("Cancel")
        for _b in (self.ok_btn, self.cancel_btn):
            _b.setFixedWidth(100)
            _b.setStyleSheet("""
                QPushButton {
                    background-color: #3aa0d8; color: white; font-size: 13px;
                    padding: 6px 14px; border-radius: 6px;
                }
                QPushButton:hover  { background-color: #52b0e4; }
                QPushButton:pressed{ background-color: #2c8fc4; }
            """)
        self.play_btn.setFixedHeight(30)
        self.play_btn.setFixedWidth(100)
        self.play_btn.setStyleSheet("""
            QPushButton {
                background-color: #59A06D; color: white; font-size: 14px;
                padding: 6px 14px; border-radius: 6px;
            }
            QPushButton:hover  { background-color: #6fb57f; }
            QPushButton:pressed{ background-color: #4a865a; }
        """)
        row.addStretch(1); row.addWidget(self.ok_btn); row.addSpacing(40)
        row.addWidget(self.play_btn); row.addSpacing(40)
        row.addWidget(self.cancel_btn); row.addStretch(1)
        v.addLayout(row)
        self._caret = QLabel(self.wave)
        self._caret.setStyleSheet("background:#3498db;")
        self._caret.resize(2, 20)
        self._caret.hide()
        self._timer = QTimer(self)
        self._timer.setInterval(50)
        self._timer.timeout.connect(self._tick)
        self.ok_btn.clicked.connect(self.accept)
        self.cancel_btn.clicked.connect(self.reject)
        self.play_btn.clicked.connect(self._toggle_play_pause)
        self.slider.valueChanged.connect(self._on_slider_changed)
        self.slider.sliderPressed.connect(lambda: setattr(self, "_dragging", True))
        self.slider.sliderReleased.connect(self._on_drag_end)

        self._restore_geometry()
        self._init_assets(initial_offset or 0.0)
        self._update_play_button(False)

    def _restore_geometry(self):
        try:
            parent = self.parent()
            cfg = getattr(parent, "_cfg", {}) if parent else {}
            g = cfg.get("music_offset_dlg_geo", {}) if isinstance(cfg, dict) else {}
            w, h = int(g.get("w", 900)), int(g.get("h", 360))
            x, y = int(g.get("x", -1)), int(g.get("y", -1))
            self.resize(max(640, w), max(360, h))
            if x >= 0 and y >= 0:
                self.move(x, y)
        except Exception:
            self.resize(900, 360)

    def _save_geometry(self):
        try:
            parent = self.parent()
            if not parent:
                return
            cfg = getattr(parent, "_cfg", None)
            if isinstance(cfg, dict):
                cfg["music_offset_dlg_geo"] = {"x": self.x(), "y": self.y(), "w": self.width(), "h": self.height()}
                _save_conf(cfg)
        except Exception:
            pass

    def _ffmpeg(self):
        exe = "ffmpeg.exe" if sys.platform.startswith("win") else "ffmpeg"
        p = os.path.join(self._bin or "", exe)
        return p if os.path.isfile(p) else exe

    def _ffprobe(self):
        exe = "ffprobe.exe" if sys.platform.startswith("win") else "ffprobe"
        p = os.path.join(self._bin or "", exe)
        return p if os.path.isfile(p) else exe

    def _probe_duration(self) -> float:
        try:
            cmd = [self._ffprobe(), "-v", "error", "-show_entries", "format=duration",
                   "-of", "default=nokey=1:noprint_wrappers=1", self._mpath]
            out = subprocess.check_output(
                cmd,
                creationflags=(subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0)
            )
            return max(0.0, float(out.decode().strip()))
        except Exception:
            return 0.0

    def _init_assets(self, initial_offset: float):
        dur = self._probe_duration()
        self._total_ms = int(dur * 1000)
        self.slider.setRange(0, self._total_ms)
        self.slider.set_duration_ms(self._total_ms)
        self.slider.setValue(int(initial_offset * 1000))
        try:
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tf:
                tmp_png = tf.name
            self._temp_png_path = tmp_png
            cmd = [
                self._ffmpeg(), "-hide_banner", "-loglevel", "error",
                "-copyts", "-start_at_zero",
                "-i", self._mpath, "-frames:v", "1",
                "-filter_complex",
                "compand=attacks=0:decays=0:points=-80/-80|-35/-18|-20/-10|0/-3|20/-1,"
                "aresample=48000,pan=mono|c0=0.5*c0+0.5*c1,"
                "showwavespic=s=1000x180:split_channels=0:colors=0xa6c8d2",
                "-y", tmp_png
            ]
            subprocess.run(
                cmd, check=True, capture_output=True, text=True,
                creationflags=(subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0)
            )
            if not os.path.isfile(tmp_png):
                self.wave.setText("Error: Waveform image not created.")
                self.wave.hide(); return
            pixmap = QPixmap(tmp_png)
            if pixmap.isNull():
                self.wave.setText("Error: Could not load waveform image.")
                self.wave.hide(); return
            self.wave.setPixmap(pixmap)
            self.wave.show(); self.wave.update()
        except Exception as e:
            self.wave.setText(f"Error: {e}")
            self.wave.hide()
        finally:
            QTimer.singleShot(0, self._sync_caret_to_slider)

    def _ensure_player(self):
        if self._player or self._vlc is None:
            return
        try:
            self._player = self._vlc.media_player_new()
            m = self._vlc.media_new(self._mpath)
            self._player.set_media(m)
            if _vlc_mod is not None:
                try:
                    em = self._player.event_manager()
                    em.event_attach(_vlc_mod.EventType.MediaPlayerEndReached, self._on_vlc_ended)
                except Exception:
                    pass
        except Exception:
            self._player = None

    def _update_play_button(self, playing: bool):
        if playing:
            self.play_btn.setText("⏸ Pause"); self.play_btn.setToolTip("Pause preview")
        else:
            self.play_btn.setText("▶ Play");  self.play_btn.setToolTip("Play preview")

    def _reset_player(self):
        try:
            if self._player:
                try: self._player.stop()
                except Exception: pass
                try: self._player.release()
                except Exception: pass
            self._player = None
            self._ensure_player()
        except Exception:
            pass

    def _toggle_play_pause(self):
        self._ensure_player()
        if not self._player:
            return
        try:
            state = str(self._player.get_state()).lower()
            if state.endswith("playing"):
                self._player.pause()
                self._update_play_button(False)
                self._timer.stop()
            else:
                self._start_playing_from_slider()
        except Exception:
            pass

    def _start_playing_from_slider(self):
        try:
            if self._player is None:
                self._reset_player()
            if not self._player:
                return
            want_ms = int(self.slider.value())
            self._player.play()
            self._player.set_time(want_ms)
            self._timer.start()
            self._update_play_button(True)
        except Exception:
            try:
                if self._timer: self._timer.stop()
                self._update_play_button(False)
            except Exception:
                pass

    def eventFilter(self, obj, event):
        if obj is self.wave and event.type() == QEvent.MouseButtonPress and event.button() == Qt.LeftButton:
            try:
                click_x = event.pos().x()
                cr = self.wave.contentsRect()
                x0 = self.wave.mapToParent(cr.topLeft()).x()
                w  = cr.width()
                if w > 0:
                    pos_fraction = max(0.0, min(1.0, (click_x - x0) / w))
                    min_val = self.slider.minimum()
                    max_val = self.slider.maximum()
                    rng = max(1, max_val - min_val)
                    target_ms = int(min_val + pos_fraction * rng)
                    self.slider.setValue(target_ms)
                    if self._player and self._player.is_playing():
                        self._player.set_time(target_ms)
                    return True
            except Exception:
                pass
        return super().eventFilter(obj, event)

    def _on_drag_end(self):
        self._dragging = False
        try:
            if self._player:
                self._player.set_time(int(self.slider.value()))
        except Exception:
            pass

    def _on_slider_changed(self, v):
        try:
            if self._player:
                self._player.set_time(int(v))
        except Exception:
            pass
        self._sync_caret_to_slider()

    def _sync_caret_to_slider(self):
        try:
            if not self.wave.isVisible() or self.wave.geometry().isEmpty():
                self._caret.hide(); return
            v = int(self.slider.value())
            vmin, vmax = self.slider.minimum(), self.slider.maximum()
            span = max(1, vmax - vmin)
            frac = (v - vmin) / span
            frac = 0.0 if frac < 0.0 else 1.0 if frac > 1.0 else frac
            cr = self.wave.contentsRect()
            top_left = self.wave.mapToParent(cr.topLeft())
            x0, y0 = top_left.x(), top_left.y()
            w, h = cr.width(), cr.height()
            x = x0 + int(frac * max(1, w - 1))
            x = max(x0, min(x0 + w - self._caret.width(), x))
            self._caret.setGeometry(x, y0, 2, h)
            self._caret.raise_(); self._caret.show()
        except Exception:
            self._caret.hide()

    def _tick(self):
        if not self._player:
            return
        try:
            state = str(self._player.get_state()).lower()
            if not state.endswith("playing"):
                self._timer.stop(); return
            raw_ms = int(self._player.get_time() or 0)
            end_ms = self.slider.maximum()
            display_ms = min(end_ms, max(0, raw_ms + PREVIEW_VISUAL_LEAD_MS))
            if display_ms >= end_ms - 10:
                self._on_vlc_ended(); return
            if not self._dragging:
                self.slider.blockSignals(True)
                self.slider.setValue(display_ms)
                self.slider.blockSignals(False)
                self._sync_caret_to_slider()
        except Exception:
            pass

    def _on_vlc_ended(self, event=None):
        QTimer.singleShot(0, lambda: (
            self._timer.stop(),
            self._update_play_button(False),
            self.slider.blockSignals(True),
            self.slider.setValue(self.slider.maximum()),
            self.slider.blockSignals(False),
            self._sync_caret_to_slider(),
            self._reset_player()
        ))

    def closeEvent(self, e):
        try:
            if getattr(self, "_temp_png_path", None) and os.path.exists(self._temp_png_path):
                os.remove(self._temp_png_path)
                self._temp_png_path = None
        except Exception:
            pass
        self._save_geometry()
        try:
            if getattr(self, "_player", None):
                self._player.stop(); self._player.release()
                self._player = None
        except Exception:
            pass
        try:
            if getattr(self, "_timer", None):
                self._timer.stop()
        except Exception:
            pass
        super().closeEvent(e)

    def accept(self):
        self.selected_offset = float(self.slider.value()) / 1000.0
        super().accept()

    def reject(self):
        super().reject()


class VideoMergerWindow(QMainWindow):
    ...
    
    MAX_FILES = 10
    status_updated = pyqtSignal(str)
    return_to_main = pyqtSignal()
    
    def __init__(self, ffmpeg_path: str | None = None, parent: QWidget | None = None, vlc_instance=None, bin_dir: str = ''):
        super().__init__(parent)
        self.vlc_instance = vlc_instance
        self.bin_dir = bin_dir
        self.logger = _get_logger()
        self.logger.info("OPEN: Video Merger window created")
        self.setWindowTitle("Video Merger")
        try:
            icon_path = str(_proj_root() / "icons" / "app_icon.ico")
            if os.path.exists(icon_path):
                self.setWindowIcon(QIcon(icon_path))
                self.logger.info("Set window icon from: %s", icon_path)
            else:
                 self.logger.warning("Icon file not found at: %s", icon_path)
        except Exception as e:
            self.logger.error("Failed to set window icon: %s", e)
        self.resize(980, 560)
        self.ffmpeg = ffmpeg_path or "ffmpeg"
        self.process: QProcess | None = None
        self._temp_dir: tempfile.TemporaryDirectory | None = None
        self._output_path: str = ""
        self._cmd: list[str] = []
        self._cfg = _load_conf()
        self._last_dir = self._cfg.get("last_dir", "")
        self._music_files = []
        self._setup_style()
        self._setup_ui()
        try:
            g = self._cfg.get("geometry", {})
            if g:
                self.move(int(g.get("x", self.x())), int(g.get("y", self.y())))
                self.resize(int(g.get("w", self.width())), int(g.get("h", self.height())))
                self.logger.info("RESTORE: Window geometry x=%s y=%s w=%s h=%s", g.get("x"), g.get("y"), g.get("w"), g.get("h"))
        except Exception:
            pass
        self._update_button_states()
        self.listw.itemSelectionChanged.connect(self._update_button_states)
        self.status_updated.connect(self._handle_status_update)
        self.listw.model().rowsInserted.connect(self._update_button_states)
        self.listw.model().rowsRemoved.connect(self._update_button_states)
        self.listw.model().rowsMoved.connect(self._update_button_states)
        self._scan_mp3_folder()
        self._populate_music_combo()
        self.add_music_checkbox.toggled.connect(self._on_add_music_toggled)
        self.music_combo.currentIndexChanged.connect(self._on_music_selected)
        self.music_volume_slider.valueChanged.connect(self._on_music_volume_changed)
        QTimer.singleShot(0, self._update_music_badge)

    def closeEvent(self, e):
        try:
            g = {"x": self.x(), "y": self.y(), "w": self.width(), "h": self.height()}
            self._cfg["geometry"]  = g
            self._cfg["last_dir"]  = self._last_dir or self._cfg.get("last_dir", "")
            self._cfg["last_out_dir"] = str(Path(self._output_path).parent) if self._output_path else self._cfg.get("last_out_dir", "")
            self._cfg["last_music_volume"] = self._music_eff()
            _save_conf(self._cfg)
            self.logger.info("SAVE: Geometry, last input dir, and last output dir saved")
        except Exception:
            pass
        return super().closeEvent(e)
    
    def _handle_status_update(self, msg: str):
        """Updates the status label with real-time feedback."""
        self.status_label.setStyleSheet("color: #43b581; font-weight: normal;")
        self.status_label.setText(f"Processing merge... {msg}")

    def _process_ffmpeg_output(self):
        """Extracts and displays the current progress from FFmpeg's stderr output."""
        try:
            output = self.process.readAllStandardError().data().decode().strip()
            last_line = output.split('\r')[-1].split('\n')[-1].strip()
            if last_line and (last_line.startswith("frame=") or last_line.startswith("size=")):
                self.status_updated.emit(last_line)
            self.logger.debug("FFMPEG_OUTPUT: %s", output)
        except Exception:
            pass

    def _setup_style(self):
        """Applies a dark theme stylesheet similar to the main app."""
        self.setStyleSheet("""
            QMainWindow, QWidget {
                background-color: #2c3e50; /* Main dark background */
                color: #ecf0f1; /* Light text */
                font-family: "Helvetica Neue", Arial, sans-serif;
                font-size: 13px;
            }
            QLabel#titleLabel {
                font-size: 18px;
                font-weight: bold;
                color: #3498db; /* Blue title color */
                padding-bottom: 10px; /* Add some space below title */
            }
            QPushButton {
                background-color: #3498db; /* Blue buttons */
                color: #ffffff;
                border: none;
                padding: 8px 16px; /* Adjusted padding */
                border-radius: 6px;
                font-weight: bold;
                min-height: 20px; /* Ensure minimum height */
            }
            QPushButton:hover {
                background-color: #2980b9; /* Darker blue on hover */
            }
            QPushButton:disabled {
                background-color: #566573; /* Greyed out when disabled */
                color: #aeb6bf;
            }
            /* Style for Add, Remove, Clear buttons */
            QPushButton#aux-btn {
                 background-color: #566573; /* Grey for auxiliary buttons */
            }
            QPushButton#aux-btn:hover {
                 background-color: #6c7a89;
            }
            /* Specific style for the Merge button */
            QPushButton#mergeButton {
                background-color: #2ecc71; /* Green merge button */
                color: #1e242d; /* Dark text on green */
                font-weight: bold;
                padding: 10px 25px; /* Slightly larger padding */
                border-radius: 8px;
            }
            QPushButton#mergeButton:hover {
                background-color: #48e68e; /* Lighter green on hover */
            }
            QPushButton#mergeButton:disabled {
                 background-color: #566573;
                 color: #aeb6bf;
            }
            /* Style for the Return button */
            QPushButton#returnButton {
                background-color: #bfa624; /* Yellow like main app merge */
                color: black;
                font-weight: 600;
                padding: 6px 12px;
                border-radius: 6px;
                min-height: 35px; /* Match height of other row buttons */
            }
            QPushButton#returnButton:hover {
                 background-color: #dcbd2f; /* Lighter yellow */
            }
            QPushButton#returnButton:disabled {
                 background-color: #566573;
                 color: #aeb6bf;
            }
            QListWidget {
                background-color: #34495e; /* Darker list background */
                border: 1px solid #4a667a;
                border-radius: 8px;
                padding: 8px;
                alternate-background-color: #2c3e50; /* Match main background */
                outline: 0;
            }
            QListWidget::item {
                padding: 10px 8px;
                margin-bottom: 4px;
                border-radius: 4px;
                background-color: #4a667a; /* Item background */
                color: #ecf0f1; /* Light text */
            }
            QListWidget::item:selected {
                background-color: #3498db; /* Blue selection */
                color: white;
            }
            /* Styles for Music Controls to match main app */
            QCheckBox { spacing: 8px; }
            QCheckBox::indicator { width: 16px; height: 16px; }
            QComboBox {
                background-color: #4a667a; border: 1px solid #3498db; border-radius: 5px;
                padding: 4px 8px; min-height: 24px; color: #ecf0f1;
            }
            QComboBox::drop-down { border: none; }
            QComboBox::down-arrow { image: url(none); }
            QComboBox QAbstractItemView {
                background-color: #34495e; border: 1px solid #4a667a; selection-background-color: #3498db;
                color: #ecf0f1;
            }
            QDoubleSpinBox {
                background-color: #4a667a; border: 1px solid #3498db; border-radius: 5px;
                padding: 4px 6px; min-height: 24px; color: #ecf0f1;
            }
            QSlider::groove:vertical {
                border: 1px solid #4a4a4a; background: #333; width: 16px; border-radius: 6px;
            }
            QSlider::handle:vertical {
                 background: #7289da; border: 1px solid #5c5c5c;
                 height: 18px; margin: 0 -2px; border-radius: 6px;
            }
            QLabel { /* Default Label */
                 padding: 0; margin: 0; /* Remove default padding for finer control */
            }
            #musicVolumeBadge { /* Ensure badge style is applied */
                 color: white; background: rgba(0,0,0,160); padding: 2px 6px;
                 border-radius: 6px; font-weight: bold;
            }
        """)

    def _setup_ui(self):
        """Builds the layout and widgets."""
        root = QWidget(self)
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(20, 16, 20, 16)
        outer.setSpacing(16)
        title = QLabel('Sort the Videos in the Correct Desired Order. Hit the "Merge Videos" Button When Done.')
        title.setObjectName("titleLabel")
        title.setAlignment(Qt.AlignHCenter)
        outer.addWidget(title)
        list_container = QHBoxLayout()
        outer.addLayout(list_container, 1)
        self.listw = QListWidget()
        self.listw.setAlternatingRowColors(True)
        self.listw.setDragDropMode(QListWidget.InternalMove)
        self.listw.setDefaultDropAction(Qt.MoveAction)
        self.listw.setSelectionMode(QListWidget.SingleSelection) 
        list_container.addWidget(self.listw, 1)
        move_btns_col = QVBoxLayout()
        move_btns_col.setContentsMargins(0, 0, 0, 0)
        move_btns_col.setSpacing(6)
        self.btn_up = QPushButton("▲ Up ▲")
        self.btn_up.setToolTip("Move selected video up")
        self.btn_up.setFixedSize(160, 35)
        self.btn_up.clicked.connect(lambda: self.move_item(-1))
        self.btn_down = QPushButton("▼ Down ▼")
        self.btn_down.setToolTip("Move selected video down")
        self.btn_down.setFixedSize(160, 35)
        self.btn_down.clicked.connect(lambda: self.move_item(1))
        move_btns_col.addStretch(1)
        move_btns_col.addWidget(self.btn_up)
        move_btns_col.addWidget(self.btn_down)
        move_btns_col.addStretch(1)
        list_container.addLayout(move_btns_col)
        music_layout = QHBoxLayout()
        music_layout.setSpacing(15)
        self.add_music_checkbox = QCheckBox("Add Background Music")
        self.add_music_checkbox.setToolTip("Toggle background MP3 mixing from the ./mp3 folder.")
        self.add_music_checkbox.setChecked(False)
        music_layout.addWidget(self.add_music_checkbox)
        self.music_combo = QComboBox()
        try:
            self.music_combo.setElideMode(Qt.ElideMiddle)
        except Exception:
            pass
        self.music_combo.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self.music_combo.setMinimumWidth(400)
        self.music_combo.setMaximumWidth(400)
        self.music_combo.setMinimumContentsLength(24)
        self.music_combo.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.music_combo.setVisible(False)
        music_layout.addWidget(self.music_combo)
        self.music_offset_input = QDoubleSpinBox()
        self.music_offset_input.setPrefix("Music Start (s): ")
        self.music_offset_input.setMinimumWidth(180)
        self.music_offset_input.setMaximumWidth(180)
        self.music_offset_input.setDecimals(2)
        self.music_offset_input.setSingleStep(0.5)
        self.music_offset_input.setRange(0.0, 0.0)
        self.music_offset_input.setValue(0.0)
        self.music_offset_input.setVisible(False)
        music_layout.addWidget(self.music_offset_input)
        self.music_volume_slider = QSlider(Qt.Vertical, self)
        self.music_volume_slider.setObjectName("musicVolumeSlider")
        self.music_volume_slider.setRange(0, 100)
        self.music_volume_slider.setTickInterval(1)
        self.music_volume_slider.setTracking(True)
        self.music_volume_slider.setVisible(False)
        self.music_volume_slider.setFocusPolicy(Qt.NoFocus)
        self.music_volume_slider.setMinimumHeight(40)
        eff_default = int(35)
        self.music_volume_slider.setValue(eff_default)
        self.music_volume_slider.setStyleSheet(f"""
            QSlider#musicVolumeSlider::groove:vertical {{
            border: 1px solid #4a4a4a; background: #333; width: 16px; border-radius: 6px;
            }}
            QSlider#musicVolumeSlider::handle:vertical {{
            background: #7289da; border: 1px solid #5c5c5c;
            height: 18px; margin: 0 -2px; border-radius: 6px;
            }}
        """)
        self.music_volume_label = QLabel(f"{eff_default}%")
        self.music_volume_label.setAlignment(Qt.AlignHCenter)
        self.music_volume_label.setVisible(False)
        self.music_volume_badge = QLabel(f"{eff_default}%", self)
        self.music_volume_badge.setObjectName("musicVolumeBadge")
        self.music_volume_badge.setStyleSheet(
            "color: white; background: rgba(0,0,0,160); padding: 2px 6px; "
            "border-radius: 6px; font-weight: bold;"
        )
        self.music_volume_badge.hide()
        music_slider_box = QVBoxLayout()
        music_slider_box.setSpacing(2)
        music_slider_box.addWidget(self.music_volume_slider, 0, Qt.AlignHCenter)
        music_slider_box.addWidget(self.music_volume_label, 0, Qt.AlignHCenter)
        music_layout.addLayout(music_slider_box)
        outer.addLayout(music_layout)
        self.status_label = QLabel("Ready. Add 2 to 10 videos to begin.")
        self.status_label.setStyleSheet("color: #7289da; font-weight: bold;")
        outer.addWidget(self.status_label)
        row = QHBoxLayout()
        outer.addLayout(row)
        self.btn_add = QPushButton("Add Videos")
        self.btn_add.setFixedSize(160, 35)
        self.btn_add.setObjectName("aux-btn")
        self.btn_add.clicked.connect(self.add_videos)
        row.addWidget(self.btn_add)
        self.btn_remove = QPushButton("Remove Selected")
        self.btn_remove.setFixedSize(160, 35)
        self.btn_remove.setObjectName("aux-btn")
        self.btn_remove.clicked.connect(self.remove_selected)
        row.addWidget(self.btn_remove)
        self.btn_clear = QPushButton("Clear All")
        self.btn_clear.setFixedSize(160, 35)
        self.btn_clear.setObjectName("aux-btn")
        self.btn_clear.clicked.connect(self.listw.clear)
        row.addWidget(self.btn_clear)
        self.btn_back = QPushButton("Return to Main App")
        self.btn_back.setFixedSize(160, 35)
        self.btn_back.setObjectName("returnButton")
        self.btn_back.clicked.connect(self.return_to_main_app)
        merge_row = QHBoxLayout()
        outer.addLayout(merge_row)
        merge_row.addStretch(1)
        self.btn_merge = QPushButton("Merge Videos")
        self.btn_merge.setObjectName("mergeButton")
        self.btn_merge.clicked.connect(self.merge_now)
        merge_row.addWidget(self.btn_merge)
        merge_row.addStretch(1)
        merge_row.addWidget(self.btn_back)

    def _update_button_states(self):
        """Enable/disable buttons based on list state and processing state."""
        n = self.listw.count()
        is_processing = self.process is not None
        selected_items = self.listw.selectedItems()
        is_single_selection = len(selected_items) == 1
        self.add_music_checkbox.setEnabled(not is_processing)
        if not is_processing:
            self._on_add_music_toggled(self.add_music_checkbox.isChecked())
        else:
            self.music_combo.setEnabled(False)
            self.music_offset_input.setEnabled(False)
            self.music_volume_slider.setEnabled(False)
        self.btn_merge.setEnabled(n >= 2 and not is_processing)
        self.btn_remove.setEnabled(bool(selected_items) and not is_processing)
        self.btn_clear.setEnabled(n > 0 and not is_processing)
        self.btn_add.setEnabled(not is_processing and n < self.MAX_FILES)
        if is_single_selection and not is_processing:
            current_row = self.listw.row(selected_items[0])
            self.btn_up.setEnabled(current_row > 0)
            self.btn_down.setEnabled(current_row < n - 1)
        else:
            self.btn_up.setEnabled(False)
            self.btn_down.setEnabled(False)
        if is_processing:
            self.status_label.setText("Processing merge... Please wait.")
        elif n == 0:
            self.status_label.setText("Ready. Add 2 to 10 videos to begin.")
        elif n < 2:
            self.status_label.setText(f"Waiting for more videos. Currently {n}/10.")
        else:
            self.status_label.setText(f"Ready to merge {n} videos. Order is set.")
        
    def set_ui_busy(self, is_busy: bool):
        """Set the UI state when processing is active."""
        if is_busy:
            self.setWindowTitle("Video Merger (Processing...)")
            self.btn_back.setDisabled(True)
            self.listw.setDisabled(True)
            self.btn_up.setDisabled(True)
            self.btn_down.setDisabled(True)
        else:
            self.setWindowTitle("Video Merger")
            self.btn_back.setDisabled(False)
            self.listw.setDisabled(False)
        self._update_button_states()

    def add_videos(self):
        start_dir = self._last_dir if self._last_dir and Path(self._last_dir).exists() else ""
        files, _ = QFileDialog.getOpenFileNames(
            self, "Select videos to merge", start_dir,
            "Videos (*.mp4 *.mov *.mkv *.m4v *.ts *.avi *.webm);;All Files (*)"
        )
        if not files:
            return
        current = self.listw.count()
        room = max(0, self.MAX_FILES - current)
        if room <= 0:
            QMessageBox.warning(self, "Limit reached", f"Maximum {self.MAX_FILES} files already added.")
            return
        current_files = {self.listw.item(i).data(Qt.UserRole) for i in range(current)}
        new_files = [f for f in files if f not in current_files]
        if new_files:
            try:
                self._last_dir = str(Path(new_files[0]).parent)
            except Exception:
                pass
        for f in new_files[:room]:
            try:
                sz = Path(f).stat().st_size
                self.logger.info("ADD: %s | size=%s | dir=%s", f, _human(sz), Path(f).parent)
            except Exception:
                pass
            item = QListWidgetItem(Path(f).name)
            item.setToolTip(f)
            item.setData(Qt.UserRole, f)
            self.listw.addItem(item)
        if len(files) > len(new_files):
             QMessageBox.warning(self, "Duplicates", "Some selected files were already in the list and were ignored.")
        if len(new_files) > room:
            QMessageBox.information(self, "Limit", f"Only {room} unique file(s) were added (max {self.MAX_FILES} total).")

    def remove_selected(self):
        for it in self.listw.selectedItems():
            self.listw.takeItem(self.listw.row(it))

    def move_item(self, direction: int):
        """Moves the selected item up (-1) or down (+1).
        Only works for the single currently selected item due to clear intent."""
        selected_items = self.listw.selectedItems()
        if not selected_items:
            return
        item_to_move = selected_items[0]
        current_row = self.listw.row(item_to_move)
        new_row = current_row + direction
        if new_row < 0 or new_row >= self.listw.count():
            return
        item = self.listw.takeItem(current_row)
        self.listw.insertItem(new_row, item)
        self.listw.setCurrentRow(new_row)

    def merge_now(self):
        n = self.listw.count()
        if n < 2:
            QMessageBox.information(self, "Need more videos", "Please add at least 2 videos to merge.")
            return
        last_out_dir = self._cfg.get("last_out_dir", self._last_dir or Path.home().as_posix())
        default_path = str(Path(last_out_dir) / "merged_video.mp4")
        out_path, _ = QFileDialog.getSaveFileName(
            self, "Save merged video as…", 
            default_path,
            "MP4 (*.mp4);;MOV (*.mov);;MKV (*.mkv);;All Files (*)"
        )
        if not out_path:
            return
        self._temp_dir = tempfile.TemporaryDirectory()
        concat_txt = Path(self._temp_dir.name, "concat_list.txt")
        with concat_txt.open("w", encoding="utf-8") as f:
            for i in range(n):
                it = self.listw.item(i)
                f.write(f"file '{it.data(Qt.UserRole).replace('\'', '\\\'')}'\n")
        self._output_path = out_path
        music_path, music_vol = self._get_selected_music()
        music_offset = self.music_offset_input.value()
        base_cmd = [self.ffmpeg, "-y", "-f", "concat", "-safe", "0", "-i", str(concat_txt)]
        if music_path:
            self.logger.info("MUSIC: Adding background music. Audio will be re-encoded.")
            base_cmd.extend(["-i", music_path])
            self._cmd = base_cmd + [
                "-filter_complex", f"[0:a]volume=1.0[a0]; [1:a]atrim=start={music_offset:.3f},volume={music_vol:.3f}[a1]; [a0][a1]amix=inputs=2:duration=first[a_out]",
                "-map", "0:v",
                "-map", "[a_out]",
                "-c:v", "copy",
                "-c:a", "aac", "-b:a", "192k",
                "-shortest",
                str(out_path)
            ]
        else:
            self.logger.info("MUSIC: No background music. Using fast stream copy.")
            self._cmd = base_cmd + [
                "-c", "copy",
                str(out_path)
            ]
        inputs = []
        total_in = 0
        for i in range(n):
            it = self.listw.item(i)
            f = it.data(Qt.UserRole)
            try:
                sz = Path(f).stat().st_size
                total_in += sz
                inputs.append({"path": f, "size": _human(sz)})
            except Exception:
                inputs.append({"path": f, "size": "?"})
        self.logger.info("MERGE_START: outputs='%s'", self._output_path)
        self.logger.info("MERGE_INPUTS: %s", inputs)
        self.logger.info("MERGE_CMD: %s", " ".join(self._cmd))
        self.logger.info("MERGE_TOTAL_INPUT_SIZE: %s", _human(total_in))
        self.process = QProcess(self)
        self.process.finished.connect(self._merge_finished)
        self.process.readyReadStandardError.connect(self._process_ffmpeg_output)
        self._merge_started_at = time.time()
        self.set_ui_busy(True)
        print(f"Starting merge process: {' '.join(self._cmd)}")
        self.process.start(self.ffmpeg, self._cmd[1:])

    def _merge_finished(self, exit_code, exit_status):
        """Handle the result of the QProcess merge."""
        try:
            stdout = self.process.readAllStandardOutput().data().decode()
        except Exception:
            stdout = ""
        try:
            stderr = self.process.readAllStandardError().data().decode()
        except Exception:
            stderr = ""
        elapsed = None
        try:
            if hasattr(self, "_merge_started_at"):
                elapsed = max(0, time.time() - self._merge_started_at)
        except Exception:
            pass
        concat_txt_path = None
        if self._temp_dir and hasattr(self._temp_dir, 'name'):
            concat_txt_path = Path(self._temp_dir.name) / "concat_list.txt"
        if self._temp_dir:
            try:
                self._temp_dir.cleanup()
                self.logger.info("Cleaned up temporary directory: %s", self._temp_dir.name)
            except Exception as e:
                self.logger.error("Error cleaning up temporary directory: %s", e)
            finally:
                self._temp_dir = None 
        if concat_txt_path and concat_txt_path.exists():
            try:
                os.remove(concat_txt_path)
                self.logger.info("Removed temporary concat list: %s", concat_txt_path)
            except Exception as e:
                 self.logger.error("Error removing concat list %s: %s", concat_txt_path, e)
        self.set_ui_busy(False)
        self.process = None
        if exit_status == QProcess.CrashExit:
             QMessageBox.critical(self, "Merge Failed", "FFmpeg process crashed unexpectedly.")
             return
        if exit_code != 0:
            QMessageBox.critical(
                self, "Merge failed",
                "ffmpeg reported an error. This usually means inputs have mismatched codecs.\n"
                "Ensure all videos share the same codec, resolution, and audio format for lossless concatenation.\n\n"
                f"Output:\n{(stdout + stderr)[:4000]}"
            )
            return
        msg = QMessageBox(self)
        msg.setWindowTitle("Done")
        path_text = f"File saved to: <font color='black'>{self._output_path}</font>"
        msg.setText("Videos merged successfully.")
        msg.setInformativeText(path_text)
        msg.setIcon(QMessageBox.Information)
        msg.addButton("OK", QMessageBox.AcceptRole)
        btn_open_folder = msg.addButton("Open Folder", QMessageBox.YesRole)            
        msg.exec_()
        clicked_button = msg.clickedButton()
        if clicked_button == btn_open_folder:
            self._open_folder(str(Path(self._output_path).parent))
            QApplication.instance().quit()
        elif self.parent() is None:
            self.close()
        try:
            out_sz = Path(self._output_path).stat().st_size if self._output_path else 0
            self.logger.info("MERGE_DONE: exit_code=%s | output='%s' | size=%s",
                            exit_code, self._output_path, _human(out_sz))
        except Exception:
            pass

    def _open_folder(self, path: str):
        """Opens the specified folder using the default file explorer."""
        folder_path = str(Path(path))
        if not folder_path or not os.path.isdir(folder_path):
            self.logger.warning("OPEN_FOLDER: Path is not a directory or does not exist: %s", folder_path)
            return
        try:
            if sys.platform == 'win32':
                os.startfile(folder_path, 'explore')
            elif sys.platform == 'darwin':
                subprocess.Popen(['open', folder_path])
            else:
                subprocess.Popen(['xdg-open', folder_path])
            self.logger.info("OPEN_FOLDER: Opened %s", folder_path)
        except Exception as e:
            self.logger.error("OPEN_FOLDER: Failed to open folder %s | Error: %s", folder_path, e)

    def return_to_main_app(self):
        """Emits a signal to tell the parent (main app) to return to main view."""
        self.logger.info("ACTION: Return to Main App clicked. Emitting return signal.")
        self.return_to_main.emit()
        self.close()

    def _mp3_dir(self) -> Path:
        """Return the absolute path to the project's central MP3 folder."""
        d = _proj_root() / "mp3"
        try:
            d.mkdir(exist_ok=True)
        except Exception:
            pass
        return d

    def _ffprobe(self) -> str:
        """Gets the path to the ffprobe executable, assuming it's next to ffmpeg."""
        try:
            ffmpeg_dir = Path(self.ffmpeg).parent
            for name in ("ffprobe", "ffprobe.exe"):
                p = ffmpeg_dir / name
                if p.exists():
                    return str(p)
        except Exception:
            pass
        return "ffprobe"

    def _probe_audio_duration(self, path: str) -> float:
        """Return audio duration in seconds (float) or 0.0 on failure."""
        try:
            cmd = [self._ffprobe(), "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path]
            r = subprocess.run(cmd, capture_output=True, text=True, check=True,
                               creationflags=(subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0))
            return max(0.0, float(r.stdout.strip()))
        except Exception:
            self.logger.exception("Failed to probe audio duration for %s", path)
            return 0.0

    def _update_music_badge(self):
        """Position the small % badge next to the music volume handle."""
        try:
            if not self.music_volume_slider.isVisible():
                self.music_volume_badge.hide()
                return
            s = self.music_volume_slider
            opt = QStyleOptionSlider()
            opt.initFrom(s)
            opt.orientation = Qt.Vertical
            opt.minimum = s.minimum()
            opt.maximum = s.maximum()
            opt.sliderPosition = int(s.value())
            opt.sliderValue = int(s.value())
            opt.upsideDown = not s.invertedAppearance()
            opt.rect = s.rect()
            handle = s.style().subControlRect(QStyle.CC_Slider, opt, QStyle.SC_SliderHandle, s)
            parent = s.parentWidget() or self
            handle_center = handle.center()
            pt = s.mapTo(parent, handle_center)
            self.music_volume_badge.setText(f"{self._music_eff(int(s.value()))}%")
            self.music_volume_badge.adjustSize()
            x = s.x() + s.width() + 8
            y = pt.y() - (self.music_volume_badge.height() // 2)
            y = max(2, min((parent.height() - self.music_volume_badge.height() - 2), y))
            self.music_volume_badge.move(x, y)
            self.music_volume_badge.show()
        except Exception:
            pass

    def _scan_mp3_folder(self):
        r"""Scan .\mp3 for .mp3 files, sorted by modified time (newest first)."""
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
            self._music_files = [(n, p) for _, n, p in files]
        except Exception:
            self._music_files = []
        self._populate_music_combo()

    def _populate_music_combo(self):
        """Refresh the dropdown safely based on self._music_files."""
        mf = getattr(self, "_music_files", [])
        self.music_combo.blockSignals(True)
        self.music_combo.clear()
        if not mf:
            self.music_combo.addItem("No MP3 files found in ./mp3", "")
            self.music_combo.setEnabled(False)
        else:
            self.music_combo.addItem("— Select an MP3 —", "")
            for name, path in mf:
                self.music_combo.addItem(name, path)
            self.music_combo.setCurrentIndex(0)
            self.music_combo.setEnabled(True)
        self.music_combo.blockSignals(False)

    def _on_add_music_toggled(self, checked: bool):
        """Show/enable music controls only if files exist and checkbox checked."""
        have_files = bool(self._music_files)
        enable = checked and have_files
        self.music_combo.setVisible(enable)
        self.music_combo.setEnabled(enable)
        self.music_volume_slider.setVisible(enable)
        self.music_volume_label.setVisible(enable)
        self.music_offset_input.setVisible(enable)
        if enable:
            self.music_volume_slider.setEnabled(True)
            self.music_offset_input.setEnabled(True)
            self._on_music_selected(self.music_combo.currentIndex())
        else:
            self.music_volume_slider.setEnabled(False)
            self.music_offset_input.setEnabled(False)

    def _on_music_selected(self, index: int):
        if not self._music_files:
            return
        try:
            p = self.music_combo.currentData()
            if not p:
                self.music_offset_input.setRange(0.0, 0.0)
                self.music_offset_input.setValue(0.0)
                return
            dur = self._probe_audio_duration(p)
            self.music_offset_input.setRange(0.0, max(0.0, dur - 0.01))
            if self.vlc_instance:
                initial_offset = self.music_offset_input.value()
                dlg = VM_MusicOffsetDialog(self, self.vlc_instance, p, initial_offset, self.bin_dir)
                if dlg.exec_() == QDialog.Accepted:
                    self.music_offset_input.setValue(dlg.selected_offset)
            else:
                self.logger.warning("VLC instance not available, cannot show music offset dialog.")
        except Exception as e:
            self.logger.error("Error on music selection or dialog: %s", e)
            self.music_offset_input.setRange(0.0, 0.0)
            self.music_offset_input.setValue(0.0)

    def _get_selected_music(self):
        """Return (path, volume_linear) or (None, None) if disabled/invalid."""
        if not self.add_music_checkbox.isChecked():
            return None, None
        if not self._music_files:
            return None, None
        path = self.music_combo.currentData() or ""
        if not path or not os.path.isfile(path):
            return None, None
        vol_pct = self._music_eff()
        return path, (vol_pct / 100.0)
    
    def _music_eff(self, raw: int | None = None) -> int:
        """Map slider value -> 0..100 respecting invertedAppearance."""
        v = int(self.music_volume_slider.value() if raw is None else raw)
        if self.music_volume_slider.invertedAppearance():
            return max(0, min(100, self.music_volume_slider.maximum() + self.music_volume_slider.minimum() - v))
        return max(0, min(100, v))

    def _on_music_volume_changed(self, raw: int):
        """Keep label/badge in effective %."""
        try:
            eff = self._music_eff(raw)
            self.music_volume_label.setText(f"{eff}%")
            self._update_music_badge()
        except Exception:
            pass

if __name__ == "__main__":
    try:
        _proj_root_path = Path(__file__).resolve().parents[2]
        if str(_proj_root_path) not in sys.path:
            sys.path.insert(0, str(_proj_root_path))
            print(f"DEBUG [Standalone]: Added project root '{_proj_root_path}' to sys.path")
    except Exception as _path_err:
        print(f"ERROR [Standalone]: Failed to modify sys.path - {_path_err}", file=sys.stderr)
    app = QApplication(sys.argv)
    try:
        icon_path = str(_proj_root_path / "icons" / "app_icon.ico")
        if os.path.exists(icon_path):
            app.setWindowIcon(QIcon(icon_path))
    except Exception as e:
        print(f"WARN [Standalone]: Failed to set application icon - {e}", file=sys.stderr)
    try:
        bin_dir = _proj_root_path / 'binaries'
        ffmpeg_path = bin_dir / 'ffmpeg.exe'
        if not ffmpeg_path.exists():
            QMessageBox.critical(None, "Error", f"ffmpeg.exe not found at {ffmpeg_path}\n"
                                               f"This test will fail.")
            sys.exit(1)
        try:
            import vlc
            vlc_instance = vlc.Instance('--no-xlib --quiet')
        except Exception as vlc_err:
            QMessageBox.warning(None, "VLC Error", f"Could not initialize VLC for music preview:\n{vlc_err}")
            vlc_instance = None
        window = VideoMergerWindow(ffmpeg_path=str(ffmpeg_path), vlc_instance=vlc_instance, bin_dir=str(bin_dir))
    except Exception as e:
        QMessageBox.critical(None, "Error", f"Failed to initialize: {e}")
        sys.exit(1)
    window.show()
    sys.exit(app.exec_())
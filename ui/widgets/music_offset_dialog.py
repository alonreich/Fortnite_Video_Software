import os
import sys
import subprocess
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QPixmap
from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QLabel, QHBoxLayout,
                             QPushButton)
from ui.widgets.trimmed_slider import TrimmedSlider

class MusicOffsetDialog(QDialog):
    """Waveform preview + single Play/Pause + thin caret line + offset slider."""
    def __init__(self, parent, vlc_instance, audio_path: str, initial_offset: float, bin_dir: str):
        super().__init__(parent)
        self.setWindowTitle("Choose Background Music Start")
        self.setModal(True)
        self._vlc = vlc_instance
        self._mpath = audio_path
        self._bin = bin_dir
        self.selected_offset = float(initial_offset or 0.0)
        self._player = None
        self._total_ms = 0
        v = QVBoxLayout(self)
        self.wave = QLabel()
        self.wave.setAlignment(Qt.AlignCenter)
        self.wave.setScaledContents(True)
        v.addWidget(self.wave)
        from ui.widgets.trimmed_slider import TrimmedSlider
        self.slider = TrimmedSlider(self)
        self.slider.enable_trim_overlays(False)
        self.slider.setFixedHeight(50)
        v.addWidget(self.slider)
        row = QHBoxLayout()
        self.ok_btn = QPushButton("OK")
        self.play_btn = QPushButton("Play")
        self.cancel_btn = QPushButton("Cancel")
        for _b in (self.ok_btn, self.cancel_btn):
            _b.setFixedWidth(100)
            _b.setStyleSheet("""
                QPushButton {
                    background-color: #3aa0d8;
                    color: white;
                    font-size: 13px;
                    padding: 6px 14px;
                    border-radius: 6px;
                }
                QPushButton:hover  { background-color: #52b0e4; }
                QPushButton:pressed{ background-color: #2c8fc4; }
            """)
        self.play_btn.setFixedHeight(30)
        self.play_btn.setFixedWidth(100)
        self.play_btn.setStyleSheet("""
            QPushButton {
                background-color: #59A06D;
                color: white;
                font-size: 14px;
                padding: 6px 14px;
                border-radius: 6px;
            }
            QPushButton:hover  { background-color: #6fb57f; }
            QPushButton:pressed{ background-color: #4a865a; }
        """)
        
        row.addStretch(1)
        row.addWidget(self.ok_btn)
        row.addSpacing(40)
        row.addWidget(self.play_btn)
        row.addSpacing(40)
        row.addWidget(self.cancel_btn)
        row.addStretch(1)
        v.addLayout(row)
        self.ok_btn.clicked.connect(self.accept)
        self.cancel_btn.clicked.connect(self.reject)
        self.play_btn.clicked.connect(self._toggle_play_pause)
        self.slider.valueChanged.connect(self._on_slider_changed)
        self._caret = QLabel(self.wave)
        self._caret.setStyleSheet("background:#3498db;")
        self._caret.resize(20, 20)
        self._caret.hide()
        self._timer = QTimer(self)
        self._timer.setInterval(100)
        self._timer.timeout.connect(self._tick)
        self._restore_geometry()
        self._init_assets(initial_offset or 0.0)
    def _restore_geometry(self):
        try:
            cm = getattr(self.parent(), "config_manager", None)
            cfg = getattr(cm, "config", None) if cm else None
            g = cfg.get("music_offset_dlg_geo", {}) if isinstance(cfg, dict) else {}
            w, h = int(g.get("w", 900)), int(g.get("h", 480))
            x, y = int(g.get("x", -1)), int(g.get("y", -1))
            self.resize(max(640, w), max(360, h))
            if x >= 0 and y >= 0:
                self.move(x, y)
        except Exception:
            pass

    def _save_geometry(self):
        try:
            cm = getattr(self.parent(), "config_manager", None)
            cfg = getattr(cm, "config", None) if cm else None
            if isinstance(cfg, dict):
                cfg["music_offset_dlg_geo"] = {"x": self.x(), "y": self.y(), "w": self.width(), "h": self.height()}
                for m in ("save", "save_config", "write"):
                    if hasattr(cm, m):
                        try:
                            getattr(cm, m)()
                            break
                        except Exception:
                            pass
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
            out = subprocess.check_output(cmd, creationflags=(subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0))
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
            tmp_png = os.path.join(os.path.dirname(self._mpath), "_waveform_preview.png")
            cmd = [self._ffmpeg(), "-hide_banner", "-loglevel", "error",
                   "-i", self._mpath, "-frames:v", "1",
                   "-filter_complex", "showwavespic=s=1400x150:split_channels=0:colors=0x86a8b4",
                   "-y", tmp_png]
            subprocess.run(cmd, check=True,
                           creationflags=(subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0))
            if os.path.isfile(tmp_png):
                self.wave.setPixmap(QPixmap(tmp_png))
        except Exception:
            pass
        QTimer.singleShot(0, self._sync_caret_to_slider)

    def _ensure_player(self):
        if self._player or self._vlc is None:
            return
        try:
            self._player = self._vlc.media_player_new()
            m = self._vlc.media_new(self._mpath)
            self._player.set_media(m)
        except Exception:
            self._player = None

    def _toggle_play_pause(self):
        self._ensure_player()
        if not self._player:
            return
        try:
            state = self._player.get_state()
            if str(state).lower().endswith("playing"):
                self._player.pause()
                self.play_btn.setText("Play")
            else:
                self._player.play()
                self._player.set_time(int(self.slider.value()))
                self.play_btn.setText("Pause")
                self._timer.start()
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
        """Place a 2px blue line exactly at the slider time over the waveform image."""
        try:
            if self.wave.pixmap() is None:
                self._caret.hide()
                return
            w = max(1, self.wave.width())
            h = max(1, self.wave.height())
            self._caret.resize(2, h)
            rng = max(1, self.slider.maximum() - self.slider.minimum())
            pos = (self.slider.value() - self.slider.minimum()) / rng
            x = int(pos * w) - 1
            x = max(0, min(w - 2, x))
            self._caret.move(x, 0)
            self._caret.show()
        except Exception:
            pass

    def _tick(self):
        if not self._player:
            return
        try:
            cur = int(self._player.get_time() or 0)
            if abs(cur - self.slider.value()) > 120:
                self.slider.blockSignals(True)
                self.slider.setValue(cur)
                self.slider.blockSignals(False)
            self._sync_caret_to_slider()
        except Exception:
            pass

    def accept(self):
        self.selected_offset = float(self.slider.value()) / 1000.0
        try:
            if self._player:
                self._player.stop()
        except Exception:
            pass
        self._save_geometry()
        super().accept()

    def reject(self):
        try:
            if self._player:
                self._player.stop()
        except Exception:
            pass
        self._save_geometry()
        super().reject()
    def _style_like_start_trim(self, btn: QPushButton):
        btn.setFixedWidth(120)
        btn.setStyleSheet("""
            QPushButton {
                font-size: 13px;
                padding: 4px 8px;
                border-radius: 6px;
            }
        """)
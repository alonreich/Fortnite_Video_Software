import os
import sys
import tempfile
import subprocess
from PyQt5.QtCore import Qt, QTimer, QPoint, QEvent
from PyQt5.QtGui import QPixmap, QMouseEvent
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QLabel, QHBoxLayout, QPushButton, QSizePolicy,
    QStyleOptionSlider, QStyle
)
from PyQt5.QtCore import QPoint
from ui.widgets.trimmed_slider import TrimmedSlider
try:
    import vlc as _vlc_mod
except Exception:
    _vlc_mod = None
AUDIO_LAG_COMPENSATION_MS = 0
PREVIEW_VISUAL_LEAD_MS = -2700

class MusicOffsetDialog(QDialog):
    """Waveform preview + single Play/Pause + thin caret line + offset slider."""

    def eventFilter(self, obj, event: QEvent):
        if obj is self.wave and event.type() == QEvent.MouseButtonPress:
            if event.button() == Qt.LeftButton:
                try:
                    click_x = event.pos().x()
                    wave_x0, _, wave_w, _ = self._wave_draw_rect()
                    if wave_w > 0:
                        relative_x = click_x - wave_x0
                        pos_fraction = max(0.0, min(1.0, relative_x / wave_w))
                        min_val = self.slider.minimum()
                        max_val = self.slider.maximum()
                        rng = max(1, max_val - min_val)
                        target_ms = int(min_val + pos_fraction * rng)
                        self.slider.setValue(target_ms)
                        if self._player and self._player.is_playing():
                            self._player.set_time(target_ms)
                        return True
                except Exception as e:
                    print(f"Error handling waveform click: {e}")
        return super().eventFilter(obj, event)

    def _stop_player_and_timer(self):
        """Safely stops the VLC player and timer."""
        try:
            if getattr(self, "_player", None):
                self._player.stop()
                self._player.release()
                self._player = None
        except Exception as e:
            print(f"DEBUG: Error stopping music preview player: {e}")
            pass
        try:
            if getattr(self, "_timer", None):
                self._timer.stop()
        except Exception as e:
            print(f"DEBUG: Error stopping music preview timer: {e}")
            pass

    def closeEvent(self, event):
        """Clean up temporary files when the dialog closes."""
        try:
            if getattr(self, "_player", None):
                self._player.stop()
                self._player.release()
                self._player = None
        except Exception:
            pass
        try:
            if getattr(self, "_timer", None):
                self._timer.stop()
        except Exception:
            pass
        try:
            if hasattr(self, "_temp_png_path") and self._temp_png_path and os.path.exists(self._temp_png_path):
                os.remove(self._temp_png_path)
                self._temp_png_path = None
        except Exception:
            pass
        self._save_geometry()
        super().closeEvent(event)

    def __init__(self, parent, vlc_instance, audio_path: str, initial_offset: float, bin_dir: str):
        super().__init__(parent)
        self.setWindowTitle("Choose Background Music Start")
        self.setModal(True)
        self._vlc = vlc_instance
        self._mpath = audio_path
        self._bin = bin_dir
        try:
            mp3_dir = os.path.dirname(self._mpath)
            legacy = os.path.join(mp3_dir, "_waveform_preview.png")
            if os.path.isfile(legacy):
                os.remove(legacy)
        except Exception:
            pass
        self.selected_offset = float(initial_offset or 0.0)
        self._player = None
        self._total_ms = 0
        self._temp_png_path = None
        v = QVBoxLayout(self)
        self.wave = QLabel("Generating waveform...")
        self.wave.setAlignment(Qt.AlignCenter)
        self.wave.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.wave.setScaledContents(True)
        self.wave.setAlignment(Qt.AlignCenter)
        v.addWidget(self.wave)
        self.wave.installEventFilter(self)
        self.slider = TrimmedSlider(self)
        self.slider.enable_trim_overlays(False)
        self.slider.setFixedHeight(50)
        self.sync_info_label = QLabel(
            "<i>Note: Audio preview sync may vary due to buffering.<br>"
            "Please rely on <b>listening</b> to choose the exact start time.</i>"
        )
        self.sync_info_label.setAlignment(Qt.AlignCenter)
        self.sync_info_label.setStyleSheet("font-size: 10px; color: #aabbcc; margin-top: 5px; margin-bottom: 10px;")
        self.sync_info_label.setWordWrap(True)
        v.addWidget(self.sync_info_label)
        v.addWidget(self.slider)
        row = QHBoxLayout()
        self.ok_btn = QPushButton("OK")
        self.play_btn = QPushButton("Play")
        self._update_play_button(False)
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
        self._caret.resize(2, 20)
        self._caret.hide()
        self._timer = QTimer(self)
        self._timer.setInterval(50)
        self._timer.timeout.connect(self._tick)
        self._dragging = False
        try:
            self.slider.sliderPressed.connect(self._on_drag_start)
            self.slider.sliderReleased.connect(self._on_drag_end)
        except Exception:
            pass
        self._restore_geometry()
        self._init_assets(initial_offset or 0.0)

    def _restore_geometry(self):
        try:
            cm = getattr(self.parent(), "config_manager", None)
            cfg = getattr(cm, "config", None) if cm else None
            g = cfg.get("music_offset_dlg_geo", {}) if isinstance(cfg, dict) else {}
            w, h = int(g.get("w", 450)), int(g.get("h", 200))
            x, y = int(g.get("x", -1)), int(g.get("y", -1))
            self.resize(max(640, w), max(360, h))
            if x >= 0 and y >= 0:
                self.move(x, y)
        # Set a more reasonable default size if loading fails or no config exists
            if x < 0 or y < 0:
                self.resize(400, 180) # Default size if no position saved
            else:
                 self.resize(max(640, w), max(360, h))
                 self.move(x, y)
        except Exception:
             self.resize(400, 180)

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
            cmd = [
                self._ffprobe(), "-v", "error", "-show_entries", "format=duration",
                "-of", "default=nokey=1:noprint_wrappers=1", self._mpath
            ]
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
            print(f"DEBUG: Running FFMPEG for waveform: {' '.join(cmd)}")
            result = subprocess.run(
                cmd, check=True, capture_output=True, text=True,
                creationflags=(subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0)
            )
            print(f"DEBUG: FFMPEG waveform output:\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}")
            if not os.path.isfile(tmp_png):
                print(f"ERROR: Waveform PNG file not found after FFMPEG ran: {tmp_png}")
                self._temp_png_path = None
                self.wave.setText("Error: Waveform image not created.")
                self.wave.hide()
                return
            pixmap = QPixmap(tmp_png)
            if pixmap.isNull():
                print(f"ERROR: QPixmap is Null. Failed to load image from {tmp_png}")
                self._temp_png_path = None
                self.wave.setText("Error: Could not load waveform image.")
                self.wave.hide()
                return
            print(f"DEBUG: QPixmap loaded successfully. Size: {pixmap.width()}x{pixmap.height()}")
            self.wave.setPixmap(pixmap)
            dpr = pixmap.devicePixelRatio() if hasattr(pixmap, 'devicePixelRatio') else 1.0
            w, h = int(pixmap.width() / dpr), int(pixmap.height() / dpr)
            print(f"DEBUG: Setting label minimum size to {w}x{h}")
            self.wave.show()
            self.wave.update()
            print("DEBUG: Set waveform pixmap and updated label.")
        except subprocess.CalledProcessError as e:
            print(f"ERROR: FFMPEG waveform generation failed. Return Code: {e.returncode}. Command: {' '.join(cmd)}")
            print(f"ERROR: FFMPEG waveform STDERR:\n{e.stderr}")
            self._temp_png_path = None
            self.wave.setText("Error: FFMPEG failed to generate waveform.")
            self.wave.hide()
        except Exception as e:
            print(f"ERROR: Exception during waveform generation/loading: {e}")
            self._temp_png_path = None
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
        """Sync play button label/icon + tooltip."""
        if not hasattr(self, "play_btn"):
            return
        if playing:
            self.play_btn.setText("⏸ Pause")
            self.play_btn.setToolTip("Pause preview")
        else:
            self.play_btn.setText("▶ Play")
            self.play_btn.setToolTip("Play preview")

    def _reset_player(self):
        """Fully reset VLC after end-of-media so we can play again."""
        try:
            if self._player:
                try:
                    self._player.stop()
                except Exception:
                    pass
                try:
                    self._player.release()
                except Exception:
                    pass
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
            is_playing = state.endswith("playing")
            if is_playing:
                self._player.pause()
                self._update_play_button(False)
                self._timer.stop()
                def _verify_paused():
                    try:
                        st = str(self._player.get_state()).lower()
                        if st.endswith("playing"):
                            self._player.stop()
                    except Exception:
                        pass
                QTimer.singleShot(120, _verify_paused)
            else:
                self._start_playing_from_slider()
        except Exception:
            pass

    def _start_playing_from_slider(self):
        """
        Robustly start playback and seek immediately.
        Handles replay after reaching the end.
        """
        try:
            state = ""
            try:
                # Ensure player exists before getting state
                if self._player:
                    state = str(self._player.get_state()).lower()
            except Exception:
                 # If getting state fails, try resetting
                 state = "error" # Treat as needing reset

            # If ended, errored, or player doesn't exist, reset/recreate it
            if ("ended" in state) or ("error" in state) or (self._player is None):
                self._reset_player()
            if not self._player:
                print("ERROR: Cannot start playback, player object invalid after reset.")
                return
            want_ms = int(self.slider.value())
            try:
                 state = str(self._player.get_state()).lower()
            except Exception:
                 print("ERROR: Failed to get player state before playing.")
                 state = "unknown"
            if state.endswith("playing"):
                self._player.set_time(want_ms)
                if not self._timer.isActive():
                    self._timer.start()
                self._update_play_button(True) # Make sure button says Pause
                print(f"DEBUG: Seeked while playing to {want_ms}ms")
            else:
                play_result = self._player.play()
                print(f"DEBUG: Called play(). Result: {play_result}") # Check if play() reports error
                set_time_result = self._player.set_time(want_ms)
                print(f"DEBUG: Called set_time({want_ms}ms). Result: {set_time_result}") # Check if set_time reports error (-1 usually)
                self._timer.start()
                self._update_play_button(True) # Update button to Pause
        except Exception as e:
            print(f"ERROR in _start_playing_from_slider: {e}")
            try:
                if self._timer: self._timer.stop()
                self._update_play_button(False)
            except Exception:
                pass

    def _on_drag_start(self):
        self._dragging = True
    
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

    def _wave_draw_rect(self):
        """
        Returns (x0, y0, w, h) of the SCALED waveform pixmap inside the QLabel.
        Accounts for alignment, contentsRect, and aspect ratio preservation.
        """
        pm = self.wave.pixmap()
        cr = self.wave.contentsRect() # Area available for drawing inside margins/borders
        if pm is None or pm.isNull() or not self.wave.hasScaledContents():
            return cr.left(), cr.top(), cr.width(), cr.height()
        pm_size = pm.size() / pm.devicePixelRatioF() # Original logical size
        lbl_size = cr.size() # Available size in label
        scaled_size = pm_size.scaled(lbl_size, Qt.KeepAspectRatio)
        x0 = cr.left()
        y0 = cr.top()
        align = self.wave.alignment()
        if align & Qt.AlignRight:
            x0 += lbl_size.width() - scaled_size.width()
        elif align & Qt.AlignHCenter:
            x0 += (lbl_size.width() - scaled_size.width()) / 2
        if align & Qt.AlignBottom:
            y0 += lbl_size.height() - scaled_size.height()
        elif align & Qt.AlignVCenter:
            y0 += (lbl_size.height() - scaled_size.height()) / 2
        return int(x0), int(y0), int(scaled_size.width()), int(scaled_size.height())

    def _sync_caret_to_slider(self):
        """Place the caret so that time maps 1:1 onto the area where the waveform is actually drawn."""
        try:
            if not self.wave.isVisible() or self.wave.geometry().isEmpty():
                self._caret.hide()
                return
            v = int(self.slider.value())
            vmin, vmax = self.slider.minimum(), self.slider.maximum()
            span = max(1, vmax - vmin)
            frac = (v - vmin) / span
            if frac < 0.0: frac = 0.0
            if frac > 1.0: frac = 1.0
            cr = self.wave.contentsRect()
            top_left = self.wave.mapToParent(cr.topLeft())
            x0, y0 = top_left.x(), top_left.y()
            w, h = cr.width(), cr.height()
            x = x0 + int(frac * max(1, w - 1))
            x = max(x0, min(x0 + w - self._caret.width(), x))
            self._caret.setGeometry(x, y0, 2, h)
            self._caret.raise_()
            self._caret.show()
        except Exception as e:
            print(f"Error in _sync_caret_to_slider: {e}")
            self._caret.hide()
    

    def _tick(self):
        if not self._player:
            return
        try:
            state = str(self._player.get_state()).lower()
            if not state.endswith("playing"):
                self._timer.stop()
                return
            raw_ms = int(self._player.get_time() or 0)
            end_ms = self.slider.maximum()
            display_ms = min(end_ms, max(0, raw_ms + PREVIEW_VISUAL_LEAD_MS))
            if display_ms >= end_ms - 10:
                self._on_vlc_ended()
                return
            if not self._dragging:
                self.slider.blockSignals(True)
                self.slider.setValue(display_ms)
                self.slider.blockSignals(False)
                self._sync_caret_to_slider()
        except Exception as e:
            print(f"Error in _tick: {e}")
            pass

    def _on_vlc_ended(self, event=None):
        def _ui():
            try:
                self._timer.stop()
                self._update_play_button(False)
                self.slider.blockSignals(True)
                self.slider.setValue(self.slider.maximum())
                self.slider.blockSignals(False)
                self._sync_caret_to_slider()
                self._reset_player()
            except Exception:
                pass
        QTimer.singleShot(0, _ui)
    
    def accept(self):
        self.selected_offset = float(self.slider.value()) / 1000.0
        self._stop_player_and_timer()
        super().accept()

    def reject(self):
        self._stop_player_and_timer()
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
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
PREVIEW_VISUAL_LEAD_MS = 1000

class MusicOffsetDialog(QDialog):
    """Waveform preview + single Play/Pause + thin caret line + offset slider."""

    def eventFilter(self, obj, event: QEvent):
        if obj is self.wave:
            if event.type() == QEvent.MouseButtonPress:
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
                            self._sync_caret_to_slider()
                            return True
                    except Exception as e:
                        (getattr(self, 'logger', __import__('logging').getLogger('MusicOffsetDialog'))
                            .error("Waveform click error: %s", e))
            elif event.type() == QEvent.Resize:
                QTimer.singleShot(0, self._sync_caret_to_slider)
        return super().eventFilter(obj, event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "_overlay"):
            self._overlay.setGeometry(0, 0, self.width(), self.height())
        QTimer.singleShot(0, self._sync_caret_to_slider)

    def _stop_player_and_timer(self):
        """Safely stops the VLC player and timer."""
        try:
            if getattr(self, "_player", None):
                self._player.stop()
                self._player.release()
                self._player = None
        except Exception as e:
            (getattr(self, 'logger', __import__('logging').getLogger('MusicOffsetDialog'))
                .debug("Error stopping music preview player: %s", e))
            (getattr(self, 'logger', __import__('logging').getLogger('MusicOffsetDialog'))
                .debug("Error stopping music preview timer: %s", e))
            pass
        try:
            if getattr(self, "_timer", None):
                self._timer.stop()
        except Exception as e:
            (getattr(self, 'logger', __import__('logging').getLogger('MusicOffsetDialog'))
                .debug("Error stopping music preview player: %s", e))
            (getattr(self, 'logger', __import__('logging').getLogger('MusicOffsetDialog'))
                .debug("Error stopping music preview timer: %s", e))
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
        self.wave.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding) 
        self.wave.setScaledContents(True)
        self.wave.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.wave.setStyleSheet("background: black;")
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
        self._overlay = QLabel(self)
        self._overlay.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self._overlay.setStyleSheet("background: transparent;")
        self._overlay.lower()
        self._caret = QLabel(self._overlay)
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

    def keyPressEvent(self, event):
        """Handle volume shortcuts for the music preview."""
        key = event.key()
        modifiers = event.modifiers()
        step = 0
        if key == Qt.Key_Up:
            step = 5 if modifiers == Qt.ShiftModifier else 1
        elif key == Qt.Key_Down:
            step = -5 if modifiers == Qt.ShiftModifier else -1
        elif key == Qt.Key_Plus or (key == Qt.Key_Equal and modifiers == Qt.ShiftModifier):
            step = 5
        elif key == Qt.Key_Minus:
            step = -5
        elif key == Qt.Key_Equal and modifiers == Qt.NoModifier:
            step = 5
        if step == 0:
            super().keyPressEvent(event)
            return
        try:
            main_window = self.parent()
            slider = getattr(main_window, "music_volume_slider", None)
            callback = getattr(main_window, "_on_music_volume_changed", None)
            if not slider or not callback:
                super().keyPressEvent(event)
                return
            current_val = slider.value()
            new_val = max(slider.minimum(), min(slider.maximum(), current_val + step))
            slider.setValue(new_val)
            callback(new_val)
            if getattr(self, "_player", None):
                eff_vol = main_window._music_eff(new_val)
                self._player.audio_set_volume(eff_vol)
            event.accept()
        except Exception as e:
            (getattr(self, 'logger', __import__('logging').getLogger('MusicOffsetDialog'))
                .error("Dialog keyPressEvent error: %s", e))
            super().keyPressEvent(event)

    def _restore_geometry(self):
        try:
            parent_obj = self.parent()
            cfg_key = "music_offset_dlg_geo"
            cm = getattr(parent_obj, "config_manager", None)
            cfg = getattr(cm, "config", None) if cm else {}
            if not cfg:
                 cfg = getattr(parent_obj, "_cfg", {})
            g = cfg.get(cfg_key, {}) if isinstance(cfg, dict) else {}
            w, h = int(g.get("w", 1200)), int(g.get("h", 350)) 
            x, y = int(g.get("x", -1)), int(g.get("y", -1))
            self.resize(max(1200, w), max(280, h))
            if x >= 0 and y >= 0:
                self.move(x, y)
        except Exception as e:
            (getattr(self, 'logger', __import__('logging').getLogger('MusicOffsetDialog'))
                .error("Restore geometry failed: %s", e))
            self.resize(1200, 350)

    def _save_geometry(self):
        try:
            parent_obj = self.parent()
            cm = getattr(parent_obj, "config_manager", None)
            if cm is None:
                return
            cfg = dict(cm.config)
            cfg["music_offset_dlg_geo"] = {"x": self.x(), "y": self.y(), "w": self.width(), "h": self.height()}
            cm.save_config(cfg)
        except Exception as e:
            (getattr(self, 'logger', __import__('logging').getLogger('MusicOffsetDialog'))
                .error("Save geometry failed: %s", e))

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
                "volume=4.0,aresample=48000,pan=mono|c0=0.5*c0+0.5*c1,"
                "showwavespic=s=1200x280:split_channels=0:colors=0xa6c8d2",
                "-y", tmp_png
            ]
            (getattr(self, 'logger', __import__('logging').getLogger('MusicOffsetDialog'))
                .debug("Running FFMPEG for waveform: %s", ' '.join(cmd)))
            subprocess.run(
                cmd, check=True,
                creationflags=(subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0)
            )
            (getattr(self, 'logger', __import__('logging').getLogger('MusicOffsetDialog'))
                .debug("FFMPEG waveform generated to %s", tmp_png))
            if not os.path.isfile(tmp_png):
                (getattr(self, 'logger', __import__('logging').getLogger('MusicOffsetDialog'))
                    .error("Waveform PNG not found after ffmpeg: %s", tmp_png))
                self._temp_png_path = None
                self.wave.setText("Error: Waveform image not created.")
                self.wave.hide()
                return
            pixmap = QPixmap(tmp_png)
            if pixmap.isNull():
                (getattr(self, 'logger', __import__('logging').getLogger('MusicOffsetDialog'))
                    .error("QPixmap is null; failed to load %s", tmp_png))
                self._temp_png_path = None
                self.wave.setText("Error: Could not load waveform image.")
                self.wave.hide()
                return
            (getattr(self, 'logger', __import__('logging').getLogger('MusicOffsetDialog'))
                .debug("Waveform pixmap loaded: %dx%d", pixmap.width(), pixmap.height()))
            self.wave.setPixmap(pixmap)
            dpr = pixmap.devicePixelRatio() if hasattr(pixmap, 'devicePixelRatio') else 1.0
            w, h = int(pixmap.width() / dpr), int(pixmap.height() / dpr)
            (getattr(self, 'logger', __import__('logging').getLogger('MusicOffsetDialog'))
                .debug("Waveform label target size %dx%d; pixmap set", w, h))
            self.wave.show()
            self.wave.update()
        except subprocess.CalledProcessError as e:
            (getattr(self, 'logger', __import__('logging').getLogger('MusicOffsetDialog'))
                .error("FFMPEG waveform failed (rc=%s): %s", getattr(e, "returncode", "?"), ' '.join(cmd)))
            self._temp_png_path = None
            self.wave.setText("Error: FFMPEG failed to generate waveform.")
            self.wave.hide()
        except Exception as e:
            (getattr(self, 'logger', __import__('logging').getLogger('MusicOffsetDialog'))
                .error("Exception during waveform generation/loading: %s", e))
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
                if self._player:
                    state = str(self._player.get_state()).lower()
            except Exception:
                 state = "error"
            if ("ended" in state) or ("error" in state) or (self._player is None):
                self._reset_player()
            if not self._player:
                (getattr(self, 'logger', __import__('logging').getLogger('MusicOffsetDialog'))
                    .error("Cannot start playback: player invalid after reset"))
                return
            want_ms = int(self.slider.value())
            try:
                 state = str(self._player.get_state()).lower()
            except Exception:
                 (getattr(self, 'logger', __import__('logging').getLogger('MusicOffsetDialog'))
                    .error("Failed to get player state before playing"))
                 state = "unknown"
            if state.endswith("playing"):
                self._player.set_time(want_ms)
                if not self._timer.isActive():
                    self._timer.start()
                self._update_play_button(True)
                (getattr(self, 'logger', __import__('logging').getLogger('MusicOffsetDialog'))
                    .debug("Seek while playing -> %d ms", want_ms))
            else:
                play_result = self._player.play()
                (getattr(self, 'logger', __import__('logging').getLogger('MusicOffsetDialog'))
                    .debug("play() -> %s", play_result))
                set_time_result = self._player.set_time(want_ms)
                (getattr(self, 'logger', __import__('logging').getLogger('MusicOffsetDialog'))
                    .debug("set_time(%d) -> %s", want_ms, set_time_result))
                self._timer.start()
                self._update_play_button(True)
        except Exception as e:
            (getattr(self, 'logger', __import__('logging').getLogger('MusicOffsetDialog'))
                .error("start_playing_from_slider error: %s", e))
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
        pm = self.wave.pixmap()
        cr = self.wave.contentsRect()
        if pm is None or pm.isNull():
            return cr.left(), cr.top(), cr.width(), cr.height()
        pm_size = pm.size() / pm.devicePixelRatioF()
        lbl_size = cr.size()
        scaled_size = pm_size.scaled(lbl_size, Qt.KeepAspectRatio)
        x0 = 0
        y0 = int((lbl_size.height() - scaled_size.height()) / 2)
        return int(x0), int(y0), lbl_size.width(), int(scaled_size.height())

    def _sync_caret_to_slider(self):
        try:
            if not self.wave.isVisible():
                self._caret.hide()
                return
            wave_x0, wave_y0, wave_w, wave_h = self._wave_draw_rect()
            if wave_w <= 0:
                self._caret.hide()
                return
            v = int(self.slider.value())
            vmin, vmax = self.slider.minimum(), self.slider.maximum()
            span = max(1, vmax - vmin)
            frac = max(0.0, min(1.0, (v - vmin) / span))
            x_in_label = wave_x0 + int(frac * wave_w)
            wave_pos_in_dialog = self.wave.mapTo(self, QPoint(0, 0))
            caret_x = wave_pos_in_dialog.x() + x_in_label
            caret_x = max(1, min(self.width() - 2, caret_x))
            caret_y = 0
            caret_h = self.height()
            if not hasattr(self, "_overlay"):
                return
            self._caret.setParent(self._overlay)
            self._caret.setGeometry(caret_x, caret_y, 2, caret_h)
            self._overlay.raise_()
            self._caret.raise_()
            self._caret.show()
        except Exception as e:
            (getattr(self, 'logger', __import__('logging').getLogger('MusicOffsetDialog'))
                .error("sync_caret_to_slider error: %s", e))
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
            (getattr(self, 'logger', __import__('logging').getLogger('MusicOffsetDialog'))
                .debug("tick error: %s", e))
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
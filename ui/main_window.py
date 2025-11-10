import faulthandler
import logging
import os
import signal
import subprocess
import sys
import threading
import traceback
from logging.handlers import RotatingFileHandler
import vlc
from PyQt5.QtCore import pyqtSignal, QTimer, QUrl
from PyQt5.QtWidgets import QWidget, QStyle, QFileDialog, QMessageBox
from system.config import ConfigManager
from system.logger import setup_logger
from ui.parts.ui_builder_mixin import UiBuilderMixin
from ui.parts.phase_overlay_mixin import PhaseOverlayMixin
from ui.parts.events_mixin import EventsMixin
from ui.parts.player_mixin import PlayerMixin
from ui.parts.volume_mixin import VolumeMixin
from ui.parts.trim_mixin import TrimMixin
from ui.parts.music_mixin import MusicMixin
from ui.parts.ffmpeg_mixin import FfmpegMixin
from ui.parts.keyboard_mixin import KeyboardMixin

class _QtLiveLogHandler(logging.Handler):
    def __init__(self, ui_owner):
        super().__init__()
        self.ui = ui_owner

    def emit(self, record):
        try:
            msg = self.format(record)
            if hasattr(self.ui, "live_log_signal"):
                self.ui.live_log_signal.emit(msg)
        except Exception:
            pass

class VideoCompressorApp(UiBuilderMixin, PhaseOverlayMixin, EventsMixin, PlayerMixin, VolumeMixin, TrimMixin, MusicMixin, FfmpegMixin, KeyboardMixin, QWidget):
    progress_update_signal = pyqtSignal(int)
    status_update_signal = pyqtSignal(str)
    process_finished_signal = pyqtSignal(bool, str)
    live_log_signal = pyqtSignal(str)
    video_ended_signal = pyqtSignal()

    def on_phase_update(self, phase: str) -> None:
        """
        Keeps the overlay, pulsing button text, and 'is_processing' flag in sync
        when the pipeline reports a phase/status change.
        """
        try:
            if hasattr(self, "_set_overlay_phase"):
                self._set_overlay_phase(phase)
            p = (phase or "").lower()
            if any(x in p for x in ("processing", "step", "encode", "intro", "core", "concat")):
                self.is_processing = True
                if hasattr(self, "_pulse_timer"):
                    self._pulse_timer.start(250)
            elif any(x in p for x in ("done", "idle", "error", "failed")):
                self.is_processing = False
                if hasattr(self, "_pulse_timer"):
                    self._pulse_timer.start(750)
            if hasattr(self, "_update_process_button_text"):
                self._update_process_button_text()
        except Exception:
            pass

    def _handle_video_end(self):
        """
        Slot to handle the video_ended_signal. Runs on the main Qt thread.
        Safely stops the player and resets the UI.
        """
        try:
            if getattr(self, "vlc_player", None):
                self.vlc_player.stop()
            self.positionSlider.blockSignals(True)
            self.positionSlider.setValue(0)
            self.positionSlider.blockSignals(False)
            if getattr(self, "playPauseButton", None):
                self.playPauseButton.setText("Play")
                self.playPauseButton.setIcon(self.style().standardIcon(QStyle.SP_MediaPlay))
            self.is_playing = False
            self.timer.stop()
        except Exception as e:
            if hasattr(self, "logger"):
                self.logger.exception("End-of-media handler failed: %s", e)

    def log_overlay_sink(self, line: str):
        """Thread-safe slot to receive log messages."""
        try:
            self._append_live_log(line)
        except Exception:
            pass

    def __init__(self, file_path=None):
        super().__init__()
        self.volume_shortcut_target = 'main'
        self.trim_start = None
        self.trim_end = None
        self.input_file_path = None
        self.original_duration = 0.0
        self.original_resolution = ""
        self.is_processing = False
        self.script_dir = os.path.dirname(sys.executable) if getattr(sys, 'frozen', False) else os.path.dirname(
            os.path.abspath(__file__))
        self.base_dir = os.path.abspath(os.path.join(self.script_dir, os.pardir))
        self.bin_dir = os.path.join(self.base_dir, 'binaries')
        self.logger = setup_logger(self.base_dir)
        self.live_log_signal.connect(self.log_overlay_sink)
        self.video_ended_signal.connect(self._handle_video_end)
        try:
            qt_handler = _QtLiveLogHandler(self) 
            qt_handler.setLevel(logging.INFO)
            if all(not isinstance(h, _QtLiveLogHandler) for h in self.logger.handlers):
                self.logger.addHandler(qt_handler)
        except Exception:
            pass
        self.logger.info("=== Application started ===")
        self.logger.info("RUN: cwd=%s | script_dir=%s", os.getcwd(), self.script_dir)
        try:
            import faulthandler, signal
            fh_stream = None
            for h in self.logger.handlers:
                if isinstance(h, RotatingFileHandler):
                    fh_stream = h.stream
                    break
            if fh_stream is not None:
                faulthandler.enable(fh_stream)
                for sig_name in ("SIGABRT", "SIGSEGV"):
                    sig = getattr(signal, sig_name, None)
                    if sig is not None:
                        faulthandler.register(sig, file=fh_stream, all_threads=True, chain=True)
        except Exception:
            pass
        def _excepthook(exc_type, exc, tb):
            import traceback
            self.logger.exception("UNCAUGHT EXCEPTION:\n%s", "".join(traceback.format_exception(exc_type, exc, tb)))
        sys.excepthook = _excepthook
        try:
            import threading
            def _thread_excepthook(args):
                self.logger.error("THREAD EXCEPTION: %s", args)
            threading.excepthook = _thread_excepthook
        except Exception:
            pass
        try:
            def _unraisable(hook):
                self.logger.error("UNRAISABLE: %s", hook)
            sys.unraisablehook = _unraisable
        except Exception:
            pass
        self.config_manager = ConfigManager(os.path.join(self.script_dir, 'Video.conf'))
        self.last_dir = self.config_manager.config.get('last_directory', os.path.expanduser('~'))
        vlc_args = [
            '--no-xlib',
            '--no-video-title-show',
            '--no-plugins-cache',
            '--file-caching=200',
            '--aout=directsound',
            '--verbose=-1',
        ]
        self.vlc_instance = vlc.Instance(vlc_args)
        self.vlc_player = self.vlc_instance.media_player_new()
        try:
            em = self.vlc_player.event_manager()
            if em:
                em.event_attach(vlc.EventType.MediaPlayerEndReached, self._on_vlc_end_reached) 
            else:
                 self.logger.warning("Could not get VLC event manager to attach EndReached handler.")
        except Exception as e:
            self.logger.error("Failed to attach VLC EndReached handler: %s", e)
        try:
            self.vlc_player.audio_set_mute(False)
            self.apply_master_volume()
        except Exception:
            pass
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
            self.setMinimumSize(1150, 575)
        else:
            self.setGeometry(200, 200, 1150, 575)
            self.setMinimumSize(1150, 575)
        self._music_files = []
        self.set_style()
        self.installEventFilter(self)
        self.init_ui()
        self._scan_mp3_folder()
        self._update_window_size_in_title()
        if file_path:
            self.handle_file_selection(file_path)

    def _on_playback_finished(self, event=None):
        try:
            self.vlc_player.stop()
            self.positionSlider.setValue(0)
            self.playPauseButton.setText("Play")
            self.playPauseButton.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MediaPlay))
            self.positionSlider.setEnabled(True)
        except Exception:
            pass

    def _update_window_size_in_title(self):
        self.setWindowTitle(f"{self._base_title}  —  {self.width()}x{self.height()}")

    def _adjust_trim_margins(self):
        """Center the rows under the video by adjusting left/right margins."""
        try:
            player_container = getattr(self, 'player_col_container', None)
            trim_container   = getattr(self, 'trim_container', None)
            center_container = getattr(self, 'center_btn_container', None)
            if player_container is not None and self.video_frame is not None:
                pw = player_container.width()
                vw = self.video_frame.width()
                pad = max(0, (pw - vw) // 2)
                if trim_container is not None:
                    trim_container.setContentsMargins(pad, 0, pad, 0)
                if center_container is not None:
                    center_container.setContentsMargins(pad, 0, pad, 0)
        except Exception:
            pass

    def showEvent(self, e):
        super().showEvent(e)
        try:
            self._layout_volume_slider()
            self._update_volume_badge()
        except Exception:
            pass

    def _on_trim_spin_changed(self):
        dur = float(self.original_duration or 0.0)
        start = (self.start_minute_input.value() * 60) + self.start_second_input.value()
        end   = (self.end_minute_input.value()   * 60) + self.end_second_input.value()
        if dur > 0.0:
            if start <= 0.0 and end <= 0.0:
                start, end = 0.0, dur
            start = max(0.0, min(start, dur))
            end   = max(0.0, min(end,   dur))
            eps = max(0.01, min(0.2, dur * 0.001))
            end = min(dur, max(end, start + eps))
            if end >= dur and start >= dur - eps:
                start = max(0.0, dur - eps)
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
                font-size: 12px;
                padding: 5px;
            }
            QFrame#dropArea {
                border: 3px dashed #3986ae;
                border-radius: 10px;
                background-color: #34495e;
                padding: 20px;
            }
            QSpinBox, QDoubleSpinBox, QSlider {
                background-color: #4a667a;
                border: 1px solid #3986ae;
                border-radius: 5px;
                padding: 10px;
                color: #ecf0f1;
                font-size: 13px;
            }
            QPushButton {
                background-color: #3986ae;
                color: #ffffff;
                border: none;
                padding: 10px 18px;
                border-radius: 8px;
                font-weight: bold;
            }
            QPushButton:hover { background-color: #2980b9; }
            QPushButton#WhatsappButton { background-color: #25D366; }
            QPushButton#DoneButton { background-color: #e74c3c; }
            QProgressBar { border: 1px solid #3986ae; border-radius: 5px; text-align: center; height: 18px; }
            QProgressBar::chunk { background-color: #2ecc71; }
        """)

    def select_file(self):
        try:
            if getattr(self, "vlc_player", None) and self.vlc_player.is_playing():
                self.vlc_player.set_pause(1)
            if getattr(self, "timer", None) and self.timer.isActive():
                self.timer.stop()
        except Exception as e:
            try:
                self.logger.error("FILE: failed to pause before dialog: %s", e)
            except Exception:
                pass
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Video File",
            self.last_dir,
            "Video Files (*.mp4 *.mkv *.mov *.avi)",
        )
        if file_path:
            self.logger.info("FILE: selected via dialog: %s", file_path)
            self.handle_file_selection(file_path)
        else:
            self.logger.info("FILE: dialog canceled")

    def handle_file_selection(self, file_path):
        try:
            player = getattr(self, "vlc_player", None)
            if player:
                if player.is_playing():
                    player.stop()
                current_media = player.get_media()
                if current_media:
                    current_media.release()
                    player.set_media(None)
            timer = getattr(self, "timer", None)
            if timer and timer.isActive():
                timer.stop()
        except Exception as stop_err:
             self.logger.error("Error stopping existing player/media: %s", stop_err)
        try:
            self.reset_app_state()
        except Exception as reset_err:
             self.logger.error("Error during UI reset: %s", reset_err)
        self.logger.info("FILE: loading for playback: %s", file_path)
        self.input_file_path = file_path
        self.drop_label.setWordWrap(True)
        self.drop_label.setText(os.path.basename(self.input_file_path))
        dir_path = os.path.dirname(file_path)
        if os.path.isdir(dir_path):
            self.last_dir = dir_path
        p = os.path.abspath(str(file_path))
        if not os.path.isfile(p):
            status_method = getattr(self, '_safe_status', None) or getattr(self, 'set_status_text_with_color', None)
            if status_method:
                status_method("Selected file not found.", "red")
            else:
                 self.logger.error("Selected file not found: %s", p)
            return
        media = self.vlc_instance.media_new_path(p)
        if media is None:
            try:
                mrl = QUrl.fromLocalFile(p).toString()
            except Exception:
                mrl = "file:///" + p.replace("\\", "/")
            media = self.vlc_instance.media_new(mrl)
        if media is None:
            status_method = getattr(self, '_safe_status', None) or getattr(self, 'set_status_text_with_color', None)
            if status_method:
                 status_method("Failed to open media.", "red")
            else:
                 self.logger.error("Failed to open media: %s", p)
            return
        try:
            media.parse_async()
        except Exception:
            try:
                media.parse()
            except Exception as parse_err:
                 self.logger.warning("Media parsing failed: %s", parse_err)
                 pass
        self.vlc_player.set_media(media)
        try:
            if sys.platform.startswith('win'):
                self.vlc_player.set_hwnd(int(self.video_frame.winId()))
            else:
                 pass
        except Exception as hwnd_err:
             self.logger.error("Failed to set HWND for player: %s", hwnd_err)
        self.vlc_player.play()
        try:
            self.vlc_player.audio_set_mute(False)
            self.apply_master_volume()
        except Exception as vol_err:
             self.logger.warning("Failed to set volume/mute state: %s", vol_err)
        if not self.timer.isActive():
            self.timer.start(100)
        self.playPauseButton.setEnabled(True)
        self.start_trim_button.setEnabled(True)
        self.end_trim_button.setEnabled(True)
        self.process_button.setEnabled(False)
        self._length_probe_attempts = 0
        def _probe_length():
            try:
                self._length_probe_attempts += 1
                ms = int((media.get_duration() if media else 0) or self.vlc_player.get_length() or 0)
                if ms > 0:
                    self.positionSlider.setRange(0, ms)
                    self.positionSlider.set_duration_ms(ms)
                    self.original_duration = ms / 1000.0
                    total_minutes = int(self.original_duration) // 60
                    max_seconds = int(self.original_duration) % 60
                    self.start_minute_input.setRange(0, total_minutes)
                    self.start_second_input.setRange(0, 59)
                    self.end_minute_input.setRange(0, total_minutes)
                    self.end_second_input.setRange(0, 59)
                    self.start_minute_input.setValue(0)
                    self.start_second_input.setValue(0)
                    self.end_minute_input.setValue(total_minutes)
                    self.end_second_input.setValue(max_seconds)
                    if not self.timer.isActive():
                        self.timer.start(100)
                    self.get_video_info()
                    self.video_frame.setFocus()
                    self.activateWindow()
                elif self._length_probe_attempts < 50:
                    if self._length_probe_attempts in (10, 20, 30):
                        try:
                            media.parse_async()
                            self.vlc_player.play()
                        except Exception:
                            pass
                    QTimer.singleShot(100, _probe_length)
                else:
                     self.logger.error("Failed to get video duration after %d attempts.", self._length_probe_attempts)
                     status_method = getattr(self, '_safe_status', None) or getattr(self, 'set_status_text_with_color', None)
                     if status_method:
                          status_method("Could not determine video duration.", "orange")
            except Exception as probe_err:
                 self.logger.error("Error during duration probe: %s", probe_err)
            self.setFocus()
        QTimer.singleShot(0, _probe_length)

    def reset_app_state(self):
        """Resets the UI and state so a new file can be loaded fresh."""
        self.input_file_path = None
        self.original_resolution = None
        self.trim_start = 0.0
        self.trim_end = 0.0
        self.process_button.setEnabled(False)
        self.progress_update_signal.emit(0)
        self.on_phase_update("Please upload a new video file.")
        try:
            self.positionSlider.setRange(0, 0)
            self.positionSlider.setValue(0)
            self.positionSlider.set_duration_ms(0)
            self.positionSlider.set_trim_times(0, 0)
        except AttributeError:
            pass
        self.drop_label.setText("Drag & Drop\r\nVideo File Here:")
    
    def handle_new_file(self):
        """Clear state and immediately open file picker."""
        self.reset_app_state()
        self.select_file()

    def _save_app_state_and_config(self):
        """Encapsulates all logic for saving application state to disk."""
        cfg = self.config_manager.config
        try:
            cfg['window_geometry'] = {
                'x': self.geometry().x(),
                'y': self.geometry().y(),
                'w': self.geometry().width(),'h': self.geometry().height()
            }
        except Exception:
            pass
        try:
            cfg['mobile_checked'] = bool(self.mobile_checkbox.isChecked())
        except Exception:
            pass
        try:
            cfg['teammates_checked'] = bool(self.teammates_checkbox.isChecked())
        except Exception:
            pass
        try:
            cfg['last_directory'] = self.last_dir
        except Exception:
            pass
        self.config_manager.save_config(cfg)
        self.logger.info("CONFIG: Saved current state to disk.")
        
    def closeEvent(self, event):
        """Saves the window position and size before closing."""
        self._save_app_state_and_config()
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

    def _reset_player_after_end(self):
        try:
            p = getattr(self, 'player', None)
            if not p:
                return
            p.blockSignals(True)
            p.pause()
            p.setPosition(0)
        except Exception:
            pass
        finally:
            try:
                p.blockSignals(False)
            except Exception:
                pass
        try:
            if hasattr(self, 'play_button'):
                self.play_button.setText("▶ Play")
            if hasattr(self, 'trim_slider'):
                self.trim_slider.setEnabled(True)
        except Exception:
            pass
        setattr(self, '_is_playing', False)
    
    def _on_media_status(self, status):
        try:
            from PyQt5.QtMultimedia import QMediaPlayer
            end_status = QMediaPlayer.EndOfMedia
        except Exception:
            from PyQt6.QtMultimedia import QMediaPlayer
            end_status = QMediaPlayer.MediaStatus.EndOfMedia
    
        if status == end_status:
            self._reset_player_after_end()
    
    def _on_position_changed(self, pos_ms):
        try:
            p = getattr(self, 'player', None)
            if not p:
                return
            dur = int(p.duration() or 0)
            if dur > 0 and pos_ms >= max(0, dur - 200):
                self._reset_player_after_end()
        except Exception:
            pass
    
    def _on_state_changed(self, state):
        try:
            is_playing = getattr(state, 'value', lambda: state)() == 1
            if hasattr(self, 'play_button'):
                self.play_button.setText("⏸ Pause" if is_playing else "▶ Play")
        except Exception:
            pass

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
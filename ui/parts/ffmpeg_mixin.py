import os
import sys
import time
import subprocess
import json
from PyQt5.QtCore import Qt, QTimer, QCoreApplication
from PyQt5.QtGui import QIcon
from PyQt5.QtWidgets import (QStyle, QApplication, QDialog, QVBoxLayout, QLabel,
                             QGridLayout, QPushButton)
from processing.worker import ProcessThread

class FfmpegMixin:

        def _safe_status(self, text: str, color: str = "white"):
            """Use set_status_text_with_color if available; otherwise just log."""
            try:
                self.set_status_text_with_color(text, color)
            except Exception:
                try:
                    if hasattr(self, "logger"):
                        self.logger.info("STATUS(%s): %s", color, text)
                except Exception:
                    pass

        def _safe_set_phase(self, name: str, ok: bool | None = None):
            """Try to update the phase overlay/label; never crash if label is missing."""
            try:
                self.on_phase_update(name)
                return
            except Exception:
                pass
            try:
                if hasattr(self, "logger"):
                    self.logger.info("PHASE: %s", name)
            except Exception:
                pass
        
        def _safe_set_duration_text(self, text: str):
            """Set duration/resolution text if a label exists; otherwise log."""
            try:
                self.duration_label.setText(text)
                return
            except Exception:
                pass
            try:
                if hasattr(self, "logger"):
                    self.logger.info("DURATION: %s", text)
            except Exception:
                pass

        def start_processing(self):
            """
            Starts the video processing sequence in a separate thread; never let exceptions kill the app.
            """
            try:
                if self.is_processing:
                    self.show_message("Info", "A video is already being processed. Please wait.")
                    return
                if not self.input_file_path or not os.path.exists(self.input_file_path):
                    self.show_message("Error", "Please select a valid video file first.")
                    return
                if self.original_resolution not in ["1920x1080", "2560x1440", "3440x1440", "3840x2160"]:
                    self._safe_status("Unsupported input resolution.", "red")
                    return
                start_time = (self.start_minute_input.value() * 60) + self.start_second_input.value()
                end_time   = (self.end_minute_input.value()   * 60) + self.end_second_input.value()
                is_mobile_format = self.mobile_checkbox.isChecked()
                speed_factor = self.speed_spinbox.value()
                if speed_factor < 0.5 or speed_factor > 3.1:
                    self.show_message("Invalid Speed", "Allowed speed range is 0.5x to 3.1x.")
                    self.is_processing = False
                    self.process_button.setEnabled(True)
                    return
                dur = float(self.original_duration or 0.0)
                if dur <= 0.0:
                    self.show_message("Error", "Video duration unavailable yet. Please wait a moment and try again.")
                    return
                if (start_time is None or start_time <= 0.0) and (end_time is None or end_time <= 0.0):
                    start_time, end_time = 0.0, dur
                start_time = max(0.0, min(float(start_time), dur))
                end_time   = max(0.0, min(float(end_time)  , dur))
                eps = max(0.01, min(0.2, dur * 0.001))
                end_time = min(dur, max(end_time, start_time + eps))
                if end_time >= dur and start_time >= dur - eps:
                    start_time = max(0.0, dur - eps)
                self.trim_start, self.trim_end = start_time, end_time
                self._update_trim_widgets_from_trim_times()
                self.positionSlider.set_trim_times(self.trim_start, self.trim_end)
                music_path, music_vol_linear = self._get_selected_music()
                q_level = int(self.quality_slider.value())
                self.logger.info(
                    "PROCESS: clicked at %s | start=%.3fs end=%.3fs speed=%sx | mobile=%s teammates=%s | quality_level=%d | disable_fades=%s | music=%s vol=%.2f",
                    time.strftime("%Y-%m-%d %H:%M:%S"),
                    start_time, end_time, speed_factor,
                    is_mobile_format, self.teammates_checkbox.isChecked(),
                    q_level,
                    self.no_fade_checkbox.isChecked(),
                    (music_path or "None"), (music_vol_linear if music_vol_linear is not None else 0.0)
                )
                self.is_processing = True
                self._proc_start_ts = time.time()
                self._pulse_phase = 0
                self.process_button.setEnabled(False)
                self.progress_bar.setRange(0, 0)
                self.progress_bar.setValue(0)
                self._pulse_timer.start()
                self.process_button.setText("Processing…")
                self.process_button.setIcon(self.style().standardIcon(QStyle.SP_BrowserReload))
                self._safe_set_phase("Processing")
                self._show_processing_overlay()
                self._safe_status("Preparing… (probing/seek)…", "white")
                QApplication.setOverrideCursor(Qt.WaitCursor)
                self.progress_update_signal.emit(0)
                cfg = dict(self.config_manager.config)
                cfg['last_speed'] = float(speed_factor)
                cfg['mobile_checked'] = bool(is_mobile_format)
                cfg['teammates_checked'] = bool(self.teammates_checkbox.isChecked())
                self.config_manager.save_config(cfg)
                q_level = int(self.quality_slider.value())
                music_path, music_vol_linear = self._get_selected_music()
                self.process_thread = ProcessThread(
                    self.input_file_path, start_time, end_time, self.original_resolution,
                    is_mobile_format, speed_factor, self.script_dir,
                    self.progress_update_signal, self.status_update_signal, self.process_finished_signal,
                    self.logger,
                    show_teammates_overlay=(is_mobile_format and self.teammates_checkbox.isChecked()),
                    quality_level=q_level,
                    bg_music_path=music_path, bg_music_volume=music_vol_linear,
                    bg_music_offset=self._get_music_offset(),
                    original_total_duration=self.original_duration,
                    disable_fades=self.no_fade_checkbox.isChecked(),
                    intro_still_sec=(0.1 if not self.no_fade_checkbox.isChecked() else 0.0),
                    intro_from_midpoint=True
                )
                self.process_thread.started.connect(lambda: self.logger.info("ProcessThread: started"))
                self.process_thread.finished.connect(lambda: self.logger.info("ProcessThread: finished"))
                self.process_thread.start()
            except Exception as e:
                self.logger.exception("start_processing crashed: %s", e)
                try:
                    self._pulse_timer.stop()
                    self._hide_processing_overlay()
                    QApplication.restoreOverrideCursor()
                    self.is_processing = False
                    self.process_button.setEnabled(True)
                    self.progress_bar.setRange(0, 100)
                    self.progress_bar.setValue(0)
                    self.on_phase_update("Error")
                    self._safe_status(f"Processing failed to start: {e}", "red")
                except Exception:
                    pass

        def on_process_finished(self, success, message):
            button_size = (185, 45)
            self.is_processing = False
            self._proc_start_ts = None
            self._phase_is_processing = False
            if hasattr(self, "_pulse_timer"):
                self._pulse_timer.stop()
            self._hide_processing_overlay()
            self.process_button.setEnabled(True)
            self.process_button.setText("Process Video")
            self.process_button.setIcon(self.style().standardIcon(QStyle.SP_DialogApplyButton))
            self.progress_bar.setRange(0, 100)
            self.progress_bar.setValue(0)
            if success:
                self._safe_set_phase("Done", ok=True)
            else:
                self._safe_set_phase("Error", ok=False)
            QApplication.restoreOverrideCursor()
            self.status_update_signal.emit("Ready to process another video.")
            try:
                if success:
                    orig_size = os.path.getsize(self.input_file_path) if self.input_file_path and os.path.exists(self.input_file_path) else 0
                    time.sleep(0.1)
                    new_size  = os.path.getsize(message) if message and os.path.exists(message) else 0
                    orig_mb = orig_size / (1024.0 * 1024.0)
                    new_mb  = new_size  / (1024.0 * 1024.0)
                    self.logger.info(
                        f"RESULT: SUCCESS | file='{os.path.basename(self.input_file_path)}' | "
                        f"original_size={orig_mb:.1f} MB | new_size={new_mb:.1f} MB"
                    )
                else:
                    self.logger.error(
                        f"RESULT: FAILURE | file='{os.path.basename(self.input_file_path) if self.input_file_path else 'N/A'}' | details={message}"
                    )
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
                new_file_button.clicked.connect(dialog.reject)
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
                result = dialog.exec_()
                if result == QDialog.Rejected:
                    self.handle_new_file()
            else:
                self.show_message("Error", "Video processing failed.\n" + message)
            try:
                for h in getattr(self.logger, "handlers", []):
                    stream = getattr(h, "stream", None)
                    if stream:
                        stream.write("-----------------------------------------------------------------------------------------------\n")
                        stream.write("-----------------------------------------------------------------------------------------------\n")
                        stream.write("-----------------------------------------------------------------------------------------------\n")
                        stream.write("-----------------------------------------------------------------------------------------------\n")
                        stream.flush()
            except Exception:
                pass

        def get_video_info(self):
            if not self.input_file_path or not os.path.exists(self.input_file_path):
                self.show_message("Error", "No valid video file selected.")
                return
            self._safe_status("Analyzing video...", "white")
            try:
                ffprobe_path = os.path.join(self.bin_dir, 'ffprobe.exe')
                cmd = [
                    ffprobe_path, '-v', 'error', '-select_streams', 'v:0',
                    '-show_entries', 'stream=width,height', '-of', 'csv=p=0:s=x',
                    self.input_file_path
                ]
                result = subprocess.run(cmd, capture_output=True, text=True, check=True,
                                        creationflags=(subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0))
                self.original_resolution = result.stdout.strip()
                if self.original_resolution not in ["1920x1080", "2560x1440", "3440x1440", "3840x2160"]:
                    error_message = "This software is designed for 1080p/1440p/3440x1440/4K inputs."
                    self._safe_status(error_message, "red")
                    self.process_button.setEnabled(False)
                    self._safe_set_duration_text(f"Duration: N/A | Resolution: {self.original_resolution}")
                    return
                self._safe_set_duration_text(
                    f"Duration: {self.original_duration:.0f} s | Resolution: {self.original_resolution}")
                self.trim_start = 0.0
                self.trim_end = self.original_duration
                self._update_trim_widgets_from_trim_times()
                self.positionSlider.set_trim_times(self.trim_start, self.trim_end)
                self._safe_status("Video loaded successfully.", "white")
            except subprocess.CalledProcessError as e:
                self._safe_status(f"Error running ffprobe: {e}", "red")
            except FileNotFoundError:
                self._safe_status("ffprobe.exe not found.", "red")
            self.process_button.setEnabled(True)

        def on_progress(self, value: int):
            if self.progress_bar.maximum() == 0:
                self.progress_bar.setRange(0, 100)
            v = int(max(0, min(100, value)))
            self.progress_bar.setValue(v)

        def _probe_audio_duration(self, path: str) -> float:
            """Return audio duration in seconds (float) or 0.0 on failure."""
            try:
                ffprobe_path = os.path.join(self.bin_dir, 'ffprobe.exe')
                cmd = [ffprobe_path, "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path]
                r = subprocess.run(cmd, capture_output=True, text=True, check=True,
                                   creationflags=(subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0))
                return max(0.0, float(r.stdout.strip()))
            except Exception:
                return 0.0

        def _probe_video_metadata(self, path: str) -> tuple[float, str]:
            """Return (duration_s, resolution_str) or (0.0, '')."""
            try:
                ffprobe_path = os.path.join(self.bin_dir, 'ffprobe.exe')
                cmd = [
                    ffprobe_path, "-v", "error", "-select_streams", "v:0",
                    "-show_entries", "stream=duration,width,height", "-of", "json", path
                ]
                r = subprocess.run(cmd, capture_output=True, text=True, check=True,
                                   creationflags=(subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0))
                data = json.loads(r.stdout.strip())
                stream = data.get('streams', [{}])[0]
                dur = float(stream.get('duration', 0.0) or 0.0)
                res = f"{stream.get('width', 0)}x{stream.get('height', 0)}"
                return max(0.0, dur), res
            except Exception:
                self.logger.exception(f"Failed to probe video metadata for {path}")
                return 0.0, ""
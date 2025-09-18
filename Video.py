# First install PYQT5 by this command from CMD As Administrator:
# pip install PyQt5
import sys
import os
import subprocess
from PyQt5.QtWidgets import (QApplication, QWidget, QVBoxLayout, QHBoxLayout,
                             QLabel, QPushButton, QProgressBar, QSpinBox, QMessageBox, QFrame, QFileDialog, QCheckBox, QDoubleSpinBox)
from PyQt5.QtCore import Qt, QMimeData, QUrl, pyqtSignal, QThread
from PyQt5.QtGui import QFont, QColor, QPalette
import json
import time

class ConfigManager:
    """
    Handles saving and loading application settings from a JSON file.
    """
    def __init__(self, file_path):
        self.file_path = file_path
        self.config = self.load_config()

    def load_config(self):
        """Loads configuration from the JSON file."""
        try:
            with open(self.file_path, 'r') as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return {}

    def save_config(self, config_data):
        """Saves configuration to the JSON file."""
        try:
            with open(self.file_path, 'w') as f:
                json.dump(config_data, f, indent=4)
        except Exception as e:
            print(f"Error saving config file: {e}")

class VideoCompressorApp(QWidget):
    """
    A GUI application for compressing and trimming video files using FFmpeg.
    The application calculates the optimal video bitrate to fit a target file size
    and maintains the highest possible resolution.
    """

    progress_update_signal = pyqtSignal(int)
    status_update_signal = pyqtSignal(str)
    process_finished_signal = pyqtSignal(bool, str)

    def __init__(self, file_path=None):
        """
        Initializes the main application window and its components.
        """
        super().__init__()
        self.setWindowTitle("Fortnite Video Compressor")
        self.setGeometry(100, 100, 700, 450)

        self.input_file_path = None
        self.original_duration = 0
        self.original_resolution = ""
        self.is_processing = False

        self.script_dir = os.path.dirname(sys.executable) if getattr(sys, 'frozen', False) else os.path.dirname(os.path.abspath(__file__))
        
        self.config_manager = ConfigManager(os.path.join(self.script_dir, 'config.json'))
        
        self.last_dir = self.config_manager.config.get('last_directory', os.path.expanduser('~'))

        self.set_style()
        self.init_ui()
        if file_path:
            self.handle_file_selection(file_path)

    def set_style(self):
        """
        Applies a consistent, clean visual style to the application.
        """
        self.setStyleSheet("""
            QWidget {
                background-color: #2c3e50;
                color: #ecf0f1;
                font-family: "Helvetica Neue", Arial, sans-serif;
            }
            QLabel {
                font-size: 16px;
                padding: 5px;
            }
            QFrame#dropArea {
                border: 3px dashed #3498db;
                border-radius: 10px;
                background-color: #34495e;
                padding: 20px;
            }
            QSpinBox, QDoubleSpinBox {
                background-color: #4a667a;
                border: 1px solid #3498db;
                border-radius: 5px;
                padding: 8px;
                color: #ecf0f1;
                font-size: 14px;
            }
            QPushButton {
                background-color: #3498db;
                color: #ffffff;
                border: none;
                padding: 12px 24px;
                border-radius: 8px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #2980b9;
            }
            QPushButton#WhatsappButton {
                background-color: #25D366;
            }
            QPushButton#WhatsappButton:hover {
                background-color: #1DA851;
            }
            QPushButton#OpenFolderButton {
                background-color: #3498db;
            }
            QPushButton#OpenFolderButton:hover {
                background-color: #2980b9;
            }
            QPushButton#DoneButton {
                background-color: #e74c3c;
            }
            QPushButton#DoneButton:hover {
                background-color: #c0392b;
            }
            QProgressBar {
                border: 1px solid #3498db;
                border-radius: 5px;
                text-align: center;
                height: 25px;
                font-weight: bold;
            }
            QProgressBar::chunk {
                background-color: #2ecc71;
            }
            QCheckBox {
                spacing: 10px;
            }
            QCheckBox::indicator {
                width: 20px;
                height: 20px;
                border: 2px solid #3498db;
                border-radius: 4px;
                background-color: #4a667a;
            }
            QCheckBox::indicator:checked {
                background-color: #2ecc71;
            }
        """)

    def init_ui(self):
        """
        Initializes all the user interface widgets and their layout.
        """
        main_layout = QVBoxLayout()
        main_layout.setSpacing(20)

        self.drop_area = DropAreaFrame()
        self.drop_area.setObjectName("dropArea")
        drop_layout = QVBoxLayout(self.drop_area)
        self.drop_label = QLabel("Drag and Drop your Video File Here")
        self.drop_label.setAlignment(Qt.AlignCenter)
        drop_layout.addWidget(self.drop_label)
        main_layout.addWidget(self.drop_area)
        
        self.upload_button = QPushButton("Or, Upload a Video File")
        self.upload_button.clicked.connect(self.select_file)
        main_layout.addWidget(self.upload_button)

        info_layout = QHBoxLayout()
        self.file_label = QLabel("File: No file selected")
        self.duration_label = QLabel("Duration: 0 s | Resolution: N/A")
        info_layout.addWidget(self.file_label)
        info_layout.addWidget(self.duration_label)
        main_layout.addLayout(info_layout)

        # 4. Trimming Inputs - now with minutes and seconds
        trim_layout = QHBoxLayout()
        start_label = QLabel("Start Time:")
        start_label.setStyleSheet("color: #ffffff; font-weight: bold;")
        self.start_minute_input = QSpinBox()
        self.start_minute_input.setRange(0, 0)
        self.start_minute_input.setSuffix(" min")
        self.start_second_input = QSpinBox()
        self.start_second_input.setRange(0, 59)
        self.start_second_input.setSuffix(" sec")
        
        end_label = QLabel("End Time:")
        end_label.setStyleSheet("color: #ffffff; font-weight: bold;")
        self.end_minute_input = QSpinBox()
        self.end_minute_input.setRange(0, 0)
        self.end_minute_input.setSuffix(" min")
        self.end_second_input = QSpinBox()
        self.end_second_input.setRange(0, 59)
        self.end_second_input.setSuffix(" sec")

        trim_layout.addWidget(start_label)
        trim_layout.addWidget(self.start_minute_input)
        trim_layout.addWidget(self.start_second_input)
        trim_layout.addWidget(end_label)
        trim_layout.addWidget(self.end_minute_input)
        trim_layout.addWidget(self.end_second_input)
        main_layout.addLayout(trim_layout)
        
        options_layout = QHBoxLayout()
        self.mobile_checkbox = QCheckBox("Optimize for Mobile (Portrait Mode)")
        options_layout.addWidget(self.mobile_checkbox)

        speed_label = QLabel("Speed:")
        speed_label.setStyleSheet("color: #ffffff; font-weight: bold;")
        options_layout.addWidget(speed_label, alignment=Qt.AlignRight)
        self.speed_spinbox = QDoubleSpinBox()
        self.speed_spinbox.setRange(0.5, 2.0)
        self.speed_spinbox.setSingleStep(0.05)
        self.speed_spinbox.setValue(1.1)
        self.speed_spinbox.setSuffix("x")
        options_layout.addWidget(self.speed_spinbox)
        main_layout.addLayout(options_layout)

        self.progress_bar = QProgressBar(self)
        self.progress_bar.setValue(0)
        main_layout.addWidget(self.progress_bar)

        self.status_label = QLabel("Ready to process.")
        self.status_label.setAlignment(Qt.AlignCenter)
        main_layout.addWidget(self.status_label)

        self.process_button = QPushButton("Process Video")
        self.process_button.clicked.connect(self.start_processing)
        main_layout.addWidget(self.process_button)
        
        self.progress_update_signal.connect(self.progress_bar.setValue)
        self.status_update_signal.connect(self.status_label.setText)
        self.process_finished_signal.connect(self.on_process_finished)
        
        self.drop_area.file_dropped.connect(self.handle_file_selection)

        self.setLayout(main_layout)
        
    def select_file(self):
        """
        Opens a file dialog for the user to select a video file.
        The initial directory is set to the last used location.
        """
        file_path, _ = QFileDialog.getOpenFileName(self, "Select Video File", self.last_dir, "Video Files (*.mp4 *.mkv *.mov *.avi)")
        if file_path:
            self.handle_file_selection(file_path)

    def handle_file_selection(self, file_path):
        """
        A common method to handle a selected file, whether via drag-and-drop or file dialog.
        """
        self.input_file_path = file_path
        self.drop_label.setText(f"File selected: {os.path.basename(self.input_file_path)}")
        self.file_label.setText(f"File: {self.input_file_path}")

        dir_path = os.path.dirname(file_path)
        if os.path.isdir(dir_path):
            self.last_dir = dir_path
            self.config_manager.save_config({'last_directory': self.last_dir})
        
        self.get_video_info()
    
    def set_status_text_with_color(self, text, color="white"):
        """
        A helper function to update the status label with a specific color.
        """
        self.status_label.setStyleSheet(f"color: {color};")
        self.status_label.setText(text)

    def get_video_info(self):
        """
        Uses ffprobe to get video duration and resolution.
        """
        if not self.input_file_path or not os.path.exists(self.input_file_path):
            self.show_message("Error", "No valid video file selected.")
            return

        self.set_status_text_with_color("Analyzing video...", "white")
        try:
            ffprobe_path = os.path.join(self.script_dir, 'ffprobe.exe')
            cmd = [
                ffprobe_path, '-v', 'error', '-select_streams', 'v:0',
                '-show_entries', 'stream=width,height', '-of',
                'csv=p=0:s=x', self.input_file_path
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, check=True, creationflags=subprocess.CREATE_NO_WINDOW)
            self.original_resolution = result.stdout.strip()

            if self.original_resolution not in ["1920x1080", "2560x1440"]:
                error_message = "This software is designed to work with HD or 1440p resolution only. Apologies!"
                self.set_status_text_with_color(error_message, "red")
                self.process_button.setEnabled(False) # Disable the button if resolution is unsupported
                self.duration_label.setText(f"Duration: N/A | Resolution: {self.original_resolution}")
                return
            
            cmd_duration = [ffprobe_path, '-v', 'error', '-show_entries', 'format=duration', '-of', 'json', self.input_file_path]
            result_duration = subprocess.run(cmd_duration, capture_output=True, text=True, check=True, creationflags=subprocess.CREATE_NO_WINDOW)
            video_info = json.loads(result_duration.stdout)
            self.original_duration = float(video_info['format']['duration'])
            
            total_seconds = int(self.original_duration)
            total_minutes = total_seconds // 60
            remaining_seconds = total_seconds % 60
            
            self.duration_label.setText(f"Duration: {total_minutes}m {remaining_seconds}s | Resolution: {self.original_resolution}")
            
            max_minutes = int(self.original_duration) // 60
            self.start_minute_input.setRange(0, max_minutes)
            self.end_minute_input.setRange(0, max_minutes)
            self.start_second_input.setRange(0, 59)
            self.end_second_input.setRange(0, 59)
            
            self.end_minute_input.setValue(total_minutes)
            self.end_second_input.setValue(remaining_seconds)
            self.set_status_text_with_color("Video analysis complete.", "white")
            self.process_button.setEnabled(True)

        except FileNotFoundError:
            self.show_message("Error", "FFprobe not found. Please ensure FFmpeg is in the same folder as the application.")
            self.set_status_text_with_color("Error: FFmpeg not found.", "red")
            self.process_button.setEnabled(False)
        except subprocess.CalledProcessError as e:
            error_message = e.stderr or e.stdout
            self.show_message("Error", f"Failed to analyze video with ffprobe: {error_message}")
            self.set_status_text_with_color("Error during analysis.", "red")
            self.process_button.setEnabled(False)
        except (KeyError, json.JSONDecodeError):
            self.show_message("Error", "Could not parse video metadata. Is the file a valid video?")
            self.set_status_text_with_color("Error: Invalid video file.", "red")
            self.process_button.setEnabled(False)

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

        if self.original_resolution not in ["1920x1080", "2560x1440"]:
            self.set_status_text_with_color("This software is designed to work with HD or 1440p resolution only. Apologies!", "red")
            return

        start_time = (self.start_minute_input.value() * 60) + self.start_second_input.value()
        end_time = (self.end_minute_input.value() * 60) + self.end_second_input.value()
        is_mobile_format = self.mobile_checkbox.isChecked()
        speed_factor = self.speed_spinbox.value()

        if start_time < 0 or end_time < 0 or start_time >= end_time or end_time > self.original_duration:
            self.show_message("Error", "Invalid start and end times. Please ensure end time > start time and within video duration.")
            return

        self.is_processing = True
        self.process_button.setEnabled(False)
        self.set_status_text_with_color("Processing video... Please wait.", "white")
        self.progress_update_signal.emit(0)

        self.process_thread = ProcessThread(
            self.input_file_path,
            start_time,
            end_time,
            self.original_duration,
            self.original_resolution,
            self.progress_update_signal,
            self.status_update_signal,
            self.process_finished_signal,
            self.script_dir,
            is_mobile_format, # Pass the new flag to the worker thread
            speed_factor # Pass the speed factor
        )
        self.process_thread.start()
        
    def on_process_finished(self, success, message):
        """
        Handles the result of the video processing.
        """
        self.is_processing = False
        self.process_button.setEnabled(True)
        if success:
            output_dir = os.path.dirname(message)
            msg_box = QMessageBox(self)
            msg_box.setWindowTitle("Success")
            msg_box.setText(f"Video processed successfully!\n\nFile saved to:\n<b>{message}</b>")
            
            whatsapp_button = QPushButton("Share via Whatsapp")
            whatsapp_button.setObjectName("WhatsappButton")
            msg_box.addButton(whatsapp_button, QMessageBox.AcceptRole)
            whatsapp_button.clicked.connect(self.share_via_whatsapp)
            
            open_folder_button = QPushButton("Open Output Folder")
            open_folder_button.setObjectName("OpenFolderButton")
            msg_box.addButton(open_folder_button, QMessageBox.AcceptRole)
            open_folder_button.clicked.connect(lambda: self.open_folder(output_dir))

            done_button = QPushButton("Done")
            done_button.setObjectName("DoneButton")
            msg_box.addButton(done_button, QMessageBox.RejectRole)
            
            msg_box.setWindowFlags(msg_box.windowFlags() & ~Qt.WindowContextHelpButtonHint)
            msg_box.exec_()

        else:
            self.show_message("Error", "Video processing failed.\n" + message)

    def show_message(self, title, message):
        """
        Displays a custom message box instead of alert().
        """
        msg_box = QMessageBox(self)
        msg_box.setWindowTitle(title)
        msg_box.setText(message)
        msg_box.setStandardButtons(QMessageBox.Ok)
        msg_box.exec_()

    def open_folder(self, path):
        """
        Opens the specified folder using the default file explorer.
        """
        if os.path.exists(path):
            try:
                # Use shell=True for better handling of paths with spaces on Windows
                if sys.platform == 'win32':
                    os.startfile(path, 'explore')
                elif sys.platform == 'darwin': # macOS
                    subprocess.Popen(['open', path])
                else: # Linux
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

class DropAreaFrame(QFrame):
    """
    A custom QFrame class to handle drag-and-drop events specifically.
    """
    file_dropped = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
    
    def dragEnterEvent(self, event):
        """
        Handles the drag-and-drop enter event. Accepts video files.
        """
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event):
        """
        Handles the drag-and-drop drop event.
        """
        if event.mimeData().hasUrls():
            file_path = event.mimeData().urls()[0].toLocalFile()
            
            if os.path.exists(file_path) and file_path.lower().endswith(('.mp4', '.mkv', '.mov', '.avi')):
                self.file_dropped.emit(file_path)
                event.acceptProposedAction()
            else:
                event.ignore()
        else:
            event.ignore()

class ProcessThread(QThread):
    """
    A QThread to run the FFmpeg process in the background.
    """
    def __init__(self, input_path, start_time, end_time, original_duration, original_resolution, progress_signal, status_signal, finished_signal, script_dir, is_mobile_format, speed_factor):
        super().__init__()
        self.input_path = input_path
        self.start_time = start_time
        self.end_time = end_time
        self.duration = end_time - start_time
        self.original_resolution = original_resolution
        self.progress_signal = progress_signal
        self.status_signal = status_signal
        self.finished_signal = finished_signal
        self.script_dir = script_dir
        self.is_mobile_format = is_mobile_format
        self.speed_factor = speed_factor

    def run(self):
        """
        The main processing logic that runs in the separate thread.
        """
        if self.speed_factor != 1.0:
            start_time_corrected = self.start_time / self.speed_factor
            end_time_corrected = self.end_time / self.speed_factor
            
            duration_corrected = end_time_corrected - start_time_corrected
            
            self.status_signal.emit(f"Correcting trim times for speed factor {self.speed_factor}x.")
            self.status_signal.emit(f"Original trim: {self.start_time:.2f}s to {self.end_time:.2f}s")
            self.status_signal.emit(f"Corrected trim: {start_time_corrected:.2f}s to {end_time_corrected:.2f}s")
        else:
            start_time_corrected = self.start_time
            end_time_corrected = self.end_time
            duration_corrected = self.end_time - self.start_time
        
        TARGET_MB = 50.0  # A good midpoint of the 40-64MB range
        AUDIO_KBPS = 128

        try:
            target_file_size_bits = TARGET_MB * 8 * 1024 * 1024
            audio_bits = AUDIO_KBPS * 1024 * duration_corrected
            video_bits = target_file_size_bits - audio_bits
            
            if video_bits < 0:
                self.finished_signal.emit(False, "Video duration is too short to meet the file size and audio bitrate requirements.")
                return

            video_bitrate_kbps = video_bits / (1024 * duration_corrected)
        except ZeroDivisionError:
            self.finished_signal.emit(False, "Selected video duration is zero.")
            return

        self.status_signal.emit(f"Calculated target bitrate: {video_bitrate_kbps:.2f} kbps")

        video_filter_cmd = ""
        healthbar_crop_string = ""
        if self.original_resolution == "1920x1080":
            healthbar_crop_string = "275:39:83:1005"
        elif self.original_resolution == "2560x1440":
            healthbar_crop_string = "367:52:111:1340"
        
        if self.is_mobile_format:
            video_filter_cmd = (
                f"split[main][healthbar];"
                f"[main]scale=1150:1920:force_original_aspect_ratio=increase,crop=1150:1920[main_cropped];"
                f"[healthbar]crop={healthbar_crop_string},scale=1150:-1[healthbar_cropped];"
                f"[main_cropped]pad=1150:1920:0:40[padded_main];"
                f"[padded_main][healthbar_cropped]overlay=0:0"
            )
            self.status_signal.emit("Optimizing for mobile: Applying complex video filter for split-screen and health bar overlay.")
        else:
            original_width, original_height = map(int, self.original_resolution.split('x'))
            target_resolution = f"scale='min(1920,iw)':-2"
            if video_bitrate_kbps < 800 and original_height > 720:
                target_resolution = f"scale='min(1280,iw)':-2"
                self.status_signal.emit("Note: Low bitrate detected. Scaling to a lower HD resolution (720p) for better quality.")
            video_filter_cmd = f"fps=60,{target_resolution}"
        
        if self.speed_factor != 1.0:
            speed_filter = f"setpts=PTS/{self.speed_factor}"
            if video_filter_cmd:
                video_filter_cmd = f"{speed_filter},{video_filter_cmd}"
            else:
                video_filter_cmd = speed_filter
            self.status_signal.emit(f"Applying speed factor: {self.speed_factor}x to video.")

        audio_filter_cmd = ""
        if self.speed_factor != 1.0:
            audio_filter_cmd = f"atempo={self.speed_factor}"
            self.status_signal.emit(f"Applying speed factor: {self.speed_factor}x to audio.")

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
        
        pass1_cmd = [
            ffmpeg_path, '-y',
            '-hwaccel', 'auto',
            '-i', self.input_path,
            '-ss', str(start_time_corrected), '-to', str(end_time_corrected),
            '-c:v', 'h264_nvenc', '-b:v', f'{video_bitrate_kbps}k',
            '-pass', '1', '-an', '-f', 'mp4'
        ]
        
        if self.is_mobile_format:
            pass1_cmd.extend(['-filter_complex', video_filter_cmd])
        elif video_filter_cmd:
            pass1_cmd.extend(['-vf', video_filter_cmd])

        if audio_filter_cmd:
            pass1_cmd.extend(['-af', audio_filter_cmd])
        
        pass1_cmd.append(os.devnull)

        pass2_cmd = [
            ffmpeg_path, '-y',
            '-hwaccel', 'auto',
            '-i', self.input_path,
            '-ss', str(start_time_corrected), '-to', str(end_time_corrected),
            '-c:v', 'h264_nvenc', '-b:v', f'{video_bitrate_kbps}k',
            '-pass', '2',
            '-c:a', 'aac', '-b:a', f'{AUDIO_KBPS}k'
        ]
        
        if self.is_mobile_format:
            pass2_cmd.extend(['-filter_complex', video_filter_cmd])
        elif video_filter_cmd:
            pass2_cmd.extend(['-vf', video_filter_cmd])

        if audio_filter_cmd:
            pass2_cmd.extend(['-af', audio_filter_cmd])

        pass2_cmd.append(output_path)
        
        try:
            self.status_signal.emit("Processing... Pass 1 of 2: Analyzing video.")
            subprocess.run(pass1_cmd, check=True, creationflags=subprocess.CREATE_NO_WINDOW, capture_output=True, text=True)
            self.progress_signal.emit(50) # Update progress after pass 1

            self.status_signal.emit("Processing... Pass 2 of 2: Encoding video.")
            subprocess.run(pass2_cmd, check=True, creationflags=subprocess.CREATE_NO_WINDOW, capture_output=True, text=True)
            
            self.progress_signal.emit(100)
            
            if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
                self.finished_signal.emit(True, output_path)
            else:
                self.finished_signal.emit(False, "Output file was created, but it is empty. This may indicate an FFmpeg error not caught by the process.")

        except FileNotFoundError:
            self.finished_signal.emit(False, f"FFmpeg not found at {ffmpeg_path}. Please ensure it's in the same folder as the application.")
        except subprocess.CalledProcessError as e:
            error_message = e.stderr or e.stdout
            self.finished_signal.emit(False, f"An FFmpeg error occurred: {error_message}")
        except Exception as e:
            self.finished_signal.emit(False, f"An unexpected error occurred: {e}")

if __name__ == "__main__":
    script_dir = os.path.dirname(sys.executable) if getattr(sys, 'frozen', False) else os.path.dirname(os.path.abspath(__file__))
    ffmpeg_path = os.path.join(script_dir, 'ffmpeg.exe')
    ffprobe_path = os.path.join(script_dir, 'ffprobe.exe')

    try:
        subprocess.run([ffmpeg_path, '-version'], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=subprocess.CREATE_NO_WINDOW)
        subprocess.run([ffprobe_path, '-version'], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=subprocess.CREATE_NO_WINDOW)
    except FileNotFoundError:
        msg_box = QMessageBox()
        msg_box.setIcon(QMessageBox.Critical)
        msg_box.setWindowTitle("Dependency Error")
        msg_box.setText("FFmpeg or FFprobe not found. Please ensure both 'ffmpeg.exe' and 'ffprobe.exe' are in the same folder as this application.")
        msg_box.exec_()
        sys.exit(1)

    app = QApplication(sys.argv)
    
    # Corrected logic to handle the command-line argument
    file_arg = sys.argv[1] if len(sys.argv) > 1 else None
    
    ex = VideoCompressorApp(file_arg) # Pass the file argument to the main class
    ex.show()
    sys.exit(app.exec_())
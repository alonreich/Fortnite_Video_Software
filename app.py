import os, sys
os.environ['PYTHONDONTWRITEBYTECODE'] = '1'
sys.dont_write_bytecode = True
from PyQt5.QtWidgets import QApplication, QMessageBox
from PyQt5.QtCore import QCoreApplication
import subprocess, ctypes
BASE_DIR  = os.path.dirname(os.path.abspath(__file__))
BIN_DIR   = os.path.join(BASE_DIR, 'binaries')
PLUGINS   = os.path.join(BIN_DIR, 'plugins')
os.environ['VLC_PLUGIN_PATH'] = PLUGINS
if hasattr(os, 'add_dll_directory'):
    if os.path.isdir(BIN_DIR):   os.add_dll_directory(BIN_DIR)
    if os.path.isdir(PLUGINS):   os.add_dll_directory(PLUGINS)
os.environ['PATH'] = BIN_DIR + os.pathsep + PLUGINS + os.pathsep + os.environ.get('PATH','')
ctypes.WinDLL(os.path.join(BIN_DIR, 'libvlccore.dll'))
ctypes.WinDLL(os.path.join(BIN_DIR, 'libvlc.dll'))
from ui.main_window import VideoCompressorApp

if __name__ == "__main__":
    ffmpeg_path = os.path.join(BIN_DIR, 'ffmpeg.exe')
    ffprobe_path = os.path.join(BIN_DIR, 'ffprobe.exe')
    try:
        subprocess.run([ffmpeg_path, '-version'], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                       creationflags=(subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0))
        subprocess.run([ffprobe_path, '-version'], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                       creationflags=(subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0))
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

def _hwenc_available(ffmpeg_path: str) -> bool:
    try:
        out = subprocess.check_output(
            [ffmpeg_path, "-hide_banner", "-encoders"],
            stderr=subprocess.STDOUT,
            creationflags=(subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0),
            text=True
        )
        txt = out.lower()
        return any(tag in txt for tag in ("h264_nvenc", "hevc_nvenc", "h264_qsv", "hevc_qsv", "h264_amf", "hevc_amf"))
    except Exception:
        return False
ffmpeg_path = os.path.join(BIN_DIR, 'ffmpeg.exe')
gpu_ok = _hwenc_available(ffmpeg_path)
if not gpu_ok:
    os.environ['VIDEO_FORCE_CPU'] = '1'
    from PyQt5.QtWidgets import QMessageBox
    m = QMessageBox()
    m.setIcon(QMessageBox.Critical)
    m.setWindowTitle("GPU Not Detected!!!")
    m.setText("GPU Not Detected!!!\nFailing over to CPU\n(This means a much slower processing of videos)")
    m.setStandardButtons(QMessageBox.Ok)
    m.setStyleSheet("""
        QMessageBox QLabel {
            color: #ff2d2d; 
            font-size: 18px; 
            font-weight: 800;
        }
        QMessageBox {
            background: #1b1b1b;
        }
        QPushButton {
            background-color: #ff2d2d; color: white;
            font-size: 14px; padding: 8px 16px; border-radius: 6px;
        }
        QPushButton:hover { background-color: #ff4d4d; }
        QPushButton:pressed { background-color: #cc2424; }
    """)
    m.exec_()
ex = VideoCompressorApp(file_arg)
ex.show()
sys.exit(app.exec_())
import os, sys
os.environ['PYTHONDONTWRITEBYTECODE'] = '1'
sys.dont_write_bytecode = True
from PyQt5.QtWidgets import QApplication, QMessageBox
from PyQt5.QtCore import QCoreApplication
from PyQt5.QtGui import QIcon
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
    sys.stdout = open(os.devnull, "w")
    sys.stderr = open(os.devnull, "w")
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
    if sys.platform.startswith("win"):
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("FortniteVideoTool.VideoCompressor")
        except Exception:
            pass
        try:
            hwnd = ctypes.windll.kernel32.GetConsoleWindow()
            if hwnd:
                ctypes.windll.user32.ShowWindow(hwnd, 0)
                ctypes.windll.kernel32.FreeConsole()
        except Exception:
            pass
    try:
        preferred = os.path.join(BASE_DIR, "icons", "Video_Icon_File.ico")
        fallback  = os.path.join(BASE_DIR, "icons", "app_icon.ico")
        icon_path = preferred if os.path.exists(preferred) else fallback
        if os.path.exists(icon_path):
            app.setWindowIcon(QIcon(icon_path))
    except Exception:
        pass
    file_arg = sys.argv[1] if len(sys.argv) > 1 else None

def _hwenc_available(ffmpeg_path: str) -> bool:
    """Probe FFmpeg for HW encoders/accels without ever raising."""
    try:
        out = subprocess.check_output(
            [ffmpeg_path, "-hide_banner", "-encoders"],
            stderr=subprocess.STDOUT,
            creationflags=(subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0),
            text=True
        ).lower()
        if any(t in out for t in ("h264_nvenc","hevc_nvenc","h264_qsv","hevc_qsv","h264_amf","hevc_amf")):
            return True
    except Exception:
        pass
    try:
        out2 = subprocess.check_output(
            [ffmpeg_path, "-hide_banner", "-hwaccels"],
            stderr=subprocess.STDOUT,
            creationflags=(subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0),
            text=True
        ).lower()
        if any(t in out2 for t in ("cuda","dxva2","d3d11va","qsv","amf")):
            return True
    except Exception:
        pass
    return False

ffmpeg_path = os.path.join(BIN_DIR, "ffmpeg.exe")
gpu_ok = _hwenc_available(ffmpeg_path)
if not gpu_ok:
    os.environ["VIDEO_FORCE_CPU"] = "1"
    try:
        import logging
        logging.getLogger("Startup").warning("Hardware-encoder probe failed; forcing CPU.")
    except Exception:
        pass
ex = VideoCompressorApp(file_arg)
try:
    if os.path.exists(icon_path):
        ex.setWindowIcon(QIcon(icon_path))
except Exception:
    pass
ex.show()
sys.exit(app.exec_())
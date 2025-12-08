import sys
import os
sys.dont_write_bytecode = True
from pathlib import Path
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QApplication, QMessageBox
from PyQt5.QtGui import QIcon
import ctypes

try:
    _proj_root_path = Path(__file__).resolve().parents[1]
    if str(_proj_root_path) not in sys.path:
        sys.path.insert(0, str(_proj_root_path))
except Exception:
    pass

from utilities.merger_ui import MergerUI
from utilities.merger_handlers import MergerHandlers
from utilities.merger_ffmpeg import FFMpegHandler
from utilities.merger_music import MusicHandler
from utilities.merger_utils import _get_logger, _load_conf, _save_conf
from utilities.merger_window import VideoMergerWindow

def main():
    if sys.platform == "win32":
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("FortniteVideoTool.Merger")
            hwnd = ctypes.windll.kernel32.GetConsoleWindow()
            if hwnd:
                ctypes.windll.user32.ShowWindow(hwnd, 0)
            ctypes.windll.kernel32.FreeConsole()
        except Exception:
            pass
    sys.stdout = open(os.devnull, 'w')
    sys.stderr = open(os.devnull, 'w')
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
    app = QApplication(sys.argv)
    try:
        _proj_root_path = Path(__file__).resolve().parents[1]
        preferred = str(_proj_root_path / "icons" / "Video_Icon_File.ico")
        fallback  = str(_proj_root_path / "icons" / "app_icon.ico")
        icon_path = preferred if os.path.exists(preferred) else fallback
        if os.path.exists(icon_path):
            app.setWindowIcon(QIcon(icon_path))
    except Exception:
        pass
    try:
        bin_dir = _proj_root_path / 'binaries'
        ffmpeg_path = bin_dir / 'ffmpeg.exe'
        if not ffmpeg_path.exists():
            QMessageBox.critical(None, "Error", f"ffmpeg.exe not found at {ffmpeg_path}\n" 
                                               f"This will fail.")
            sys.exit(1)
        
        vlc_instance = None
        try:
            import vlc
            vlc_instance = vlc.Instance('--no-xlib --quiet')
        except Exception as vlc_err:
            QMessageBox.warning(None, "VLC Error", f"Could not initialize VLC for music preview:\n{vlc_err}")
            
        window = VideoMergerWindow(ffmpeg_path=str(ffmpeg_path), vlc_instance=vlc_instance, bin_dir=str(bin_dir), base_dir=_proj_root_path)
        window.show()
        sys.exit(app.exec_())
    except Exception as e:
        QMessageBox.critical(None, "Error", f"Failed to initialize: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()

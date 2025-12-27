import sys
sys.dont_write_bytecode = True
import os
from pathlib import Path
import ctypes
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QApplication, QMessageBox
from PyQt5.QtGui import QIcon
import subprocess

def _ensure_project_root_on_path():
    root = Path(__file__).resolve().parents[1]
    rp = str(root)
    if rp not in sys.path:
        sys.path.insert(0, rp)
    return root

def main():
    root = _ensure_project_root_on_path()
    from utilities.merger_window import VideoMergerWindow
    if sys.platform == "win32":
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("FortniteVideoTool.Merger")
            hwnd = ctypes.windll.kernel32.GetConsoleWindow()
            if hwnd:
                pass
        except Exception:
            pass
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
    app = QApplication(sys.argv)
    try:
        preferred = root / "icons" / "Video_Icon_File.ico"
        fallback  = root / "icons" / "app_icon.ico"
        icon_path = preferred if preferred.exists() else fallback
        if icon_path.exists():
            app.setWindowIcon(QIcon(str(icon_path)))
        bin_dir = root / "binaries"
        ffmpeg_path = bin_dir / "ffmpeg.exe"
        if not ffmpeg_path.exists():
            QMessageBox.critical(None, "Error", f"ffmpeg.exe not found at {ffmpeg_path}")
            sys.exit(1)
        vlc_instance = None
        try:
            import vlc
            vlc_instance = vlc.Instance('--no-xlib --quiet')
        except Exception:
            pass
        w = VideoMergerWindow(
            ffmpeg_path=str(ffmpeg_path),
            vlc_instance=vlc_instance,
            bin_dir=str(bin_dir),
            base_dir=str(root),
        )
        w.show()
        sys.exit(app.exec_())
    except Exception as e:
        QMessageBox.critical(None, "Error", f"Failed to initialize: {e}")
        sys.exit(1)
if __name__ == "__main__":
    main()
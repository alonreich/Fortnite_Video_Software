import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.dont_write_bytecode = True
import ctypes
import tempfile
from PyQt5.QtWidgets import QApplication, QWidget
from PyQt5.QtCore import Qt, QTimer
from utils import PersistentWindowMixin
from Keyboard_Mixing import KeyboardShortcutMixin
from media_processor import MediaProcessor
from ui_setup import Ui_CropApp
from app_handlers import CropAppHandlers
from config import CROP_APP_STYLESHEET
from logger_setup import setup_logger

class CropApp(KeyboardShortcutMixin, PersistentWindowMixin, QWidget, CropAppHandlers):

    def __init__(self, file_path=None):
        super().__init__()
        self.base_title = "Crop Tool"
        self.config_path = os.path.join('Config', 'crop_tool.conf')
        self.last_dir = os.path.expanduser('~')
        self.script_dir = os.path.dirname(os.path.abspath(__file__))
        self.base_dir = os.path.abspath(os.path.join(self.script_dir, '..'))
        self.bin_dir = os.path.join(self.base_dir, 'binaries')
        self.snapshot_path = os.path.join(tempfile.gettempdir(), "snapshot.png")
        self.media_processor = MediaProcessor(self.bin_dir)
        self.portrait_window = None
        self.ui = Ui_CropApp()
        self.ui.setupUi(self)
        self.connect_signals()
        self.timer = QTimer(self)
        self.timer.setInterval(100)
        self.timer.timeout.connect(self.update_ui)
        self.timer.start()
        self.set_style()
        self.setFocusPolicy(Qt.StrongFocus)
        self.setFocus()
        self.setup_persistence(
            config_path=self.config_path,
            settings_key='window_geometry',
            default_geo={'x': 83, 'y': 39, 'w': 1665, 'h': 922},
            title_info_provider=self.get_title_info
        )
        if file_path and os.path.exists(file_path):
            self.load_file(file_path)

def main():
    logger = setup_logger()
    logger.info("Application starting...")
    sys.dont_write_bytecode = True
    BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
    BIN_DIR = os.path.join(BASE_DIR, 'binaries')
    PLUGINS_DIR = os.path.join(BIN_DIR, 'plugins')
    os.environ['VLC_PLUGIN_PATH'] = PLUGINS_DIR
    if hasattr(os, 'add_dll_directory'):
        if os.path.isdir(BIN_DIR): os.add_dll_directory(BIN_DIR)
        if os.path.isdir(PLUGINS_DIR): os.add_dll_directory(PLUGINS_DIR)
    os.environ['PATH'] = f"{BIN_DIR}{os.pathsep}{PLUGINS_DIR}{os.pathsep}{os.environ.get('PATH', '')}"
    try:
        ctypes.WinDLL(os.path.join(BIN_DIR, 'libvlccore.dll'))
        ctypes.WinDLL(os.path.join(BIN_DIR, 'libvlc.dll'))
    except Exception as e:
        print(f"Error loading VLC DLLs: {e}")
    app = QApplication(sys.argv)
    app.setStyle('Fusion')
    file_path = sys.argv[1] if len(sys.argv) > 1 else None
    player = CropApp(file_path=file_path)
    player.show()
    sys.exit(app.exec_())
if __name__ == '__main__':
    main()

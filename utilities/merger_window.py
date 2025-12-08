import sys
import os
import subprocess
from pathlib import Path
from PyQt5.QtWidgets import QMainWindow, QFileDialog, QApplication, QPushButton, QListWidget, QLabel
from PyQt5.QtCore import pyqtSignal, Qt, QPropertyAnimation, QEasingCurve, QTimer
from PyQt5.QtGui import QIcon
from utilities.merger_ui import MergerUI
from utilities.merger_handlers import MergerHandlers
from utilities.merger_ffmpeg import FFMpegHandler
from utilities.merger_music import MusicHandler
from utilities.merger_utils import _get_logger, _load_conf, _save_conf
from ui.widgets.draggable_list_widget import DraggableListWidget

class VideoMergerWindow(QMainWindow):
    MAX_FILES = 10
    status_updated = pyqtSignal(str)
    return_to_main = pyqtSignal()

    def __init__(self, ffmpeg_path: str | None = None, parent: QMainWindow | None = None, vlc_instance=None, bin_dir: str = '', config_manager=None, base_dir: str = ''):
        super().__init__(parent)
        self.base_dir = base_dir
        self.ffmpeg = ffmpeg_path or "ffmpeg"
        self.vlc_instance = vlc_instance
        self.bin_dir = bin_dir
        self.config_manager = config_manager
        self.logger = _get_logger()
        self.ui_handler = MergerUI(self)
        self.event_handler = MergerHandlers(self)
        self.ffmpeg_handler = FFMpegHandler(self)
        self.music_handler = MusicHandler(self)
        self.init_ui()
        self.connect_signals()
        self.load_config()
        self.music_handler._scan_mp3_folder()
        self.event_handler.update_button_states()
        QTimer.singleShot(0, self.ui_handler._update_music_badge)
        self.logger.info("OPEN: Video Merger window created")

    def init_ui(self):
        self.setWindowTitle("Video Merger")
        self.resize(980, 560)
        self.setMinimumHeight(560)
        self.ui_handler.set_style()
        self.ui_handler.setup_ui()
        self.set_icon()
        
    def set_icon(self):
        try:
            _proj_root_path = Path(__file__).resolve().parents[1]
            preferred = str(_proj_root_path / "icons" / "Video_Icon_File.ico")
            fallback  = str(_proj_root_path / "icons" / "app_icon.ico")
            icon_path = preferred if os.path.exists(preferred) else fallback
            if os.path.exists(icon_path):
                self.setWindowIcon(QIcon(icon_path))
        except Exception as e:
            self.logger.error("Failed to set window icon: %s", e)

    def connect_signals(self):
        self.listw.itemSelectionChanged.connect(self.event_handler.update_button_states)
        self.status_updated.connect(self.handle_status_update)
        self.listw.model().rowsInserted.connect(self.event_handler.update_button_states)
        self.listw.model().rowsRemoved.connect(self.event_handler.update_button_states)
        self.listw.model().rowsMoved.connect(self.event_handler.update_button_states)
        self.listw.model().rowsMoved.connect(self.event_handler.on_rows_moved)
        self.add_music_checkbox.toggled.connect(self.music_handler._on_add_music_toggled)
        self.music_combo.currentIndexChanged.connect(self.music_handler._on_music_selected)
        self.music_volume_slider.valueChanged.connect(self.music_handler._on_music_volume_changed)
        self.listw.itemSelectionChanged.connect(self.event_handler.on_selection_changed)

    def load_config(self):
        self._cfg = _load_conf()
        self._last_dir = self._cfg.get("last_dir", "")
        try:
            g = self._cfg.get("geometry", {})
            if g:
                self.move(int(g.get("x", self.x())), int(g.get("y", self.y())))
                self.resize(int(g.get("w", self.width())), int(g.get("h", self.height())))
        except Exception:
            pass

    def save_config(self):
        try:
            g = {"x": self.x(), "y": self.y(), "w": self.width(), "h": self.height()}
            save_cfg = self.config_manager.config if self.config_manager else self._cfg
            save_cfg["geometry"]  = g
            save_cfg["last_dir"]  = self._last_dir or save_cfg.get("last_dir", "")
            save_cfg["last_out_dir"] = str(Path(self.ffmpeg_handler._output_path).parent) if self.ffmpeg_handler._output_path else save_cfg.get("last_out_dir", "")
            save_cfg["last_music_volume"] = self.music_handler._music_eff()
            if self.config_manager:
                self.config_manager.save_config(save_cfg)
            else:
                _save_conf(save_cfg)
        except Exception as err:
             self.logger.error("Error saving config in merger closeEvent: %s", err)

    def closeEvent(self, e):
        self.save_config()
        super().closeEvent(e)

    def handle_status_update(self, msg: str):
        self.status_label.setStyleSheet("color: #43b581; font-weight: normal;")
        self.status_label.setText(f"Processing merge... {msg}")

    def on_merge_clicked(self):
        self.event_handler.on_merge_clicked()

    def add_videos(self):
        self.event_handler.add_videos()

    def remove_selected(self):
        self.event_handler.remove_selected()

    def move_item(self, direction: int):
        self.event_handler.move_item(direction)

    def return_to_main_app(self):
        self.logger.info("ACTION: Return to Main App clicked.")
        try:
            app_py_path = os.path.join(self.base_dir, 'app.py')
            if not os.path.exists(app_py_path):
                self.logger.critical(f"ERROR: Main app script not found at {app_py_path}")
                self.close()
                return
            command = [sys.executable, app_py_path]
            subprocess.Popen(command, cwd=self.base_dir)
            self.close()
        except Exception as e:
            self.logger.critical(f"ERROR: Failed to launch Main App. Error: {e}")
            self.close()

    def create_draggable_list_widget(self):
        listw = DraggableListWidget()
        listw.setAlternatingRowColors(False)
        listw.setSpacing(6)
        listw.setSelectionMode(QListWidget.SingleSelection)
        listw.setUniformItemSizes(False)
        return listw

    def set_ui_busy(self, is_busy: bool):
        if is_busy:
            self.setWindowTitle("Video Merger (Processing...)")
            self.btn_back.setDisabled(True)
            self.listw.setDisabled(True)
            self.btn_up.setDisabled(True)
            self.btn_down.setDisabled(True)
        else:
            self.setWindowTitle("Video Merger")
            self.btn_back.setDisabled(False)
            self.listw.setDisabled(False)
        self.event_handler.update_button_states()

    def open_save_dialog(self, default_path):
        return QFileDialog.getSaveFileName(
            self, "Save merged video as…",
            default_path,
            "MP4 (*.mp4);;MOV (*.mov);;MKV (*.mkv);;All Files (*)"
        )

    def show_success_dialog(self, output_path):
        self.event_handler.show_success_dialog(output_path)
    
    def make_item_widget(self, path):
        return self.event_handler.make_item_widget(path)

    def can_anim(self, row, new_row):
        if row == new_row or not (0 <= row < self.listw.count()) or not (0 <= new_row < self.listw.count()):
            return False
        if getattr(self, "_animating", False):
            return False
        if not self.listw.itemWidget(self.listw.item(row)) or not self.listw.itemWidget(self.listw.item(new_row)):
            return False
        return True
    
    def start_swap_animation(self, row, new_row):
        try:
            v = self.listw.viewport()
            it1, it2 = self.listw.item(row), self.listw.item(new_row)
            w1, w2 = self.listw.itemWidget(it1), self.listw.itemWidget(it2)
            r1 = self.listw.visualItemRect(it1)
            r2 = self.listw.visualItemRect(it2)
            if r1.isNull() or r2.isNull():
                return False
            pm1 = w1.grab()
            pm2 = w2.grab()
            from PyQt5.QtWidgets import QLabel
            ghost1 = QLabel(v); ghost1.setPixmap(pm1); ghost1.setAttribute(Qt.WA_TransparentForMouseEvents, True)
            ghost2 = QLabel(v); ghost2.setPixmap(pm2); ghost2.setAttribute(Qt.WA_TransparentForMouseEvents, True)
            ghost1.move(r1.topLeft()); ghost1.show()
            ghost2.move(r2.topLeft()); ghost2.show()
            w1.setVisible(False); w2.setVisible(False)
            a1 = QPropertyAnimation(ghost1, b"pos", self); a1.setDuration(140)
            a2 = QPropertyAnimation(ghost2, b"pos", self); a2.setDuration(140)
            a1.setStartValue(r1.topLeft()); a1.setEndValue(r2.topLeft()); a1.setEasingCurve(QEasingCurve.InOutQuad)
            a2.setStartValue(r2.topLeft()); a2.setEndValue(r1.topLeft()); a2.setEasingCurve(QEasingCurve.InOutQuad)
            self._animating = True
            def _finish():
                try:
                    self.perform_swap(row, new_row)
                finally:
                    try:
                        w1.setVisible(True); w2.setVisible(True)
                        ghost1.deleteLater(); ghost2.deleteLater()
                    except Exception:
                        pass
                    self._animating = False
            a2.finished.connect(_finish)
            a1.start(); a2.start()
            return True
        except Exception:
            return False

    def perform_swap(self, row, new_row):
        i1, i2 = self.listw.item(row), self.listw.item(new_row)
        if not i1 or not i2:
            return
        p1, p2 = i1.data(Qt.UserRole), i2.data(Qt.UserRole)
        i1.setData(Qt.UserRole, p2); i2.setData(Qt.UserRole, p1)
        i1.setToolTip(p2);           i2.setToolTip(p1)
        w1 = self.listw.itemWidget(i1)
        if w1:
            lbl = w1.findChild(QLabel, "fileLabel") or w1.findChild(QLabel)
            if lbl: lbl.setText(os.path.basename(p2))
            btn = w1.findChild(QPushButton, "playButton")
            if btn: btn.setProperty("path", p2)
        w2 = self.listw.itemWidget(i2)
        if w2:
            lbl = w2.findChild(QLabel, "fileLabel") or w2.findChild(QLabel)
            if lbl: lbl.setText(os.path.basename(p1))
            btn = w2.findChild(QPushButton, "playButton")
            if btn: btn.setProperty("path", p1)
    
        self.listw.setCurrentRow(new_row)
        self.listw.viewport().update()

if __name__ == '__main__':
    app = QApplication(sys.argv)
    try:
        _root = Path(__file__).resolve().parents[1]
        _bin_dir = _root / 'binaries'
        _ffmpeg = _bin_dir / 'ffmpeg.exe'
        main_window = VideoMergerWindow(
            ffmpeg_path=str(_ffmpeg), 
            bin_dir=str(_bin_dir),
            base_dir=str(_root)
        )
        main_window.show()
        sys.exit(app.exec_())
    except Exception as e:
        print(f"Failed to launch standalone: {e}")
from ui.widgets.trimmed_slider import TrimmedSlider
import json
import logging
import os
import subprocess, tempfile, os, sys
import sys
import tempfile
import time
from pathlib import Path

if __name__ == "__main__":
    try:
        _proj_root_path = Path(__file__).resolve().parents[2]
        if str(_proj_root_path) not in sys.path:
            sys.path.insert(0, str(_proj_root_path))
            print(f"DEBUG [Standalone]: Added project root '{_proj_root_path}' to sys.path")
    except Exception as _path_err:
        print(f"ERROR [Standalone]: Failed to modify sys.path - {_path_err}", file=sys.stderr)
from ui.widgets.music_offset_dialog import MusicOffsetDialog
from PyQt5.QtCore import QProcess, Qt, QTimer, pyqtSignal, QEvent, QUrl, QPoint, QEasingCurve, QPropertyAnimation
from PyQt5.QtGui import QColor, QFontMetrics, QIcon, QPixmap, QDesktopServices
from PyQt5.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QDoubleSpinBox, QFileDialog,
    QGridLayout, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QMainWindow,
    QMessageBox, QPushButton, QSlider, QStyle, QStyleOptionSlider,
    QVBoxLayout, QWidget, QSizePolicy, QLayout
)

def _proj_root() -> Path:
    return Path(__file__).resolve().parents[2]

def _conf_path() -> Path:
    return _proj_root() / "ui" / "Video.conf"

def _human(n_bytes: int) -> str:
    units = ["B","KB","MB","GB","TB"]
    s = 0
    n = float(n_bytes)
    while n >= 1024.0 and s < len(units)-1:
        n /= 1024.0; s += 1
    return f"{n:.2f} {units[s]}"

def _get_logger():
    import logging
    logger = logging.getLogger("VideoMerger")
    if logger.handlers:
        return logger
    try:
        from logger import get_logger
        return get_logger("VideoMerger")
    except Exception:
        pass
    try:
        log_dir = _proj_root() / "logs"
        log_dir.mkdir(exist_ok=True)
        import logging
        logger.setLevel(logging.INFO)
        log_path = log_dir / "Fortnite-Video-Converter.log"
        fh = logging.FileHandler(str(log_path)) 
        fh.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
        logger.addHandler(fh)
    except Exception:
        pass
    return logger

def _load_conf() -> dict:
    p = _conf_path()
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}

def _save_conf(cfg: dict) -> None:
    p = _conf_path()
    try:
        p.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    except Exception:
        pass

try:
    import vlc as _vlc_mod
except Exception:
    _vlc_mod = None

class VideoMergerWindow(QMainWindow):
    ...
    MAX_FILES = 10
    status_updated = pyqtSignal(str)
    return_to_main = pyqtSignal()

    def _can_anim(self, row, new_row):
        if row == new_row or not (0 <= row < self.listw.count()) or not (0 <= new_row < self.listw.count()):
            return False
        if getattr(self, "_animating", False):
            return False
        if not self.listw.itemWidget(self.listw.item(row)) or not self.listw.itemWidget(self.listw.item(new_row)):
            return False
        return True
    
    def _start_swap_animation(self, row, new_row):
        # Create two lightweight overlays (pixmap snapshots) and slide them
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
            self._anim_ghosts = (ghost1, ghost2)
            self._anim_pair = (w1, w2)
            def _finish():
                try:
                    self._perform_swap(row, new_row)
                finally:
                    try:
                        w1.setVisible(True); w2.setVisible(True)
                        ghost1.deleteLater(); ghost2.deleteLater()
                    except Exception:
                        pass
                    self._animating = False
                    self._anim_ghosts = None
                    self._anim_pair = None
            a2.finished.connect(_finish)
            a1.start(); a2.start()
            self._anim_anims = (a1, a2)
            return True
        except Exception:
            return False
    
    def _perform_swap(self, row, new_row):
        """Swap item metadata + refresh text/preview path on existing row widgets (no reparenting)."""
        i1, i2 = self.listw.item(row), self.listw.item(new_row)
        if not i1 or not i2:
            return
        p1, p2 = i1.data(Qt.UserRole), i2.data(Qt.UserRole)
        i1.setData(Qt.UserRole, p2); i2.setData(Qt.UserRole, p1)
        i1.setToolTip(p2);           i2.setToolTip(p1)
    
        import os
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
    


    def _preview_file(self, path: str):
        try:
            from PyQt5.QtCore import QUrl
            from PyQt5.QtGui import QDesktopServices
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))
        except Exception as e:
            try:
                self.logger.error("Preview failed: %s", e)
            except Exception:
                pass

    def _preview_clicked(self):
        try:
            btn = self.sender()
            p = btn.property("path")
            if p:
                self._preview_file(str(p))
        except Exception:
            pass

    def _make_item_widget(self, path: str):
        from PyQt5.QtWidgets import QWidget, QHBoxLayout, QLabel, QPushButton
        import os
        w = QWidget()
        w.setStyleSheet("background-color:#4a667a; border-radius:6px;")
        h = QHBoxLayout(w)
        h.setContentsMargins(4, 2, 4, 2)
        h.setSpacing(2)
        lbl = QLabel(os.path.basename(path))
        lbl.setObjectName("fileLabel")
        lbl.setStyleSheet("font-size:15px;")
        lbl.setToolTip(path)
        lbl.setWordWrap(False)
        lbl.setMinimumWidth(120)
        lbl.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        lbl.setFixedHeight(15)
        btn = QPushButton("▶  Preview  ▶")
        btn.setObjectName("playButton")
        btn.setFixedSize(120, 52)
        btn.setStyleSheet("background-color:#2c687e; color:white; border-radius:6px; font-size:12px")
        btn.setProperty("path", path)
        btn.clicked.connect(self._preview_clicked)
        h.addWidget(lbl, 1)
        h.addWidget(btn, 0, Qt.AlignRight | Qt.AlignVCenter)
        w.setFixedHeight(46) # Increased by 15% (40 * 1.15 = 46)
        return w
            
    def _ensure_processing_overlay(self):
        if getattr(self, "_overlay", None):
            return
        from PyQt5.QtWidgets import QWidget, QPlainTextEdit
        self._overlay = QWidget(self)
        self._overlay.setWindowFlags(Qt.SubWindow | Qt.FramelessWindowHint)
        self._overlay.setAttribute(Qt.WA_NoSystemBackground, True)
        self._overlay.setAttribute(Qt.WA_TransparentForMouseEvents, False)
        self._overlay.setStyleSheet("background: rgba(0,0,0,165);")
        self._overlay.hide()
    
    def _show_processing_overlay(self):
        self._ensure_processing_overlay()
        self._overlay.setGeometry(self.rect())
        self._overlay.show()
        self._overlay.raise_()
        if not getattr(self, "_pulse_timer", None):
            self._pulse_timer = QTimer(self)
            self._pulse_timer.setInterval(100)
            self._pulse_timer.timeout.connect(self._pulse_merge_btn)
        self._pulse_phase = 0
        self._pulse_timer.start()
    
    def _hide_processing_overlay(self):
        try:
            if getattr(self, "_pulse_timer", None):
                self._pulse_timer.stop()
        except Exception:
            pass
        try:
            if getattr(self, "_overlay", None):
                self._overlay.hide()
        except Exception:
            pass
        try:
            self.btn_merge.setText("Merge Videos")
            self.btn_merge.setStyleSheet(self._merge_btn_base_css)
        except Exception:
            pass
    
    def _pulse_merge_btn(self):
        try:
            self._pulse_phase = (getattr(self, "_pulse_phase", 0) + 1) % 20
            t = self._pulse_phase / 20.0
            import math
            k = (math.sin(4 * math.pi * t) + 1) / 2
            g1 = (72, 235, 90)
            g2 = (10,  80, 16)
            r = int(g1[0] * k + g2[0] * (1 - k))
            g = int(g1[1] * k + g2[1] * (1 - k))
            b = int(g1[2] * k + g2[2] * (1 - k))
            self.btn_merge.setStyleSheet(
                f"background-color: rgb({r},{g},{b});"
                "color: black;"
                "font-weight: bold;"
                "font-size: 16px;"
                "border-radius: 15px;"
                "padding: 6px 20px;"
            )
        except Exception:
            pass
    
    def _on_merge_clicked(self):
        try:
            self.btn_merge.setEnabled(False)
            self.btn_back.setEnabled(False)
            self.listw.setEnabled(False)
            self._show_processing_overlay()
            self.btn_merge.setText("Processing…")
        except Exception:
            pass
        self.merge_now()

    def __init__(self, ffmpeg_path: str | None = None, parent: QWidget | None = None, vlc_instance=None, bin_dir: str = '', config_manager=None):
        super().__init__(parent)
        self.config_manager = config_manager
        self.vlc_instance = vlc_instance
        self.bin_dir = bin_dir
        self.logger = _get_logger()
        self.logger.info("OPEN: Video Merger window created")
        self.setWindowTitle("Video Merger")
        try:
            preferred = str(_proj_root() / "icons" / "Video_Icon_File.ico")
            fallback  = str(_proj_root() / "icons" / "app_icon.ico")
            icon_path = preferred if os.path.exists(preferred) else fallback
            if os.path.exists(icon_path):
                self.setWindowIcon(QIcon(icon_path))
                self.logger.info("Set window icon from: %s", icon_path)
            else:
                self.logger.warning("Icon file not found at: %s", icon_path)
            try:
                import ctypes
                from ctypes import wintypes
                hwnd = int(self.winId())
                # Load the .ico (try ICO, then PNG as fallback)
                hicon = ctypes.windll.user32.LoadImageW(
                    0, icon_path, 1, 0, 0, 0x00000010
                )
                if not hicon:
                    png_fallback = str((_proj_root() / "icons" / "app_icon.png"))
                    if os.path.exists(png_fallback):
                        pm = QIcon(png_fallback).pixmap(256, 256)
                        hicon = pm.toImage().cacheKey()
                if hicon:
                    WM_SETICON = 0x0080
                    ICON_SMALL, ICON_BIG = 0, 1
                    ctypes.windll.user32.SendMessageW(hwnd, WM_SETICON, ICON_BIG,  hicon)
                    ctypes.windll.user32.SendMessageW(hwnd, WM_SETICON, ICON_SMALL, hicon)
            except Exception as e:
                self.logger.warning("WM_SETICON failed: %s", e)
        except Exception as e:
            self.logger.error("Failed to set window icon: %s", e)
        self.setWindowFlag(Qt.Tool, False)
        self.setWindowFlag(Qt.SubWindow, False)
        self.setWindowFlag(Qt.Window, True)
        self.resize(980, 560)
        self.setMinimumHeight(560)
        self.ffmpeg = ffmpeg_path or "ffmpeg"
        self.process: QProcess | None = None
        self._temp_dir: tempfile.TemporaryDirectory | None = None
        self._output_path: str = ""
        self._cmd: list[str] = []
        self._cfg = _load_conf()
        self._last_dir = self._cfg.get("last_dir", "")
        self._music_files = []
        self._setup_style()
        self._setup_ui()
        try:
            g = self._cfg.get("geometry", {})
            if g:
                self.move(int(g.get("x", self.x())), int(g.get("y", self.y())))
                self.resize(int(g.get("w", self.width())), int(g.get("h", self.height())))
                self.logger.info("RESTORE: Window geometry x=%s y=%s w=%s h=%s", g.get("x"), g.get("y"), g.get("w"), g.get("h"))
        except Exception:
            pass
        self._update_button_states()
        self.listw.itemSelectionChanged.connect(self._update_button_states)
        self.status_updated.connect(self._handle_status_update)
        self.listw.model().rowsInserted.connect(self._update_button_states)
        self.listw.model().rowsRemoved.connect(self._update_button_states)
        self.listw.model().rowsMoved.connect(self._update_button_states)
        self.listw.model().rowsMoved.connect(self._on_rows_moved)
        self._scan_mp3_folder()
        self._populate_music_combo()
        self.add_music_checkbox.toggled.connect(self._on_add_music_toggled)
        self.music_combo.currentIndexChanged.connect(self._on_music_selected)
        self.music_volume_slider.valueChanged.connect(self._on_music_volume_changed)
        QTimer.singleShot(0, self._update_music_badge)

    def closeEvent(self, e):
        try:
            g = {"x": self.x(), "y": self.y(), "w": self.width(), "h": self.height()}
            save_cfg = self.config_manager.config if self.config_manager else self._cfg
            save_cfg["geometry"]  = g
            save_cfg["last_dir"]  = self._last_dir or save_cfg.get("last_dir", "")
            save_cfg["last_out_dir"] = str(Path(self._output_path).parent) if self._output_path else save_cfg.get("last_out_dir", "")
            save_cfg["last_music_volume"] = self._music_eff()
            if self.config_manager:
                self.config_manager.save_config(save_cfg)
            else:
                _save_conf(save_cfg)
            self.logger.info("SAVE: Geometry, last input dir, and last output dir saved")
        except Exception as err:
             self.logger.error("Error saving config in merger closeEvent: %s", err)
        return super().closeEvent(e)
    
    def _handle_status_update(self, msg: str):
        """Updates the status label with real-time feedback."""
        self.status_label.setStyleSheet("color: #43b581; font-weight: normal;")
        self.status_label.setText(f"Processing merge... {msg}")

    def _process_ffmpeg_output(self):
        """Extracts and displays the current progress from FFmpeg's stderr output."""
        try:
            output = self.process.readAllStandardError().data().decode().strip()
            last_line = output.split('\r')[-1].split('\n')[-1].strip()
            if last_line and (last_line.startswith("frame=") or last_line.startswith("size=")):
                self.status_updated.emit(last_line)
            self.logger.debug("FFMPEG_OUTPUT: %s", output)
        except Exception:
            pass

    def _setup_style(self):
        """Applies a dark theme stylesheet similar to the main app."""
        self.setStyleSheet("""
            QMainWindow, QWidget {
                background-color: #2c3e50; /* Main dark background */
                color: #ecf0f1; /* Light text */
                font-family: "Helvetica Neue", Arial, sans-serif;
                font-size: 13px;
            }
            QLabel#titleLabel {
                font-size: 18px;
                font-weight: bold;
                color: #3498db; /* Blue title color */
                padding-bottom: 10px; /* Add some space below title */
            }
            QPushButton {
                background-color: #3498db; /* Blue buttons */
                color: #ffffff;
                border: none;
                padding: 8px 16px; /* Adjusted padding */
                border-radius: 6px;
                font-weight: bold;
                min-height: 20px; /* Ensure minimum height */
            }
            QPushButton:hover {
                background-color: #2980b9; /* Darker blue on hover */
            }
            QPushButton[class="move-btn"] {
                 background-color: #2b7089;
                 color: white;
            }
            QPushButton[class="move-btn"]:hover {
                 background-color: #3b8099;
            }
            QPushButton:disabled {
                background-color: #566573; /* Greyed out when disabled */
                color: #aeb6bf;
            }
            /* Style for Add button (neutral) */
            QPushButton#aux-btn {
                 background-color: #2b7089;
            }
            QPushButton#aux-btn:hover {
                 background-color: #3b8099;
            }
            /* Light red “danger” buttons (Remove / Clear) */
            QPushButton#danger-btn {
                 background-color: #d96a6a;  /* light red fill */
                 color: #ffffff;
            }
            QPushButton#danger-btn:hover {
                 background-color: #c05252;  /* a bit darker on hover */
            }
            /* Specific style for the Merge button */
            QPushButton#mergeButton {
                background-color: #2ecc71; /* Green merge button */
                color: #1e242d; /* Dark text on green */
                font-weight: bold;
                padding: 10px 25px; /* Slightly larger padding */
                border-radius: 8px;
            }
            QPushButton#mergeButton:hover {
                background-color: #48e68e; /* Lighter green on hover */
            }
            QPushButton#mergeButton:disabled {
                 background-color: #566573;
                 color: #aeb6bf;
            }
            /* Style for the Return button */
            QPushButton#returnButton {
                background-color: #bfa624; /* Yellow like main app merge */
                color: black;
                font-weight: 600;
                padding: 6px 12px;
                border-radius: 6px;
                min-height: 35px; /* Match height of other row buttons */
            }
            QPushButton#returnButton:hover {
                 background-color: #dcbd2f; /* Lighter yellow */
            }
            QPushButton#returnButton:disabled {
                 background-color: #566573;
                 color: #aeb6bf;
            }
            QListWidget {
                background-color: #34495e;
                border: 1px solid #4a667a;
                border-radius: 8px;
                padding: 8px;
                outline: 0;
            }
            QListWidget::item {
                padding: 0;               /* we paint the row ourselves */
                margin: 2px 0;            /* tiny vertical gap only */
                border: 0;
                background: transparent;  /* no double background behind our widget */
                color: #ecf0f1;
            }
            QListWidget::item:selected {
                background: rgba(52,152,219,0.25); /* subtle overlay */
                color: #ecf0f1;
            }
            QCheckBox { spacing: 8px; }
            QCheckBox::indicator { width: 16px; height: 16px; }
            QComboBox {
                background-color: #4a667a; border: 1px solid #3498db; border-radius: 5px;
                padding: 4px 8px; min-height: 24px; color: #ecf0f1;
            }
            QComboBox::drop-down { border: none; }
            QComboBox::down-arrow { image: url(none); }
            QComboBox QAbstractItemView {
                background-color: #34495e; border: 1px solid #4a667a; selection-background-color: #3498db;
                color: #ecf0f1;
            }
            QDoubleSpinBox {
                background-color: #4a667a; border: 1px solid #3498db; border-radius: 5px;
                padding: 4px 6px; min-height: 24px; color: #ecf0f1;
            }
            QSlider::groove:vertical {
                border: 1px solid #4a4a4a; background: #333; width: 16px; border-radius: 6px;
            }
            QSlider::handle:vertical {
                 background: #7289da; border: 1px solid #5c5c5c;
                 height: 18px; margin: 0 -2px; border-radius: 6px;
            }
            QLabel { /* Default Label */
                 padding: 0; margin: 0; /* Remove default padding for finer control */
            }
            #musicVolumeBadge { /* Ensure badge style is applied */
                 color: white; background: rgba(0,0,0,160); padding: 2px 6px;
                 border-radius: 6px; font-weight: bold;
            }
        """)

    def _setup_ui(self):
        """Builds the layout and widgets."""
        root = QWidget(self)
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(20, 16, 20, 16)
        outer.setSpacing(16)
        title = QLabel('Sort the Videos in the Correct Desired Order. Hit the "Merge Videos" Button When Done.')
        title.setObjectName("titleLabel")
        title.setAlignment(Qt.AlignHCenter)
        outer.addWidget(title)
        list_container = QHBoxLayout()
        outer.addLayout(list_container)
        self.listw = QListWidget()
        self.listw.setAlternatingRowColors(False)
        self.listw.setSpacing(6)
        self.listw.setDragDropMode(QListWidget.InternalMove)
        self.listw.setDefaultDropAction(Qt.MoveAction)
        self.listw.setSelectionMode(QListWidget.SingleSelection) 
        self.listw.setUniformItemSizes(False)
        list_container.addWidget(self.listw, 1)
        move_btns_col = QVBoxLayout()
        move_btns_col.setContentsMargins(0, 0, 0, 0)
        move_btns_col.setSpacing(20)
        self.btn_up = QPushButton("▲ Up ▲")
        self.btn_up.setToolTip("Move selected video up")
        self.btn_up.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.btn_up.setMinimumWidth(160)
        self.btn_up.setMaximumWidth(160)
        self.btn_up.setMinimumHeight(50)
        self.btn_up.setMaximumHeight(50)
        self.btn_up.setProperty("class", "move-btn") 
        self.btn_up.setStyleSheet("min-height:64px;") # Keep min-height here
        self.btn_up.clicked.connect(lambda: self.move_item(-1))
        self.btn_down = QPushButton("▼ Down ▼")
        self.btn_down.setToolTip("Move selected video down")
        self.btn_down.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.btn_down.setMinimumWidth(160)
        self.btn_down.setMaximumWidth(160)
        self.btn_down.setMinimumHeight(50)
        self.btn_down.setMaximumHeight(50)
        self.btn_down.setProperty("class", "move-btn")
        self.btn_down.setStyleSheet("min-height:64px;")
        self.btn_down.clicked.connect(lambda: self.move_item(1))
        self.btn_down.clicked.connect(lambda: self.move_item(1))
        move_btns_col.addStretch(1)
        move_btns_col.addWidget(self.btn_up)
        move_btns_col.addWidget(self.btn_down)
        move_btns_col.addStretch(1)
        list_container.addLayout(move_btns_col)
        list_container.setStretch(0, 1)
        list_container.setStretch(1, 0)
        band = QHBoxLayout()
        band.setContentsMargins(0, 0, 0, 0)
        band.setSpacing(0)
        music_layout = QHBoxLayout()
        music_layout.setSpacing(15)
        self.add_music_checkbox = QCheckBox("Add Background Music")
        self.add_music_checkbox.setToolTip("Toggle background MP3 mixing from the ./mp3 folder.")
        self.add_music_checkbox.setChecked(False)
        music_layout.addWidget(self.add_music_checkbox)
        self.music_combo = QComboBox()
        try:
            self.music_combo.setElideMode(Qt.ElideMiddle)
        except Exception:
            pass
        self.music_combo.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self.music_combo.setMinimumWidth(400)
        self.music_combo.setMaximumWidth(400)
        self.music_combo.setMinimumContentsLength(24)
        self.music_combo.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.music_combo.setVisible(False)
        music_layout.addWidget(self.music_combo)
        self.music_offset_input = QDoubleSpinBox()
        self.music_offset_input.setPrefix("Music Start (s): ")
        self.music_offset_input.setMinimumWidth(180)
        self.music_offset_input.setMaximumWidth(180)
        self.music_offset_input.setDecimals(2)
        self.music_offset_input.setSingleStep(0.5)
        self.music_offset_input.setRange(0.0, 0.0)
        self.music_offset_input.setValue(0.0)
        self.music_offset_input.setVisible(False)
        music_layout.addWidget(self.music_offset_input)
        self.music_volume_slider = QSlider(Qt.Vertical, self)
        self.music_volume_slider.setObjectName("musicVolumeSlider")
        self.music_volume_slider.setRange(0, 100)
        self.music_volume_slider.setTickInterval(1)
        self.music_volume_slider.setTracking(True)
        self.music_volume_slider.setVisible(False)
        self.music_volume_slider.setFocusPolicy(Qt.NoFocus)
        self.music_volume_slider.setMinimumHeight(150)
        self.music_volume_slider.setInvertedAppearance(True)
        eff_default = int(35)
        self.music_volume_slider.setValue(eff_default)
        _knob = "#7289da"
        self.music_volume_slider.setStyleSheet(f"""
            QSlider#musicVolumeSlider {{
            padding: 0px; border: 0; background: transparent;
            }}
            QSlider#musicVolumeSlider::groove:vertical {{
            margin: 0px; border: 1px solid #3498db;
            background: qlineargradient(x1:0, y1:1, x2:0, y2:0,
                stop:0   #e64c4c,
                stop:0.25 #f7a8a8,
                stop:0.50 #f2f2f2,
                stop:0.75 #7bcf43,
                stop:1   #009b00);
            width: 22px;
            border-radius: 6px;
            }}
            QSlider#musicVolumeSlider::handle:vertical {{
            background: {_knob};
            border: 1px solid #5c5c5c;
            width: 30px; height: 30px;
            margin: -2px 0;
            border-radius: 6px;
            }}
            QSlider#musicVolumeSlider::sub-page:vertical,
            QSlider#musicVolumeSlider::add-page:vertical {{
            background: transparent;
            }}
        """)
        self.music_volume_label = QLabel(f"{eff_default}%")
        self.music_volume_label.setAlignment(Qt.AlignHCenter)
        self.music_volume_label.setVisible(False)
        self.music_volume_badge = QLabel(f"{eff_default}%", self)
        self.music_volume_badge.setObjectName("musicVolumeBadge")
        self.music_volume_badge.setStyleSheet(
            "color: white; background: rgba(0,0,0,160); padding: 2px 6px; "
            "border-radius: 6px; font-weight: bold;"
        )
        self.music_volume_badge.hide()
        music_slider_box = QVBoxLayout()
        music_slider_box.setSpacing(2)
        music_slider_box.addWidget(self.music_volume_slider, 0, Qt.AlignHCenter)
        music_slider_box.addWidget(self.music_volume_label, 0, Qt.AlignHCenter)
        music_layout.addLayout(music_slider_box)
        left_wrap = QWidget(); left_wrap.setLayout(music_layout)
        center = QHBoxLayout()
        center.setContentsMargins(0, 0, 0, 0)
        center.setSpacing(14)
        self.btn_add = QPushButton("Add Videos")
        self.btn_add.setFixedSize(185, 40)
        self.btn_add.setObjectName("aux-btn")
        self.btn_add.clicked.connect(self.add_videos)
        self.btn_remove = QPushButton("Remove Selected Video")
        self.btn_remove.setFixedSize(185, 40)
        self.btn_remove.setObjectName("danger-btn")
        self.btn_remove.clicked.connect(self.remove_selected)
        self.btn_clear = QPushButton("Remove All Videos")
        self.btn_clear.setFixedSize(160, 40)
        self.btn_clear.setObjectName("danger-btn")
        self.btn_clear.clicked.connect(self.listw.clear)
        center.addWidget(self.btn_add)
        center.addWidget(self.btn_remove)
        center.addWidget(self.btn_clear)
        center_wrap = QWidget(); center_wrap.setLayout(center)
        band.addStretch(1)
        band.addWidget(center_wrap, 0)
        band.addSpacing(8)
        band.addWidget(left_wrap, 0)
        band.addStretch(1)
        band_wrap = QWidget(); band_wrap.setLayout(band)
        band_wrap.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        outer.addWidget(band_wrap)
        self.status_label = QLabel("Ready. Add 2 to 10 videos to begin.")
        self.status_label.setStyleSheet("color: #7289da; font-weight: bold;")
        outer.addWidget(self.status_label)
        self.btn_back = QPushButton("Return to Main App")
        self.btn_back.setFixedSize(185, 40)
        self.btn_back.setObjectName("returnButton")
        self.btn_back.clicked.connect(self.return_to_main_app)
        merge_row = QHBoxLayout()
        merge_wrap = QWidget()
        merge_wrap.setLayout(merge_row)
        merge_wrap.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        outer.addWidget(merge_wrap)
        merge_row.addStretch(1)
        self.btn_merge = QPushButton("Merge Videos")
        self.btn_merge.setObjectName("mergeButton")
        self.btn_merge.setFixedSize(260, 48)
        self._merge_btn_base_css = (
            "background-color: #59A06D;"
            "color: black;"
            "font-weight: bold;"
            "font-size: 16px;"
            "border-radius: 15px;"
            "padding: 6px 20px;"
        )
        self.btn_merge.setStyleSheet(self._merge_btn_base_css)
        self.btn_merge.clicked.connect(self._on_merge_clicked)
        merge_row.addWidget(self.btn_merge)
        merge_row.addStretch(1)
        merge_row.addWidget(self.btn_back)
        outer.setStretch(0, 0)
        outer.setStretch(1, 1)
        outer.setStretch(2, 0)
        outer.setStretch(3, 0)
        outer.setStretch(4, 0)
        outer.setStretch(5, 0)

    def _update_button_states(self):
        """Enable/disable buttons based on list state and processing state."""
        n = self.listw.count()
        is_processing = self.process is not None
        selected_items = self.listw.selectedItems()
        is_single_selection = len(selected_items) == 1
        self.add_music_checkbox.setEnabled(not is_processing)
        if not is_processing:
            self._on_add_music_toggled(self.add_music_checkbox.isChecked())
        else:
            self.music_combo.setEnabled(False)
            self.music_offset_input.setEnabled(False)
            self.music_volume_slider.setEnabled(False)
        self.btn_merge.setEnabled(n >= 2 and not is_processing)
        self.btn_remove.setEnabled(bool(selected_items) and not is_processing)
        self.btn_clear.setEnabled(n > 0 and not is_processing)
        self.btn_add.setEnabled(not is_processing and n < self.MAX_FILES)
        if is_single_selection and not is_processing:
            current_row = self.listw.row(selected_items[0])
            self.btn_up.setEnabled(current_row > 0)
            self.btn_down.setEnabled(current_row < n - 1)
        else:
            self.btn_up.setEnabled(False)
            self.btn_down.setEnabled(False)
        if is_processing:
            self.status_label.setText("Processing merge... Please wait.")
        elif n == 0:
            self.status_label.setText("Ready. Add 2 to 10 videos to begin.")
        elif n < 2:
            self.status_label.setText(f"Waiting for more videos. Currently {n}/10.")
        else:
            self.status_label.setText(f"Ready to merge {n} videos. Order is set.")
            
    def _on_rows_moved(self, parent, start, end, destination, row):
        """
        Re-applies the sizeHint to fix item height after drag-and-drop move.
        This iterates through all rows that were moved in case of multiple selections,
        and uses the destination row index for the update.
        """
        try:
            # The row argument is the *first* row in the destination where insertion began.
            # We iterate through the block of items that was moved.
            num_moved = end - start + 1
            for i in range(num_moved):
                item_to_update = self.listw.item(row + i)
                if item_to_update is None:
                    continue
                widget = self.listw.itemWidget(item_to_update)
                if widget is None:
                    continue
                # Force the item to re-read the height from the widget's sizeHint
                item_to_update.setSizeHint(widget.sizeHint())
            self.listw.viewport().update() # Force a visual refresh on the viewport
        except Exception as e:
            self.logger.error("LISTW: Failed to re-apply sizeHint after move: %s", e)
        
    def set_ui_busy(self, is_busy: bool):
        """Set the UI state when processing is active."""
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
        self._update_button_states()

    def add_videos(self):
        start_dir = self._last_dir if self._last_dir and Path(self._last_dir).exists() else ""
        files, _ = QFileDialog.getOpenFileNames(
            self, "Select videos to merge", start_dir,
            "Videos (*.mp4 *.mov *.mkv *.m4v *.ts *.avi *.webm);;All Files (*)"
        )
        if not files:
            return
        current = self.listw.count()
        room = max(0, self.MAX_FILES - current)
        if room <= 0:
            QMessageBox.warning(self, "Limit reached", f"Maximum {self.MAX_FILES} files already added.")
            return
        current_files = {self.listw.item(i).data(Qt.UserRole) for i in range(current)}
        new_files = [f for f in files if f not in current_files]
        if new_files:
            try:
                self._last_dir = str(Path(new_files[0]).parent)
            except Exception:
                pass
        for f in new_files[:room]:
            try:
                sz = Path(f).stat().st_size
                self.logger.info("ADD: %s | size=%s | dir=%s", f, _human(sz), Path(f).parent)
            except Exception:
                pass
            item = QListWidgetItem()
            item.setToolTip(f)
            item.setData(Qt.UserRole, f)
            w = self._make_item_widget(f)
            item.setSizeHint(w.sizeHint())
            self.listw.addItem(item)
            self.listw.setItemWidget(item, w)
            item.setSizeHint(w.sizeHint())
        if len(files) > len(new_files):
             QMessageBox.warning(self, "Duplicates", "Some selected files were already in the list and were ignored.")
        if len(new_files) > room:
            QMessageBox.information(self, "Limit", f"Only {room} unique file(s) were added (max {self.MAX_FILES} total).")

    def remove_selected(self):
        for it in self.listw.selectedItems():
            self.listw.takeItem(self.listw.row(it))

    def move_item(self, direction: int):
        """Animate then swap; fall back to instant swap if animation not possible."""
        sel = self.listw.selectedItems()
        if not sel:
            return
        row = self.listw.row(sel[0])
        new_row = row + direction
        if new_row < 0 or new_row >= self.listw.count():
            return
        if self._can_anim(row, new_row) and self._start_swap_animation(row, new_row):
            return
        self._perform_swap(row, new_row)
    
    def merge_now(self):
        n = self.listw.count()
        if n < 2:
            QMessageBox.information(self, "Need more videos", "Please add at least 2 videos to merge.")
            return
        last_out_dir = self._cfg.get("last_out_dir", self._last_dir or Path.home().as_posix())
        default_path = str(Path(last_out_dir) / "merged_video.mp4")
        out_path, _ = QFileDialog.getSaveFileName(
            self, "Save merged video as…", 
            default_path,
            "MP4 (*.mp4);;MOV (*.mov);;MKV (*.mkv);;All Files (*)"
        )
        if not out_path:
            return
        self._temp_dir = tempfile.TemporaryDirectory()
        concat_txt = Path(self._temp_dir.name, "concat_list.txt")
        with concat_txt.open("w", encoding="utf-8") as f:
            for i in range(n):
                it = self.listw.item(i)
                f.write(f"file '{it.data(Qt.UserRole).replace('\'', '\\\'')}'\n")
        self._output_path = out_path
        music_path, music_vol = self._get_selected_music()
        music_offset = self.music_offset_input.value()
        base_cmd = [self.ffmpeg, "-y", "-f", "concat", "-safe", "0", "-i", str(concat_txt)]
        if music_path:
            self.logger.info("MUSIC: Adding background music. Audio will be re-encoded.")
            base_cmd.extend(["-i", music_path])
            self._cmd = base_cmd + [
                "-filter_complex", f"[0:a]volume=1.0[a0]; [1:a]atrim=start={music_offset:.3f},volume={music_vol:.3f}[a1]; [a0][a1]amix=inputs=2:duration=first[a_out]",
                "-map", "0:v",
                "-map", "[a_out]",
                "-c:v", "copy",
                "-c:a", "aac", "-b:a", "192k",
                "-shortest",
                str(out_path)
            ]
        else:
            self.logger.info("MUSIC: No background music. Using fast stream copy.")
            self._cmd = base_cmd + [
                "-c", "copy",
                str(out_path)
            ]
        inputs = []
        total_in = 0
        for i in range(n):
            it = self.listw.item(i)
            f = it.data(Qt.UserRole)
            try:
                sz = Path(f).stat().st_size
                total_in += sz
                inputs.append({"path": f, "size": _human(sz)})
            except Exception:
                inputs.append({"path": f, "size": "?"})
        self.logger.info("MERGE_START: outputs='%s'", self._output_path)
        self.logger.info("MERGE_INPUTS: %s", inputs)
        self.logger.info("MERGE_CMD: %s", " ".join(self._cmd))
        self.logger.info("MERGE_TOTAL_INPUT_SIZE: %s", _human(total_in))
        self.process = QProcess(self)
        self.process.finished.connect(self._merge_finished)
        self.process.readyReadStandardError.connect(self._process_ffmpeg_output)
        self._merge_started_at = time.time()
        self.set_ui_busy(True)
        self.logger.info("MERGE_EXEC: %s", " ".join(self._cmd))
        self.process.start(self.ffmpeg, self._cmd[1:])

    def _merge_finished(self, exit_code, exit_status):
        self._hide_processing_overlay()
        try:
            self.btn_merge.setEnabled(True)
            self.btn_back.setEnabled(True)
            self.listw.setEnabled(True)
            self.btn_merge.setText("Merge Videos")
        except Exception:
            pass
        """Handle the result of the QProcess merge."""
        try:
            stdout = self.process.readAllStandardOutput().data().decode()
        except Exception:
            stdout = ""
        try:
            stderr = self.process.readAllStandardError().data().decode()
        except Exception:
            stderr = ""
        elapsed = None
        try:
            if hasattr(self, "_merge_started_at"):
                elapsed = max(0, time.time() - self._merge_started_at)
        except Exception:
            pass
        concat_txt_path = None
        if self._temp_dir and hasattr(self._temp_dir, 'name'):
            concat_txt_path = Path(self._temp_dir.name) / "concat_list.txt"
        if self._temp_dir:
            try:
                self._temp_dir.cleanup()
                self.logger.info("Cleaned up temporary directory: %s", self._temp_dir.name)
            except Exception as e:
                self.logger.error("Error cleaning up temporary directory: %s", e)
            finally:
                self._temp_dir = None 
        if concat_txt_path and concat_txt_path.exists():
            try:
                os.remove(concat_txt_path)
                self.logger.info("Removed temporary concat list: %s", concat_txt_path)
            except Exception as e:
                 self.logger.error("Error removing concat list %s: %s", concat_txt_path, e)
        self.set_ui_busy(False)
        self.process = None
        if exit_status == QProcess.CrashExit:
             QMessageBox.critical(self, "Merge Failed", "FFmpeg process crashed unexpectedly.")
             return
        if exit_code != 0:
            QMessageBox.critical(
                self, "Merge failed",
                "ffmpeg reported an error. This usually means inputs have mismatched codecs.\n"
                "Ensure all videos share the same codec, resolution, and audio format for lossless concatenation.\n\n"
                f"Output:\n{(stdout + stderr)[:4000]}"
            )
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("Done! Video Processed Successfully!")
        dialog.setModal(True)
        fm = QFontMetrics(dialog.font())
        btn_h = max(58, fm.height() * 2 + 18)   # fits two lines + padding
        dialog.resize(max(860, int(self.width() * 0.85)), 3 * btn_h + 160)
        layout = QVBoxLayout(dialog)
        layout.setSizeConstraint(QLayout.SetMinimumSize)  # grow to fit content
        label = QLabel(f"File saved to:\n{self._output_path}")
        layout.addWidget(label)
        grid = QGridLayout()
        grid.setHorizontalSpacing(40)
        grid.setVerticalSpacing(30)
        grid.setContentsMargins(30, 20, 30, 24)
        button_size = (220, btn_h)
        def _open_whatsapp():
            try:
                QDesktopServices.openUrl(QUrl("https://web.whatsapp.com"))
            except Exception as e:
                try:
                    self.logger.error("Failed to open WhatsApp Web: %s", e)
                except Exception:
                    pass

        whatsapp_button = QPushButton("✆   Share via Whatsapp   ✆")
        whatsapp_button.setFixedSize(*button_size)
        whatsapp_button.setStyleSheet("background-color: #328742; color: white;")
        whatsapp_button.clicked.connect(lambda: (_open_whatsapp(), dialog.accept(), QApplication.instance().quit()))

        open_folder_button = QPushButton("Open Output Folder")
        open_folder_button.setFixedSize(*button_size)
        open_folder_button.setStyleSheet("background-color: #6c5f9e; color: white;")
        open_folder_button.clicked.connect(lambda: (
            dialog.accept(),
            self._open_folder(os.path.dirname(self._output_path)),
            QApplication.instance().quit()
        ))
        new_file_button = QPushButton("📂   Upload a New File   📂")
        new_file_button.setFixedSize(*button_size)
        new_file_button.setStyleSheet("background-color: #6c5f9e; color: white;")
        new_file_button.clicked.connect(dialog.reject)
        done_button = QPushButton("Done")
        done_button.setFixedSize(*button_size)
        done_button.setStyleSheet("background-color: #821e1e; color: white; padding: 8px 16px;")
        done_button.clicked.connect(dialog.accept)
        finished_button = QPushButton("Close The App!\r\n(Exit)")
        finished_button.setFixedSize(*button_size)
        finished_button.setStyleSheet("background-color: #c90e0e; color: white; padding: 8px 16px;")
        finished_button.clicked.connect(lambda: (dialog.accept(), QApplication.instance().quit()))
        grid.addWidget(whatsapp_button,   0, 0, alignment=Qt.AlignCenter)
        grid.addWidget(open_folder_button,0, 1, alignment=Qt.AlignCenter)
        grid.addWidget(new_file_button,   0, 2, alignment=Qt.AlignCenter)
        grid.addWidget(done_button,       1, 0, 1, 3, alignment=Qt.AlignCenter)
        grid.addWidget(finished_button,   2, 0, 1, 3, alignment=Qt.AlignCenter)
        layout.addLayout(grid)
        dialog.setLayout(layout)
        result = dialog.exec_()
        if result == QDialog.Rejected:
            self.add_videos()
        try:
            out_sz = Path(self._output_path).stat().st_size if self._output_path else 0
            self.logger.info("MERGE_DONE: exit_code=%s | output='%s' | size=%s",
                            exit_code, self._output_path, _human(out_sz))
        except Exception:
            pass

    def _open_folder(self, path: str):
        """Opens the specified folder using the default file explorer."""
        folder_path = str(Path(path))
        if not folder_path or not os.path.isdir(folder_path):
            self.logger.warning("OPEN_FOLDER: Path is not a directory or does not exist: %s", folder_path)
            return
        try:
            if sys.platform == 'win32':
                os.startfile(folder_path, 'explore')
            elif sys.platform == 'darwin':
                subprocess.Popen(['open', folder_path])
            else:
                subprocess.Popen(['xdg-open', folder_path])
            self.logger.info("OPEN_FOLDER: Opened %s", folder_path)
        except Exception as e:
            self.logger.error("OPEN_FOLDER: Failed to open folder %s | Error: %s", folder_path, e)

    def return_to_main_app(self):
        """Emits a signal to tell the parent (main app) to return to main view."""
        self.logger.info("ACTION: Return to Main App clicked. Emitting return signal.")
        self.return_to_main.emit()
        self.close()

    def _mp3_dir(self) -> Path:
        """Return the absolute path to the project's central MP3 folder."""
        d = _proj_root() / "mp3"
        try:
            d.mkdir(exist_ok=True)
        except Exception:
            pass
        return d

    def _ffprobe(self) -> str:
        """Gets the path to the ffprobe executable, assuming it's next to ffmpeg."""
        try:
            ffmpeg_dir = Path(self.ffmpeg).parent
            for name in ("ffprobe", "ffprobe.exe"):
                p = ffmpeg_dir / name
                if p.exists():
                    return str(p)
        except Exception:
            pass
        return "ffprobe"

    def _probe_audio_duration(self, path: str) -> float:
        """Return audio duration in seconds (float) or 0.0 on failure."""
        try:
            cmd = [self._ffprobe(), "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path]
            r = subprocess.run(cmd, capture_output=True, text=True, check=True,
                               creationflags=(subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0))
            return max(0.0, float(r.stdout.strip()))
        except Exception:
            self.logger.exception("Failed to probe audio duration for %s", path)
            return 0.0

    def _update_music_badge(self):
        """Position the small % badge next to the music volume handle."""
        try:
            if not self.music_volume_slider.isVisible():
                self.music_volume_badge.hide()
                return
            s = self.music_volume_slider
            parent = s.parentWidget() or self
            opt = QStyleOptionSlider()
            opt.initFrom(s)
            opt.orientation = Qt.Vertical
            opt.minimum = s.minimum()
            opt.maximum = s.maximum()
            opt.sliderPosition = int(s.value())
            opt.sliderValue = int(s.value())
            opt.upsideDown = not s.invertedAppearance()
            opt.rect = s.rect()
            handle = s.style().subControlRect(QStyle.CC_Slider, opt, QStyle.SC_SliderHandle, s)
            handle_center = handle.center()
            pt = s.mapTo(self, handle_center) # Map to QMainWindow (self)
            eff_volume = self._music_eff(int(s.value()))
            self.music_volume_badge.setText(f"{eff_volume}%")
            self.music_volume_badge.adjustSize()
            x_slider_right = s.mapTo(self, s.rect().topRight()).x()
            x = x_slider_right + 8
            y = pt.y() - (self.music_volume_badge.height() // 2)
            y = max(2, min((self.height() - self.music_volume_badge.height() - 2), y))
            self.music_volume_badge.move(x, y)
            self.music_volume_badge.show()
        except Exception:
            pass

    def _scan_mp3_folder(self):
        r"""Scan .\mp3 for .mp3 files, sorted by modified time (newest first)."""
        try:
            d = self._mp3_dir()
            files = []
            for name in os.listdir(d):
                if name.lower().endswith(".mp3"):
                    p = os.path.join(d, name)
                    try:
                        mt = os.path.getmtime(p)
                    except Exception:
                        mt = 0
                    files.append((mt, name, p))
            files.sort(key=lambda x: x[0], reverse=True)
            self._music_files = [(n, p) for _, n, p in files]
        except Exception:
            self._music_files = []
        self._populate_music_combo()

    def _populate_music_combo(self):
        """Refresh the dropdown safely based on self._music_files."""
        mf = getattr(self, "_music_files", [])
        self.music_combo.blockSignals(True)
        self.music_combo.clear()
        if not mf:
            self.music_combo.addItem("No MP3 files found in ./mp3", "")
            self.music_combo.setEnabled(False)
        else:
            self.music_combo.addItem("— Select an MP3 —", "")
            for name, path in mf:
                self.music_combo.addItem(name, path)
            self.music_combo.setCurrentIndex(0)
            self.music_combo.setEnabled(True)
        self.music_combo.blockSignals(False)

    def _on_add_music_toggled(self, checked: bool):
        """Show/enable music controls only if files exist and checkbox checked."""
        have_files = bool(self._music_files)
        enable = checked and have_files
        self.music_combo.setVisible(enable)
        self.music_combo.setEnabled(enable)
        self.music_volume_slider.setVisible(enable)
        self.music_volume_label.setVisible(enable)
        self.music_offset_input.setVisible(enable)
        if enable:
            self.music_volume_slider.setEnabled(True)
            self.music_offset_input.setEnabled(True)
            self._on_music_selected(self.music_combo.currentIndex())
        else:
            self.music_volume_slider.setEnabled(False)
            self.music_offset_input.setEnabled(False)

    def _on_music_selected(self, index: int):
        if not self._music_files:
            return
        if self.music_volume_slider.value() in (0, 35):
             self.music_volume_slider.setValue(35)
        try:
            p = self.music_combo.currentData()
            if not p:
                self.music_offset_input.setRange(0.0, 0.0)
                self.music_offset_input.setValue(0.0)
                return
            dur = self._probe_audio_duration(p)
            self.music_offset_input.setRange(0.0, max(0.0, dur - 0.01))
            if self.vlc_instance:
                if self.vlc_instance:
                    def _configure_dialog_player(vlc_player):
                        try:
                            vlc_player.audio_output_set('directsound')
                            volume = self._music_eff()
                            vlc_player.audio_set_volume(volume)
                            return None
                        except Exception as e:
                            self.logger.error("Failed to patch VLC player with directsound/volume: %s", e)
                            return None
                    setattr(self, "_vlc_setup_hook", _configure_dialog_player)
                    import ui.widgets.music_offset_dialog as _mod_mdlg
                    _orig_lead = getattr(_mod_mdlg, "PREVIEW_VISUAL_LEAD_MS", 0)
                    try:
                        _mod_mdlg.PREVIEW_VISUAL_LEAD_MS = 0
                        initial_offset = self.music_offset_input.value()
                        from PyQt5.QtWidgets import QApplication
                        parent = self.window() if callable(getattr(self, "window", None)) else self
                        dlg = MusicOffsetDialog(parent, self.vlc_instance, p, initial_offset, self.bin_dir)
                        dlg.setWindowModality(Qt.ApplicationModal)
                        dlg.setAttribute(Qt.WA_DeleteOnClose, True)
                        dlg.show()
                        dlg.raise_()
                        dlg.activateWindow()
                        QApplication.processEvents()
                        if dlg.exec_() == QDialog.Accepted:
                            self.music_offset_input.setValue(dlg.selected_offset)
                    except Exception as e:
                        self.logger.exception("Failed to open MusicOffsetDialog: %s", e)
                    finally:
                        _mod_mdlg.PREVIEW_VISUAL_LEAD_MS = _orig_lead
                        if hasattr(self, "_vlc_setup_hook"):
                            delattr(self, "_vlc_setup_hook")
            else:
                self.logger.warning("VLC instance not available, cannot show music offset dialog.")
        except Exception as e:
            self.logger.error("Error on music selection or dialog: %s", e)
            self.music_offset_input.setRange(0.0, 0.0)
            self.music_offset_input.setValue(0.0)

    def _get_selected_music(self):
        """Return (path, volume_linear) or (None, None) if disabled/invalid."""
        if not self.add_music_checkbox.isChecked():
            return None, None
        if not self._music_files:
            return None, None
        path = self.music_combo.currentData() or ""
        if not path or not os.path.isfile(path):
            return None, None
        vol_pct = self._music_eff()
        return path, (vol_pct / 100.0)
    
    def _music_eff(self, raw: int | None = None) -> int:
        """Map slider value -> 0..100 respecting invertedAppearance."""
        v = int(self.music_volume_slider.value() if raw is None else raw)
        if self.music_volume_slider.invertedAppearance():
            return max(0, min(100, self.music_volume_slider.maximum() + self.music_volume_slider.minimum() - v))
        return max(0, min(100, v))

    def _on_music_volume_changed(self, raw: int):
        """Keep label/badge in effective %."""
        try:
            eff = self._music_eff(raw)
            self.music_volume_label.setText(f"{eff}%")
            self._update_music_badge()
        except Exception:
            pass

if __name__ == "__main__":
    try:
        _proj_root_path = Path(__file__).resolve().parents[2]
        if str(_proj_root_path) not in sys.path:
            sys.path.insert(0, str(_proj_root_path))
            print(f"DEBUG [Standalone]: Added project root '{_proj_root_path}' to sys.path")
    except Exception as _path_err:
        print(f"ERROR [Standalone]: Failed to modify sys.path - {_path_err}", file=sys.stderr)
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("FortniteVideoTool.Merger")
            ctypes.windll.kernel32.FreeConsole()
        except Exception:
            pass
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
    app = QApplication(sys.argv)
    try:
        preferred = str(_proj_root_path / "icons" / "Video_Icon_File.ico")
        fallback  = str(_proj_root_path / "icons" / "app_icon.ico")
        icon_path = preferred if os.path.exists(preferred) else fallback
        if os.path.exists(icon_path):
            app.setWindowIcon(QIcon(icon_path))
        else:
            print(f"[WARN] icon not found at {icon_path}")
    except Exception as e:
        print(f"WARN [Standalone]: Failed to set application icon - {e}", file=sys.stderr)
    try:
        bin_dir = _proj_root_path / 'binaries'
        ffmpeg_path = bin_dir / 'ffmpeg.exe'
        if not ffmpeg_path.exists():
            QMessageBox.critical(None, "Error", f"ffmpeg.exe not found at {ffmpeg_path}\n"
                                               f"This test will fail.")
            sys.exit(1)
        try:
            import vlc
            vlc_instance = vlc.Instance('--no-xlib --quiet')
        except Exception as vlc_err:
            QMessageBox.warning(None, "VLC Error", f"Could not initialize VLC for music preview:\n{vlc_err}")
            vlc_instance = None
        window = VideoMergerWindow(ffmpeg_path=str(ffmpeg_path), vlc_instance=vlc_instance, bin_dir=str(bin_dir))
    except Exception as e:
        QMessageBox.critical(None, "Error", f"Failed to initialize: {e}")
        sys.exit(1)
    window.show()
    sys.exit(app.exec_())
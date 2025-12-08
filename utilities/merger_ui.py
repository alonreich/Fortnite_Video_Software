from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QCheckBox, 
    QComboBox, QDoubleSpinBox, QSlider, QSizePolicy
)
from PyQt5.QtCore import Qt, QSize

class MergerUI:
    def __init__(self, parent):
        self.parent = parent

    def setup_ui(self):
        """Builds the layout and widgets."""
        root = QWidget(self.parent)
        self.parent.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(20, 16, 20, 16)
        outer.setSpacing(16)
        title = QLabel('Sort the Videos in the Correct Desired Order. Hit the "Merge Videos" Button When Done.')
        title.setObjectName("titleLabel")
        title.setAlignment(Qt.AlignHCenter)
        outer.addWidget(title)
        list_container = QHBoxLayout()
        outer.addLayout(list_container)
        self.parent.listw = self.parent.create_draggable_list_widget()
        list_container.addWidget(self.parent.listw, 1)
        move_btns_col = self.create_move_buttons()
        list_container.addLayout(move_btns_col)
        list_container.setStretch(0, 1)
        list_container.setStretch(1, 0)
        band = self.create_bottom_band()
        outer.addWidget(band)
        self.parent.status_label = QLabel("Ready. Add 2 to 10 videos to begin.")
        self.parent.status_label.setStyleSheet("color: #7289da; font-weight: bold;")
        outer.addWidget(self.parent.status_label)
        merge_row = self.create_merge_row()
        outer.addWidget(merge_row)
        outer.setStretch(0, 0)
        outer.setStretch(1, 1)
        outer.setStretch(2, 0)
        outer.setStretch(3, 0)
        outer.setStretch(4, 0)
        outer.setStretch(5, 0)

    def create_move_buttons(self):
        move_btns_col = QVBoxLayout()
        move_btns_col.setContentsMargins(0, 0, 0, 0)
        move_btns_col.setSpacing(20)
        self.parent.btn_up = QPushButton("▲ Up ▲")
        self.parent.btn_up.setToolTip("Move selected video up")
        self.parent.btn_up.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.parent.btn_up.setMinimumWidth(160)
        self.parent.btn_up.setMaximumWidth(160)
        self.parent.btn_up.setMinimumHeight(50)
        self.parent.btn_up.setMaximumHeight(50)
        self.parent.btn_up.setProperty("class", "move-btn") 
        self.parent.btn_up.setStyleSheet("min-height:64px;")
        self.parent.btn_up.clicked.connect(lambda: self.parent.move_item(-1))
        self.parent.btn_down = QPushButton("▼ Down ▼")
        self.parent.btn_down.setToolTip("Move selected video down")
        self.parent.btn_down.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.parent.btn_down.setMinimumWidth(160)
        self.parent.btn_down.setMaximumWidth(160)
        self.parent.btn_down.setMinimumHeight(50)
        self.parent.btn_down.setMaximumHeight(50)
        self.parent.btn_down.setProperty("class", "move-btn")
        self.parent.btn_down.setStyleSheet("min-height:64px;")
        self.parent.btn_down.clicked.connect(lambda: self.parent.move_item(1))
        move_btns_col.addStretch(1)
        move_btns_col.addWidget(self.parent.btn_up)
        move_btns_col.addWidget(self.parent.btn_down)
        move_btns_col.addStretch(1)
        return move_btns_col

    def create_bottom_band(self):
        band = QHBoxLayout()
        band.setContentsMargins(0, 0, 0, 0)
        band.setSpacing(0)
        music_layout = self.create_music_layout()
        left_wrap = QWidget()
        left_wrap.setLayout(music_layout)
        center = self.create_center_buttons()
        center_wrap = QWidget()
        center_wrap.setLayout(center)
        band.addStretch(1)
        band.addWidget(center_wrap, 0)
        band.addSpacing(8)
        band.addWidget(left_wrap, 0)
        band.addStretch(1)
        band_wrap = QWidget()
        band_wrap.setLayout(band)
        band_wrap.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        return band_wrap

    def create_music_layout(self):
        music_layout = QHBoxLayout()
        music_layout.setSpacing(15)
        self.parent.add_music_checkbox = QCheckBox("Add Background Music")
        self.parent.add_music_checkbox.setToolTip("Toggle background MP3 mixing from the ./mp3 folder.")
        self.parent.add_music_checkbox.setChecked(False)
        music_layout.addWidget(self.parent.add_music_checkbox)
        self.parent.music_combo = QComboBox()
        try:
            self.parent.music_combo.setElideMode(Qt.ElideMiddle)
        except Exception:
            pass
        self.parent.music_combo.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self.parent.music_combo.setMinimumWidth(400)
        self.parent.music_combo.setMaximumWidth(400)
        self.parent.music_combo.setMinimumContentsLength(24)
        self.parent.music_combo.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.parent.music_combo.setVisible(False)
        music_layout.addWidget(self.parent.music_combo)
        self.parent.music_offset_input = QDoubleSpinBox()
        self.parent.music_offset_input.setPrefix("Music Start (s): ")
        self.parent.music_offset_input.setMinimumWidth(180)
        self.parent.music_offset_input.setMaximumWidth(180)
        self.parent.music_offset_input.setDecimals(2)
        self.parent.music_offset_input.setSingleStep(0.5)
        self.parent.music_offset_input.setRange(0.0, 0.0)
        self.parent.music_offset_input.setValue(0.0)
        self.parent.music_offset_input.setVisible(False)
        music_layout.addWidget(self.parent.music_offset_input)
        music_slider_box = self.create_music_slider()
        music_layout.addLayout(music_slider_box)
        return music_layout

    def create_music_slider(self):
        self.parent.music_volume_slider = QSlider(Qt.Vertical, self.parent)
        self.parent.music_volume_slider.setObjectName("musicVolumeSlider")
        self.parent.music_volume_slider.setRange(0, 100)
        self.parent.music_volume_slider.setTickInterval(1)
        self.parent.music_volume_slider.setTracking(True)
        self.parent.music_volume_slider.setVisible(False)
        self.parent.music_volume_slider.setFocusPolicy(Qt.NoFocus)
        self.parent.music_volume_slider.setMinimumHeight(150)
        self.parent.music_volume_slider.setInvertedAppearance(True)
        eff_default = int(25)
        self.parent.music_volume_slider.setValue(eff_default)
        _knob = "#7289da"
        self.parent.music_volume_slider.setStyleSheet(f"""
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
        self.parent.music_volume_label = QLabel(f"{eff_default}%")
        self.parent.music_volume_label.setAlignment(Qt.AlignHCenter)
        self.parent.music_volume_label.setVisible(False)
        self.parent.music_volume_badge = QLabel(f"{eff_default}%", self.parent)
        self.parent.music_volume_badge.setObjectName("musicVolumeBadge")
        self.parent.music_volume_badge.setStyleSheet(
            "color: white; background: rgba(0,0,0,160); padding: 2px 6px; "
            "border-radius: 6px; font-weight: bold;"
        )
        self.parent.music_volume_badge.hide()
        music_slider_box = QVBoxLayout()
        music_slider_box.setSpacing(2)
        music_slider_box.addWidget(self.parent.music_volume_slider, 0, Qt.AlignHCenter)
        music_slider_box.addWidget(self.parent.music_volume_label, 0, Qt.AlignHCenter)
        return music_slider_box

    def create_center_buttons(self):
        center = QHBoxLayout()
        center.setContentsMargins(0, 0, 0, 0)
        center.setSpacing(14)
        self.parent.btn_add = QPushButton("Add Videos")
        self.parent.btn_add.setFixedSize(185, 40)
        self.parent.btn_add.setObjectName("aux-btn")
        self.parent.btn_add.clicked.connect(self.parent.add_videos)
        self.parent.btn_remove = QPushButton("Remove Selected Video")
        self.parent.btn_remove.setFixedSize(185, 40)
        self.parent.btn_remove.setObjectName("danger-btn")
        self.parent.btn_remove.clicked.connect(self.parent.remove_selected)
        self.parent.btn_clear = QPushButton("Remove All Videos")
        self.parent.btn_clear.setFixedSize(160, 40)
        self.parent.btn_clear.setObjectName("danger-btn")
        self.parent.btn_clear.clicked.connect(self.parent.listw.clear)
        center.addWidget(self.parent.btn_add)
        center.addWidget(self.parent.btn_remove)
        center.addWidget(self.parent.btn_clear)
        return center

    def create_merge_row(self):
        self.parent.btn_back = QPushButton("Return to Main App")
        self.parent.btn_back.setFixedSize(185, 40)
        self.parent.btn_back.setObjectName("returnButton")
        self.parent.btn_back.clicked.connect(self.parent.return_to_main_app)
        merge_row = QHBoxLayout()
        merge_wrap = QWidget()
        merge_wrap.setLayout(merge_row)
        merge_wrap.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        merge_row.addStretch(1)
        self.parent.btn_merge = QPushButton("Merge Videos")
        self.parent.btn_merge.setObjectName("mergeButton")
        self.parent.btn_merge.setFixedSize(260, 48)
        self.parent._merge_btn_base_css = (
            "background-color: #59A06D;"
            "color: black;"
            "font-weight: bold;"
            "font-size: 16px;"
            "border-radius: 15px;"
            "padding: 6px 20px;"
        )
        self.parent.btn_merge.setStyleSheet(self.parent._merge_btn_base_css)
        self.parent.btn_merge.clicked.connect(self.parent.on_merge_clicked)
        merge_row.addWidget(self.parent.btn_merge)
        merge_row.addStretch(1)
        merge_row.addWidget(self.parent.btn_back)
        return merge_wrap

    def set_style(self):
        """Applies a dark theme stylesheet similar to the main app."""
        self.parent.setStyleSheet("""
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

    def _ensure_processing_overlay(self):
        if hasattr(self.parent, "_overlay"):
            return
        self.parent._overlay = QWidget(self.parent)
        self.parent._overlay.setWindowFlags(Qt.SubWindow | Qt.FramelessWindowHint)
        self.parent._overlay.setAttribute(Qt.WA_NoSystemBackground, True)
        self.parent._overlay.setAttribute(Qt.WA_TransparentForMouseEvents, False)
        self.parent._overlay.setStyleSheet("background: rgba(0,0,0,165);")
        self.parent._overlay.hide()

    def _show_processing_overlay(self):
        self._ensure_processing_overlay()
        self.parent._overlay.setGeometry(self.parent.rect())
        self.parent._overlay.show()
        self.parent._overlay.raise_()
        if not hasattr(self.parent, "_pulse_timer"):
            from PyQt5.QtCore import QTimer
            self.parent._pulse_timer = QTimer(self.parent)
            self.parent._pulse_timer.setInterval(100)
            self.parent._pulse_timer.timeout.connect(self._pulse_merge_btn)
        self.parent._pulse_phase = 0
        self.parent._pulse_timer.start()

    def _hide_processing_overlay(self):
        if hasattr(self.parent, "_pulse_timer"):
            self.parent._pulse_timer.stop()
        if hasattr(self.parent, "_overlay"):
            self.parent._overlay.hide()
        self.parent.btn_merge.setText("Merge Videos")
        self.parent.btn_merge.setStyleSheet(self.parent._merge_btn_base_css)

    def _pulse_merge_btn(self):
        self.parent._pulse_phase = (getattr(self.parent, "_pulse_phase", 0) + 1) % 20
        t = self.parent._pulse_phase / 20.0
        import math
        k = (math.sin(4 * math.pi * t) + 1) / 2
        g1 = (72, 235, 90)
        g2 = (10, 80, 16)
        r = int(g1[0] * k + g2[0] * (1 - k))
        g = int(g1[1] * k + g2[1] * (1 - k))
        b = int(g1[2] * k + g2[2] * (1 - k))
        self.parent.btn_merge.setStyleSheet(
            f"background-color: rgb({r},{g},{b});"
            "color: black;"
            "font-weight: bold;"
            "font-size: 16px;"
            "border-radius: 15px;"
            "padding: 6px 20px;"
        )

    def _update_music_badge(self):
        """Position the small % badge next to the music volume handle."""
        try:
            if not self.parent.music_volume_slider.isVisible():
                self.parent.music_volume_badge.hide()
                return
            s = self.parent.music_volume_slider
            from PyQt5.QtWidgets import QStyleOptionSlider, QStyle
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
            pt = s.mapTo(self.parent, handle_center) # Map to QMainWindow (self)
            eff_volume = self.parent.music_handler._music_eff(int(s.value()))
            self.parent.music_volume_badge.setText(f"{eff_volume}%")
            self.parent.music_volume_badge.adjustSize()
            x_slider_right = s.mapTo(self.parent, s.rect().topRight()).x()
            x = x_slider_right + 8
            y = pt.y() - (self.parent.music_volume_badge.height() // 2)
            y = max(2, min((self.parent.height() - self.parent.music_volume_badge.height() - 2), y))
            self.parent.music_volume_badge.move(x, y)
            self.parent.music_volume_badge.show()
        except Exception:
            pass

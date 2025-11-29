from PyQt5.QtCore import Qt, QTimer, QSize, QEvent
from PyQt5.QtGui import QPixmap, QPainter, QFont, QIcon, QFontMetrics
from PyQt5.QtWidgets import (QGridLayout, QMessageBox, QSizePolicy, QHBoxLayout,
                             QVBoxLayout, QFrame, QSlider, QLabel, QStyle,
                             QPushButton, QSpinBox, QDoubleSpinBox, QCheckBox,
                             QProgressBar, QComboBox, QWidget, QStyleOptionSpinBox)
from ui.widgets.trimmed_slider import TrimmedSlider
from ui.widgets.drop_area import DropAreaFrame

class ClickableSpinBox(QDoubleSpinBox):
    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            opt = QStyleOptionSpinBox()
            self.initStyleOption(opt)
            up_rect = self.style().subControlRect(QStyle.CC_SpinBox, opt, QStyle.SC_SpinBoxUp, self)
            down_rect = self.style().subControlRect(QStyle.CC_SpinBox, opt, QStyle.SC_SpinBoxDown, self)
            if up_rect.contains(event.pos()) or down_rect.contains(event.pos()):
                super().mousePressEvent(event)
                return
        super().mousePressEvent(event)

class UiBuilderMixin:

        def _pick_thumbnail_from_current_frame(self):
            """
            Capture the current absolute player time (seconds) as the desired
            thumbnail frame. Validates that the frame is WITHIN the user's trim.
            """
            try:
                pos_ms = 0
                try:
                    pos_ms = int(self.positionSlider.value())
                except Exception:
                    pass
                if (not pos_ms) and getattr(self, 'vlc_player', None):
                    pos_ms = int(self.vlc_player.get_time() or 0)
                pos_s = float(pos_ms) / 1000.0
                if pos_s <= 0.0 and self.original_duration <= 0.0:
                    QMessageBox.information(self, "No Position", "Move the playhead to a frame first.")
                    return
                start_s = (self.start_minute_input.value() * 60) + self.start_second_input.value()
                end_s   = (self.end_minute_input.value()   * 60) + self.end_second_input.value()
                self.selected_intro_abs_time = pos_s
                mm = int(self.selected_intro_abs_time // 60)
                ss = self.selected_intro_abs_time % 60.0
                label = f"📸 Thumbnail\n Set: {mm:02d}:{ss:05.2f}"
                self.thumb_pick_btn.setText(label)
                if hasattr(self, "logger"):
                    self.logger.info("THUMB: user picked thumbnail at %.3fs (absolute timeline, within trim)", self.selected_intro_abs_time)
                self.status_update_signal.emit("Thumbnail frame selected from current position.")
            except Exception as e:
                try:
                    if hasattr(self, "logger"):
                        self.logger.exception("Thumbnail pick failed: %s", e)
                finally:
                    QMessageBox.warning(self, "Error", f"Failed to pick thumbnail: {e}")

        def _update_process_button_text(self) -> None:
            """Updates the process button text AND spinner icon."""
            try:
                self._pulse_phase = (getattr(self, "_pulse_phase", 0) + 1) % 8
                if getattr(self, "is_processing", False):
                    dots = "." * (1 + (self._pulse_phase // 2))
                    text = f"Processing{dots}"
                    spinner = "◐◓◑◒"
                    glyph = spinner[(self._pulse_phase // 2) % len(spinner)]
                    px = 26
                    pm = QPixmap(px, px)
                    pm.fill(Qt.transparent)
                    p = QPainter(pm)
                    f = QFont(self.font())
                    f.setPointSize(px)
                    p.setFont(f)
                    p.setPen(Qt.black)
                    p.drawText(pm.rect(), Qt.AlignCenter, glyph)
                    p.end()
                    self.process_button.setText(text)
                    self.process_button.setIcon(QIcon(pm))
                    self.process_button.setIconSize(QSize(px, px))
                else:
                    self.process_button.setText("Process Video")
                    self.process_button.setIcon(QIcon())
            except Exception:
                pass

        def _safe_add_to_grid(self, layout, w, r=None, c=None, rs=1, cs=1, align=Qt.Alignment()):
            """Add widget whether layout is QGridLayout or QBoxLayout/etc."""
            try:
                from PyQt5.QtWidgets import QGridLayout
                if isinstance(layout, QGridLayout) and r is not None and c is not None:
                    layout.addWidget(w, r, c, rs, cs, align)
                else:
                    if align:
                        layout.addWidget(w, 0, align)
                    else:
                        layout.addWidget(w)
            except Exception:
                try:
                    layout.addWidget(w)
                except Exception:
                    pass

        def _ensure_default_trim(self):
            """
            If user didn't set trims, default to full video length based on the current
            spinbox maxima (updated when media loads).
            """
            try:
                if self.end_minute_input.maximum() == 0 and self.positionSlider.maximum() == 0:
                    QMessageBox.warning(self, "No video", "Please load a video file first.")
                    if hasattr(self, "logger"): self.logger.error("PROCESS: blocked - no video loaded")
                    return False
                start_is_zero = (self.start_minute_input.value() == 0 and
                                self.start_second_input.value() == 0)
                end_is_zero   = (self.end_minute_input.value()   == 0 and
                                self.end_second_input.value()   == 0)
                if start_is_zero and end_is_zero:
                    end_min = self.end_minute_input.maximum()
                    end_sec = self.end_second_input.maximum()
                    self.end_minute_input.setValue(end_min)
                    self.end_second_input.setValue(end_sec)
                    if hasattr(self, "logger"):
                        self.logger.info("TRIM: defaulted to full length end=%02d:%02d", end_min, end_sec)
                return True
            except Exception as e:
                try:
                    if hasattr(self, "logger"): self.logger.exception("TRIM default failed: %s", e)
                except Exception:
                    pass
                return False
        
        def _on_process_clicked(self):
            """Click-safe entrypoint: log, ensure trims, then call existing processing."""
            try:
                if hasattr(self, "logger"): self.logger.info("CLICK: Process Video")
                try:
                    if getattr(self, "vlc_player", None):
                        self.vlc_player.stop()
                except Exception:
                    pass
                if (self.end_minute_input.maximum() == 0 and
                    self.positionSlider.maximum() == 0):
                    QMessageBox.warning(self, "No video", "Please load a video file first.")
                    if hasattr(self, "logger"): self.logger.error("PROCESS: blocked - no video loaded")
                    return
                if not self._ensure_default_trim():
                    return
                self._show_processing_overlay()
                self._append_live_log("Processing started…")
                self.start_processing()
            except Exception as e:
                try:
                    if hasattr(self, "logger"): self.logger.exception("PROCESS click failed: %s", e)
                except Exception:
                    pass
                QMessageBox.critical(self, "Error", "Could not start processing. See log for details.")

        def _maybe_enable_process(self):
            """
            Turn on the Process button once duration exists,
            and if user hasn’t set trims yet, default to full video.
            """
            try:
                has_duration = (self.positionSlider.maximum() > 0) or (self.end_minute_input.maximum() > 0)
                if has_duration:
                    if not self.process_button.isEnabled():
                        if hasattr(self, "logger"): self.logger.info("READY: Media loaded; enabling Process button")
                    self.process_button.setEnabled(True)
                    self._ensure_default_trim()
            except Exception:
                pass

        def launch_video_merger(self):
            try:
                from ui.widgets.video_merger import VideoMergerWindow 
            except ImportError:
                self.logger.critical("ERROR: Could not import VideoMergerWindow. Check your PYTHONPATH.")
                QMessageBox.critical(self, "Error", "Cannot load Video Merger module.")
                return
            try:
                self.logger.info("ACTION: Launching Video Merger…")
                vlc_instance = getattr(self, 'vlc_instance', None)
                bin_dir = getattr(self, 'bin_dir', '')
                config_manager = getattr(self, 'config_manager', None)
                self.merger_window = VideoMergerWindow(
                    parent=None,
                    vlc_instance=vlc_instance,
                    bin_dir=bin_dir,
                    config_manager=config_manager
                )
                self.merger_window.return_to_main.connect(self.show)
                self.hide()
                self.merger_window.show()
                self.merger_window.raise_()
                self.merger_window.activateWindow()
                self.logger.info("STATUS: Video Merger launched as top-level window; main UI hidden.")
            except Exception as e:
                self.logger.critical(f"ERROR: Failed to launch Video Merger in-process. Error: {e}")
                QMessageBox.critical(self, "Launch Failed", f"Could not launch Video Merger. Error: {e}")
                self.show()
        
        def eventFilter(self, obj, event):
            if event.type() == QEvent.Resize:
                if obj is getattr(self, "player_col_container", None):
                    if hasattr(self, "_center_timer"):
                        self._center_timer.start(16)
            return super().eventFilter(obj, event)
        
        def _recenter_process_controls(self):
            """
            Exact centering that respects the *current* side widths (including Mobile Format visibility)
            and applies a single safe nudge to eliminate 1–2px drift.
            """
            if getattr(self, "_centering", False):
                return
            self._centering = True
            try:
                grid = self.center_btn_container
                if not isinstance(grid, QGridLayout):
                    return
                pc = self.player_col_container
                if pc is None:
                    return
                container_w = pc.width() or pc.sizeHint().width()
                btn_w = self.process_button.width() or self.process_button.sizeHint().width()
                if container_w <= 0 or btn_w <= 0:
                    return
                gap = grid.horizontalSpacing() or 0
                cx  = self.playPauseButton.mapTo(self.player_col_container,
                                                self.playPauseButton.rect().center()).x()
                def _minw(w):
                    if not w or not w.isVisible():
                        return 0
                    return w.sizeHint().width() + 8
                left_min  = _minw(self.left_group_widget)
                right_min = _minw(self.right_group_widget)
                L = max(left_min, int(round(cx - (btn_w / 2.0) - gap)))
                R = max(right_min, container_w - (L + btn_w + 2 * gap))
                if R < right_min:
                    L = max(left_min, container_w - (btn_w + 2 * gap + right_min))
                    R = max(right_min, container_w - (L + btn_w + 2 * gap))
                total = L + btn_w + 2 * gap + R
                if total > container_w:
                    over = total - container_w
                    takeL = min(over // 2, max(0, L - left_min)); L -= takeL; over -= takeL
                    takeR = min(over,        max(0, R - right_min)); R -= takeR; over -= takeR
                    if over > 0:
                        if R - right_min >= over:
                            R -= over
                        elif L - left_min >= over:
                            L -= over
                actual_cx = L + gap + (btn_w / 2.0)
                delta = (actual_cx - cx)
                if abs(delta) >= 0.5:
                    if delta > 0:
                        shift = min(delta, max(0, L - left_min))
                        L -= shift; R += shift
                    else:
                        shift = min(-delta, max(0, R - right_min))
                        L += shift; R -= shift
                curL = grid.columnMinimumWidth(0)
                curR = grid.columnMinimumWidth(2)
                if abs(L - curL) >= 2 or abs(R - curR) >= 2:
                    self.setUpdatesEnabled(False)
                    grid.setColumnStretch(0, 0); grid.setColumnStretch(1, 0); grid.setColumnStretch(2, 0)
                    grid.setColumnMinimumWidth(0, max(0, L))
                    grid.setColumnMinimumWidth(2, max(0, R))
                    if hasattr(self, "quality_container"):
                        reserve_for_speed = 260
                        room = max(140, R - reserve_for_speed)
                        self.quality_container.setMaximumWidth(min(room, 340))
                    self.setUpdatesEnabled(True)
            finally:
                self._centering = False

        def showEvent(self, e):
            super().showEvent(e)
            if hasattr(self, "_center_timer"):
                self._center_timer.start(0)

        def resizeEvent(self, e):
            super().resizeEvent(e)
            if hasattr(self, "_center_timer"):
                self._center_timer.start(16)

        def init_ui(self):
            main_layout = QHBoxLayout()
            self.setContentsMargins(0, 0, 0, 0)
            left_layout = QVBoxLayout()
            left_layout.setContentsMargins(0, 0, 0, 0)
            left_layout.setSpacing(0)
            self.video_frame = QFrame()
            self.video_frame.setStyleSheet("background-color: black;")
            self.video_frame.setMinimumHeight(360)
            self.video_frame.setFocusPolicy(Qt.NoFocus)
            self.setFocusPolicy(Qt.StrongFocus)
            top_row = QHBoxLayout()
            top_row.setSpacing(12)
            player_col = QVBoxLayout()
            player_col.setSpacing(6)
            self.video_frame.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
            player_col.addWidget(self.video_frame)
            self.positionSlider = TrimmedSlider(self)
            self.positionSlider.setRange(0, 0)
            self.positionSlider.setFixedHeight(50)
            self.positionSlider.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            self.positionSlider.setObjectName("timelineSlider")
            self.positionSlider.setStyleSheet("""
                QSlider#timelineSlider::groove:horizontal {
                    border: 1px solid #565656;
                    background: #383838;
                    height: 6px;
                    margin: 0px;
                    border-radius: 3px;
                }

                QSlider#timelineSlider::handle:horizontal {
                    background: #2196F3; /* A nice, professional blue */
                    border: 1px solid #1976D2;
                    width: 3px; /* A thin line */
                    height: 20px;
                    line-height: 20px;
                    margin: -7px 0; /* Center it vertically */
                    border-radius: 2px;
                }

                QSlider#timelineSlider::add-page:horizontal {
                    background: #5c5c5c;
                }

                QSlider#timelineSlider::sub-page:horizontal {
                    background: #2196F3;
                }
            """)
            self.positionSlider.sliderMoved.connect(self.set_vlc_position)
            self.positionSlider.rangeChanged.connect(lambda *_: self._maybe_enable_process())
            player_col.addWidget(self.positionSlider)
            self.volume_slider = QSlider(Qt.Vertical, self)
            self.volume_slider.setObjectName("volumeSlider")
            self.volume_slider.setRange(0, 100)
            self.volume_slider.setSingleStep(1)
            self.volume_slider.setPageStep(15)
            self.volume_slider.setTickInterval(10)
            self.volume_slider.setTickPosition(QSlider.TicksBothSides)
            self.volume_slider.setTracking(True)
            self.volume_slider.setInvertedAppearance(True)
            try:
                eff = int(self.config_manager.config.get('last_volume', 100))
            except Exception:
                eff = 100
            raw = self.volume_slider.maximum() + self.volume_slider.minimum() - eff
            self.volume_slider.setValue(max(self.volume_slider.minimum(),
                                            min(self.volume_slider.maximum(), raw)))
            _knob = self.positionSlider.palette().highlight().color().name()
            self.volume_slider.setStyleSheet(f"""
            QSlider#volumeSlider {{
            padding: 0px;
            background: transparent;
            border: 0;
            }}
            QSlider#volumeSlider::groove:vertical {{
            margin: 0px;
            border: 1px solid #3498db;
            background: qlineargradient(x1:0, y1:1, x2:0, y2:0,
                stop:0   #e64c4c,
                stop:0.25 #f7a8a8,
                stop:0.50 #f2f2f2,
                stop:0.75 #7bcf43,
                stop:1   #009b00);
            width: 22px;
            border-radius: 6px;
            }}
            QSlider#volumeSlider::handle:vertical {{
            background: {_knob};
            border: 1px solid #5c5c5c;
            width: 30px; height: 30px;
            margin: -2px 0;
            border-radius: 6px;
            }}
            QSlider#volumeSlider::sub-page:vertical,
            QSlider#volumeSlider::add-page:vertical {{
            background: transparent;
            }}
            """)
            self.volume_slider.valueChanged.connect(self._on_master_volume_changed)
            self.volume_slider.sliderMoved.connect(lambda _: self._update_volume_badge())
            self.volume_slider.installEventFilter(self)
            self.volume_badge = QLabel("0%", self)
            self.volume_badge.setObjectName("volumeBadge")
            self.volume_badge.setStyleSheet("color: white; background: rgba(0,0,0,160); padding: 2px 6px; border-radius: 6px; font-weight: bold;")
            self.volume_badge.adjustSize()
            self.volume_badge.hide()
            QTimer.singleShot(0, self._layout_volume_slider)
            QTimer.singleShot(0, self._update_volume_badge)
            self.volume_slider.show()
            self.volume_slider.raise_()
            player_col.setStretch(0, 1)
            player_col.setStretch(1, 0)
            player_container = QWidget()
            player_container.setLayout(player_col)
            self.player_col_container = player_container
            self.player_col_container.installEventFilter(self)
            top_row.addWidget(player_container, stretch=6)
            self._top_row = top_row
            left_layout.addLayout(self._top_row)
            self.playPauseButton = QPushButton("Play")
            self.playPauseButton.setIcon(self.style().standardIcon(QStyle.SP_MediaPlay))
            self.playPauseButton.clicked.connect(self.toggle_play)
            self.playPauseButton.setFocusPolicy(Qt.NoFocus)
            self.playPauseButton.setStyleSheet("""
                QPushButton {
                    background-color: #59A06D;
                    color: white;
                    font-size: 14px;
                    padding: 4px 8px;
                    border-radius: 6px;
                }
                QPushButton:hover {
                    background-color: #6fb57f;
                }
                QPushButton:pressed {
                    background-color: #4a865a;
                }
            """)
            self.thumb_pick_btn = QPushButton("📸 Set Thumbnail 📸")
            self.thumb_pick_btn.setToolTip("Pick the exact frame at the current player position for the 0.1s intro still.")
            self.thumb_pick_btn.setFocusPolicy(Qt.NoFocus)
            self.thumb_pick_btn.setStyleSheet("font-size: 11px; font-weight: bold;")
            self.thumb_pick_btn.clicked.connect(self._pick_thumbnail_from_current_frame)
            _left_col = QVBoxLayout()
            _left_col.setContentsMargins(0, 0, 0, 0)
            _left_col.setSpacing(6)
            left_group = QHBoxLayout()
            trim_layout = QHBoxLayout()
            trim_layout.setContentsMargins(0, 0, 0, 0)
            trim_layout.setSpacing(14)
            self.start_minute_input = QSpinBox(); self.start_minute_input.setRange(0, 0)
            self.start_minute_input.setFixedHeight(35)
            self.start_second_input = QSpinBox(); self.start_second_input.setRange(0, 59)
            self.start_second_input.setFixedHeight(35)
            self.end_minute_input   = QSpinBox(); self.end_minute_input.setRange(0, 0)
            self.end_minute_input.setFixedHeight(35)
            self.end_second_input   = QSpinBox(); self.end_second_input.setRange(0, 59)
            self.end_second_input.setFixedHeight(35)
            self.start_minute_input.valueChanged.connect(self._on_trim_spin_changed)
            self.start_second_input.valueChanged.connect(self._on_trim_spin_changed)
            self.end_minute_input.valueChanged.connect(self._on_trim_spin_changed)
            self.end_second_input.valueChanged.connect(self._on_trim_spin_changed)
            self.start_trim_button = QPushButton("Set Start")
            self.start_trim_button.clicked.connect(self.set_start_time)
            self.start_trim_button.setFocusPolicy(Qt.NoFocus)
            self.end_trim_button = QPushButton("Set End")
            self.end_trim_button.clicked.connect(self.set_end_time)
            self.end_trim_button.setFocusPolicy(Qt.NoFocus)
            for spin in (self.start_minute_input, self.start_second_input, self.end_minute_input, self.end_second_input):
                spin.setMaximumWidth(48)
            self.start_trim_button.setFixedWidth(90)
            self.end_trim_button.setFixedWidth(90)
            self.playPauseButton.setFixedWidth(140)
            self.playPauseButton.setFixedHeight(35)
            start_min_layout = QHBoxLayout(); start_min_layout.setContentsMargins(0,0,0,0); start_min_layout.setSpacing(0)
            start_sec_layout = QHBoxLayout(); start_sec_layout.setContentsMargins(0,0,0,0); start_sec_layout.setSpacing(0)
            end_min_layout   = QHBoxLayout(); end_min_layout.setContentsMargins(0,0,0,0); end_min_layout.setSpacing(0)
            end_sec_layout   = QHBoxLayout(); end_sec_layout.setContentsMargins(0,0,0,0); end_sec_layout.setSpacing(0)
            lbl_start_min = QLabel("Start Min:"); lbl_start_min.setStyleSheet("font-size: 10px;")
            lbl_start_sec = QLabel("Sec:");       lbl_start_sec.setStyleSheet("font-size: 10px;")
            lbl_end_min   = QLabel("End Min:");   lbl_end_min.setStyleSheet("font-size: 10px;")
            lbl_end_sec   = QLabel("Sec:");       lbl_end_sec.setStyleSheet("font-size: 10px;")
            start_min_layout.addWidget(lbl_start_min); start_min_layout.addWidget(self.start_minute_input)
            start_sec_layout.addWidget(lbl_start_sec); start_sec_layout.addWidget(self.start_second_input)
            end_min_layout.addWidget(lbl_end_min);     end_min_layout.addWidget(self.end_minute_input)
            end_sec_layout.addWidget(lbl_end_sec);     end_sec_layout.addWidget(self.end_second_input)
            start_group = QHBoxLayout(); start_group.setContentsMargins(0,0,0,0); start_group.setSpacing(0)
            start_group.addLayout(start_min_layout); start_group.addLayout(start_sec_layout)
            end_group = QHBoxLayout();   end_group.setContentsMargins(0,0,0,0);   end_group.setSpacing(0)
            end_group.addLayout(end_min_layout);     end_group.addLayout(end_sec_layout)
            trim_layout.addLayout(start_group)
            trim_layout.addWidget(self.start_trim_button)
            trim_layout.addSpacing(14)
            trim_layout.addWidget(self.playPauseButton)
            trim_layout.addSpacing(14)
            trim_layout.addWidget(self.end_trim_button)
            trim_layout.addLayout(end_group)
            self.merge_btn = QPushButton("Merge Multiple \nVideos Into One")
            self.merge_btn.setStyleSheet(
                "background-color: #bfa624; color: black; font-weight:600;"
                "padding:6px 12px; border-radius:6px;"
            )
            self.merge_btn.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
            self.merge_btn.clicked.connect(self.launch_video_merger)
            trim_container = QHBoxLayout()
            trim_container.setContentsMargins(0, 0, 0, 0)
            trim_container.addWidget(self.thumb_pick_btn, 0, Qt.AlignLeft)
            trim_container.addStretch(1)
            trim_container.addLayout(trim_layout)
            trim_container.addStretch(1)
            player_col.addLayout(trim_container)
            self.thumb_pick_btn.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
            self.quality_label = QLabel("Output Quality")
            self.quality_label.setAlignment(Qt.AlignHCenter)
            self.quality_label.setStyleSheet("font-size: 11px; font-weight: bold; margin-left: 10px; margin-right: 10px; padding: 0;")
            self.quality_slider = QSlider(Qt.Horizontal)
            self.quality_slider.setRange(0, 4)
            self.quality_slider.setSingleStep(1)
            self.quality_slider.setPageStep(1)
            self.quality_slider.setTickInterval(1)
            self.quality_slider.setTickPosition(QSlider.TicksBelow)
            self.quality_slider.setValue(2)
            self.quality_slider.setFixedHeight(15)
            self.quality_slider.setMinimumWidth(150)
            self.quality_slider.setMaximumWidth(300)
            self.quality_slider.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            _knob = self.positionSlider.palette().highlight().color().name()
            self.quality_slider.setObjectName("qualitySlider")
            self.quality_slider.setStyleSheet(
                "QSlider#qualitySlider {"
                "  padding: 0px; border: 0; background: transparent;"
                "}"
                "QSlider#qualitySlider::groove:horizontal {"
                "  margin: 0px; border: 0px solid #bbb;"
                "  background: qlineargradient(x1:0, y1:0, x2:1, y2:0,"
                "    stop:0   #e64c4c, stop:0.25 #f7a8a8, stop:0.5  #f2f2f2,"
                "    stop:0.75 #7bcf43, stop:1   #009b00);"
                "  height: 20px; border-radius: 6px;"
                "}"
                "QSlider#qualitySlider::handle:horizontal {"
                f"  background: {_knob}; border: 1px solid #5c5c5c;"
                "  width: 27px; height: 22px; margin: 0px; border-radius: 6px;"
                "}"
                "QSlider#qualitySlider::sub-page:horizontal, QSlider#qualitySlider::add-page:horizontal { background: transparent; }"
            )
            self.quality_value_label = QLabel("Standard")
            self.quality_value_label.setAlignment(Qt.AlignHCenter)
            self.quality_value_label.setStyleSheet("font-size: 10px; margin: 0; padding: 0;")
            fm = QFontMetrics(self.quality_value_label.font())
            fixed_w = fm.horizontalAdvance("Maximum (For Social Media)") + 16
            self.quality_value_label.setMinimumWidth(fixed_w)
            def _on_quality_changed(value: int):
                titles = [
                    "Bad (Lightning Speed Shares)",
                    "Okay (Easier to Share)",
                    "Standard",
                    "Good",
                    "Maximum (For Social Media)",
                ]
                idx = max(0, min(4, int(value)))
                self.quality_value_label.setText(titles[idx])
                self.logger.info(f"OPTION: Video Output Quality -> {titles[idx]}")
            self.quality_slider.valueChanged.connect(_on_quality_changed)
            self.process_button = QPushButton("Process Video")
            self.process_button.setFixedSize(200, 70)
            self._original_process_btn_style = """
                QPushButton {
                    background-color: #148c14;
                    color: black;
                    font-weight: bold;
                    font-size: 16px;
                    border-radius: 15px;
                    margin-bottom: 6px;
                }
                QPushButton:hover { background-color: #c8f7c5; }
            """
            self.is_processing = False
            self._pulse_phase = 0
            self._pulse_timer = QTimer(self)
            self._pulse_timer.setSingleShot(False)
            self._pulse_timer.timeout.connect(self._update_process_button_text)
            self._pulse_timer.start(750)
            self.process_button.setStyleSheet(self._original_process_btn_style)
            self.process_button.clicked.connect(self._on_process_clicked)
            self.process_button.setEnabled(False)
            self.speed_spinbox = ClickableSpinBox()
            self.speed_spinbox.setDecimals(1)
            self.speed_spinbox.setSingleStep(0.1)
            self.speed_spinbox.setRange(0.5, 3.1)
            self.speed_spinbox.setValue(1.1)
            self.speed_spinbox.setMinimumWidth(0)
            self.speed_spinbox.setStyleSheet("font-size: 11px;")
            self.speed_spinbox.valueChanged.connect(self._on_speed_changed)
            self.speed_label = QLabel("Speed Multiplier")
            self.speed_label.setStyleSheet("font-size: 11px; font-weight: bold; margin-left: 10px; padding: 0; margin-right: 10px; padding: 0;")
            self.speed_spinbox.setAlignment(Qt.AlignCenter)
            speed_layout = QVBoxLayout(); speed_layout.setContentsMargins(0,0,0,0); speed_layout.setSpacing(2); speed_layout.setAlignment(Qt.AlignHCenter)
            speed_layout.addWidget(self.speed_label, alignment=Qt.AlignHCenter)
            speed_layout.addWidget(self.speed_spinbox, alignment=Qt.AlignHCenter)
            speed_widget = QWidget(); speed_widget.setLayout(speed_layout)
            speed_widget.setMinimumWidth(0)
            speed_widget.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Fixed)
            self.mobile_checkbox = QCheckBox("Mobile Format (Portrait)")
            self.mobile_checkbox.setStyleSheet("font-size: 14px; font-weight: bold; margin-left: 0px; padding: 0; margin-right: 0px; padding: 0;")
            self.mobile_checkbox.setChecked(bool(self.config_manager.config.get('mobile_checked', False)))
            self.teammates_checkbox = QCheckBox("Show Teammates Healthbar")
            self.teammates_checkbox.setStyleSheet("font-size: 11px; margin-left: 15px; margin-right: 0px; padding: 0;")
            self.teammates_checkbox.setChecked(bool(self.config_manager.config.get('teammates_checked', False)))
            self.teammates_checkbox.toggled.connect(lambda c: self.logger.info("OPTION: Show Teammates Healthbar -> %s", c))
            self.no_fade_checkbox = QCheckBox("Disable Fade-In/Out", self)
            self.no_fade_checkbox.setChecked(False)
            _fm = QFontMetrics(self.no_fade_checkbox.font())
            _minw = _fm.horizontalAdvance("Disable Fade-In/Out") + 26
            self.no_fade_checkbox.setMinimumWidth(_minw)
            self.no_fade_checkbox.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
            self.no_fade_checkbox.toggled.connect(
                lambda c: self.logger.info("OPTION: Disable Fade-In/Out -> %s", c)
            )
            def _on_mobile_toggled(checked: bool):
                self.logger.info("OPTION: Mobile Format -> %s", checked)
                self.teammates_checkbox.setVisible(checked)
                self.teammates_checkbox.setEnabled(checked)
                if not checked:
                    self.teammates_checkbox.setChecked(False)
                QTimer.singleShot(0, self._recenter_process_controls)
            self.mobile_checkbox.toggled.connect(_on_mobile_toggled)
            self.teammates_checkbox.setVisible(self.mobile_checkbox.isChecked())
            self.teammates_checkbox.setEnabled(self.mobile_checkbox.isChecked())
            if not self.mobile_checkbox.isChecked():
                self.teammates_checkbox.setChecked(False)
            process_controls = QGridLayout()
            process_controls.setContentsMargins(0, 0, 0, 0)
            process_controls.setHorizontalSpacing(16)
            process_controls.setVerticalSpacing(0)
            left_group = QHBoxLayout()
            left_group.setContentsMargins(0, 0, 0, 0)
            left_group.setSpacing(10)
            left_group.addWidget(self.mobile_checkbox)
            left_group.addWidget(self.teammates_checkbox)
            _left_col = QVBoxLayout()
            _left_col.setContentsMargins(0, 0, 0, 0)
            _left_col.setSpacing(6)
            _left_col.addLayout(left_group)
            self.left_group_widget = QWidget()
            self.left_group_widget.setLayout(_left_col)
            self.left_group_widget.setSizePolicy(QSizePolicy.MinimumExpanding, QSizePolicy.Fixed)
            vbox = QVBoxLayout(); vbox.setContentsMargins(0,0,0,0); vbox.setSpacing(2); vbox.setAlignment(Qt.AlignHCenter)
            vbox.addWidget(self.quality_label, alignment=Qt.AlignHCenter)
            vbox.addWidget(self.quality_slider, alignment=Qt.AlignHCenter)
            vbox.addWidget(self.quality_value_label, alignment=Qt.AlignHCenter)
            self.quality_container = QWidget(); self.quality_container.setLayout(vbox)
            self.quality_container.setMinimumWidth(0)
            self.quality_container.setMaximumWidth(340)
            self.quality_container.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            right_group = QHBoxLayout()
            right_group.setContentsMargins(0, 0, 0, 0)
            right_group.addWidget(self.quality_container, 1)
            right_group.addWidget(speed_widget, 0)
            self.right_group_widget = QWidget(); self.right_group_widget.setLayout(right_group)
            self.right_group_widget.setSizePolicy(QSizePolicy.MinimumExpanding, QSizePolicy.Fixed)
            process_controls.setColumnStretch(0, 1)
            process_controls.setColumnStretch(1, 0)
            process_controls.setColumnStretch(2, 1)
            process_controls.setColumnMinimumWidth(0, 0)
            process_controls.setColumnMinimumWidth(2, 0)
            process_controls.addWidget(self.process_button,     0, 1, 1, 1, Qt.AlignHCenter | Qt.AlignVCenter)
            self._safe_add_to_grid(process_controls, self.left_group_widget,  0, 0, 1, 1, Qt.AlignLeft  | Qt.AlignVCenter)
            self._safe_add_to_grid(process_controls, self.right_group_widget, 0, 2, 1, 1, Qt.AlignRight | Qt.AlignVCenter)
            self.center_btn_container = process_controls
            player_col.addLayout(process_controls)
            QTimer.singleShot(0, self._recenter_process_controls)
            self.mobile_checkbox.toggled.connect(lambda _: QTimer.singleShot(0, self._recenter_process_controls))
            self.quality_slider.valueChanged.connect(lambda _: self._recenter_process_controls())
            self.speed_spinbox.valueChanged.connect(lambda _: self._recenter_process_controls())
            left_layout.addSpacing(-10)
            self.progress_bar = QProgressBar()
            self.progress_bar.setValue(0)
            left_layout.addWidget(self.progress_bar)
            #self._pulse_phase = 0
            self.progress_update_signal.connect(self.on_progress)
            self.status_update_signal.connect(self.on_phase_update)
            self.process_finished_signal.connect(self.on_process_finished)
            self.selected_intro_abs_time = None
            self.thumb_pick_btn.setText("📸 Set Thumbnail 📸")
            def _mirror_overlay_progress(pct: int):
                try:
                    if getattr(self, "_overlay_progress", None):
                        self._overlay_progress.setValue(int(max(0, min(100, pct))))
                except Exception:
                    pass
            self.progress_update_signal.connect(_mirror_overlay_progress)
            self.right_panel = QWidget()
            right_col = QVBoxLayout(self.right_panel)
            self.right_panel.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
            right_col.setContentsMargins(0, 0, 0, 33)
            self.drop_area = DropAreaFrame()
            self.drop_area.setObjectName("dropArea")
            self.drop_area.setFocusPolicy(Qt.NoFocus)
            self.drop_area.file_dropped.connect(self.handle_file_selection)
            drop_layout = QVBoxLayout(self.drop_area)
            drop_layout.setContentsMargins(0, 0, 0, 0)
            self.drop_label = QLabel("Drag & Drop\r\na Video File Here:")
            self.drop_label.setStyleSheet("font-size: 11px; font-weight: bold; margin-top: 0px; margin-right: 0px; margin-bottom: 0px; margin-left: 0px; padding: 0px;")
            self.drop_label.setAlignment(Qt.AlignCenter)
            drop_layout.addWidget(self.drop_label)
            self.drop_area.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
            right_col.addWidget(self.drop_area, stretch=10)
            self.upload_button = QPushButton("📂 Upload Video File 📂")
            self.upload_button.clicked.connect(self.select_file)
            self.upload_button.setFocusPolicy(Qt.NoFocus)
            self.upload_button.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
            self.upload_button.setMaximumWidth(150)
            self.upload_button.setMaximumHeight(45)
            self.upload_button.setMinimumHeight(45)
            self.upload_button.setStyleSheet("font-size: 11px; font-weight: bold; margin-top: 8px; margin-right: 0px; margin-bottom: 0px; margin-left: 0px; padding: 5px;")
            self.drop_area.setStyleSheet("font-size: 11px; font-weight: bold; margin-top: 10px; margin-right: 0px; margin-bottom: 0px; margin-left: 0px; padding: 5px;")
            self.drop_area.setMinimumWidth(150)
            self.drop_area.setMaximumWidth(150)
            right_col.addWidget(self.upload_button, 0, Qt.AlignBottom)
            self.add_music_checkbox = QCheckBox("Add Background Music")
            self.add_music_checkbox.setToolTip("Toggle background MP3 mixing from the ./mp3 folder.")
            self.add_music_checkbox.setChecked(False)
            self.add_music_checkbox.setStyleSheet("font-size: 11px; font-weight: bold; margin-top: 20px; margin-right: 0px; margin-bottom: 20px; margin-left: 0px; padding: 0px;")
            right_col.addWidget(self.add_music_checkbox)
            self.music_combo = QComboBox()
            self.music_combo.setSizeAdjustPolicy(QComboBox.AdjustToContents)
            self.music_combo.setVisible(False)
            right_col.addWidget(self.music_combo)
            self.music_volume_slider = QSlider(Qt.Vertical, self)
            self.music_volume_slider.setObjectName("musicVolumeSlider")
            self.music_volume_slider.setRange(0, 100)
            self.music_volume_slider.setSingleStep(1)
            self.music_volume_slider.setPageStep(15)
            self.music_volume_slider.setTickInterval(1)
            self.music_volume_slider.setTickPosition(QSlider.TicksBothSides)
            self.music_volume_slider.setTracking(True)
            self.music_volume_slider.setVisible(True)
            self.music_volume_slider.setFocusPolicy(Qt.NoFocus)
            self.music_volume_slider.installEventFilter(self)
            eff_default = int(self.config_manager.config.get('last_music_volume', 35))
            raw = self.music_volume_slider.maximum() + self.music_volume_slider.minimum() - eff_default
            _knob = self.positionSlider.palette().highlight().color().name()
            self.music_volume_slider.setStyleSheet(f"""
            QSlider#musicVolumeSlider::groove:vertical {{
            border: 1px solid #4a4a4a;
            background: qlineargradient(x1:0, y1:1, x2:0, y2:0,
                stop:0   #e64c4c,
                stop:0.25 #f7a8a8,
                stop:0.50 #f2f2f2,
                stop:0.75 #7bcf43,
                stop:1   #009b00);
            width: 16px;
            border-radius: 6px;
            }}
            QSlider#musicVolumeSlider::handle:vertical {{
            background: {_knob};
            border: 1px solid #5c5c5c;
            width: 18px; height: 18px;
            margin: -2px 0;
            border-radius: 6px;
            }}
            QSlider#musicVolumeSlider::sub-page:vertical,
            QSlider#musicVolumeSlider::add-page:vertical {{ background: transparent; }}
            """)
            self.music_offset_input = QDoubleSpinBox()
            self.music_offset_input.setPrefix("Music Start (s): ")
            self.music_offset_input.setDecimals(2)
            self.music_offset_input.setSingleStep(0.5)
            self.music_offset_input.setRange(0.0, 0.0)
            self.music_offset_input.setValue(0.0)
            self.music_offset_input.setVisible(False)
            right_col.addWidget(self.music_offset_input)
            self.music_volume_label = QLabel("35%")
            self.music_volume_label.setAlignment(Qt.AlignHCenter)
            self.music_volume_label.setVisible(False)
            self.music_volume_label.setStyleSheet("font-size: 11px; font-weight: bold; margin-top: 10px; margin-right: 0px; margin-bottom: 10px; margin-left: 0px; padding: 0px;")
            init_raw = int(self.music_volume_slider.value())
            init_eff = self._music_eff(init_raw)
            self.music_volume_label.setText(f"{init_eff}%")
            self.music_volume_badge = QLabel("35%", self)
            self.music_volume_badge.setObjectName("musicVolumeBadge")
            self.music_volume_badge.setStyleSheet(
                "color: white; background: rgba(0,0,0,160); padding: 2px 6px; "
                "border-radius: 6px; font-weight: bold;"
            )
            self.music_volume_badge.hide()
            right_col.addWidget(self.music_volume_slider, alignment=Qt.AlignHCenter)
            right_col.addWidget(self.music_volume_label, alignment=Qt.AlignHCenter)
            right_col.addStretch(1)
            bottom_box = QWidget(self.right_panel)
            bottom_box.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Maximum)
            bb = QVBoxLayout(bottom_box)
            bb.setSpacing(28)
            bb.addWidget(self.merge_btn, 0, Qt.AlignCenter)
            bb.addWidget(self.no_fade_checkbox, 0, Qt.AlignRight)
            right_col.addWidget(bottom_box, 0, Qt.AlignBottom | Qt.AlignRight)
            self.music_volume_slider.valueChanged.connect(self._on_music_volume_changed)
            self.music_volume_slider.valueChanged.connect(lambda _: self._update_music_badge())
            QTimer.singleShot(0, self._update_music_badge)
            self.add_music_checkbox.toggled.connect(self._on_add_music_toggled)
            self.music_combo.currentIndexChanged.connect(self._on_music_selected)
            self._populate_music_combo()
            self._top_row.addWidget(self.right_panel, stretch=1)
            self.video_frame.installEventFilter(self)
            main_layout.addLayout(left_layout, stretch=1)
            self.setLayout(main_layout)
            self._ensure_overlay_widgets()
            self._hide_processing_overlay()
            old_resize = getattr(self, "resizeEvent", None)
            def _resized(e):
                if callable(old_resize):
                    old_resize(e)
                try:
                    self._resize_overlay()
                except Exception:
                    pass
            self.resizeEvent = _resized
            QTimer.singleShot(0, self._adjust_trim_margins)
            QTimer.singleShot(0, self.apply_master_volume)
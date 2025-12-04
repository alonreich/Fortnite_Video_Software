from PyQt5.QtCore import Qt, QRect, QPoint, pyqtSignal
from PyQt5.QtGui import QPainter, QColor, QFont, QFontMetrics, QPen, QCursor
from PyQt5.QtWidgets import QSlider, QStyleOptionSlider, QStyle, QToolTip, QApplication

class TrimmedSlider(QSlider):
    trim_times_changed = pyqtSignal(float, float)

    def __init__(self, parent=None):
        super().__init__(Qt.Horizontal, parent)
        self.trimmed_start = None
        self.trimmed_end = None
        self._duration_ms = 0
        self.setMouseTracking(True)
        self.setStyleSheet("""
            QSlider::groove:horizontal {
                background: #4a667a;
                height: 2px;
                border-radius: 4px;
                margin-bottom: 10px;
            }
            QSlider::handle:horizontal {
                background: transparent;
                border: none;
                width: 26px;
                margin: -10px 0;
            }
            QSlider::sub-page:horizontal { background: transparent; border-radius: 4px; }
            QSlider::add-page:horizontal { background: transparent; border-radius: 4px; }
        """)
        self.sliderPressed.connect(self._on_pressed)
        self.sliderReleased.connect(self._on_released)
        self._is_pressed = False
        self._show_trim = True
        self._dragging_handle = None # 'start', 'end', 'playhead', or None
        self._hovering_handle = None # 'start', 'end', 'playhead', or None

    def enable_trim_overlays(self, enabled: bool):
        self._show_trim = bool(enabled)
        self.update()

    def _get_groove_rect(self):
        opt = QStyleOptionSlider()
        self.initStyleOption(opt)
        groove = self.style().subControlRect(QStyle.CC_Slider, opt, QStyle.SC_SliderGroove, self)
        if groove.width() <= 0:
            h = 8
            top = (self.height() - h) // 2
            groove = QRect(8, top, self.width() - 16, h)
        return QRect(groove.left(), groove.center().y() - 2, groove.width(), 4)

    def _map_pos_to_value(self, x_pos):
        groove = self._get_groove_rect()
        if groove.width() <= 0:
            return self.minimum()
        pos = x_pos - groove.left()
        val = QStyle.sliderValueFromPosition(self.minimum(), self.maximum(), pos, groove.width())
        return val

    def _get_handle_rect(self, handle_type):
        if self._duration_ms <= 0: return QRect()

        time_sec = self.trimmed_start if handle_type == 'start' else self.trimmed_end
        if time_sec is None: return QRect()

        groove = self._get_groove_rect()
        minv, maxv = self.minimum(), self.maximum()
        
        def map_to_x(ms):
            if maxv <= minv: return groove.left()
            return int(groove.left() + ((ms - minv) / (maxv - minv)) * groove.width())

        x = map_to_x(time_sec * 1000)
        
        trim_handle_width = 8 # Match caret width
        trim_rect_h = groove.height() + 26 # Match caret height
        trim_rect_y = groove.center().y() - trim_rect_h // 2
        return QRect(x - (trim_handle_width//2), trim_rect_y, trim_handle_width, trim_rect_h)

    def _get_playhead_rect(self):
        groove = self._get_groove_rect()
        minv, maxv = self.minimum(), self.maximum()
        
        def map_to_x(ms):
            if maxv <= minv: return groove.left()
            return int(groove.left() + ((ms - minv) / (maxv - minv)) * groove.width())

        cx = map_to_x(self.value())
        playhead_width = 10 
        playhead_height = groove.height() + 26
        playhead_y = groove.center().y() - playhead_height // 2
        return QRect(cx - playhead_width // 2, playhead_y, playhead_width, playhead_height)

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            playhead_rect = self._get_playhead_rect()
            if playhead_rect.contains(e.pos()):
                self._dragging_handle = 'playhead'
                self.update()
                return

            if self._show_trim:
                start_handle_rect = self._get_handle_rect('start')
                end_handle_rect = self._get_handle_rect('end')
                if start_handle_rect.contains(e.pos()):
                    self._dragging_handle = 'start'
                    self.update()
                    return
                elif end_handle_rect.contains(e.pos()):
                    self._dragging_handle = 'end'
                    self.update()
                    return

        # Fallback to default behavior if not dragging a handle, but still allow slider to move
        if e.button() == Qt.LeftButton and not self._dragging_handle:
            val = self._map_pos_to_value(e.pos().x())
            self.setSliderPosition(val)
            self.sliderMoved.emit(val)
        
        super().mousePressEvent(e)
    
    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._dragging_handle = None
            self.update()
        super().mouseReleaseEvent(e)

    def set_duration_ms(self, ms: int):
        self._duration_ms = max(0, int(ms))
        self.update()

    def _fmt(self, ms: int) -> str:
        s = max(0, ms // 1000)
        h, s = divmod(s, 3600)
        m, s = divmod(s, 60)
        return f"{h:d}:{m:02d}:{s:02d}" if h else f"{m:d}:{s:02d}"
    
    def mouseMoveEvent(self, e):
        if self._dragging_handle == 'playhead':
            new_val = self._map_pos_to_value(e.pos().x())
            if new_val != self.sliderPosition():
                self.setSliderPosition(new_val)
                self.sliderMoved.emit(new_val)
                self.update()
            return
        elif self._dragging_handle in ('start', 'end'):
            new_val = self._map_pos_to_value(e.pos().x())
            new_time_sec = (new_val / self.maximum()) * (self._duration_ms / 1000.0) if self.maximum() > 0 else 0

            new_start = self.trimmed_start
            new_end = self.trimmed_end

            if self._dragging_handle == 'start':
                new_start = min(new_time_sec, (self.trimmed_end or 0) - 0.01)
                new_start = max(0.0, new_start)
            elif self._dragging_handle == 'end':
                new_end = max(new_time_sec, (self.trimmed_start or 0) + 0.01)
                new_end = min(self._duration_ms / 1000.0, new_end)
            
            if new_start != self.trimmed_start or new_end != self.trimmed_end:
                self.trimmed_start = new_start
                self.trimmed_end = new_end
                self.trim_times_changed.emit(self.trimmed_start, self.trimmed_end)
            self.update()
            return

        # Handle hover effects
        new_hover_handle = None
        playhead_rect = self._get_playhead_rect()
        if playhead_rect.contains(e.pos()):
            new_hover_handle = 'playhead'
        elif self._show_trim:
            start_handle_rect = self._get_handle_rect('start')
            end_handle_rect = self._get_handle_rect('end')
            if start_handle_rect.contains(e.pos()):
                new_hover_handle = 'start'
            elif end_handle_rect.contains(e.pos()):
                new_hover_handle = 'end'

        if self._hovering_handle != new_hover_handle:
            self._hovering_handle = new_hover_handle
            self.setCursor(QCursor(Qt.PointingHandCursor) if self._hovering_handle else QCursor(Qt.ArrowCursor))
            self.update() # Repaint to show hover effect
        
        # Fallback to default behavior if not dragging a handle
        if self._is_pressed and not self._dragging_handle:
            val = self._map_pos_to_value(e.pos().x())
            if val != self.sliderPosition():
                self.setSliderPosition(val)
                self.sliderMoved.emit(val)

        super().mouseMoveEvent(e)
        #if self._duration_ms > 0 and self.maximum() > 0 and not self._dragging_handle and not self._hovering_handle:
        #    val = self._map_pos_to_value(e.pos().x())
        #    ms = (val / max(1, self.maximum())) * self._duration_ms
        #    QToolTip.showText(self.mapToGlobal(e.pos()), self._fmt(int(ms)), self)

    def _on_pressed(self):
        if not self._dragging_handle: # Only set _is_pressed if not already dragging a specific handle
            self._is_pressed = True

    def _on_released(self):
        self._is_pressed = False
        self._dragging_handle = None

    def set_trim_times(self, start, end):
        self.trimmed_start = start
        self.trimmed_end = end
        self.update()

    def paintEvent(self, event):
        super().paintEvent(event)
        p = QPainter(self)
        try:
            p.setRenderHint(QPainter.Antialiasing)
            p.fillRect(self.rect(), QColor(44, 62, 80, 255))

            f = QFont(self.font())
            groove_rect = self._get_groove_rect()
            minv, maxv = self.minimum(), self.maximum()
            def map_to_x(ms):
                if maxv <= minv: return groove_rect.left()
                return int(groove_rect.left() + ((ms - minv) / (maxv - minv)) * groove_rect.width())

            # Draw base groove (grey)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor("#3d3d3d"))
            p.drawRoundedRect(groove_rect, 2, 2)

            # Draw filled "kept" range on top
            if self.trimmed_start is not None and self.trimmed_end is not None:
                fill_color = QColor("#59B1D5") # Brighter color
                fill_color.setAlpha(150)
                p.setBrush(fill_color)
                
                kept_left = map_to_x(self.trimmed_start * 1000)
                kept_right = map_to_x(self.trimmed_end * 1000)
                
                if kept_left > kept_right:
                    kept_left, kept_right = kept_right, kept_left
                
                kept_rect = QRect(kept_left, groove_rect.y(), kept_right - kept_left, groove_rect.height())
                p.drawRect(kept_rect)

            # Draw timeline labels and ticks
            if self._duration_ms > 0 and groove_rect.width() > 10:
                f.setPointSize(max(10, f.pointSize()))
                p.setFont(f)
                fm = QFontMetrics(f)
                
                major_tick_pixels = 120 
                num_major_ticks = max(1, int(round(groove_rect.width() / major_tick_pixels)))
                
                for i in range(num_major_ticks + 1):
                    ratio = i / float(num_major_ticks)
                    ms = self._duration_ms * ratio
                    x = groove_rect.left() + int(ratio * groove_rect.width())
                    
                    is_obscured = False
                    start_handle_rect = self._get_handle_rect('start')
                    end_handle_rect = self._get_handle_rect('end')
                    if start_handle_rect.isValid() and (abs(x - start_handle_rect.center().x()) < (start_handle_rect.width() / 2 + 5) or \
                       abs(x - end_handle_rect.center().x()) < (end_handle_rect.width() / 2 + 5)):
                        is_obscured = True
                    
                    playhead_rect = self._get_playhead_rect()
                    if playhead_rect.isValid() and abs(x - playhead_rect.center().x()) < (playhead_rect.width() / 2 + 5):
                        is_obscured = True

                    if not is_obscured:
                        p.setPen(QColor(180, 180, 180))
                        p.drawLine(x, groove_rect.bottom() + 1, x, groove_rect.bottom() + 6)
                        
                        time_str = self._fmt(int(ms))
                        text_width = fm.horizontalAdvance(time_str)
                        p.drawText(x - text_width // 2, groove_rect.bottom() + 18, time_str)

            # Draw trim handles
            for handle_type in ['start', 'end']:
                handle_rect = self._get_handle_rect(handle_type)
                if not handle_rect.isValid(): continue

                color = QColor(0, 0, 0, 150)
                if self._hovering_handle == handle_type or self._dragging_handle == handle_type:
                    color = QColor(230, 126, 34, 200)
                
                p.setPen(Qt.NoPen)
                p.setBrush(color)
                p.drawRoundedRect(handle_rect, 4, 4)

            # Draw playhead
            playhead_rect = self._get_playhead_rect()
            if playhead_rect.isValid():
                playhead_color = QColor("#59B1D5") # Brighter color
                if self._hovering_handle == 'playhead' or self._dragging_handle == 'playhead':
                    playhead_color = QColor(255, 170, 0, 255)
                
                p.setPen(Qt.NoPen)
                p.setBrush(playhead_color)
                p.drawRoundedRect(playhead_rect, 4, 4)

        finally:
            if p.isActive():
                p.end()

    def map_value_to_pixel(self, value):
        style = QApplication.style()
        style_option = QStyleOptionSlider()
        self.initStyleOption(style_option)
        style_option.initFrom(self)
        style_option.orientation = self.orientation()
        style_option.minimum = self.minimum()
        style_option.maximum = self.maximum()
        style_option.sliderPosition = value
        return style.sliderPositionFromValue(style_option.minimum, style_option.maximum, value, self.width())

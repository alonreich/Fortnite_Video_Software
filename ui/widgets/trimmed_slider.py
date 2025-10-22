from PyQt5.QtCore import Qt, QRect, QPoint
from PyQt5.QtGui import QPainter, QColor, QFont, QFontMetrics, QPen
from PyQt5.QtWidgets import QSlider, QStyleOptionSlider, QStyle, QToolTip, QApplication

class TrimmedSlider(QSlider):
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

    def enable_trim_overlays(self, enabled: bool):
        self._show_trim = bool(enabled)
        self.update()
    
    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            opt = QStyleOptionSlider()
            self.initStyleOption(opt)
            groove = self.style().subControlRect(QStyle.CC_Slider, opt, QStyle.SC_SliderGroove, self)
            groove.translate(0, -12)
            if groove.width() > 0:
                x = max(groove.left(), min(e.pos().x(), groove.right()))
                pos = x - groove.left()
                val = QStyle.sliderValueFromPosition(self.minimum(), self.maximum(), pos, groove.width())
                self.setSliderPosition(val)
                self.sliderMoved.emit(val)
                self.update()
        super().mousePressEvent(e)
    
    def set_duration_ms(self, ms: int):
        self._duration_ms = max(0, int(ms))
        self.update()

    def _fmt(self, ms: int) -> str:
        s = max(0, ms // 1000)
        h, s = divmod(s, 3600)
        m, s = divmod(s, 60)
        return f"{h:d}:{m:02d}:{s:02d}" if h else f"{m:d}:{s:02d}"
    
    def mouseMoveEvent(self, e):
        if getattr(self, "_is_pressed", False):
            opt = QStyleOptionSlider()
            self.initStyleOption(opt)
            groove = self.style().subControlRect(QStyle.CC_Slider, opt, QStyle.SC_SliderGroove, self)
            groove.translate(0, -12)
            if groove.width() > 0:
                x = max(groove.left(), min(e.pos().x(), groove.right()))
                pos = x - groove.left()
                val = QStyle.sliderValueFromPosition(self.minimum(), self.maximum(), pos, groove.width())
                if val != self.sliderPosition():
                    self.setSliderPosition(val)
                    self.sliderMoved.emit(val)
                    self.update()
        super().mouseMoveEvent(e)
        if self._duration_ms > 0 and self.maximum() > 0:
            x = e.pos().x()
            val = self.minimum() + (self.maximum() - self.minimum()) * max(0, min(x, self.width())) / max(1, self.width())
            ms = int((val / max(1, self.maximum())) * self._duration_ms)
            QToolTip.showText(self.mapToGlobal(e.pos()), self._fmt(ms), self)

    def _on_pressed(self):
        self._is_pressed = True

    def _on_released(self):
        self._is_pressed = False

    def set_trim_times(self, start, end):
        self.trimmed_start = start
        self.trimmed_end = end
        self.update()

    def paintEvent(self, event):
        super().paintEvent(event)
        opt = QStyleOptionSlider()
        self.initStyleOption(opt)
        groove = self.style().subControlRect(QStyle.CC_Slider, opt, QStyle.SC_SliderGroove, self)
        if groove.width() <= 0:
            h = 8
            top = (self.height() - h) // 2
            groove = QRect(8, top, self.width() - 16, h)
        groove.translate(0, -12)
        minv, maxv = self.minimum(), self.maximum()
        def map_to_x(ms):
            if maxv == minv:
                return groove.left()
            ratio = (ms - minv) / float(maxv - minv)
            return int(groove.left() + ratio * groove.width())
        if (self.trimmed_start is not None) and (self.trimmed_end is not None):
            start_ms = int(self.trimmed_start * 1000)
            end_ms   = int(self.trimmed_end   * 1000)
            start_x  = map_to_x(start_ms)
            end_x    = map_to_x(end_ms)
            left_x, right_x = (start_x, end_x) if start_x <= end_x else (end_x, start_x)
        else:
            start_x = end_x = left_x = right_x = None
        p = QPainter(self)
        try:
            p.setRenderHint(QPainter.Antialiasing)
            p.fillRect(self.rect(), QColor(44, 62, 80, 255))
            f = QFont(self.font())
            f.setPointSize(max(10, f.pointSize() + 1))
            p.setFont(f)
            cx = map_to_x(self.value())
            bar_w  = 14
            bar_h  = groove.height() + 22
            cy   = groove.center().y()
            top  = max(3, cy - bar_h // 2)
            bar  = QRect(cx - bar_w // 2, top, bar_w, bar_h)
            if self._show_trim and (start_x is not None):
                p.setPen(Qt.NoPen)
                p.setBrush(QColor(200, 200, 200, 140))
                if left_x > groove.left():
                    p.drawRect(groove.left(), groove.top(), left_x - groove.left(), groove.height())
                if right_x < groove.right():
                    p.drawRect(right_x, groove.top(), groove.right() - right_x + 1, groove.height())
                p.setBrush(QColor(46, 204, 113, 180))
                p.drawRect(left_x, groove.top(), max(0, right_x - left_x), groove.height())
                p.setBrush(QColor(30, 200, 255))
                p.drawRect(start_x - bar_w // 2, groove.top() - 2, bar_w, groove.height() + 4)
                p.setBrush(QColor(30, 200, 255))
                p.drawRect(end_x - bar_w // 2, groove.top() - 2, bar_w, groove.height() + 4)
            label_strip_top = groove.bottom() + 1
            label_strip_h   = 28
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(44, 62, 80, 255))
            p.drawRect(QRect(groove.left(), label_strip_top, groove.width(), label_strip_h))
            p.setPen(QColor(30, 40, 50))
            p.drawLine(groove.left(), label_strip_top, groove.right(), label_strip_top)
            if getattr(self, "_duration_ms", 0) > 0 and self.maximum() > 0:
                fm = p.fontMetrics()
                maxv = max(1, self.maximum())
                ms_now = int((max(0, self.value()) / maxv) * self._duration_ms)
                live = self._fmt(ms_now)
                pad_w, pad_h = 10, 6
                tw = fm.width(live) + pad_w
                th = fm.height() + pad_h
                if cx + 14 + tw <= self.width() - 2:
                    tx = cx + 14
                else:
                    tx = max(2, cx - tw - 14)
                ty = max(2, label_strip_top - th - 8)
                rect = QRect(tx, ty, tw, th)
                p.setPen(QColor(30, 40, 50))
                p.setBrush(QColor(62, 80, 99, 230))
                p.drawRoundedRect(rect, 6, 6)
                p.setPen(QColor(240, 240, 240))
                p.drawText(rect, Qt.AlignCenter, live)
            if getattr(self, "_duration_ms", 0) > 0 and self.maximum() > 0:
                fm = p.fontMetrics()
                w = self.width()
                groove_y = label_strip_top + 3
                dur_s = max(1.0, self._duration_ms / 1000.0)
                maxv = self.maximum()
                def x_for(sec):
                    val = (sec * 1000) / self._duration_ms * maxv
                    return int(groove.left() + (val / max(1, maxv)) * groove.width())
                px_per_sec = groove.width() / dur_s
                target_px  = 70.0
                candidates = [1, 2, 5, 10, 15, 20, 30, 60, 120, 300, 600, 900, 1200, 1800]
                label_step = candidates[-1]
                for s in candidates:
                    if s * px_per_sec >= target_px:
                        label_step = s
                        break
                minor = max(1, int(round(label_step / 5.0)))
                major = int(label_step)
                sec = 0
                sec = 0
                pen_minor = QPen(QColor(200, 210, 220, 170), 1)
                p.setPen(pen_minor)
                while sec <= int(dur_s + 0.5):
                    x = x_for(sec)
                    p.drawLine(x, groove_y, x, groove_y + 4)
                    sec += minor
                sec = 0
                pen_major = QPen(QColor(235, 242, 250), 2)
                p.setPen(pen_major)
                while sec <= int(dur_s + 0.5):
                    x = x_for(sec)
                    p.drawLine(x, groove_y, x, groove_y + 8)
                    label = self._fmt(int(sec * 1000))
                    tw = fm.width(label)
                    if abs(x - cx) > (tw // 2 + 6):
                        tx = max(0, min(w - tw, x - tw // 2))
                        p.drawText(QPoint(tx, groove_y + 10 + fm.ascent()), label)
                    sec += major
            pen = QPen(QColor(10, 10, 10)); pen.setWidth(2)
            p.setPen(pen)
            p.setBrush(QColor("#531616"))
            p.drawRoundedRect(bar, 3, 3)
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
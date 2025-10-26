from PyQt5.QtCore import QEvent, Qt, QRect
from PyQt5.QtGui import QPainter, QColor, QFont, QPen

class EventsMixin:
        def eventFilter(self, obj, event):
            if obj is getattr(self, "_overlay", None) and event.type() == QEvent.Paint:
                p = QPainter(self._overlay)
                try:
                    p.setRenderHint(QPainter.Antialiasing)
                    p.fillRect(self._overlay.rect(), QColor(0, 0, 0, 165))
                    panel = self._graph.geometry()
                    p.fillRect(panel, QColor(12, 22, 32, 235))
                    p.setPen(QColor(190, 190, 190))
                    p.setBrush(Qt.NoBrush)
                    p.drawRect(panel.adjusted(0, 0, -1, -1))
                    f = QFont(self.font()); f.setPointSize(11); p.setFont(f)
                    left  = panel.left() + 80
                    top   = panel.top()  + 24
                    right = panel.right() - 16
                    bottom= panel.bottom() - 16
                    w     = max(1, right - left)
                    h     = max(1, bottom - top)
                    gap   = 12
                    bands = 4
                    band_h = (h - gap*(bands-1)) // bands
                    def band_rect(row: int):
                        y0 = top + row * (band_h + gap)
                        return QRect(left, y0, w, band_h)
                    def draw_band_frame(r: QRect):
                        pen_axes = QPen(QColor(230,230,230)); pen_axes.setWidth(2)
                        p.setPen(pen_axes); p.drawRect(r)
                        pen_grid = QPen(QColor(130,130,130)); pen_grid.setStyle(Qt.DashLine)
                        p.setPen(pen_grid); p.drawLine(r.left(), r.center().y(), r.right(), r.center().y())
                    def plot_band(hist, label, color, row):
                        r = band_rect(row)
                        draw_band_frame(r)
                        last = int(list(hist)[-1]) if hist else 0
                        p.setPen(QColor(240,240,240))
                        p.drawText(panel.left()+12, r.top()+14, label)
                        p.drawText(r.right()-36,   r.top()+14, f"{last}%")
                        vals = list(hist)[-(r.width()-2):] if hist else []
                        if not vals:
                            return
                        plot_left  = r.left()+1
                        plot_right = r.right()-1
                        plot_w     = max(1, plot_right - plot_left)
                        scale_h    = r.height()-18
                        base_y     = r.bottom()-8
                        pen_line = QPen(color); pen_line.setWidth(2); p.setPen(pen_line)
                        prev = None
                        pad = plot_w - len(vals)
                        for i, v in enumerate(vals):
                            x = plot_left + max(0, pad) + i
                            v = max(0, min(100, int(v)))
                            y = base_y - int((v/100.0) * scale_h)
                            if prev: p.drawLine(prev[0], prev[1], x, y)
                            prev = (x, y)
                        p.drawEllipse(prev[0]-2, prev[1]-2, 4, 4)
                    plot_band(self._cpu_hist,  "CPU %",   QColor(70, 210, 255), 0)
                    plot_band(self._gpu_hist,  "GPU %",   QColor(80, 255, 150), 1)
                    plot_band(self._mem_hist,  "MEM %",   QColor(255, 165, 90),  2)
                    plot_band(self._iops_hist, "IOPS %",  QColor(255, 210, 80),  3)
                finally:
                    p.end()
                return True
            if obj is getattr(self, "video_frame", None):
                if event.type() == QEvent.KeyPress and event.key() == Qt.Key_Space:
                    self.toggle_play()
                    return True
                if event.type() in (QEvent.Resize, QEvent.Move):
                    try:
                        self._layout_volume_slider()
                        self._update_volume_badge()
                    except Exception:
                        pass
                    return False
            return super().eventFilter(obj, event)

        def keyPressEvent(self, event):
            if event.key() == Qt.Key_Space:
                self.toggle_play()
                event.accept()
            elif event.key() in (Qt.Key_Left, Qt.Key_Right):
                try:
                    is_fine_seek = bool(event.modifiers() & Qt.ControlModifier)
                    normal_seek_ms = 300
                    fine_seek_ms = 7
                    seek_amount_ms = fine_seek_ms if is_fine_seek else normal_seek_ms
                    if event.key() == Qt.Key_Left:
                        seek_amount_ms = -seek_amount_ms
                    if hasattr(self, 'vlc_player') and hasattr(self, 'positionSlider'):
                        current_ms = int(self.vlc_player.get_time() or 0)
                        max_ms = int(self.positionSlider.maximum() or 0)
                        new_ms = current_ms + seek_amount_ms
                        new_ms = max(0, min(max_ms, new_ms)) # Clamp within bounds
                        if hasattr(self, 'set_vlc_position'):
                            self.set_vlc_position(new_ms)
                            self.positionSlider.blockSignals(True)
                            self.positionSlider.setValue(new_ms)
                            self.positionSlider.blockSignals(False)
                        event.accept()
                    else:
                        super().keyPressEvent(event)
                except Exception as e:
                     if hasattr(self, 'logger'):
                         self.logger.error("Error during keyboard seek: %s", e)
                     super().keyPressEvent(event)
            else:
                super().keyPressEvent(event)

        def resizeEvent(self, event):
            self._update_window_size_in_title()
            try:
                self._layout_volume_slider()
                self._update_volume_badge()
            except Exception:
                pass
            try:
                if getattr(self, "_overlay", None) and self._overlay.isVisible():
                    gw, gh = self._graph.width(), self._graph.height()
                    x = max(10, (self._overlay.width()  - gw) // 2)
                    y = max(10, int(self._overlay.height() * 0.06))
                    self._graph.move(x, y)
                    self._update_overlay_mask()
            except Exception:
                pass
            try:
                player_container = getattr(self, 'player_col_container', None)
                trim_container = getattr(self, 'trim_container', None)
                if player_container is not None and trim_container is not None:
                    player_w = player_container.width()
                    video_w = self.video_frame.width()
                    pad = max(0, (player_w - video_w) // 2)
                    trim_container.setContentsMargins(pad, 0, pad, 0)
            except Exception:
                pass
            return super().resizeEvent(event)
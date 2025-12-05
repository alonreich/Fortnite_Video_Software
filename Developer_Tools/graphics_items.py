from PyQt5.QtWidgets import QGraphicsObject, QGraphicsRectItem, QGraphicsItem
from PyQt5.QtCore import Qt, pyqtSignal, QRectF, QTimer
from PyQt5.QtGui import QBrush, QColor, QPen

class ResizablePixmapItem(QGraphicsObject):
    item_changed = pyqtSignal()
    def __init__(self, pixmap, crop_rect, parent=None):
        super(ResizablePixmapItem, self).__init__(parent)
        self.original_pixmap = pixmap 
        self.crop_rect = crop_rect
        self.current_width = pixmap.width()
        self.current_height = pixmap.height()
        self.setFlags(QGraphicsItem.ItemIsMovable | QGraphicsItem.ItemIsSelectable | QGraphicsItem.ItemSendsGeometryChanges)
        self.setAcceptHoverEvents(True)
        self.handle = QGraphicsRectItem(QRectF(0, 0, 10, 10), self)
        self.handle.setBrush(QBrush(QColor("red")))
        self.update_handle_position()
        self.is_resizing = False
        self.ant_timer = QTimer(self)
        self.ant_timer.timeout.connect(self.update_ant_dash)
        self.ant_dash_offset = 0

    def update_ant_dash(self):
        self.ant_dash_offset += 1
        if self.ant_dash_offset > 7:
            self.ant_dash_offset = 0
        self.update()

    def boundingRect(self):
        return QRectF(0, 0, self.current_width, self.current_height)

    def paint(self, painter, option, widget):
        painter.drawPixmap(self.boundingRect(), self.original_pixmap, QRectF(self.original_pixmap.rect()))
        if self.isSelected():
            pen = QPen(QColor("white"), 1, Qt.CustomDashLine)
            pen.setDashPattern([4, 4])
            pen.setDashOffset(self.ant_dash_offset)
            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush)
            painter.drawRect(self.boundingRect())

    def update_handle_position(self):
        self.handle.setPos(self.current_width - 10, self.current_height - 10)

    def hoverMoveEvent(self, event):
        if self.handle.isUnderMouse():
            self.setCursor(Qt.SizeFDiagCursor)
        else:
            self.setCursor(Qt.ArrowCursor)
        super(ResizablePixmapItem, self).hoverMoveEvent(event)

    def mousePressEvent(self, event):
        if self.handle.isUnderMouse():
            self.is_resizing = True
            self.resize_start_pos = event.pos()
            self.start_width = self.current_width
            self.start_height = self.current_height
        else:
            super(ResizablePixmapItem, self).mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self.is_resizing:
            delta = event.pos() - self.resize_start_pos
            new_width = self.start_width + delta.x()
            aspect_ratio = self.original_pixmap.width() / self.original_pixmap.height()
            new_height = new_width / aspect_ratio
            if new_width > 10 and new_height > 10:
                self.prepareGeometryChange()
                self.current_width = new_width
                self.current_height = new_height
                self.update_handle_position()
                self.item_changed.emit()
        else:
            super(ResizablePixmapItem, self).mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self.is_resizing = False
        super(ResizablePixmapItem, self).mouseReleaseEvent(event)
        self.item_changed.emit()

    def itemChange(self, change, value):
        if change == QGraphicsItem.ItemSelectedHasChanged:
            if value:
                self.ant_timer.start(100)
            else:
                self.ant_timer.stop()
        elif change == QGraphicsItem.ItemPositionHasChanged:
            real_x = value.x() * 2
            real_y = value.y() * 2
            print(f"Debug - Item moved to (1150x1920): x={real_x:.0f}, y={real_y:.0f}")
            self.item_changed.emit()
        return super(ResizablePixmapItem, self).itemChange(change, value)

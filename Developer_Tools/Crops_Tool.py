# Required pip packages for this script:
# pip install --upgrade pip
# pip install PyQt5
# pip install python-vlc
# pip install Pillow
# pip install pypiwin32
# pip install pynput
# pip install opencv-python
# pip install PyQtWebEngine

import sys
import os
import ctypes
import tempfile
import vlc
import json
import subprocess
from PyQt5.QtWidgets import (
    QApplication, QWidget, QPushButton, QHBoxLayout, QVBoxLayout,
    QFileDialog, QLabel, QSlider, QStyle, QStackedWidget,
    QGraphicsScene, QGraphicsView, QGraphicsPixmapItem,
    QGraphicsItem, QGraphicsRectItem, QGraphicsObject,
    QDialog, QTextEdit, QMessageBox
)
from PyQt5.QtCore import Qt, QPoint, QRect, QTimer, pyqtSignal, QRectF, QSizeF
from PyQt5.QtGui import QPainter, QPen, QBrush, QColor, QPixmap, QCursor

PORTRAIT_WINDOW_STYLESHEET = """
QWidget { background-color: #2c3e50; color: #ecf0f1; font-family: 'Helvetica Neue', Arial, sans-serif; }
QLabel { font-size: 12px; padding: 5px; }
QPushButton {
    background-color: #3986ae;
    color: #ffffff;
    border: none;
    padding: 5px;
    border-radius: 6px;
    font-weight: bold;
    min-width: 140px;
    font-size: 11px;
}
QPushButton:hover { background-color: #2980b9; }
"""

CROP_APP_STYLESHEET = """
QWidget { background-color: #2c3e50; color: #ecf0f1; font-family: 'Helvetica Neue', Arial, sans-serif; }
QLabel { font-size: 12px; padding: 5px; }
QSlider::groove:horizontal { border: 1px solid #3986ae; height: 8px; background: #34495e; margin: 2px 0; }
QSlider::handle:horizontal { background: #3986ae; border: 1px solid #2980b9; width: 18px; margin: -2px 0; border-radius: 3px; }
QPushButton { 
    background-color: #3986ae; 
    color: #ffffff; 
    border: none; 
    padding: 10px 18px; 
    border-radius: 8px; 
    font-weight: bold; 
}
QPushButton:hover { background-color: #2980b9; }
"""

class FinishedDialog(QDialog):
    def __init__(self, data_string, parent=None):
        super(FinishedDialog, self).__init__(parent)
        self.setWindowTitle("Crop Information")
        self.setMinimumWidth(500)
        self.setMinimumHeight(400)
        self.text_edit = QTextEdit(self)
        self.text_edit.setReadOnly(True)
        self.text_edit.setText(data_string)
        self.copy_button = QPushButton("Copy to Clipboard", self)
        self.copy_button.clicked.connect(self.copy_text)
        layout = QVBoxLayout(self)
        layout.addWidget(self.text_edit)
        layout.addWidget(self.copy_button)
        self.setLayout(layout)

    def copy_text(self):
        QApplication.clipboard().setText(self.text_edit.toPlainText())

class PortraitWindow(QWidget):
    def __init__(self, original_resolution, config_path, parent=None):
        super(PortraitWindow, self).__init__(parent)
        self.original_resolution = original_resolution
        self.config_path = config_path
        self.setWindowTitle("Portrait Composer (1150x1920)")
        self.setFixedSize(575, 960) # Scaled down 1150x1920 (50%)
        self.load_settings()
        self.scene = QGraphicsScene(self)
        self.scene.setSceneRect(0, 0, 575, 960)
        self.view = QGraphicsView(self.scene, self)
        self.view.setRenderHint(QPainter.Antialiasing)
        self.view.setRenderHint(QPainter.SmoothPixmapTransform)
        self.view.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.view.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.finished_button = QPushButton("Show Cropps Coordinate")
        self.finished_button.clicked.connect(self.on_finished)
        self.delete_button = QPushButton("Delete Selected Cropped Piece")
        self.delete_button.clicked.connect(self.delete_selected)
        self.pos_label = QLabel("Position: ")
        self.scale_label = QLabel("Size: ")
        self.set_style()
        layout = QVBoxLayout(self)
        layout.addWidget(self.view)
        info_layout = QHBoxLayout()
        info_layout.addWidget(self.pos_label)
        info_layout.addWidget(self.scale_label)
        layout.addLayout(info_layout)
        buttons_layout = QHBoxLayout()
        buttons_layout.addWidget(self.finished_button)
        buttons_layout.addWidget(self.delete_button)
        layout.addLayout(buttons_layout)
        self.setLayout(layout)
        self.scene.selectionChanged.connect(self.on_selection_changed)

    def set_background(self, pixmap):
        if not pixmap.isNull():
            bg_item = QGraphicsPixmapItem(pixmap.scaled(int(self.scene.width()), int(self.scene.height()), Qt.KeepAspectRatio, Qt.SmoothTransformation))
            bg_item.setZValue(-1)
            self.scene.addItem(bg_item)

    def set_style(self):
        self.setStyleSheet(PORTRAIT_WINDOW_STYLESHEET)
        self.delete_button.setStyleSheet("background-color: #c0392b; color: white;")

    def on_selection_changed(self):
        try:
            self.scene.selectionChanged.disconnect(self.on_selection_changed)
        except TypeError:
            pass 
        selected_items = self.scene.selectedItems()
        if len(selected_items) > 1:
            current_item = selected_items[0]
            for item in selected_items[1:]:
                item.setSelected(False)
            selected_items = [current_item]
        if selected_items:
            item = selected_items[0]
            for i in self.scene.items():
                if isinstance(i, ResizablePixmapItem):
                    try:
                        i.item_changed.disconnect()
                    except TypeError:
                        pass
            item.item_changed.connect(lambda: self.update_item_info(item))
            self.update_item_info(item)
        else:
            self.pos_label.setText("Position: ")
            self.scale_label.setText("Size: ")
        self.scene.selectionChanged.connect(self.on_selection_changed)

    def add_scissored_item(self, pixmap, crop_rect):
        item = ResizablePixmapItem(pixmap, crop_rect)
        self.scene.addItem(item)
        item.setPos(self.scene.width()/2 - item.boundingRect().width()/2,
                    self.scene.height()/2 - item.boundingRect().height()/2)
        item.setSelected(True)
        self.update_item_info(item)

    def update_item_info(self, item):
        pos = item.pos()
        real_x = pos.x() * 2
        real_y = pos.y() * 2
        self.pos_label.setText(f"Pos (1150x1920): x={real_x:.0f}, y={real_y:.0f}")
        current_w = item.boundingRect().width()
        current_h = item.boundingRect().height()
        real_w = current_w * 2
        real_h = current_h * 2
        self.scale_label.setText(f"Size: {real_w:.0f}x{real_h:.0f}")

    def delete_selected(self):
        for item in self.scene.selectedItems():
            self.scene.removeItem(item)

    def load_settings(self):
        try:
            with open(self.config_path, 'r') as f:
                settings = json.load(f)
                geom = settings.get('portrait_window_geometry')
                if geom:
                    self.move(geom['x'], geom['y'])
        except (FileNotFoundError, json.JSONDecodeError):
            pass 

    def closeEvent(self, event):
        if hasattr(self, 'parent_window') and self.parent_window:
            self.parent_window.show()
        try:
            with open(self.config_path, 'r') as f:
                settings = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            settings = {}
        settings['portrait_window_geometry'] = {
            'x': self.geometry().x(),
            'y': self.geometry().y(),
        }
        try:
            with open(self.config_path, 'w') as f:
                json.dump(settings, f, indent=4)
        except Exception as e:
            print(f"Error saving portrait window settings: {e}")
        super().closeEvent(event)

    def on_finished(self):
        print("--- on_finished ---")
        data = []
        data.append(f"Original Video Resolution: {getattr(self, 'original_resolution', 'N/A')}")
        data.append("Target Canvas: 1150x1920")
        for item in self.scene.items():
            if isinstance(item, ResizablePixmapItem):
                data.append("---")
                crop_rect = item.crop_rect
                data.append(f"SOURCE CROP (Original): crop={crop_rect.width()}:{crop_rect.height()}:{crop_rect.x()}:{crop_rect.y()}")
                pos = item.pos()
                real_x = pos.x() * 2
                real_y = pos.y() * 2
                current_rect = item.boundingRect()
                target_w = current_rect.width() * 2
                target_h = current_rect.height() * 2
                data.append(f"FFMPEG COMMANDS (1:1 Match):")
                data.append(f"  filter: scale={target_w:.0f}:{target_h:.0f}")
                data.append(f"  overlay: {real_x:.0f}:{real_y:.0f}")
        dialog = FinishedDialog("\n".join(data), self)
        dialog.exec_()

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

    def boundingRect(self):
        return QRectF(0, 0, self.current_width, self.current_height)

    def paint(self, painter, option, widget):
        painter.drawPixmap(self.boundingRect(), self.original_pixmap, QRectF(self.original_pixmap.rect()))

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
        if change == QGraphicsItem.ItemPositionHasChanged:
            real_x = value.x() * 2
            real_y = value.y() * 2
            print(f"Debug - Item moved to (1150x1920): x={real_x:.0f}, y={real_y:.0f}")
            self.item_changed.emit()
        return super(ResizablePixmapItem, self).itemChange(change, value)

class DrawWidget(QWidget):
    def __init__(self, parent=None):
        super(DrawWidget, self).__init__(parent)
        self.begin = QPoint()
        self.end = QPoint()
        self.mode = 'none' # none, drawing, moving, resizing
        self.resize_edge = None
        self._crop_rect = QRect()
        self.pixmap = QPixmap()
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.handle_size = 10

    def clear_selection(self):
        self._crop_rect = QRect()
        self.update()

    def setImage(self, image_path):
        self.pixmap = QPixmap(image_path)
        self.update()

    def get_selection(self):
        if self.pixmap.isNull() or self._crop_rect.isNull() or not self._crop_rect.isValid():
            return None, None
        widget_rect = self.rect()
        pixmap_rect = self.pixmap.rect()
        scaled_pixmap = self.pixmap.scaled(widget_rect.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
        scaled_rect = scaled_pixmap.rect()
        scaled_rect.moveCenter(widget_rect.center())
        x_scale = pixmap_rect.width() / scaled_rect.width()
        y_scale = pixmap_rect.height() / scaled_rect.height()
        selection_relative_to_image = self._crop_rect.translated(-scaled_rect.topLeft())
        final_rect = QRect(
            int(selection_relative_to_image.x() * x_scale),
            int(selection_relative_to_image.y() * y_scale),
            int(selection_relative_to_image.width() * x_scale),
            int(selection_relative_to_image.height() * y_scale)
        )
        final_rect = final_rect.intersected(pixmap_rect)
        if final_rect.width() < 1 or final_rect.height() < 1:
            return None, None
        cropped_pixmap = self.pixmap.copy(final_rect)
        return cropped_pixmap, final_rect

    def get_handle_at(self, pos):
        r = self._crop_rect
        if r.isNull(): return None
        hs = self.handle_size
        # Corners
        if (pos - r.topLeft()).manhattanLength() < hs: return 'top_left'
        if (pos - r.topRight()).manhattanLength() < hs: return 'top_right'
        if (pos - r.bottomLeft()).manhattanLength() < hs: return 'bottom_left'
        if (pos - r.bottomRight()).manhattanLength() < hs: return 'bottom_right'
        if abs(pos.x() - r.left()) < hs and r.top() < pos.y() < r.bottom(): return 'left'
        if abs(pos.x() - r.right()) < hs and r.top() < pos.y() < r.bottom(): return 'right'
        if abs(pos.y() - r.top()) < hs and r.left() < pos.x() < r.right(): return 'top'
        if abs(pos.y() - r.bottom()) < hs and r.left() < pos.x() < r.right(): return 'bottom'
        if r.contains(pos): return 'move'
        return None

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        if not self.pixmap.isNull():
            widget_rect = self.rect()
            scaled_pixmap = self.pixmap.scaled(widget_rect.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
            scaled_rect = scaled_pixmap.rect()
            scaled_rect.moveCenter(widget_rect.center())
            painter.drawPixmap(scaled_rect, scaled_pixmap)
        if self.mode == 'drawing':
            rect_to_draw = QRect(self.begin, self.end).normalized()
        else:
            rect_to_draw = self._crop_rect
        if not rect_to_draw.isNull():
            pen = QPen(QColor(0, 255, 0), 2, Qt.SolidLine)
            painter.setPen(pen)
            brush = QBrush(QColor(0, 255, 0, 50))
            painter.setBrush(brush)
            painter.drawRect(rect_to_draw)
            painter.setBrush(QBrush(QColor(255, 255, 255)))
            painter.setPen(QPen(QColor(0, 0, 0)))
            hs = 6
            r = rect_to_draw
            painter.drawRect(r.left(), r.top(), hs, hs)
            painter.drawRect(r.right()-hs, r.top(), hs, hs)
            painter.drawRect(r.left(), r.bottom()-hs, hs, hs)
            painter.drawRect(r.right()-hs, r.bottom()-hs, hs, hs)
            painter.drawRect(r.left() + r.width()//2 - hs//2, r.top(), hs, hs)
            painter.drawRect(r.left() + r.width()//2 - hs//2, r.bottom()-hs, hs, hs)
            painter.drawRect(r.left(), r.top() + r.height()//2 - hs//2, hs, hs)
            painter.drawRect(r.right()-hs, r.top() + r.height()//2 - hs//2, hs, hs)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            handle = self.get_handle_at(event.pos())
            if handle == 'move':
                self.mode = 'moving'
                self.last_mouse_pos = event.pos()
            elif handle:
                self.mode = 'resizing'
                self.resize_edge = handle
                self.last_mouse_pos = event.pos()
            else:
                self.mode = 'drawing'
                self.begin = event.pos()
                self.end = event.pos()
                self._crop_rect = QRect()
            self.update()

    def mouseMoveEvent(self, event):
        # Update Cursor based on hover
        if self.mode == 'none':
            handle = self.get_handle_at(event.pos())
            if handle in ['top_left', 'bottom_right']: self.setCursor(Qt.SizeFDiagCursor)
            elif handle in ['top_right', 'bottom_left']: self.setCursor(Qt.SizeBDiagCursor)
            elif handle in ['left', 'right']: self.setCursor(Qt.SizeHorCursor)
            elif handle in ['top', 'bottom']: self.setCursor(Qt.SizeVerCursor)
            elif handle == 'move': self.setCursor(Qt.SizeAllCursor)
            else: self.setCursor(Qt.CrossCursor)
        if self.mode == 'drawing':
            self.end = event.pos()
            self.update()
        elif self.mode == 'moving':
            delta = event.pos() - self.last_mouse_pos
            self._crop_rect.translate(delta)
            self.last_mouse_pos = event.pos()
            self.update()
        elif self.mode == 'resizing':
            r = self._crop_rect
            p = event.pos() 
            if 'left' in self.resize_edge: r.setLeft(min(r.right()-10, p.x()))
            if 'right' in self.resize_edge: r.setRight(max(r.left()+10, p.x()))
            if 'top' in self.resize_edge: r.setTop(min(r.bottom()-10, p.y()))
            if 'bottom' in self.resize_edge: r.setBottom(max(r.top()+10, p.y()))
            self.update()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            if self.mode == 'drawing':
                self._crop_rect = QRect(self.begin, self.end).normalized()
            self.mode = 'none'
            self.resize_edge = None
            self.update()

    def keyPressEvent(self, event):
        if not self._crop_rect.isNull():
            step = 1
            if event.modifiers() & Qt.ShiftModifier:
                step = 10
            is_resizing = event.modifiers() & Qt.ControlModifier
            if event.key() == Qt.Key_Left:
                if is_resizing: self._crop_rect.setWidth(max(1, self._crop_rect.width() - step)) 
                else: self._crop_rect.translate(-step, 0)
            elif event.key() == Qt.Key_Right:
                if is_resizing: self._crop_rect.setWidth(self._crop_rect.width() + step)
                else: self._crop_rect.translate(step, 0)
            elif event.key() == Qt.Key_Up:
                if is_resizing: self._crop_rect.setHeight(max(1, self._crop_rect.height() - step))
                else: self._crop_rect.translate(0, -step)
            elif event.key() == Qt.Key_Down:
                if is_resizing: self._crop_rect.setHeight(self._crop_rect.height() + step)
                else: self._crop_rect.translate(0, step)
            self.update()
        else:
            super().keyPressEvent(event)


class CropApp(QWidget):
    def __init__(self, file_path=None, vlc_instance=None):
        super().__init__()
        self.setWindowTitle("Crop Tool")
        self.config_path = "crop_tool.conf"
        self.last_dir = os.path.expanduser('~')
        self.load_settings()
        self.media = None
        temp_dir = tempfile.gettempdir()
        self.snapshot_path = os.path.join(temp_dir, "snapshot.png")
        for ext in [".png", ".jpg", ".jpeg"]:
            garbage_path = os.path.join(temp_dir, f"snapshot{ext}")
            if os.path.exists(garbage_path):
                try: os.remove(garbage_path)
                except: pass
        self.portrait_window = None
        self.original_resolution = None
        self.input_file_path = None
        self.script_dir = os.path.dirname(os.path.abspath(__file__))
        self.base_dir = os.path.abspath(os.path.join(self.script_dir, '..'))
        self.bin_dir = os.path.join(self.base_dir, 'binaries')
        if vlc_instance:
            self.vlc_instance = vlc_instance
        else:
            vlc_args = ['--no-xlib', '--no-video-title-show', '--no-plugins-cache', '--file-caching=200', '--aout=directsound', '--verbose=-1']
            self.vlc_instance = vlc.Instance(vlc_args)
        self.media_player = self.vlc_instance.media_player_new()
        self.view_stack = QStackedWidget(self)
        self.video_frame = QWidget(self)
        self.video_frame.setStyleSheet("background-color: black;")
        self.video_frame.setFocusPolicy(Qt.StrongFocus)
        self.draw_widget = DrawWidget(self)
        self.view_stack.addWidget(self.video_frame)
        self.view_stack.addWidget(self.draw_widget)
        self.play_pause_button = QPushButton("Play")
        self.play_pause_button.setEnabled(False)
        self.play_pause_button.setIcon(self.style().standardIcon(QStyle.SP_MediaPlay))
        self.play_pause_button.clicked.connect(self.play_pause)
        self.open_button = QPushButton("Open File")
        self.open_button.clicked.connect(self.open_file)
        self.snapshot_button = QPushButton("Begin Crops")
        self.snapshot_button.setEnabled(False)
        self.snapshot_button.clicked.connect(self.take_snapshot)
        self.back_button = QPushButton("Back to Video")
        self.back_button.clicked.connect(self.show_video_view)
        self.send_crop_button = QPushButton("Send to Portrait")
        self.send_crop_button.clicked.connect(self.trigger_portrait_add)
        self.position_slider = QSlider(Qt.Horizontal)
        self.position_slider.setRange(0, 1000)
        self.position_slider.sliderMoved.connect(self.set_position)
        self.coordinates_label = QLabel("Crop coordinates will be shown here")
        self.coordinates_label.setAlignment(Qt.AlignCenter)
        control_layout = QHBoxLayout()
        control_layout.setSpacing(20)
        control_layout.addStretch()
        control_layout.addWidget(self.open_button)
        control_layout.addWidget(self.play_pause_button)
        control_layout.addWidget(self.snapshot_button)
        control_layout.addWidget(self.back_button)
        control_layout.addWidget(self.send_crop_button)
        control_layout.addStretch()
        vbox = QVBoxLayout()
        vbox.addWidget(self.view_stack, 1)
        vbox.addWidget(self.position_slider)
        vbox.addLayout(control_layout)
        vbox.addWidget(self.coordinates_label)
        self.setLayout(vbox)
        self.timer = QTimer(self)
        self.timer.setInterval(100)
        self.timer.timeout.connect(self.update_ui)
        self.timer.start()
        self.set_style()
        self.setFocusPolicy(Qt.StrongFocus)
        self.setFocus()
        self.video_frame.setFocus()
        if file_path and os.path.exists(file_path):
            self.load_file(file_path)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Space:
            self.play_pause()
        else:
            if self.view_stack.currentWidget() == self.draw_widget:
                self.draw_widget.keyPressEvent(event)
            else:
                super().keyPressEvent(event)

    def set_style(self):
        self.setStyleSheet(CROP_APP_STYLESHEET)
        self.snapshot_button.setStyleSheet("background-color: #2ecc71;")
        self.send_crop_button.setStyleSheet("background-color: #e67e22; color: white; padding: 5px; border-radius: 6px; font-weight: bold; max-width: 120px;")

    def trigger_portrait_add(self):
        pix, rect = self.draw_widget.get_selection()
        if pix and rect:
            self.update_crop_coordinates_label(rect)
            if self.portrait_window is None:
                self.portrait_window = PortraitWindow(self.original_resolution, self.config_path)
            self.portrait_window.add_scissored_item(pix, rect)
            self.draw_widget.clear_selection()
            self.portrait_window.show()
        else:
            self.coordinates_label.setText("Please draw a box first!")

    def open_file(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "Open Video", self.last_dir, "Video Files (*.mp4 *.avi *.mkv)")
        if file_path:
            self.load_file(file_path)

    def load_file(self, file_path):
        self.last_dir = os.path.dirname(file_path)
        self.input_file_path = file_path
        self.media = self.vlc_instance.media_new(file_path)
        self.media_player.set_media(self.media)
        self.media_player.set_hwnd(self.video_frame.winId())
        self.play_pause_button.setEnabled(True)
        self.snapshot_button.setEnabled(False)
        self.show_video_view()
        self.play_pause()
        self.get_video_info()
        QTimer.singleShot(1500, lambda: self.snapshot_button.setEnabled(True))

    def play_pause(self):
        if self.media_player.is_playing():
            self.media_player.pause()
            self.play_pause_button.setText("Play")
            self.play_pause_button.setIcon(self.style().standardIcon(QStyle.SP_MediaPlay))
        else:
            if self.media:
                self.media_player.play()
                self.play_pause_button.setText("Pause")
                self.play_pause_button.setIcon(self.style().standardIcon(QStyle.SP_MediaPause))
    
    def take_snapshot(self):
        print("--- take_snapshot called ---")
        if not self.media or not self.input_file_path:
            self.coordinates_label.setText("No media loaded.")
            return
        if not self.original_resolution:
            self.coordinates_label.setText("Please wait for video information.")
            return

        if self.media_player.is_playing():
            self.media_player.pause()
            self.play_pause_button.setText("Play")
            self.play_pause_button.setIcon(self.style().standardIcon(QStyle.SP_MediaPlay))

        try:
            self.coordinates_label.setText("Generating snapshot with FFmpeg...")
            QApplication.processEvents()
            ffmpeg_path = os.path.join(self.bin_dir, 'ffmpeg.exe')
            curr_time = max(0, self.media_player.get_time() / 1000.0)
            cmd = [
                ffmpeg_path,
                '-ss', f"{curr_time:.3f}",
                '-i', self.input_file_path,
                '-frames:v', '1',
                '-q:v', '2',
                '-y', self.snapshot_path
            ]
            subprocess.run(
                cmd,
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=(subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0)
            )
            self.coordinates_label.setText("Snapshot created. Loading...")
            self._show_draw_view()
        except Exception as e:
            self.coordinates_label.setText(f"Error: FFmpeg snapshot failed: {e}")
            print(f"FFmpeg snapshot failed: {e}")

    def _show_draw_view(self):
        if not os.path.exists(self.snapshot_path) or os.path.getsize(self.snapshot_path) == 0:
            self.coordinates_label.setText("Snapshot file is missing or empty.")
            return

        snapshot_pixmap = QPixmap(self.snapshot_path)
        if snapshot_pixmap.isNull():
            self.coordinates_label.setText("Failed to load snapshot image.")
            return

        if self.portrait_window is None:
            self.portrait_window = PortraitWindow(self.original_resolution, self.config_path)

        target_aspect = 1150 / 1920
        img_aspect = snapshot_pixmap.width() / snapshot_pixmap.height()
        
        if img_aspect > target_aspect:
            h = snapshot_pixmap.height()
            w = int(h * target_aspect)
            x = (snapshot_pixmap.width() - w) // 2
            y = 0
        else:
            w = snapshot_pixmap.width()
            h = int(w / target_aspect)
            x = 0
            y = (snapshot_pixmap.height() - h) // 2
        
        center_crop_rect = QRect(x, y, w, h)
        background_pixmap = snapshot_pixmap.copy(center_crop_rect)

        self.portrait_window.set_background(background_pixmap)
        self.portrait_window.show()
        
        self.draw_widget.setImage(self.snapshot_path)
        self.view_stack.setCurrentWidget(self.draw_widget)
        self.send_crop_button.setVisible(True)
        self.draw_widget.setFocus()
        self.coordinates_label.setText("Ready to draw crops.")

    def show_video_view(self):
        self.view_stack.setCurrentWidget(self.video_frame)
        self.send_crop_button.setVisible(False)

    def set_position(self, position):
        if self.media_player.is_seekable():
            self.media_player.set_position(position / 1000.0)

    def update_ui(self):
        if self.media and self.view_stack.currentWidget() == self.video_frame:
            media_pos = int(self.media_player.get_position() * 1000)
            self.position_slider.setValue(media_pos)
            if self.media_player.get_state() == vlc.State.Ended:
                self.media_player.stop()
                self.play_pause_button.setText("Play")
                self.play_pause_button.setIcon(self.style().standardIcon(QStyle.SP_MediaPlay))
                self.position_slider.setValue(0)

    def update_crop_coordinates_label(self, rect):
        self.coordinates_label.setText(f"Crop: x={rect.x()}, y={rect.y()}, w={rect.width()}, h={rect.height()}")

    def get_video_info(self):
        if not self.input_file_path or not os.path.exists(self.input_file_path):
            return
        QTimer.singleShot(500, self._fetch_vlc_resolution)
        try:
            ffprobe_path = os.path.join(self.bin_dir, 'ffprobe.exe') 
            if not os.path.exists(ffprobe_path):
                return
            cmd = [
                ffprobe_path, '-v', 'error', '-select_streams', 'v:0',
                '-show_entries', 'stream=width,height', '-of', 'csv=p=0:s=x',
                self.input_file_path
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, check=True,
                                    creationflags=(subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0))
            res_string = result.stdout.strip()
            if res_string:
                self.original_resolution = res_string
                self.coordinates_label.setText(f"Resolution: {self.original_resolution}")
        except (subprocess.CalledProcessError, FileNotFoundError) as e:
            self.coordinates_label.setText(f"Error getting video info: {e}")
    def _fetch_vlc_resolution(self):
        if not self.original_resolution:
            w, h = self.media_player.video_get_size(0)
            if w > 0 and h > 0:
                self.original_resolution = f"{w}x{h}"
                self.coordinates_label.setText(f"Resolution: {self.original_resolution}")

    def load_settings(self):
        try:
            with open(self.config_path, 'r') as f:
                settings = json.load(f)
                geom = settings.get('window_geometry')
                if geom:
                    self.setGeometry(geom['x'], geom['y'], geom['w'], geom['h'])
                else:
                    self.setGeometry(300, 300, 800, 600)
                self.last_dir = settings.get('last_directory', os.path.expanduser('~'))
        except (FileNotFoundError, json.JSONDecodeError):
            self.setGeometry(300, 300, 800, 600) 
            self.last_dir = os.path.expanduser('~')

    def closeEvent(self, event):
        if self.portrait_window:
            self.portrait_window.close()
        
        temp_dir = tempfile.gettempdir()
        for ext in [".png", ".jpg", ".jpeg"]:
            garbage_path = os.path.join(temp_dir, f"snapshot{ext}")
            if os.path.exists(garbage_path):
                try: os.remove(garbage_path)
                except: pass
        try:
            with open(self.config_path, 'r') as f:
                settings = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            settings = {}
        settings['window_geometry'] = {
            'x': self.geometry().x(),
            'y': self.geometry().y(),
            'w': self.geometry().width(),
            'h': self.geometry().height()
        }
        settings['last_directory'] = self.last_dir
        try:
            with open(self.config_path, 'w') as f:
                json.dump(settings, f, indent=4)
        except Exception as e:
            print(f"Error saving settings: {e}")
        super().closeEvent(event)

def main():
    BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
    BIN_DIR = os.path.join(BASE_DIR, 'binaries')
    PLUGINS_DIR = os.path.join(BIN_DIR, 'plugins')
    os.environ['VLC_PLUGIN_PATH'] = PLUGINS_DIR
    if hasattr(os, 'add_dll_directory'):
        if os.path.isdir(BIN_DIR): os.add_dll_directory(BIN_DIR)
        if os.path.isdir(PLUGINS_DIR): os.add_dll_directory(PLUGINS_DIR)
    os.environ['PATH'] = BIN_DIR + os.pathsep + PLUGINS_DIR + os.pathsep + os.environ.get('PATH', '')
    try:
        ctypes.WinDLL(os.path.join(BIN_DIR, 'libvlccore.dll'))
        ctypes.WinDLL(os.path.join(BIN_DIR, 'libvlc.dll'))
    except Exception as e:
        print(f"Error loading VLC DLLs: {e}")
    app = QApplication(sys.argv)
    file_path = sys.argv[1] if len(sys.argv) > 1 else None
    player = CropApp(file_path=file_path)
    player.show()
    sys.exit(app.exec_())

if __name__ == '__main__':
    main()

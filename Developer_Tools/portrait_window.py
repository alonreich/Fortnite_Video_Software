from PyQt5.QtWidgets import (
    QApplication, QWidget, QPushButton, QHBoxLayout, QVBoxLayout,
    QLabel, QGraphicsScene, QGraphicsView, QGraphicsPixmapItem,
    QDialog, QTextEdit, QMessageBox
)
from PyQt5.QtCore import Qt, QSize, QEvent
from PyQt5.QtGui import QPainter

from utils import PersistentWindowMixin
from graphics_items import ResizablePixmapItem
from config import PORTRAIT_WINDOW_STYLESHEET

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
        button_size = QSize(160, 40)
        self.copy_button.setFixedSize(button_size)
        self.setLayout(layout)

    def copy_text(self):
        QApplication.clipboard().setText(self.text_edit.toPlainText())

class PortraitWindow(PersistentWindowMixin, QWidget):
    def __init__(self, original_resolution, config_path, parent=None):
        super(PortraitWindow, self).__init__(parent)
        self.original_resolution = original_resolution
        self.base_title = "Portrait Composer"
        self.setFixedWidth(575)
        self.setMinimumHeight(400)
        self.setMaximumHeight(3000)
        
        self.setup_persistence(
            config_path=config_path,
            settings_key='portrait_window_geometry',
            default_geo={'x': 0, 'y': 0, 'h': 1000},
            title_info_provider=self.get_title_info
        )
        
        self.scene = QGraphicsScene(self)
        self.scene.setSceneRect(0, 0, 575, 960)
        self.view = QGraphicsView(self.scene, self)
        self.view.viewport().installEventFilter(self)
        self.view.setRenderHint(QPainter.Antialiasing)
        self.view.setRenderHint(QPainter.SmoothPixmapTransform)
        self.view.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.view.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        
        self.finished_button = QPushButton("Show Cropping Coordinates")
        self.finished_button.clicked.connect(self.on_finished)
        self.finished_button.setEnabled(False)
        self.delete_button = QPushButton("Delete Selected Piece")
        self.delete_button.clicked.connect(self.delete_selected)
        self.delete_button.setEnabled(False)
        
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
        
        button_size = QSize(184, 40)
        self.finished_button.setFixedSize(button_size)
        self.delete_button.setFixedSize(button_size)
        self.setLayout(layout)
        
        self.scene.selectionChanged.connect(self.on_selection_changed)

    def eventFilter(self, source, event):
        if source == self.view.viewport() and event.type() == QEvent.KeyPress:
            selected_items = self.scene.selectedItems()
            if selected_items:
                item = selected_items[0]
                delta = 1
                x, y = item.pos().x(), item.pos().y()

                key = event.key()
                if key == Qt.Key_Up:
                    item.setPos(x, y - delta)
                elif key == Qt.Key_Down:
                    item.setPos(x, y + delta)
                elif key == Qt.Key_Left:
                    item.setPos(x - delta, y)
                elif key == Qt.Key_Right:
                    item.setPos(x + delta, y)
                else:
                    return super().eventFilter(source, event)
                return True # Event handled
        return super().eventFilter(source, event)

    def get_title_info(self):
        monitor_id = QApplication.desktop().screenNumber(self) + 1
        pos = self.frameGeometry()
        return (
                f"{self.base_title} (1150x1920) "
                f"mntr: {monitor_id}  |  "
                f"Pos: x={pos.x()}, y={pos.y()}  |  "
                f"Height: {self.height()}"
        )

    def set_background(self, pixmap):
        if not pixmap.isNull():
            bg_item = QGraphicsPixmapItem(pixmap.scaled(int(self.scene.width()), int(self.scene.height()), Qt.KeepAspectRatio, Qt.SmoothTransformation))
            bg_item.setZValue(-1)
            self.scene.addItem(bg_item)

    def set_style(self):
        self.setStyleSheet(PORTRAIT_WINDOW_STYLESHEET)
        self.delete_button.setStyleSheet("background-color: #c0392b; color: white;")

    def on_selection_changed(self):
        selected_items = self.scene.selectedItems()
        are_items_selected = bool(selected_items)
        
        self.finished_button.setEnabled(are_items_selected)
        self.delete_button.setEnabled(are_items_selected)

        if are_items_selected:
            item = selected_items[0]
            # Ensure only one item is ever selected
            if len(selected_items) > 1:
                for i in selected_items[1:]:
                    i.setSelected(False)
            
            # Update info based on the single selected item
            self.update_item_info(item)
        else:
            self.pos_label.setText("Position: ")
            self.scale_label.setText("Size: ")

    def add_scissored_item(self, pixmap, crop_rect):
        item = ResizablePixmapItem(pixmap, crop_rect)
        self.scene.addItem(item)
        item.setPos(self.scene.width()/2 - item.boundingRect().width()/2,
                    self.scene.height()/2 - item.boundingRect().height()/2)
        item.setSelected(True)

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

    def closeEvent(self, event):
        if hasattr(self, 'parent_window') and self.parent_window:
            self.parent_window.show()
        super().closeEvent(event)

    def on_finished(self):
        data = []
        data.append(f"Original Video Resolution: {getattr(self, 'original_resolution', 'N/A')}")
        data.append("Target Canvas: 1150x1920")
        selected_items = self.scene.selectedItems()
        if not selected_items:
            # This case should ideally not be reachable if button is disabled
            QMessageBox.information(self, "No Item Selected", "Please select a cropped piece to show its coordinates.")
            return
        item = selected_items[0]
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
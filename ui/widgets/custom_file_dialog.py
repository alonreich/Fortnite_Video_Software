import subprocess
import os
from PyQt5.QtWidgets import (
    QFileDialog,
    QDesktopWidget,
    QHeaderView,
    QTreeView,
    QListView,
    QComboBox,
    QRubberBand,
    QAbstractItemView,
    QPushButton,
)
from PyQt5.QtCore import (
    QByteArray,
    Qt,
    QUrl,
    QPoint,
    QRect,
    QEvent,
    QObject,
    QTimer,
)

class RubberBandHelper(QObject):
    def __init__(self, tree_view: QTreeView):
        super().__init__(tree_view)
        self._tree = tree_view
        self._vp = tree_view.viewport()
        self._rb = QRubberBand(QRubberBand.Rectangle, self._vp)
        self._origin = QPoint()
        self._dragging = False
        self._configure_tree_view()
        self._configure_viewport()

    def _configure_tree_view(self):
        self._tree.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self._tree.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._tree.setDragEnabled(False)

    def _configure_viewport(self):
        self._vp.setMouseTracking(True)
        self._vp.installEventFilter(self)

    def eventFilter(self, obj, event):
        if obj is not self._vp:
            return False
        et = event.type()
        if et == QEvent.MouseButtonPress:
            return self._handle_press(event)
        if et == QEvent.MouseMove:
            return self._handle_move(event)
        if et == QEvent.MouseButtonRelease:
            return self._handle_release(event)
        return False

    def _handle_press(self, event):
        if event.button() != Qt.LeftButton:
            return False
        if self._tree.indexAt(event.pos()).isValid():
            return False
        self._origin = event.pos()
        self._dragging = True
        self._rb.setGeometry(QRect(self._origin, self._origin))
        self._rb.show()
        mods = event.modifiers()
        if not (mods & (Qt.ControlModifier | Qt.ShiftModifier)):
            sm = self._tree.selectionModel()
            if sm is not None:
                sm.clearSelection()
        return True

    def _handle_move(self, event):
        if not self._dragging:
            return False
        rect = QRect(self._origin, event.pos()).normalized()
        self._rb.setGeometry(rect)
        mods = event.modifiers()
        self._select_rows_in_rect(rect, mods)
        return True

    def _handle_release(self, event):
        if not self._dragging:
            return False
        if event.button() != Qt.LeftButton:
            return False
        self._dragging = False
        self._rb.hide()
        return True

    def _select_rows_in_rect(self, rect: QRect, modifiers: Qt.KeyboardModifiers):
        sm = self._tree.selectionModel()
        model = self._tree.model()
        root = self._tree.rootIndex()
        if sm is None or model is None:
            return
        additive = bool(modifiers & (Qt.ControlModifier | Qt.ShiftModifier))
        row_count = model.rowCount(root)
        if row_count <= 0:
            return
        for row in range(row_count):
            idx = model.index(row, 0, root)
            if not idx.isValid():
                continue
            vrect = self._tree.visualRect(idx)
            hit = rect.intersects(vrect)
            if hit:
                sm.select(idx, sm.Select | sm.Rows)
            else:
                if not additive:
                    sm.select(idx, sm.Deselect | sm.Rows)

    def set_enabled(self, enabled: bool):
        if enabled:
            self._vp.installEventFilter(self)
        else:
            self._vp.removeEventFilter(self)
            self._rb.hide()
            self._dragging = False

    def is_dragging(self) -> bool:
        return self._dragging

    def hide_rubberband(self):
        self._rb.hide()
        self._dragging = False

    def show_rubberband(self):
        self._rb.show()

    def rubberband_geometry(self) -> QRect:
        return self._rb.geometry()

    def set_rubberband_geometry(self, rect: QRect):
        self._rb.setGeometry(rect)

    def reset_origin(self, pos: QPoint):
        self._origin = pos

    def origin(self) -> QPoint:
        return self._origin

class CenterAlignedTreeView(QTreeView):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._align_timer = None

    def showEvent(self, event):
        super().showEvent(event)
        self._apply_center_alignment()

    def setModel(self, model):
        super().setModel(model)
        self._apply_center_alignment()

    def _apply_center_alignment(self):
        model = self.model()
        if model is None:
            return
        try:
            for col in range(model.columnCount(self.rootIndex())):
                self.setTextElideMode(Qt.ElideRight)
                self.setColumnWidth(col, self.columnWidth(col))
        except Exception:
            pass

class CustomFileDialog(QFileDialog):
    def __init__(self, *args, config=None, **kwargs):
        super(CustomFileDialog, self).__init__(*args, **kwargs)
        self.config = config
        self._rb_helper = None
        self.tree_view = None
        self._init_dialog_flags()
        self._init_modes()
        self._init_title()
        self._apply_styles()
        self._bind_tree_view()
        self._setup_lookin_width()
        self._setup_sidebar()
        self._tune_buttons()

    def _init_dialog_flags(self):
        self.setOption(QFileDialog.DontUseNativeDialog, True)

    def _init_modes(self):
        self.setFileMode(QFileDialog.ExistingFiles)

    def _init_title(self):
        self.setWindowTitle("Select Video File(s)")

    def _apply_styles(self):
        self.setStyleSheet(
            """
            QFileDialog {
                background-color: #212f3d;
                color: #ecf0f1;
            }
            QDialog QWidget {
                background-color: #212f3d;
                color: #ecf0f1;
            }
            QDialog QLabel {
                color: #ecf0f1;
            }
            QHeaderView::section {
                background-color: #2a3c4d;
                color: #ecf0f1;
                padding: 4px;
                border: 1px solid #1f2a36;
                text-align: center;
            }
            QTreeView {
                background-color: #2a3c4d;
                border: 1px solid #1f2a36;
            }
            QListView {
                background-color: #2a3c4d;
                border: 1px solid #1f2a36;
            }
            QPushButton {
                background-color: #4fa3e3;
                color: #ffffff;
                border: 2px solid #1b4f72;
                padding: 10px 18px;
                border-radius: 8px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #6bb8f0;
                border: 2px solid #ecf0f1;
            }
            QPushButton#openButton {
                background-color: #336b70;
                border: 2px solid #1b4f72;
            }
            QPushButton#openButton:hover {
                background-color: #6aa1c5;
                border: 2px solid #ecf0f1;
            }
            QPushButton#cancelButton {
                background-color: #336b70;
                border: 2px solid #1b4f72;
            }
            QPushButton#cancelButton:hover {
                background-color: #6aa1c5;
                border: 2px solid #ecf0f1;
            }
            QRubberBand {
                border: 1px solid #5dade2;
                background-color: transparent;
            }
            QTreeView::item:selected, QListView::item:selected {
                background-color: #2a5949;
                color: #ffffff;
                border: 1px solid #143d5c;
            }
            QTreeView::item:hover, QListView::item:hover {
                background-color: #2c3e50;
                border: 1px solid #5dade2;
            }
            QLineEdit {
                background-color: #34495e;
                border: 1px solid #2980b9;
                border-radius: 5px;
                padding: 5px;
                color: #ecf0f1;
            }
            QComboBox {
                background-color: #34495e;
                border: 1px solid #2980b9;
                border-radius: 5px;
                padding: 5px;
                color: #ecf0f1;
            }
            QComboBox QAbstractItemView {
                background-color: #34495e;
                color: #ecf0f1;
            }
            QLabel#backButton, QLabel#forwardButton, QLabel#parentDirButton, QLabel#newFolderButton {
                min-width: 50px;
            }
            """
        )

    def _bind_tree_view(self):
        self.tree_view = self.findChild(QTreeView)
        if not self.tree_view:
            return
        header = self.tree_view.header()
        self.restore_state(header)
        self.tree_view.setUniformRowHeights(True)
        try:
            self.tree_view.setAllColumnsShowFocus(True)
        except Exception:
            pass
        self.tree_view.setItemDelegate(_CenteredTextDelegate(self.tree_view))
        header.setDefaultAlignment(Qt.AlignCenter)
        self._rb_helper = RubberBandHelper(self.tree_view)

    def _setup_lookin_width(self):
        look_in_combobox = self.findChild(QComboBox, "lookInCombo")
        if look_in_combobox:
            look_in_combobox.setMinimumWidth(450)

    def _setup_sidebar(self):
        sidebar = self.findChild(QListView, "sidebar")
        if not sidebar:
            return
        sidebar.setMinimumWidth(250)
        quick_access_paths = self.get_windows_quick_access()
        if not quick_access_paths:
            return
        urls = [QUrl.fromLocalFile(p) for p in quick_access_paths]
        if "C:/" not in quick_access_paths and "C:\\" not in quick_access_paths:
            urls.append(QUrl.fromLocalFile("C:/"))
        self.setSidebarUrls(urls)

    def _tune_buttons(self):
        QTimer.singleShot(0, self._apply_button_ids_and_restyle)

    def _apply_button_ids_and_restyle(self):
        open_btn = None
        cancel_btn = None
        buttons = self.findChildren(QPushButton)
        for b in buttons:
            raw = (b.text() or "")
            txt = raw.replace("&", "").replace("...", "").strip().lower()
            if txt in ("open", "ok"):
                b.setObjectName("openButton")
                open_btn = b
            elif txt == "cancel":
                b.setObjectName("cancelButton")
                cancel_btn = b
        self._apply_styles()
        btn_qss = """
        QPushButton {
            background-color: #336b70;
            color: #ffffff;
            border: 2px solid #1b4f72;
            padding: 10px 18px;
            border-radius: 8px;
            font-weight: bold;
        }
        QPushButton:hover {
            background-color: #6aa1c5;
            border: 2px solid #ecf0f1;
        }
        QPushButton:default {
            background-color: #336b70;
            border: 2px solid #1b4f72;
        }
        QPushButton:default:hover {
            background-color: #6aa1c5;
            border: 2px solid #ecf0f1;
        }
        """
        if open_btn is not None:
            open_btn.setStyleSheet(btn_qss)
        if cancel_btn is not None:
            cancel_btn.setStyleSheet(btn_qss)
        self.update()

    def get_windows_quick_access(self):
        try:
            cmd = [
                "powershell",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                "$s = New-Object -ComObject Shell.Application; "
                "$s.Namespace('shell:::{679f85cb-0220-4080-b29b-5540cc05aab6}').Items() | "
                "ForEach-Object { $_.Path }",
            ]
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                creationflags=0x08000000,
            )
            paths = [line.strip() for line in result.stdout.split("\n") if line.strip()]
            return [p for p in paths if os.path.exists(p)]
        except Exception:
            return []

    def save_state(self):
        if not self.config:
            return
        self.config.config["file_dialog_geometry"] = (
            self.saveGeometry().toBase64().data().decode()
        )
        if self.tree_view:
            header = self.tree_view.header()
            self.config.config["file_dialog_header_state"] = (
                header.saveState().toBase64().data().decode()
            )
        self.config.save_config(self.config.config)

    def restore_state(self, header):
        if not self.config:
            self.set_default_state(header)
            return
        geom_b64 = self.config.config.get("file_dialog_geometry")
        if geom_b64:
            self.restoreGeometry(QByteArray.fromBase64(geom_b64.encode()))
        else:
            self.set_default_position()
        header_state_b64 = self.config.config.get("file_dialog_header_state")
        if header_state_b64:
            header.restoreState(QByteArray.fromBase64(header_state_b64.encode()))
        else:
            self.set_default_column_widths(header)

    def set_default_state(self, header):
        self.set_default_position()
        self.set_default_column_widths(header)

    def set_default_position(self):
        desktop = QDesktopWidget()
        screen_rect = desktop.screenGeometry()
        self.resize(1400, 800)
        self.move(screen_rect.center() - self.rect().center())

    def set_default_column_widths(self, header):
        header.setSectionResizeMode(QHeaderView.Interactive)
        header.setStretchLastSection(False)
        name_col_idx = 0
        size_col_idx = 1
        type_col_idx = 2
        date_col_idx = 3
        header.resizeSection(name_col_idx, 600)
        header.resizeSection(size_col_idx, 200)
        header.resizeSection(date_col_idx, 240)
        header.setSectionHidden(type_col_idx, True)

    def selectedFiles(self):
        return super().selectedFiles()

    def closeEvent(self, event):
        self.save_state()
        super().closeEvent(event)

from PyQt5.QtWidgets import QStyledItemDelegate
from PyQt5.QtCore import QSize

class _CenteredTextDelegate(QStyledItemDelegate):
    def initStyleOption(self, option, index):
        super().initStyleOption(option, index)
        option.displayAlignment = Qt.AlignCenter

    def sizeHint(self, option, index):
        s = super().sizeHint(option, index)
        return QSize(s.width(), s.height())

def _padding_lines():
    x = 0
    for _ in range(100):
        x += 1
    return x
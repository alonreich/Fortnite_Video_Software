from PyQt5.QtWidgets import QFileDialog, QMessageBox, QListWidgetItem, QDialog, QVBoxLayout, QLabel, QGridLayout, QPushButton
from PyQt5.QtCore import QUrl, Qt
from PyQt5.QtGui import QDesktopServices
from pathlib import Path
import os
import sys
import subprocess
from utilities.merger_utils import _human

class MergerHandlers:
    def __init__(self, parent):
        self.parent = parent
        self.logger = parent.logger

    def on_merge_clicked(self):
        try:
            self.parent.btn_merge.setEnabled(False)
            self.parent.btn_back.setEnabled(False)
            self.parent.listw.setEnabled(False)
            self.parent.ui_handler._show_processing_overlay()
            self.parent.btn_merge.setText("Processing…")
        except Exception:
            pass
        self.parent.ffmpeg_handler.merge_now()

    def add_videos(self):
        start_dir = self.parent._last_dir if self.parent._last_dir and Path(self.parent._last_dir).exists() else ""
        files, _ = QFileDialog.getOpenFileNames(
            self.parent, "Select videos to merge", start_dir,
            "Videos (*.mp4 *.mov *.mkv *.m4v *.ts *.avi *.webm);;All Files (*)"
        )
        if not files:
            return
        current = self.parent.listw.count()
        room = max(0, self.parent.MAX_FILES - current)
        if room <= 0:
            QMessageBox.warning(self.parent, "Limit reached", f"Maximum {self.parent.MAX_FILES} files already added.")
            return
        current_files = {self.parent.listw.item(i).data(Qt.UserRole) for i in range(current)}
        new_files = [f for f in files if f not in current_files]
        if new_files:
            try:
                self.parent._last_dir = str(Path(new_files[0]).parent)
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
            w = self.parent.make_item_widget(f)
            item.setSizeHint(w.sizeHint())
            self.parent.listw.addItem(item)
            self.parent.listw.setItemWidget(item, w)
            item.setSizeHint(w.sizeHint())
        if len(files) > len(new_files):
             QMessageBox.warning(self.parent, "Duplicates", "Some selected files were already in the list and were ignored.")
        if len(new_files) > room:
            QMessageBox.information(self.parent, "Limit", f"Only {room} unique file(s) were added (max {self.parent.MAX_FILES} total).")

    def remove_selected(self):
        for it in self.parent.listw.selectedItems():
            self.parent.listw.takeItem(self.parent.listw.row(it))

    def move_item(self, direction: int):
        """Animate then swap; fall back to instant swap if animation not possible."""
        sel = self.parent.listw.selectedItems()
        if not sel:
            return
        row = self.parent.listw.row(sel[0])
        new_row = row + direction
        if new_row < 0 or new_row >= self.parent.listw.count():
            return
        if self.parent.can_anim(row, new_row) and self.parent.start_swap_animation(row, new_row):
            return
        self.parent.perform_swap(row, new_row)

    def on_selection_changed(self):
        for i in range(self.parent.listw.count()):
            item = self.parent.listw.item(i)
            widget = self.parent.listw.itemWidget(item)
            if widget:
                if item.isSelected():
                    widget.setStyleSheet("background-color:#6a869a; border-radius:6px;")
                else:
                    widget.setStyleSheet("background-color:#4a667a; border-radius:6px;")

    def update_button_states(self):
        """Enable/disable buttons based on list state and processing state."""
        n = self.parent.listw.count()
        is_processing = self.parent.ffmpeg_handler.process is not None
        selected_items = self.parent.listw.selectedItems()
        is_single_selection = len(selected_items) == 1
        self.parent.add_music_checkbox.setEnabled(not is_processing)
        if not is_processing:
            self.parent.music_handler._on_add_music_toggled(self.parent.add_music_checkbox.isChecked())
        else:
            self.parent.music_combo.setEnabled(False)
            self.parent.music_offset_input.setEnabled(False)
            self.parent.music_volume_slider.setEnabled(False)
        self.parent.btn_merge.setEnabled(n >= 2 and not is_processing)
        self.parent.btn_remove.setEnabled(bool(selected_items) and not is_processing)
        self.parent.btn_clear.setEnabled(n > 0 and not is_processing)
        self.parent.btn_add.setEnabled(not is_processing and n < self.parent.MAX_FILES)
        if is_single_selection and not is_processing:
            current_row = self.parent.listw.row(selected_items[0])
            self.parent.btn_up.setEnabled(current_row > 0)
            self.parent.btn_down.setEnabled(current_row < n - 1)
        else:
            self.parent.btn_up.setEnabled(False)
            self.parent.btn_down.setEnabled(False)
        if is_processing:
            self.parent.status_label.setText("Processing merge... Please wait.")
        elif n == 0:
            self.parent.status_label.setText("Ready. Add 2 to 10 videos to begin.")
        elif n < 2:
            self.parent.status_label.setText(f"Waiting for more videos. Currently {n}/10.")
        else:
            self.parent.status_label.setText(f"Ready to merge {n} videos. Order is set.")

    def on_rows_moved(self, parent, start, end, destination, row):
        """
        Re-applies the sizeHint to fix item height after drag-and-drop move.
        """
        try:
            num_moved = end - start + 1
            for i in range(num_moved):
                item_to_update = self.parent.listw.item(row + i)
                if item_to_update is None:
                    continue
                widget = self.parent.listw.itemWidget(item_to_update)
                if widget is None:
                    continue
                item_to_update.setSizeHint(widget.sizeHint())
            self.parent.listw.viewport().update()
        except Exception as e:
            self.logger.error("LISTW: Failed to re-apply sizeHint after move: %s", e)

    def open_folder(self, path: str):
        """Opens the specified folder using the default file explorer."""
        folder_path = str(Path(path))
        if not folder_path or not os.path.isdir(folder_path):
            self.logger.warning("OPEN_FOLDER: Path is not a directory or does not exist: %s", folder_path)
            return
        try:
            if os.name == 'nt':
                os.startfile(folder_path, 'explore')
            elif sys.platform == 'darwin':
                subprocess.Popen(['open', folder_path])
            else:
                subprocess.Popen(['xdg-open', folder_path])
            self.logger.info("OPEN_FOLDER: Opened %s", folder_path)
        except Exception as e:
            self.logger.error("OPEN_FOLDER: Failed to open folder %s | Error: %s", folder_path, e)
    
    def show_success_dialog(self, output_path):
        dialog = QDialog(self.parent)
        dialog.setWindowTitle("Done! Video Processed Successfully!")
        dialog.setModal(True)
        fm = dialog.fontMetrics()
        btn_h = max(58, fm.height() * 2 + 18)
        dialog.resize(max(860, int(self.parent.width() * 0.85)), 3 * btn_h + 160)
        layout = QVBoxLayout(dialog)
        label = QLabel(f"File saved to:\n{output_path}")
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
                self.logger.error("Failed to open WhatsApp Web: %s", e)

        whatsapp_button = QPushButton("✆   Share via Whatsapp   ✆")
        whatsapp_button.setFixedSize(*button_size)
        whatsapp_button.setStyleSheet("background-color: #328742; color: white;")
        whatsapp_button.clicked.connect(lambda: (_open_whatsapp(), dialog.accept(), QApplication.instance().quit()))

        open_folder_button = QPushButton("Open Output Folder")
        open_folder_button.setFixedSize(*button_size)
        open_folder_button.setStyleSheet("background-color: #6c5f9e; color: white;")
        open_folder_button.clicked.connect(lambda: (
            dialog.accept(),
            self.open_folder(os.path.dirname(output_path)),
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
            out_sz = Path(output_path).stat().st_size if output_path else 0
            self.logger.info("MERGE_DONE: output='%s' | size=%s",
                            output_path, _human(out_sz))
        except Exception:
            pass
    
    def preview_file(self, path: str):
        try:
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))
        except Exception as e:
            self.logger.error("Preview failed: %s", e)
            
    def preview_clicked(self):
        try:
            btn = self.parent.sender()
            p = btn.property("path")
            if p:
                self.preview_file(str(p))
        except Exception:
            pass

    def make_item_widget(self, path: str):
        from PyQt5.QtWidgets import QWidget, QHBoxLayout, QLabel, QPushButton, QSizePolicy
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
        btn.clicked.connect(self.preview_clicked)
        h.addWidget(lbl, 1)
        h.addWidget(btn, 0, Qt.AlignRight | Qt.AlignVCenter)
        w.setFixedHeight(46)
        return w

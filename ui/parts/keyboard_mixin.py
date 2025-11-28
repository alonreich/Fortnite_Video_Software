from PyQt5.QtCore import Qt, QEvent
from PyQt5.QtWidgets import QWidget, QApplication


class KeyboardMixin(QWidget):
    """Handles global keyboard shortcuts for the main window."""

    def eventFilter(self, obj, event):
        if event.type() == QEvent.KeyPress:
            if QApplication.activeModalWidget() is not None:
                return super().eventFilter(obj, event)
            
            key = event.key()

            if key in (Qt.Key_Up, Qt.Key_Down):
                if self._handle_volume_keys(key, event.modifiers()):
                    return True

            if getattr(self, "input_file_path", None):
                if key == Qt.Key_Space:
                    self.toggle_play()
                    return True
        return super().eventFilter(obj, event)

    def _handle_volume_keys(self, key, modifiers) -> bool:
        try:
            vol_step = 15 if modifiers == Qt.ShiftModifier else 1
            if key == Qt.Key_Down:
                vol_step = -vol_step

            if self.volume_shortcut_target == 'music':
                slider = self.music_volume_slider
                eff_func = self._music_eff
                callback = self._on_music_volume_changed
                log_name = "Music"
            else:
                slider = self.volume_slider
                eff_func = self._vol_eff
                callback = self._on_master_volume_changed
                log_name = "Main"

            current_eff_vol = eff_func()
            new_eff_vol = max(0, min(100, current_eff_vol + vol_step))

            if slider.invertedAppearance():
                new_raw_val = slider.maximum() + slider.minimum() - new_eff_vol
            else:
                new_raw_val = new_eff_vol
            
            new_raw_val = max(slider.minimum(), min(slider.maximum(), new_raw_val))

            slider.setValue(new_raw_val)
            callback(new_raw_val)
            if hasattr(self, "logger"):
                self.logger.debug(f"KEYBOARD: {log_name} volume set to {new_eff_vol}%")
            return True
        except Exception as e:
            if hasattr(self, "logger"):
                self.logger.error(f"Failed to handle volume key: {e}")
            return False

    def seek_relative_time(self, ms_offset: int):
        """Moves the player's position by a given millisecond offset."""
        if not getattr(self, "vlc_player", None):
            return
        current_time = self.vlc_player.get_time()
        new_time = max(0, current_time + ms_offset)
        max_time = self.vlc_player.get_length()
        new_time = min(new_time, max_time)
        self.set_vlc_position(new_time)
        if hasattr(self, "logger"):
            self.logger.debug("KEYBOARD: Seeked %dms to %dms", ms_offset, new_time)
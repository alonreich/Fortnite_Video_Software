from PyQt5.QtCore import Qt, QEvent
from PyQt5.QtWidgets import QWidget

class KeyboardMixin(QWidget):
    """Handles global keyboard shortcuts for the main window."""

    def eventFilter(self, obj, event):
        """Intercepts key presses for global shortcuts."""
        if event.type() == QEvent.KeyPress:
            if not getattr(self, "input_file_path", None):
                return super().eventFilter(obj, event)
            key = event.key()
            offset_ms = 0
            if event.modifiers() == Qt.ControlModifier:
                if key == Qt.Key_Left:
                    offset_ms = -10
                elif key == Qt.Key_Right:
                    offset_ms = 10
            elif event.modifiers() == Qt.NoModifier:
                if key == Qt.Key_Left:
                    offset_ms = -500
                elif key == Qt.Key_Right:
                    offset_ms = 500
            elif key == Qt.Key_Space:
                self.toggle_play()
                return True
            elif key == Qt.Key_Home:
                if getattr(self, "trim_start", None) is not None:
                    self.set_vlc_position(int(self.trim_start * 1000))
                    self.logger.debug("KEYBOARD: Jumped to trim start (%.3fs)", self.trim_start)
                return True
            elif key == Qt.Key_End:
                if getattr(self, "trim_end", None) is not None:
                    self.set_vlc_position(int(self.trim_end * 1000))
                    self.logger.debug("KEYBOARD: Jumped to trim end (%.3fs)", self.trim_end)
                return True
            if offset_ms != 0:
                self.seek_relative_time(offset_ms)
                return True
            if key in (Qt.Key_Up, Qt.Key_Down, Qt.Key_Plus, Qt.Key_Minus, Qt.Key_Equal):
                if self._handle_volume_keys(key, event.modifiers()):
                    return True
        return super().eventFilter(obj, event)

    def _handle_volume_keys(self, key, modifiers) -> bool:
        """Handles volume adjustments for the currently focused slider."""
        try:
            step = 0
            if key == Qt.Key_Up:
                step = 5 if modifiers == Qt.ShiftModifier else 1
            elif key == Qt.Key_Down:
                step = -5 if modifiers == Qt.ShiftModifier else -1
            elif key == Qt.Key_Plus or (key == Qt.Key_Equal and modifiers == Qt.ShiftModifier):
                step = 5
            elif key == Qt.Key_Minus:
                step = -5
            elif key == Qt.Key_Equal and modifiers == Qt.NoModifier:
                step = 5
            if step == 0:
                return False
            if self.volume_shortcut_target == 'music':
                slider = self.music_volume_slider
                callback = self._on_music_volume_changed
                log_name = "Music"
            else:
                slider = self.volume_slider
                callback = self._on_master_volume_changed
                log_name = "Main"
            current_val = slider.value()
            if slider.invertedAppearance():
                new_val = max(slider.minimum(), min(slider.maximum(), current_val - step))
            else:
                new_val = max(slider.minimum(), min(slider.maximum(), current_val + step))
            slider.setValue(new_val)
            callback(new_val)
            if hasattr(self, "logger"):
                eff_vol = 0
                if log_name == "Music":
                    eff_vol = self._music_eff(new_val)
                else:
                    eff_vol = self._vol_eff(new_val)
                self.logger.debug(f"KEYBOARD: {log_name} volume set to {eff_vol}%")
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
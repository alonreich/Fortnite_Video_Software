from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QWidget

class KeyboardMixin(QWidget):
    """Handles global keyboard shortcuts for the main window."""

    def keyPressEvent(self, event):
        """Intercepts key presses for global shortcuts."""
        if not getattr(self, "input_file_path", None):
            super().keyPressEvent(event)
            return
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
            return
        elif key == Qt.Key_Home:
            if getattr(self, "trim_start", None) is not None:
                self.set_vlc_position(int(self.trim_start * 1000))
                self.logger.debug("KEYBOARD: Jumped to trim start (%.3fs)", self.trim_start)
            return
        elif key == Qt.Key_End:
            if getattr(self, "trim_end", None) is not None:
                self.set_vlc_position(int(self.trim_end * 1000))
                self.logger.debug("KEYBOARD: Jumped to trim end (%.3fs)", self.trim_end)
            return
        if offset_ms != 0:
            self.seek_relative_time(offset_ms)
            return
        super().keyPressEvent(event)

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
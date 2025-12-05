from PyQt5.QtCore import Qt

class KeyboardShortcutMixin:
    def keyPressEvent(self, event):
        key = event.key()
        if key == Qt.Key_F12:
            if hasattr(self, '_launch_main_app') and callable(self._launch_main_app):
                self._launch_main_app()
                event.accept()
                return
        if key == Qt.Key_Space:
            if hasattr(self, 'view_stack') and hasattr(self, 'video_frame') and hasattr(self, 'play_pause'):
                if self.view_stack.currentWidget() == self.video_frame:
                    self.play_pause()
                    event.accept()
                    return
        super().keyPressEvent(event)
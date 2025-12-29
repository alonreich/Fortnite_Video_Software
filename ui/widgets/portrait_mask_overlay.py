from PyQt5.QtWidgets import QWidget
from PyQt5.QtGui import QPainter, QColor
from PyQt5.QtCore import Qt, QRect

class PortraitMaskOverlay(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents) # Allow clicks to pass through
        self.original_video_resolution = "" # e.g., "1920x1080"
        self.current_video_frame_size = None # QSize of the video frame widget
        self.setHidden(True) # Start hidden

    def set_video_info(self, resolution_str: str, frame_size):
        if self.original_video_resolution != resolution_str or self.current_video_frame_size != frame_size:
            self.original_video_resolution = resolution_str
            self.current_video_frame_size = frame_size
            self.update() # Request a repaint

    def paintEvent(self, event):
        if not self.isVisible() or not self.current_video_frame_size or not self.original_video_resolution:
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        # Get the actual video dimensions from the resolution string
        try:
            orig_w, orig_h = map(int, self.original_video_resolution.split('x'))
        except ValueError:
            return # Invalid resolution string

        if orig_w == 0 or orig_h == 0:
            return # Avoid division by zero

        # Check if the video is a standard landscape aspect ratio
        aspect_ratio = orig_w / orig_h
        if aspect_ratio < 1.5: # e.g., 4:3 (1.33), 3:2 (1.5), or portrait
            return # Don't apply dimming to non-landscape or near-square videos

        # Calculate the visible video area within the frame, maintaining aspect ratio
        frame_w = self.width()
        frame_h = self.height()

        video_display_w = frame_w
        video_display_h = int(frame_w / aspect_ratio)

        if video_display_h > frame_h:
            video_display_h = frame_h
            video_display_w = int(frame_h * aspect_ratio)

        # Center the displayed video
        video_x = (frame_w - video_display_w) // 2
        video_y = (frame_h - video_display_h) // 2
        
        # Target portrait dimensions (1150x1920)
        target_portrait_aspect = 1150 / 1920

        # Calculate the inner clear rectangle based on the video's displayed size
        clear_w = video_display_w
        clear_h = int(video_display_w / target_portrait_aspect) # Would be taller than video_display_h

        if clear_h > video_display_h: # If the clear box height exceeds the video height
            clear_h = video_display_h
            clear_w = int(video_display_h * target_portrait_aspect)

        clear_x_offset = (video_display_w - clear_w) // 2
        clear_y_offset = (video_display_h - clear_h) // 2

        clear_rect = QRect(video_x + clear_x_offset, video_y + clear_y_offset, clear_w, clear_h)


        # Draw the dimming outside the clear_rect
        dim_color = QColor(0, 0, 0, 128) # Black with 50% alpha (128 out of 255)
        painter.fillRect(self.rect(), dim_color)
        
        # "Punch a hole" in the dimming to show the clear area
        painter.setCompositionMode(QPainter.CompositionMode_Clear)
        painter.fillRect(clear_rect, Qt.transparent)

        painter.end()
import vlc
from PyQt5.QtCore import QTimer
from PyQt5.QtMultimedia import QMediaPlayer
from PyQt5.QtWidgets import QStyle

class PlayerMixin:

        def _safe_stop_playback(self):
            try:
                if getattr(self, "player", None):
                    self.player.stop()
                    self.player.setPosition(0)
                if getattr(self, "play_button", None):
                    self.play_button.setChecked(False)
                    self.play_button.setText("Play")
                if getattr(self, "position_slider", None):
                    self.position_slider.setValue(0)
            except Exception:
                pass

        def _on_media_status_changed(self, status):
            try:
                from PyQt5.QtMultimedia import QMediaPlayer
                if status == QMediaPlayer.EndOfMedia:
                    self._safe_stop_playback()
            except Exception:
                if int(status) == 7:
                    self._safe_stop_playback()

        def toggle_play(self):
            if not getattr(self, "input_file_path", None):
                return
            if self.vlc_player.is_playing():
                self.vlc_player.pause()
                self.playPauseButton.setText("Play")
                self.playPauseButton.setIcon(self.style().standardIcon(QStyle.SP_MediaPlay))
            else:
                self.vlc_player.play()
                self.playPauseButton.setText("Pause")
                self.playPauseButton.setIcon(self.style().standardIcon(QStyle.SP_MediaPause))
            if not self.timer.isActive():
                self.timer.start(100)

        def update_player_state(self):
            if self.vlc_player:
                current_time = self.vlc_player.get_time()
                if current_time >= 0:
                    if not getattr(self.positionSlider, "_is_pressed", False):
                        self.positionSlider.blockSignals(True)
                        self.positionSlider.setValue(current_time)
                        self.positionSlider.blockSignals(False)
                if self.vlc_player.is_playing():
                    self.playPauseButton.setText("Pause")
                    self.playPauseButton.setIcon(self.style().standardIcon(QStyle.SP_MediaPause))
                else:
                    self.playPauseButton.setText("Play")
                    self.playPauseButton.setIcon(self.style().standardIcon(QStyle.SP_MediaPlay))

        def set_vlc_position(self, position):
            """Sets the player position. If stopped, play/pause briefly to update state."""
            try:
                p = int(position)
            except Exception:
                p = position
            try:
                is_stopped = self.vlc_player.get_state() == vlc.State.Stopped
                self.vlc_player.set_time(p)
                if is_stopped:
                    self.vlc_player.play()
                    QTimer.singleShot(0, self.vlc_player.pause) 
                    self.playPauseButton.setText("Play")
                    self.playPauseButton.setIcon(self.style().standardIcon(QStyle.SP_MediaPlay))
            except Exception as e:
                try:
                    logger = getattr(self, 'logger', None)
                    if logger:
                        logger.error("Error in set_vlc_position: %s", e)
                except Exception:
                    pass

        def _on_vlc_end_reached(self, event=None):
            """
            VLC reached end.
            This is called from a VLC thread, so DO NOT touch any Qt widgets.
            Just emit a signal to be handled by the main thread.
            """
            try:
                self.video_ended_signal.emit()
            except Exception:
                pass
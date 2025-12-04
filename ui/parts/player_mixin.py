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

        def _finish_seek_from_end(self):
            """Callback to finish the seek operation, re-enabling the UI."""
            self.vlc_player.pause()
            self.playPauseButton.setEnabled(True)
            self._is_seeking_from_end = False

        def toggle_play_pause(self):
            """Toggles play/pause, handling restarts from the end and ignoring clicks during seeks."""
            if getattr(self, '_is_seeking_from_end', False):
                return  # Ignore clicks while seek is in progress

            if not getattr(self, "input_file_path", None):
                return

            player_state = self.vlc_player.get_state()

            if player_state == vlc.State.Playing:
                self.vlc_player.pause()
                self.playPauseButton.setText("Play")
                self.playPauseButton.setIcon(self.style().standardIcon(QStyle.SP_MediaPlay))
                if self.timer.isActive():
                    self.timer.stop()
            else:  # Paused, Stopped, Ended, etc.
                pos = self.vlc_player.get_position()
                if player_state == vlc.State.Ended or (player_state == vlc.State.Paused and pos >= 0.999):
                    self.vlc_player.stop()
                    self.vlc_player.play()
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
                
                player_state = self.vlc_player.get_state()
                if player_state == vlc.State.Playing:
                    if not self.is_playing:
                        self.playPauseButton.setText("Pause")
                        self.playPauseButton.setIcon(self.style().standardIcon(QStyle.SP_MediaPause))
                        self.is_playing = True
                else:
                    if self.is_playing:
                        self.playPauseButton.setText("Play")
                        self.playPauseButton.setIcon(self.style().standardIcon(QStyle.SP_MediaPlay))
                        self.is_playing = False


        def set_vlc_position(self, position):
            """Sets the player position, handling the fragile seek-from-end case."""
            try:
                p = int(position)
            except Exception:
                p = position
            try:
                player_state = self.vlc_player.get_state()
                is_stopped_or_ended = player_state in (vlc.State.Stopped, vlc.State.Ended)

                if not is_stopped_or_ended:
                    self.vlc_player.set_time(p)
                    return

                # If we are here, the player is Stopped or Ended.
                # To reliably seek from this state, we must stop and restart the player.
                self.vlc_player.stop()

                # Prevent user from clicking play during the state transition
                self._is_seeking_from_end = True
                self.playPauseButton.setEnabled(False)
                
                self.vlc_player.play()      # Play (will start from beginning)
                self.vlc_player.set_time(p) # Immediately seek to the desired time 'p'
                
                # Schedule a pause to leave the player in a stable, paused state at the new frame
                QTimer.singleShot(200, self._finish_seek_from_end)

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